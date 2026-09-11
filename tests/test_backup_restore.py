import hashlib
import importlib
import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BackupRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_home = os.environ.get("HOME")
        self.original_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = self.temporary_directory.name
        os.environ["USERPROFILE"] = self.temporary_directory.name

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

        self.database = importlib.import_module("app.database")
        self.database.initialize_database()
        self.admin_id = self.database.create_user(
            "admin",
            "admin-password",
            role="admin",
        )
        self.member_id = self.database.create_user(
            "member",
            "member-password",
            role="user",
        )
        self.backup = importlib.import_module("app.backup")

    def tearDown(self):
        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

        if self.original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.original_home

        if self.original_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self.original_userprofile

        self.temporary_directory.cleanup()

    def login(self, client, username):
        return client.post(
            "/api/auth/login",
            json={
                "username": username,
                "password": f"{username}-password",
            },
        )

    def test_restore_round_trip_creates_safety_backup(self):
        user_uploads = self.backup.UPLOAD_DIR / str(self.member_id)
        user_uploads.mkdir(parents=True)
        stored_file = user_uploads / "document.txt"
        stored_file.write_text("original", encoding="utf-8")

        self.database.create_private_message(
            self.admin_id,
            self.member_id,
            "Mesaj păstrat în backup",
        )
        original_key = self.backup.MESSAGE_KEY_PATH.read_bytes()
        archive = self.backup.create_backup(keep=20)

        self.database.create_user(
            "later-user",
            "later-user-password",
        )
        stored_file.write_text("changed", encoding="utf-8")
        (user_uploads / "new.txt").write_text("new", encoding="utf-8")

        result = self.backup.restore_backup(archive.name, keep=20)

        self.assertEqual(result["restored_backup"], archive.name)
        self.assertTrue(
            (self.backup.BACKUP_DIR / result["safety_backup"]).is_file()
        )
        self.assertIsNone(
            self.database.find_user_by_username("later-user")
        )
        self.assertEqual(stored_file.read_text(encoding="utf-8"), "original")
        self.assertFalse((user_uploads / "new.txt").exists())
        self.assertEqual(
            self.backup.MESSAGE_KEY_PATH.read_bytes(),
            original_key,
        )

        _contact, messages = self.database.get_private_conversation(
            self.member_id,
            self.admin_id,
        )
        self.assertEqual(messages[0]["content"], "Mesaj păstrat în backup")

    def test_tampered_archive_is_rejected(self):
        archive = self.backup.create_backup()

        with archive.open("ab") as backup_file:
            backup_file.write(b"tampered")

        with self.assertRaisesRegex(
            self.backup.BackupValidationError,
            "Checksumul",
        ):
            self.backup.verify_backup(archive.name)

    def test_failed_restore_rolls_back_current_state(self):
        user_uploads = self.backup.UPLOAD_DIR / str(self.member_id)
        user_uploads.mkdir(parents=True)
        stored_file = user_uploads / "document.txt"
        stored_file.write_text("backup-version", encoding="utf-8")
        archive = self.backup.create_backup(keep=20)

        self.database.create_user(
            "current-user",
            "current-user-password",
        )
        stored_file.write_text("current-version", encoding="utf-8")

        with patch.object(
            self.database,
            "initialize_database",
            side_effect=RuntimeError("simulated failure"),
        ):
            with self.assertRaises(self.backup.BackupRestoreError):
                self.backup.restore_backup(archive.name, keep=20)

        self.assertIsNotNone(
            self.database.find_user_by_username("current-user")
        )
        self.assertEqual(
            stored_file.read_text(encoding="utf-8"),
            "current-version",
        )
        self.assertGreaterEqual(
            len(list(self.backup.BACKUP_DIR.glob("*.tar.gz"))),
            2,
        )

    def test_path_traversal_archive_is_rejected(self):
        self.backup.BACKUP_DIR.mkdir(parents=True)
        archive = self.backup.BACKUP_DIR / (
            "cloud-in-buzunar-20260911T120000000000Z.tar.gz"
        )

        with tarfile.open(archive, "w:gz") as malicious_archive:
            member = tarfile.TarInfo("../outside.txt")
            payload = b"outside"
            member.size = len(payload)
            malicious_archive.addfile(member, io.BytesIO(payload))

        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        Path(f"{archive}.sha256").write_text(
            f"{checksum}  {archive.name}\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            self.backup.BackupValidationError,
            "în afara zonei permise",
        ):
            self.backup.verify_backup(archive.name)

        self.assertFalse(
            (Path(self.temporary_directory.name) / "outside.txt").exists()
        )

    def test_admin_routes_require_auth_and_exact_confirmation(self):
        archive = self.backup.create_backup()
        main = importlib.import_module("app.main")
        backup_admin = importlib.import_module("app.backup_admin")
        client = main.app.test_client()

        self.assertEqual(client.get("/api/admin/backups").status_code, 401)
        self.assertEqual(self.login(client, "member").status_code, 200)
        self.assertEqual(client.get("/api/admin/backups").status_code, 403)

        with client.session_transaction() as user_session:
            user_session.clear()

        self.assertEqual(self.login(client, "admin").status_code, 200)
        list_response = client.get("/api/admin/backups")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json()["backups"][0]["name"], archive.name)

        restore_url = f"/api/admin/backups/{archive.name}/restore"
        wrong_confirmation = client.post(
            restore_url,
            json={"confirmation": "wrong"},
        )
        self.assertEqual(wrong_confirmation.status_code, 400)

        restore_result = {
            "restored_backup": archive.name,
            "safety_backup": "safety.tar.gz",
            "restored_at": "2026-09-11T12:00:00+00:00",
        }

        with (
            patch.object(
                backup_admin,
                "restore_backup",
                return_value=restore_result,
            ),
            patch.object(backup_admin, "schedule_gunicorn_reload") as reload_mock,
        ):
            response = client.post(
                restore_url,
                json={"confirmation": archive.name},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["restart_scheduled"])
        reload_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
