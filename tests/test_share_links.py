import hashlib
import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


class ShareLinkRoutesTest(unittest.TestCase):
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
        cls.database.create_user("admin", "admin-password", role="admin")
        cls.database.create_user("owner", "owner-password", role="user")
        cls.database.create_user("other", "other-password", role="user")
        cls.main = importlib.import_module("app.main")
        cls.owner = cls.database.find_user_by_username("owner")
        cls.other = cls.database.find_user_by_username("other")

        owner_root = cls.main.app.config["UPLOAD_DIR"] / str(cls.owner["id"])
        owner_root.mkdir(parents=True, exist_ok=True)
        (owner_root / "document.txt").write_text("secret", encoding="utf-8")

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
        self.client = self.main.app.test_client()

    def login(self, username, password=None):
        return self.client.post(
            "/api/auth/login",
            json={
                "username": username,
                "password": password or f"{username}-password",
            },
        )

    def create_share(self, **overrides):
        payload = {
            "path": "document.txt",
            "expiry_hours": 24,
            "max_downloads": None,
        }
        payload.update(overrides)
        return self.client.post("/api/shares", json=payload)

    def test_owner_creates_public_download_without_storing_raw_token(self):
        self.assertEqual(self.login("owner").status_code, 200)
        response = self.create_share(max_downloads=2)

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        raw_token = payload["url"].rsplit("/", 1)[-1]
        connection = self.database.open_database()

        try:
            stored = connection.execute(
                "SELECT token_hash, relative_path FROM file_shares WHERE id = ?",
                (payload["id"],),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(
            stored["token_hash"],
            hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(stored["token_hash"], raw_token)
        self.assertNotIn(self.temporary_directory.name, response.get_data(as_text=True))

        self.client.post("/api/auth/logout")
        download = self.client.get(payload["url"])

        try:
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.data, b"secret")
        finally:
            download.close()

    def test_download_limit_is_enforced(self):
        self.login("owner")
        url = self.create_share(max_downloads=1).get_json()["url"]
        self.client.post("/api/auth/logout")

        download = self.client.get(url)
        self.assertEqual(download.status_code, 200)
        download.close()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_expired_and_revoked_links_are_unavailable(self):
        self.login("owner")
        created = self.create_share().get_json()
        expired_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        connection = self.database.open_database()

        try:
            connection.execute(
                "UPDATE file_shares SET expires_at = ? WHERE id = ?",
                (expired_at, created["id"]),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(self.client.get(created["url"]).status_code, 404)

        active = self.create_share().get_json()
        self.assertEqual(
            self.client.delete(f"/api/shares/{active['id']}").status_code,
            200,
        )
        self.assertEqual(self.client.get(active["url"]).status_code, 404)

    def test_owner_cannot_share_another_vault_or_revoke_its_share(self):
        self.login("owner")
        forbidden = self.create_share(owner_user_id=self.other["id"])
        self.assertEqual(forbidden.status_code, 403)

        own_share = self.create_share().get_json()
        self.client.post("/api/auth/logout")
        self.login("other")
        response = self.client.delete(f"/api/shares/{own_share['id']}")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_share_selected_vault_and_list_all_shares(self):
        self.login("admin", "admin-password")
        response = self.create_share(owner_user_id=self.owner["id"])
        self.assertEqual(response.status_code, 201)

        listing = self.client.get("/api/shares")
        self.assertEqual(listing.status_code, 200)
        self.assertGreaterEqual(listing.get_json()["count"], 1)
        self.assertEqual(
            listing.get_json()["shares"][0]["owner"]["username"],
            "owner",
        )

    def test_invalid_paths_and_settings_are_rejected(self):
        self.login("owner")
        self.assertEqual(
            self.create_share(path="../outside.txt").status_code,
            400,
        )
        self.assertEqual(
            self.create_share(expiry_hours=2).status_code,
            400,
        )
        self.assertEqual(
            self.create_share(max_downloads=0).status_code,
            400,
        )

    def test_share_api_requires_login(self):
        self.assertEqual(self.create_share().status_code, 401)
        self.assertEqual(self.client.get("/api/shares").status_code, 401)


if __name__ == "__main__":
    unittest.main()
