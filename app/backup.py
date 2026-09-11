import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
UPLOAD_DIR = DATA_DIR / "uploads"
MEDIA_DIR = DATA_DIR / "media"
DATABASE_PATH = DATA_DIR / "cloud-in-buzunar.sqlite3"
MESSAGE_KEY_PATH = DATA_DIR / "message-encryption-key"
BACKUP_DIR = DATA_DIR / "backups"

DEFAULT_KEEP = 7
BACKUP_NAME_PATTERN = re.compile(
    r"^cloud-in-buzunar-\d{8}T\d{12}Z\.tar\.gz$"
)
RESTORE_LOCK_PATH = DATA_DIR / "runtime" / "backup-restore.lock"
MESSAGE_TOKEN_PREFIX = "aes256ctr-hmacsha256:v1:"


class BackupValidationError(ValueError):
    pass


class BackupRestoreError(RuntimeError):
    pass


class BackupRestoreInProgressError(BackupRestoreError):
    pass


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


def resolve_backup_path(backup_name):
    if not isinstance(backup_name, str):
        raise BackupValidationError("Numele backupului este invalid.")

    normalized_name = backup_name.strip()

    if not BACKUP_NAME_PATTERN.fullmatch(normalized_name):
        raise BackupValidationError("Numele backupului este invalid.")

    backup_root = BACKUP_DIR.resolve()
    archive_path = (backup_root / normalized_name).resolve()

    if archive_path.parent != backup_root:
        raise BackupValidationError("Calea backupului este invalidă.")

    if not archive_path.is_file():
        raise FileNotFoundError(
            f"Backupul nu există: {normalized_name}"
        )

    return archive_path


def read_expected_checksum(archive_path):
    checksum_path = Path(f"{archive_path}.sha256")

    if not checksum_path.is_file():
        raise BackupValidationError(
            "Fișierul SHA-256 al backupului lipsește."
        )

    fields = checksum_path.read_text(
        encoding="utf-8"
    ).strip().split()

    if (
        len(fields) != 2
        or fields[1] != archive_path.name
        or re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]) is None
    ):
        raise BackupValidationError(
            "Fișierul SHA-256 al backupului este invalid."
        )

    return fields[0].lower()


def verify_backup_checksum(archive_path):
    expected_checksum = read_expected_checksum(archive_path)
    actual_checksum = calculate_sha256(archive_path).lower()

    if not hmac.compare_digest(
        expected_checksum,
        actual_checksum,
    ):
        raise BackupValidationError(
            "Checksumul backupului nu corespunde."
        )

    return actual_checksum


def validate_archive_member(member):
    name = member.name

    if not name or "\\" in name:
        raise BackupValidationError(
            "Backupul conține o cale invalidă."
        )

    pure_path = PurePosixPath(name)

    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise BackupValidationError(
            "Backupul încearcă să scrie în afara zonei permise."
        )

    top_level = pure_path.parts[0]
    allowed_top_level = {
        "manifest.json",
        "cloud-in-buzunar.sqlite3",
        "message-encryption-key",
        "uploads",
    }

    if top_level not in allowed_top_level:
        raise BackupValidationError(
            f"Fișier neașteptat în backup: {name}"
        )

    if top_level != "uploads" and len(pure_path.parts) != 1:
        raise BackupValidationError(
            f"Cale neașteptată în backup: {name}"
        )

    if not (member.isdir() or member.isfile()):
        raise BackupValidationError(
            "Backupul conține linkuri sau fișiere speciale."
        )

    return pure_path


def extract_validated_archive(archive_path, destination):
    destination_root = destination.resolve()

    try:
        archive = tarfile.open(archive_path, "r:gz")
    except (tarfile.TarError, OSError) as error:
        raise BackupValidationError(
            "Arhiva backupului nu poate fi deschisă."
        ) from error

    with archive:
        members = archive.getmembers()
        member_names = set()

        for member in members:
            pure_path = validate_archive_member(member)

            if member.name in member_names:
                raise BackupValidationError(
                    f"Cale duplicată în backup: {member.name}"
                )

            member_names.add(member.name)
            target = destination.joinpath(*pure_path.parts).resolve()

            if (
                target != destination_root
                and destination_root not in target.parents
            ):
                raise BackupValidationError(
                    "Backupul conține o cale nesigură."
                )

            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)

            if source is None:
                raise BackupValidationError(
                    f"Fișierul {member.name} nu poate fi citit."
                )

            with source, target.open("wb") as output_file:
                shutil.copyfileobj(source, output_file)


def read_backup_manifest(extracted_directory):
    manifest_path = extracted_directory / "manifest.json"

    if not manifest_path.is_file():
        raise BackupValidationError(
            "Manifestul backupului lipsește."
        )

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise BackupValidationError(
            "Manifestul backupului este invalid."
        ) from error

    if (
        not isinstance(manifest, dict)
        or manifest.get("service") != "CloudInBuzunar"
        or manifest.get("database")
        != "cloud-in-buzunar.sqlite3"
    ):
        raise BackupValidationError(
            "Manifestul nu aparține CloudInBuzunar."
        )

    return manifest


def validate_database_snapshot(database_path):
    if not database_path.is_file():
        raise BackupValidationError(
            "Baza de date lipsește din backup."
        )

    try:
        connection = sqlite3.connect(
            f"{database_path.resolve().as_uri()}?mode=ro",
            uri=True,
        )

        try:
            integrity = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()
            tables = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                )
            }
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise BackupValidationError(
            "Baza de date din backup nu poate fi citită."
        ) from error

    if integrity is None or integrity[0] != "ok":
        raise BackupValidationError(
            "Verificarea de integritate SQLite a eșuat."
        )

    if "users" not in tables:
        raise BackupValidationError(
            "Backupul nu conține tabela de utilizatori."
        )

    return tables


def database_requires_message_key(database_path, tables):
    if "private_messages" not in tables:
        return False

    connection = sqlite3.connect(database_path)

    try:
        row = connection.execute(
            """
            SELECT 1
            FROM private_messages
            WHERE content LIKE ?
            LIMIT 1
            """,
            (f"{MESSAGE_TOKEN_PREFIX}%",),
        ).fetchone()
    finally:
        connection.close()

    return row is not None


def validate_extracted_backup(extracted_directory):
    manifest = read_backup_manifest(extracted_directory)
    database_path = (
        extracted_directory / "cloud-in-buzunar.sqlite3"
    )
    tables = validate_database_snapshot(database_path)
    key_path = extracted_directory / "message-encryption-key"
    uploads_path = extracted_directory / "uploads"

    if (
        database_requires_message_key(database_path, tables)
        and not key_path.is_file()
    ):
        raise BackupValidationError(
            "Backupul are mesaje criptate, dar cheia lor lipsește."
        )

    if manifest.get("message_encryption_key_included"):
        if not key_path.is_file():
            raise BackupValidationError(
                "Manifestul declară o cheie care lipsește."
            )

        try:
            import base64

            decoded_key = base64.urlsafe_b64decode(
                key_path.read_bytes().strip()
            )
        except (OSError, ValueError) as error:
            raise BackupValidationError(
                "Cheia mesajelor din backup este invalidă."
            ) from error

        if len(decoded_key) != 32:
            raise BackupValidationError(
                "Cheia mesajelor din backup este invalidă."
            )

    if manifest.get("uploads_included") and not uploads_path.is_dir():
        raise BackupValidationError(
            "Manifestul declară fișiere încărcate care lipsesc."
        )

    return {
        "manifest": manifest,
        "database_path": database_path,
        "key_path": key_path if key_path.is_file() else None,
        "uploads_path": (
            uploads_path if uploads_path.is_dir() else None
        ),
    }


def verify_backup(backup_name):
    archive_path = resolve_backup_path(backup_name)
    checksum = verify_backup_checksum(archive_path)

    with tempfile.TemporaryDirectory(
        dir=BACKUP_DIR
    ) as temporary_directory:
        extracted_directory = Path(temporary_directory)
        extract_validated_archive(
            archive_path,
            extracted_directory,
        )
        validated = validate_extracted_backup(extracted_directory)

    return {
        "name": archive_path.name,
        "sha256": checksum,
        "created_at": validated["manifest"].get("created_at"),
        "uploads_included": bool(
            validated["manifest"].get("uploads_included")
        ),
        "message_encryption_key_included": bool(
            validated["manifest"].get(
                "message_encryption_key_included"
            )
        ),
    }


@contextmanager
def backup_restore_lock():
    RESTORE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    if RESTORE_LOCK_PATH.is_file():
        try:
            lock_payload = json.loads(
                RESTORE_LOCK_PATH.read_text(encoding="utf-8")
            )
            lock_pid = int(lock_payload["pid"])
            os.kill(lock_pid, 0)
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            OSError,
        ):
            RESTORE_LOCK_PATH.unlink(missing_ok=True)

    try:
        descriptor = os.open(
            RESTORE_LOCK_PATH,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise BackupRestoreInProgressError(
            "O restaurare este deja în desfășurare."
        ) from error

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
            lock_file.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "started_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }
                )
            )

        yield
    finally:
        RESTORE_LOCK_PATH.unlink(missing_ok=True)


def restore_database_snapshot(source_path):
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(DATABASE_PATH)

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def replace_message_key(source_path):
    temporary_key = MESSAGE_KEY_PATH.with_name(
        f".{MESSAGE_KEY_PATH.name}.restore-{os.getpid()}"
    )
    shutil.copyfile(source_path, temporary_key)
    temporary_key.chmod(0o600)
    temporary_key.replace(MESSAGE_KEY_PATH)


def restore_backup(backup_name, keep=DEFAULT_KEEP):
    archive_path = resolve_backup_path(backup_name)

    with backup_restore_lock():
        verify_backup_checksum(archive_path)

        with tempfile.TemporaryDirectory(
            prefix="restore-",
            dir=BACKUP_DIR,
        ) as temporary_directory:
            working_directory = Path(temporary_directory)
            extracted_directory = working_directory / "archive"
            extracted_directory.mkdir()
            extract_validated_archive(
                archive_path,
                extracted_directory,
            )
            validated = validate_extracted_backup(
                extracted_directory
            )

            existing_backups = len(
                list(BACKUP_DIR.glob("cloud-in-buzunar-*.tar.gz"))
            )
            safety_backup = create_backup(
                keep=max(keep, existing_backups + 1)
            )
            current_database = working_directory / "current.sqlite3"
            create_database_snapshot(current_database)
            current_key = (
                MESSAGE_KEY_PATH.read_bytes()
                if MESSAGE_KEY_PATH.is_file()
                else None
            )
            prepared_uploads = working_directory / "uploads-new"
            previous_uploads = None
            uploads_swapped = False

            if validated["uploads_path"] is not None:
                shutil.copytree(
                    validated["uploads_path"],
                    prepared_uploads,
                )
            else:
                prepared_uploads.mkdir()

            try:
                restore_database_snapshot(
                    validated["database_path"]
                )

                if validated["key_path"] is not None:
                    replace_message_key(validated["key_path"])
                else:
                    MESSAGE_KEY_PATH.unlink(missing_ok=True)

                previous_uploads = working_directory / "uploads-old"

                if UPLOAD_DIR.exists():
                    UPLOAD_DIR.replace(previous_uploads)

                prepared_uploads.replace(UPLOAD_DIR)
                uploads_swapped = True

                from app.database import initialize_database

                initialize_database()
            except Exception as error:
                restore_database_snapshot(current_database)

                if current_key is None:
                    MESSAGE_KEY_PATH.unlink(missing_ok=True)
                else:
                    temporary_key = working_directory / "original-key"
                    temporary_key.write_bytes(current_key)
                    replace_message_key(temporary_key)

                if uploads_swapped and UPLOAD_DIR.exists():
                    shutil.rmtree(UPLOAD_DIR)

                if (
                    previous_uploads is not None
                    and previous_uploads.exists()
                ):
                    previous_uploads.replace(UPLOAD_DIR)

                raise BackupRestoreError(
                    "Restaurarea a eșuat; starea anterioară a fost refăcută."
                ) from error

    return {
        "restored_backup": archive_path.name,
        "safety_backup": safety_backup.name,
        "restored_at": datetime.now(timezone.utc).isoformat(),
    }


def get_backup_records():
    records = []

    for archive in sorted(
        BACKUP_DIR.glob("cloud-in-buzunar-*.tar.gz"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        checksum_path = Path(f"{archive}.sha256")
        record = {
            "name": archive.name,
            "size_bytes": archive.stat().st_size,
            "modified_at": datetime.fromtimestamp(
                archive.stat().st_mtime,
                timezone.utc,
            ).isoformat(),
            "checksum_available": checksum_path.is_file(),
            "created_at": None,
            "uploads_included": None,
            "message_encryption_key_included": None,
        }

        try:
            with tarfile.open(archive, "r:gz") as backup_archive:
                manifest_member = backup_archive.getmember(
                    "manifest.json"
                )

                if (
                    not manifest_member.isfile()
                    or manifest_member.size > 1024 * 1024
                ):
                    raise ValueError("Invalid manifest member")

                manifest_file = backup_archive.extractfile(
                    manifest_member
                )

                if manifest_file is not None:
                    with manifest_file:
                        manifest = json.load(manifest_file)

                    record["created_at"] = manifest.get("created_at")
                    record["uploads_included"] = bool(
                        manifest.get("uploads_included")
                    )
                    record[
                        "message_encryption_key_included"
                    ] = bool(
                        manifest.get(
                            "message_encryption_key_included"
                        )
                    )
        except (KeyError, OSError, tarfile.TarError, ValueError):
            record["manifest_invalid"] = True

        records.append(record)

    return records


def reload_gunicorn():
    project_directory = Path(__file__).resolve().parent.parent
    pattern = (
        f"{project_directory}/.venv/bin/gunicorn.*app.main:app"
    )

    try:
        result = subprocess.run(
            ["pgrep", "-o", "-f", pattern],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        pid = int(result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False

    if result.returncode != 0 or pid <= 1:
        return False

    try:
        os.kill(pid, signal.SIGHUP)
    except OSError:
        return False

    return True


def list_backups():
    archives = get_backup_records()

    if not archives:
        print("No backups found")
        return

    for archive in archives:
        size_mb = (
            archive["size_bytes"] /
            (1024 * 1024)
        )

        print(
            f"{archive['name']}  "
            f"{size_mb:.2f} MB"
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Create, verify and restore "
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

    verify_parser = commands.add_parser(
        "verify",
        help="Verify checksum, archive paths and SQLite integrity",
    )
    verify_parser.add_argument("backup_name")

    restore_parser = commands.add_parser(
        "restore",
        help="Safely restore a local backup",
    )
    restore_parser.add_argument("backup_name")
    restore_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation",
    )
    restore_parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Do not reload Gunicorn after a successful restore",
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

    if arguments.command == "verify":
        try:
            result = verify_backup(arguments.backup_name)
        except (FileNotFoundError, BackupValidationError) as error:
            print(f"Backup verification failed: {error}")
            return 1

        print(
            "Backup verified: "
            f"{result['name']}\nSHA-256: {result['sha256']}"
        )
        return 0

    if arguments.command == "restore":
        if not arguments.yes:
            expected_confirmation = (
                f"RESTORE {arguments.backup_name}"
            )
            print(
                "A safety backup will be created before restoring.\n"
                "This operation replaces the current database and, when "
                "present, user uploads and the message encryption key."
            )
            confirmation = input(
                f"Type {expected_confirmation!r} to continue: "
            )

            if confirmation != expected_confirmation:
                print("Restore cancelled.")
                return 1

        try:
            result = restore_backup(arguments.backup_name)
        except (
            FileNotFoundError,
            BackupValidationError,
            BackupRestoreError,
        ) as error:
            print(f"Backup restore failed: {error}")
            return 1

        print(
            f"Restored: {result['restored_backup']}\n"
            f"Safety backup: {result['safety_backup']}"
        )

        if not arguments.no_reload:
            if reload_gunicorn():
                print("Gunicorn reload requested.")
            else:
                print(
                    "Gunicorn was not found; reload it manually if needed."
                )

        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
