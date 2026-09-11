import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "cloud-migrate.py"


def load_module():
    specification = importlib.util.spec_from_file_location(
        "cloud_migrate_tested", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class CloudMigrationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "cloud-in-buzunar-data"
        self.backups = self.data / "backups"
        self.backups.mkdir(parents=True)
        self.module.DATA_DIR = self.data
        self.module.BACKUP_DIR = self.backups
        self.module.DEFAULT_EXPORT_DIR = self.root / "exports"

        self.core = self.backups / "cloud-in-buzunar-20260911T120000000000Z.tar.gz"
        self.core.write_bytes(b"validated application backup")
        self.core_checksum = Path(f"{self.core}.sha256")
        self.core_checksum.write_text(
            f"{self.module.sha256_file(self.core)}  {self.core.name}\n",
            encoding="utf-8",
        )
        (self.data / "autostart.conf").write_text(
            "START_WEB=true\n", encoding="utf-8"
        )
        (self.data / "models").mkdir()
        (self.data / "models" / "model.gguf").write_bytes(b"model")
        (self.data / "media").mkdir()
        (self.data / "media" / "video.mp4").write_bytes(b"video")

    def tearDown(self):
        self.temporary.cleanup()

    def create_export(self, **include):
        selected = {"models": False, "media": False, "recordings": False}
        selected.update(include)
        output = self.root / "portable.tar.gz"
        with patch("app.backup.create_backup", return_value=self.core):
            result = self.module.create_export(output, selected)
        self.assertEqual(result["archive"], str(output.resolve()))
        return output

    def test_default_export_excludes_large_optional_content(self):
        output = self.create_export()
        verified = self.module.verify_archive(output)
        paths = {entry["path"] for entry in verified["manifest"]["files"]}

        self.assertIn("payload/config/autostart.conf", paths)
        self.assertFalse(any(path.startswith("payload/models/") for path in paths))
        self.assertFalse(any(path.startswith("payload/media/") for path in paths))
        self.assertTrue(Path(f"{output}.sha256").is_file())

    def test_optional_content_requires_explicit_export_switch(self):
        output = self.create_export(models=True, media=True)
        paths = {
            entry["path"]
            for entry in self.module.verify_archive(output)["manifest"]["files"]
        }
        self.assertIn("payload/models/model.gguf", paths)
        self.assertIn("payload/media/video.mp4", paths)

    def test_modified_payload_fails_checksum_validation(self):
        output = self.create_export()
        corrupted = self.root / "corrupted.tar.gz"
        with tarfile.open(output, "r:gz") as source, tarfile.open(corrupted, "w:gz") as target:
            for member in source.getmembers():
                content = source.extractfile(member).read()
                if member.name == "payload/config/autostart.conf":
                    content = b"START_WEB=false\n"
                    member.size = len(content)
                target.addfile(member, io.BytesIO(content))

        with self.assertRaisesRegex(self.module.MigrationError, "Checksum invalid"):
            self.module.verify_archive(corrupted)

    def test_path_traversal_is_rejected_before_extraction(self):
        archive_path = self.root / "traversal.tar.gz"
        payload = b"bad"
        manifest = {
            "format": self.module.FORMAT_NAME,
            "version": self.module.FORMAT_VERSION,
            "optional_content": {
                "models": False,
                "media": False,
                "recordings": False,
            },
            "files": [
                {
                    "path": "payload/../escape",
                    "size": len(payload),
                    "sha256": self.module.hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
        encoded = json.dumps(manifest).encode("utf-8")
        with tarfile.open(archive_path, "w:gz") as archive:
            payload_info = tarfile.TarInfo("payload/../escape")
            payload_info.size = len(payload)
            archive.addfile(payload_info, io.BytesIO(payload))
            manifest_info = tarfile.TarInfo("manifest.json")
            manifest_info.size = len(encoded)
            archive.addfile(manifest_info, io.BytesIO(encoded))

        with self.assertRaisesRegex(self.module.MigrationError, "traversarea"):
            self.module.verify_archive(archive_path)
        self.assertFalse((self.root / "escape").exists())

    def test_noninteractive_import_requires_exact_archive_name(self):
        archive = self.root / "migration.tar.gz"
        archive.touch()
        with self.assertRaisesRegex(self.module.MigrationError, "--confirm"):
            self.module.require_confirmation(archive, True, "different.tar.gz")
        self.module.require_confirmation(archive, True, "migration.tar.gz")

    def test_unexpected_configuration_path_is_rejected(self):
        manifest = {
            "optional_content": {
                "models": False,
                "media": False,
                "recordings": False,
            },
            "files": [
                {
                    "path": "payload/config/not-allowed",
                    "size": 0,
                    "sha256": "0" * 64,
                }
            ],
        }
        with self.assertRaisesRegex(self.module.MigrationError, "nepermis"):
            self.module.validate_manifest_files(manifest)

    def test_import_restores_configuration_only_after_validation_and_confirmation(self):
        output = self.create_export()
        (self.data / "cloud-in-buzunar.sqlite3").write_bytes(b"current database")
        (self.data / "autostart.conf").write_text(
            "START_WEB=false\n", encoding="utf-8"
        )
        safety_result = {"archive": str(self.root / "safety.tar.gz")}
        restore_result = {
            "safety_backup": "application-safety.tar.gz",
            "restored_backup": self.core.name,
        }

        with (
            patch.object(self.module, "create_export", return_value=safety_result),
            patch("app.backup.restore_backup", return_value=restore_result),
        ):
            result = self.module.restore_export(
                output,
                yes=True,
                confirmation=output.name,
            )

        self.assertEqual(
            (self.data / "autostart.conf").read_text(encoding="utf-8"),
            "START_WEB=true\n",
        )
        self.assertEqual(result["safety_archive"], safety_result["archive"])


class InstallerScriptTests(unittest.TestCase):
    def test_installer_has_safe_local_one_command_flow(self):
        script = (PROJECT_DIR / "scripts" / "install-cloud-in-buzunar.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("set -Eeuo pipefail", script)
        self.assertIn("pkg install -y", script)
        self.assertIn("python -m venv", script)
        self.assertIn("initialize_database", script)
        self.assertIn("install-termux-autostart.sh", script)
        self.assertIn("cloud-migrate.py", script)
        self.assertIn("caddy", script)
        self.assertIn("rpc-save-upload-metadata=true", script)
        self.assertIn("--admin", script)
        self.assertNotIn("curl |", script)
        self.assertNotIn("curl -", script)


if __name__ == "__main__":
    unittest.main()
