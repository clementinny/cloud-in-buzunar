import hashlib
import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


class ReliabilityAlertTest(unittest.TestCase):
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

        cls.database = importlib.import_module("app.database")
        cls.database.initialize_database()
        cls.admin_id = cls.database.create_user(
            "admin",
            "test-password",
            role="admin",
        )
        cls.database.create_user(
            "member",
            "test-password",
            role="user",
        )
        cls.alerts = importlib.import_module("app.reliability_alerts")
        cls.main = importlib.import_module("app.main")
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

    def setUp(self):
        connection = self.database.open_database()

        try:
            connection.execute("DELETE FROM system_alert_deliveries")
            connection.execute("DELETE FROM system_alert_events")
            connection.execute("DELETE FROM system_alert_states")
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        with self.client.session_transaction() as user_session:
            user_session.clear()

    def login(self, username):
        return self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "test-password"},
        )

    def test_condition_builder_detects_configured_failures(self):
        settings = self.database.get_system_alert_settings()
        status = {
            "services": [
                {
                    "id": "database",
                    "name": "Bază de date",
                    "state": "offline",
                    "impact": "critical",
                    "summary": "Nu răspunde.",
                },
                {
                    "id": "transmission",
                    "name": "Transmission",
                    "state": "idle",
                    "impact": "none",
                    "summary": "Oprit intenționat.",
                },
                {
                    "id": "supervisor",
                    "name": "Watchdog",
                    "state": "offline",
                    "impact": "warning",
                    "summary": "Watchdog-ul nu rulează.",
                },
            ]
        }
        resources = {
            "storage": {"available": True, "used_percent": 95.2}
        }
        power = {
            "battery": {
                "percentage": 20,
                "plugged": "UNPLUGGED",
                "status": "DISCHARGING",
                "temperature_c": 44,
            },
            "thermal": {"severity": 2},
        }

        conditions = self.alerts.build_alert_conditions(
            status,
            resources,
            power,
            settings,
        )
        keys = {condition["alert_key"] for condition in conditions}

        self.assertEqual(
            keys,
            {
                "server:database",
                "service:supervisor",
                "charger:unplugged",
                "battery:low",
                "thermal:high",
                "storage:full",
            },
        )
        self.assertNotIn("service:transmission", keys)

    def test_deduplication_cooldown_and_resolution(self):
        condition = self.alerts.alert_condition(
            "storage:full",
            "storage",
            "warning",
            "Stocare plină",
            "90% ocupat",
        )
        first_time = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)

        first = self.database.sync_system_alert_conditions(
            [condition],
            60,
            now=first_time,
        )
        suppressed = self.database.sync_system_alert_conditions(
            [condition],
            60,
            now=first_time + timedelta(minutes=30),
        )
        repeated = self.database.sync_system_alert_conditions(
            [condition],
            60,
            now=first_time + timedelta(minutes=61),
        )
        resolved = self.database.sync_system_alert_conditions(
            [],
            60,
            now=first_time + timedelta(minutes=62),
        )

        self.assertEqual(first[0]["event_type"], "triggered")
        self.assertEqual(suppressed, [])
        self.assertEqual(repeated[0]["event_type"], "repeated")
        self.assertEqual(resolved[0]["event_type"], "resolved")
        self.assertEqual(self.database.list_active_system_alerts(), [])

    def test_management_routes_are_admin_only(self):
        self.assertEqual(
            self.client.get("/api/system/alerts").status_code,
            401,
        )
        self.assertEqual(self.login("member").status_code, 200)
        self.assertEqual(
            self.client.get("/api/system/alerts").status_code,
            403,
        )

    def test_admin_can_save_settings_and_create_test_alert(self):
        self.assertEqual(self.login("admin").status_code, 200)
        settings = self.database.get_system_alert_settings()
        settings.pop("updated_at")
        settings["battery_low_percent"] = 30
        settings["cooldown_minutes"] = 180

        response = self.client.post(
            "/api/system/alerts/settings",
            json=settings,
        )
        test_response = self.client.post("/api/system/alerts/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["settings"]["battery_low_percent"],
            30,
        )
        self.assertEqual(test_response.status_code, 201)
        history = self.client.get("/api/system/alerts").get_json()["alerts"]
        self.assertEqual(history[-1]["event_type"], "test")

    def test_invalid_settings_are_rejected(self):
        self.login("admin")
        response = self.client.post(
            "/api/system/alerts/settings",
            json={"enabled": True},
        )

        self.assertEqual(response.status_code, 400)

    def test_paired_device_feed_returns_and_acknowledges_events(self):
        token = "device-secret-token"
        code_hash = hashlib.sha256(b"pair-code").hexdigest()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.database.create_monitor_pairing_code(code_hash, self.admin_id)
        device = self.database.consume_monitor_pairing_code(
            code_hash,
            "Telefon principal",
            token_hash,
        )
        event_id = self.database.record_system_alert_event(
            self.alerts.alert_condition(
                "test:manual",
                "test",
                "info",
                "Test",
                "Mesaj de test",
            ),
            event_type="test",
        )
        headers = {"Authorization": f"Bearer {token}"}

        feed = self.client.get(
            "/api/system/alerts/feed",
            headers=headers,
        )
        acknowledgement = self.client.post(
            "/api/system/alerts/feed/ack",
            headers=headers,
            json={"event_ids": [event_id]},
        )
        empty_feed = self.client.get(
            "/api/system/alerts/feed",
            headers=headers,
        )

        self.assertIsNotNone(device)
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(feed.get_json()["alerts"][0]["id"], event_id)
        self.assertIn("configuration_version", feed.get_json())
        self.assertEqual(acknowledgement.status_code, 200)
        self.assertEqual(acknowledgement.get_json()["acknowledged"], 1)
        self.assertEqual(empty_feed.get_json()["alerts"], [])

    def test_device_feed_rejects_missing_bearer_token(self):
        self.assertEqual(
            self.client.get("/api/system/alerts/feed").status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()
