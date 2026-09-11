import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SystemStatusRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.original_home = os.environ.get("HOME")
        cls.original_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = cls.temporary_directory.name
        os.environ["USERPROFILE"] = cls.temporary_directory.name

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

        database = importlib.import_module("app.database")
        database.initialize_database()
        database.create_user("admin", "test-password", role="admin")
        database.create_user("member", "test-password", role="user")

        cls.database = database
        cls.main = importlib.import_module("app.main")
        cls.status_module = importlib.import_module("app.system_status")
        cls.client = cls.main.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if cls.original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = cls.original_home

        if cls.original_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = cls.original_userprofile

        cls.temporary_directory.cleanup()

    def tearDown(self):
        with self.client.session_transaction() as user_session:
            user_session.clear()

    def login(self, username):
        return self.client.post(
            "/api/auth/login",
            json={
                "username": username,
                "password": "test-password",
            },
        )

    def test_api_requires_authentication(self):
        response = self.client.get("/api/system/status")

        self.assertEqual(response.status_code, 401)

    def test_api_rejects_regular_users(self):
        self.assertEqual(self.login("member").status_code, 200)

        response = self.client.get("/api/system/status")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_read_status(self):
        payload = {
            "overall": "healthy",
            "summary": "Sistem funcțional.",
            "generated_at": "2026-09-11T10:00:00+00:00",
            "services": [],
        }
        self.assertEqual(self.login("admin").status_code, 200)

        with patch.object(
            self.status_module,
            "collect_system_status",
            return_value=payload,
        ):
            response = self.client.get("/api/system/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)

    def test_resource_api_requires_admin(self):
        self.assertEqual(
            self.client.get("/api/system/resources").status_code,
            401,
        )
        self.assertEqual(self.login("member").status_code, 200)
        self.assertEqual(
            self.client.get("/api/system/resources").status_code,
            403,
        )

    def test_admin_can_read_resource_snapshot(self):
        payload = {
            "cpu": {"available": True, "usage_percent": 12.5},
            "processes": [],
            "managed_services": [],
        }
        self.assertEqual(self.login("admin").status_code, 200)

        with (
            patch.object(
                self.status_module,
                "collect_resource_usage",
                return_value=payload,
            ),
            patch.object(
                self.status_module,
                "collect_battery_data",
                return_value={
                    "temperature": 35.4,
                    "health": "GOOD",
                },
            ),
        ):
            response = self.client.get("/api/system/resources")

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["cpu"]["usage_percent"], 12.5)
        self.assertEqual(result["temperature"]["celsius"], 35.4)

    def test_power_and_history_apis_require_admin(self):
        for path in ("/api/system/power", "/api/system/history?hours=24"):
            self.assertEqual(self.client.get(path).status_code, 401)

        self.assertEqual(self.login("member").status_code, 200)

        for path in ("/api/system/power", "/api/system/history?hours=24"):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_admin_can_read_power_and_history(self):
        self.assertEqual(self.login("admin").status_code, 200)
        power = {
            "battery": {"percentage": 82},
            "thermal": {"severity": 0},
        }
        metric = {
            "recorded_at": "2026-09-11T10:00:00+00:00",
            "cpu_usage_percent": 12.5,
        }

        with (
            patch.object(
                self.status_module,
                "collect_power_snapshot",
                return_value=power,
            ),
            patch.object(
                self.status_module,
                "get_thermal_policy",
                return_value={"enabled": True},
            ),
            patch.object(
                self.status_module,
                "get_guardian_status",
                return_value={"level": "normal"},
            ),
            patch.object(
                self.status_module,
                "list_system_metrics",
                return_value=[metric],
            ) as list_metrics,
        ):
            power_response = self.client.get("/api/system/power")
            history_response = self.client.get(
                "/api/system/history?hours=24"
            )

        self.assertEqual(power_response.status_code, 200)
        self.assertEqual(
            power_response.get_json()["battery"]["percentage"],
            82,
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.get_json()["metrics"], [metric])
        list_metrics.assert_called_once_with(24)

    def test_history_downsampling_keeps_first_and_last_measurement(self):
        for value in range(6):
            self.database.record_system_metric(
                {"cpu_usage_percent": value}
            )

        metrics = self.database.list_system_metrics(hours=1, limit=3)

        self.assertEqual(len(metrics), 3)
        self.assertEqual(metrics[0]["cpu_usage_percent"], 0)
        self.assertEqual(metrics[-1]["cpu_usage_percent"], 5)

    def test_power_policy_rejects_unknown_fields(self):
        self.assertEqual(self.login("admin").status_code, 200)

        response = self.client.post(
            "/api/system/power/policy",
            json={"run_any_command": True},
        )

        self.assertEqual(response.status_code, 400)

    def test_charge_limit_requires_supported_kernel_control(self):
        self.assertEqual(self.login("admin").status_code, 200)

        with patch.object(
            self.status_module,
            "collect_power_snapshot",
            return_value={
                "battery": {"charge_control": {"supported": False}}
            },
        ):
            response = self.client.post(
                "/api/system/power/charge-limit",
                json={"limit_percent": 85},
            )

        self.assertEqual(response.status_code, 409)

    def test_admin_can_apply_supported_charge_limit(self):
        self.assertEqual(self.login("admin").status_code, 200)

        with (
            patch.object(
                self.status_module,
                "collect_power_snapshot",
                return_value={
                    "battery": {
                        "charge_control": {
                            "supported": True,
                            "driver": "standard",
                        }
                    }
                },
            ),
            patch.object(
                self.status_module,
                "apply_charge_limit",
                return_value=85,
            ) as apply_limit,
            patch.object(
                self.status_module,
                "save_thermal_policy",
                return_value={"charge_limit_percent": 85},
            ) as save_policy,
        ):
            response = self.client.post(
                "/api/system/power/charge-limit",
                json={"limit_percent": 85},
            )

        self.assertEqual(response.status_code, 200)
        apply_limit.assert_called_once_with("standard", 85)
        save_policy.assert_called_once_with({"charge_limit_percent": 85})

    def test_admin_can_control_only_supported_resource_services(self):
        self.assertEqual(self.login("admin").status_code, 200)

        with patch.object(
            self.status_module,
            "set_ai_enabled",
            return_value=False,
        ) as set_ai:
            response = self.client.post(
                "/api/system/resources/services/ai",
                json={"enabled": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["enabled"])
        set_ai.assert_called_once_with(False)

        unsupported = self.client.post(
            "/api/system/resources/services/web",
            json={"enabled": False},
        )
        self.assertEqual(unsupported.status_code, 404)

    def test_status_collection_returns_every_service(self):
        payload = self.status_module.collect_system_status()
        service_ids = {
            service["id"] for service in payload["services"]
        }

        self.assertEqual(
            service_ids,
            {
                "web",
                "database",
                "storage",
                "memory",
                "battery",
                "backup",
                "aria2",
                "transmission",
                "ai",
                "monitor",
                "supervisor",
            },
        )
        self.assertIn(
            payload["overall"],
            {"healthy", "warning", "critical"},
        )

    def test_status_page_is_admin_only(self):
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 302)

        self.assertEqual(self.login("member").status_code, 200)
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 403)

        with self.client.session_transaction() as user_session:
            user_session.clear()

        self.assertEqual(self.login("admin").status_code, 200)
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Starea serviciilor", response.get_data(as_text=True))

    def test_intentionally_stopped_transmission_is_not_a_warning(self):
        with patch.object(
            self.status_module,
            "transmission_is_enabled",
            return_value=False,
        ):
            result = self.status_module.collect_transmission_service()

        self.assertEqual(result["state"], "idle")
        self.assertEqual(result["impact"], "none")


if __name__ == "__main__":
    unittest.main()
