import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class MigrationAdminRoutesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("HOME")
        self.previous_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = self.temporary.name
        os.environ["USERPROFILE"] = self.temporary.name
        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

        self.database = importlib.import_module("app.database")
        self.database.initialize_database()
        self.database.create_user("admin", "admin-password", role="admin")
        self.database.create_user("member", "member-password", role="user")
        self.main = importlib.import_module("app.main")
        self.module = importlib.import_module("app.migration_admin")
        self.client = self.main.app.test_client()

    def tearDown(self):
        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]
        if self.previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.previous_home
        if self.previous_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self.previous_userprofile
        self.temporary.cleanup()

    def login(self, username):
        return self.client.post(
            "/api/auth/login",
            json={"username": username, "password": f"{username}-password"},
        )

    def test_routes_require_administrator(self):
        self.assertEqual(self.client.get("/api/admin/migrations").status_code, 401)
        self.login("member")
        self.assertEqual(self.client.get("/api/admin/migrations").status_code, 403)

    def test_admin_can_list_and_download_exact_migration(self):
        root = Path(self.temporary.name) / "migrations"
        root.mkdir()
        archive = root / "cloud-in-buzunar-migration-20260912T120000Z.tar.gz"
        archive.write_bytes(b"portable")
        checksum = "a" * 64
        Path(f"{archive}.sha256").write_text(
            f"{checksum}  {archive.name}\n", encoding="utf-8"
        )
        self.module.MIGRATION_DIR = root
        self.login("admin")

        listing = self.client.get("/api/admin/migrations")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()["migrations"][0]["sha256"], checksum)
        download = self.client.get(
            f"/api/admin/migrations/{archive.name}/download"
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b"portable")

    def test_create_rejects_unknown_or_non_boolean_options(self):
        self.login("admin")
        self.assertEqual(
            self.client.post("/api/admin/migrations", json={"other": True}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/api/admin/migrations", json={"models": "yes"}).status_code,
            400,
        )

    def test_create_uses_compact_defaults(self):
        self.login("admin")
        root = Path(self.temporary.name) / "migrations"
        root.mkdir()
        archive = root / "cloud-in-buzunar-migration-20260912T130000Z.tar.gz"
        archive.write_bytes(b"portable")
        Path(f"{archive}.sha256").write_text(
            f"{'b' * 64}  {archive.name}\n", encoding="utf-8"
        )
        self.module.MIGRATION_DIR = root

        fake_module = Mock()
        fake_module.default_export_path.return_value = archive
        fake_module.create_export.return_value = {"archive": str(archive)}
        with patch.object(self.module, "load_migration_module", return_value=fake_module):
            response = self.client.post("/api/admin/migrations", json={})

        self.assertEqual(response.status_code, 201)
        fake_module.create_export.assert_called_once_with(
            archive,
            {"models": False, "media": False, "recordings": False},
        )


if __name__ == "__main__":
    unittest.main()
