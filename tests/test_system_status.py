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


if __name__ == "__main__":
    unittest.main()
