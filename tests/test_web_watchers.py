import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


class WebWatcherTest(unittest.TestCase):
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
        cls.database.create_user("admin", "test-password", role="admin")
        cls.database.create_user("member", "test-password", role="user")
        cls.watchers = importlib.import_module("app.web_watchers")
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
            connection.execute("DELETE FROM web_watchers")
            connection.execute("DELETE FROM system_alert_deliveries")
            connection.execute("DELETE FROM system_alert_events")
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

    def create_watcher(self, mode="change", needle=None):
        watcher_id = self.database.create_web_watcher(
            "Test",
            "https://example.com/page",
            mode,
            needle,
            15,
        )
        return self.database.find_web_watcher(watcher_id)

    def test_admin_crud_routes(self):
        payload = {
            "name": "Stoc produs",
            "url": "https://example.com/product",
            "mode": "contains",
            "needle": "în stoc",
            "interval_minutes": 30,
            "enabled": True,
        }

        self.assertEqual(self.client.get("/api/watchers").status_code, 401)
        self.login("member")
        self.assertEqual(self.client.get("/api/watchers").status_code, 403)
        self.client.post("/api/auth/logout")
        self.login("admin")

        with patch.object(
            self.watchers,
            "validate_public_url",
            side_effect=lambda value: value,
        ):
            created = self.client.post("/api/watchers", json=payload)

        watcher_id = created.get_json()["id"]
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            self.client.get("/api/watchers").get_json()["watchers"][0]["name"],
            "Stoc produs",
        )
        self.assertEqual(
            self.client.patch(
                f"/api/watchers/{watcher_id}/enabled",
                json={"enabled": False},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(f"/api/watchers/{watcher_id}").status_code,
            200,
        )

    def test_change_mode_builds_baseline_then_alerts(self):
        watcher = self.create_watcher()
        baseline = self.watchers.check_web_watcher(
            watcher,
            fetcher=lambda _url: "prima versiune",
            now=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
        )
        changed = self.watchers.check_web_watcher(
            self.database.find_web_watcher(watcher["id"]),
            fetcher=lambda _url: "a doua versiune",
            now=datetime(2026, 9, 12, 10, 16, tzinfo=timezone.utc),
        )
        events = self.database.list_system_alert_events()

        self.assertEqual(baseline["status"], "ok")
        self.assertTrue(changed["changed"])
        self.assertEqual(events[0]["category"], "watcher")
        self.assertIn("Pagină modificată", events[0]["title"])

    def test_phrase_mode_alerts_only_on_transition(self):
        watcher = self.create_watcher("contains", "disponibil")
        first = self.watchers.check_web_watcher(
            watcher,
            fetcher=lambda _url: "produs epuizat momentan",
        )
        second = self.watchers.check_web_watcher(
            self.database.find_web_watcher(watcher["id"]),
            fetcher=lambda _url: "produs disponibil acum",
        )
        third = self.watchers.check_web_watcher(
            self.database.find_web_watcher(watcher["id"]),
            fetcher=lambda _url: "produs disponibil acum",
        )

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "alert")
        self.assertEqual(third["status"], "alert")
        self.assertEqual(len(self.database.list_system_alert_events()), 1)

    def test_three_failures_create_one_alert_and_recovery(self):
        watcher = self.create_watcher()

        for _attempt in range(3):
            self.watchers.check_web_watcher(
                self.database.find_web_watcher(watcher["id"]),
                fetcher=lambda _url: (_ for _ in ()).throw(
                    ValueError("indisponibil")
                ),
            )

        self.watchers.check_web_watcher(
            self.database.find_web_watcher(watcher["id"]),
            fetcher=lambda _url: "pagina a revenit",
        )
        events = self.database.list_system_alert_events()

        self.assertEqual([event["event_type"] for event in events], [
            "triggered",
            "resolved",
        ])

    def test_local_addresses_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "publice"):
            self.watchers.validate_public_url("http://127.0.0.1:8080")

    def test_html_normalization_ignores_script_and_spacing(self):
        normalized = self.watchers.normalize_page_content(
            "<html><style>x</style><body> Bună   lume <script>secret</script></body></html>",
            "text/html",
        )
        self.assertEqual(normalized, "Bună lume")


if __name__ == "__main__":
    unittest.main()
