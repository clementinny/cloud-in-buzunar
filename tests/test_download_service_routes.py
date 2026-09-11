import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


class DownloadServiceRoutesTest(unittest.TestCase):
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
        database.create_user(
            "admin",
            "test-password",
            role="admin",
        )

        cls.main = importlib.import_module("app.main")
        cls.downloads = importlib.import_module("app.downloads")
        cls.client = cls.main.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

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
        response = self.client.post(
            "/api/auth/login",
            json={
                "username": "admin",
                "password": "test-password",
            },
        )
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        with self.client.session_transaction() as user_session:
            user_session.clear()

    def test_admin_can_stop_transmission(self):
        with patch.object(
            self.downloads,
            "set_transmission_enabled",
            return_value=False,
        ) as set_enabled:
            response = self.client.post(
                "/api/downloads/transmission/service",
                json={"enabled": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["enabled"])
        set_enabled.assert_called_once_with(False)

    def test_service_control_rejects_non_boolean_value(self):
        response = self.client.post(
            "/api/downloads/transmission/service",
            json={"enabled": "false"},
        )

        self.assertEqual(response.status_code, 400)

    def test_list_marks_intentionally_stopped_service(self):
        with (
            patch.object(
                self.downloads,
                "transmission_is_enabled",
                return_value=False,
            ),
            patch.object(
                self.downloads,
                "get_all_downloads",
                return_value=[],
            ),
            patch.object(
                self.downloads,
                "get_transmission_downloads",
            ) as get_torrents,
        ):
            response = self.client.get("/api/downloads")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["services"]["transmission"], "stopped")
        self.assertFalse(payload["transmission"]["online"])
        get_torrents.assert_not_called()


if __name__ == "__main__":
    unittest.main()
