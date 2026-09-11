import argparse
import hashlib
import json
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
UPLOAD_DIR = DATA_DIR / "uploads"
MEDIA_DIR = DATA_DIR / "media"
DATABASE_PATH = DATA_DIR / "cloud-in-buzunar.sqlite3"
MESSAGE_KEY_PATH = DATA_DIR / "message-encryption-key"
BACKUP_DIR = DATA_DIR / "backups"

DEFAULT_KEEP = 7


def calculate_sha256(path):
    digest = hashlib.sha256()

    with path.open("rb") as backup_file:
        for chunk in iter(
            lambda: backup_file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def create_database_snapshot(destination):
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}"
        )

    source = sqlite3.connect(DATABASE_PATH)
    snapshot = sqlite3.connect(destination)

    try:
        source.backup(snapshot)
    finally:
        snapshot.close()
        source.close()


def remove_old_backups(keep):
    archives = sorted(
        BACKUP_DIR.glob(
            "cloud-in-buzunar-*.tar.gz"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for archive in archives[keep:]:
        checksum_file = Path(
            f"{archive}.sha256"
        )

        archive.unlink(missing_ok=True)
        checksum_file.unlink(missing_ok=True)


def create_backup(keep=DEFAULT_KEEP):
    if keep < 1:
        raise ValueError(
            "At least one backup must be kept"
        )

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    BACKUP_DIR.chmod(0o700)

    created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    archive_name = (
        f"cloud-in-buzunar-{timestamp}.tar.gz"
    )
    archive_path = BACKUP_DIR / archive_name

    with tempfile.TemporaryDirectory(
        dir=BACKUP_DIR
    ) as temporary_directory:
        temporary_path = Path(
            temporary_directory
        )

        database_snapshot = (
            temporary_path /
            "cloud-in-buzunar.sqlite3"
        )
        manifest_path = (
            temporary_path / "manifest.json"
        )
        temporary_archive = (
            temporary_path / archive_name
        )

        create_database_snapshot(
            database_snapshot
        )

        manifest = {
            "service": "CloudInBuzunar",
            "created_at": (
                created_at.isoformat()
            ),
            "database": (
                "cloud-in-buzunar.sqlite3"
            ),
            "uploads_included": (
                UPLOAD_DIR.is_dir()
            ),
            "media_included": False,
            "media_directory": str(MEDIA_DIR),
            "message_encryption_key_included": (
                MESSAGE_KEY_PATH.is_file()
            ),
        }

        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with tarfile.open(
            temporary_archive,
            "w:gz",
        ) as archive:
            archive.add(
                database_snapshot,
                arcname=(
                    "cloud-in-buzunar.sqlite3"
                ),
            )
            archive.add(
                manifest_path,
                arcname="manifest.json",
            )

            if MESSAGE_KEY_PATH.is_file():
                archive.add(
                    MESSAGE_KEY_PATH,
                    arcname="message-encryption-key",
                )

            if UPLOAD_DIR.is_dir():
                archive.add(
                    UPLOAD_DIR,
                    arcname="uploads",
                )

        temporary_archive.replace(
            archive_path
        )

    archive_path.chmod(0o600)

    checksum = calculate_sha256(
        archive_path
    )
    checksum_path = Path(
        f"{archive_path}.sha256"
    )

    checksum_path.write_text(
        f"{checksum}  {archive_name}\n",
        encoding="utf-8",
    )
    checksum_path.chmod(0o600)

    remove_old_backups(keep)

    return archive_path


def list_backups():
    archives = sorted(
        BACKUP_DIR.glob(
            "cloud-in-buzunar-*.tar.gz"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not archives:
        print("No backups found")
        return

    for archive in archives:
        size_mb = (
            archive.stat().st_size /
            (1024 * 1024)
        )

        print(
            f"{archive.name}  "
            f"{size_mb:.2f} MB"
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Create and inspect "
            "CloudInBuzunar backups"
        )
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create_parser = commands.add_parser(
        "create",
        help="Create a new backup",
    )
    create_parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP,
    )

    commands.add_parser(
        "list",
        help="List existing backups",
    )

    return parser


def main():
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command == "create":
        archive_path = create_backup(
            arguments.keep
        )
        print(
            f"Backup created: {archive_path}"
        )
        return 0

    if arguments.command == "list":
        list_backups()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
