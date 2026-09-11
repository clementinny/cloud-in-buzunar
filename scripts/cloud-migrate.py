#!/usr/bin/env python3
"""Create and restore validated CloudInBuzunar migration archives."""

import argparse
import hashlib
import hmac
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

DATA_DIR = Path.home() / "cloud-in-buzunar-data"
BACKUP_DIR = DATA_DIR / "backups"
DEFAULT_EXPORT_DIR = Path.home() / "cloud-in-buzunar-migrations"
FORMAT_NAME = "cloud-in-buzunar-portable"
FORMAT_VERSION = 1
MAX_MEMBERS = 100_000
MAX_FILE_SIZE = 64 * 1024**3
MAX_TOTAL_SIZE = 256 * 1024**3

CONFIG_FILES = (
    "autostart.conf",
    "flask-secret-key",
    "thermal-policy.json",
    "ai/model-mode",
    "aria2/aria2.conf",
    "aria2/rpc-secret",
    "transmission/settings.json",
    "caddy/Caddyfile",
    "caddy/proxy.conf",
)

OPTIONAL_TREES = {
    "models": ("models", "payload/models"),
    "media": ("media", "payload/media"),
    "recordings": ("monitor-recordings", "payload/monitor-recordings"),
}


class MigrationError(RuntimeError):
    """Raised when a migration archive is unsafe or invalid."""


def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_regular_source(path):
    if path.is_symlink():
        raise MigrationError(f"Linkurile simbolice nu sunt acceptate: {path}")
    if not path.is_file():
        raise MigrationError(f"Sursa nu este un fișier obișnuit: {path}")


def iter_tree_files(root):
    if root.is_symlink():
        raise MigrationError(f"Directorul nu poate fi link simbolic: {root}")
    if not root.exists():
        return
    if not root.is_dir():
        raise MigrationError(f"Calea nu este director: {root}")

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise MigrationError(f"Linkurile simbolice nu sunt acceptate: {path}")
        if path.is_file():
            yield path
        elif not path.is_dir():
            raise MigrationError(f"Fișier special neacceptat: {path}")


def build_source_list(core_backup, core_checksum, include):
    sources = [
        (core_backup, f"payload/core/{core_backup.name}"),
        (core_checksum, f"payload/core/{core_checksum.name}"),
    ]

    for relative_name in CONFIG_FILES:
        source = DATA_DIR / relative_name
        if source.exists():
            ensure_regular_source(source)
            sources.append((source, f"payload/config/{relative_name}"))

    for option_name, (relative_root, archive_root) in OPTIONAL_TREES.items():
        if not include[option_name]:
            continue
        source_root = DATA_DIR / relative_root
        for source in iter_tree_files(source_root):
            relative = source.relative_to(source_root).as_posix()
            sources.append((source, f"{archive_root}/{relative}"))

    archive_names = [archive_name for _, archive_name in sources]
    if len(archive_names) != len(set(archive_names)):
        raise MigrationError("Exportul ar conține căi duplicate.")
    return sources


def manifest_for_sources(sources, include):
    files = []
    for source, archive_name in sources:
        ensure_regular_source(source)
        size = source.stat().st_size
        if size > MAX_FILE_SIZE:
            raise MigrationError(f"Fișier prea mare pentru export: {source}")
        files.append(
            {
                "path": archive_name,
                "size": size,
                "sha256": sha256_file(source),
            }
        )

    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project": "CloudInBuzunar",
        "optional_content": {
            "models": bool(include["models"]),
            "media": bool(include["media"]),
            "recordings": bool(include["recordings"]),
        },
        "files": files,
    }


def add_regular_file(archive, source, archive_name):
    ensure_regular_source(source)
    information = archive.gettarinfo(str(source), arcname=archive_name)
    information.uid = 0
    information.gid = 0
    information.uname = ""
    information.gname = ""
    information.mode = 0o600
    with source.open("rb") as source_file:
        archive.addfile(information, source_file)


def write_archive(output_path, sources, manifest):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{os.getpid()}")
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for source, archive_name in sources:
                add_regular_file(archive, source, archive_name)

            encoded_manifest = json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            information = tarfile.TarInfo("manifest.json")
            information.size = len(encoded_manifest)
            information.mode = 0o600
            information.mtime = int(datetime.now(timezone.utc).timestamp())
            import io

            archive.addfile(information, io.BytesIO(encoded_manifest))

        temporary.chmod(0o600)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)

    checksum_path = Path(f"{output_path}.sha256")
    checksum_path.write_text(
        f"{sha256_file(output_path)}  {output_path.name}\n",
        encoding="utf-8",
    )
    checksum_path.chmod(0o600)


def default_export_path(prefix="cloud-in-buzunar-migration"):
    return DEFAULT_EXPORT_DIR / f"{prefix}-{utc_timestamp()}.tar.gz"


def create_export(output_path, include, force=False, dry_run=False):
    output_path = output_path.expanduser().resolve()
    if output_path.exists() and not force:
        raise MigrationError(
            f"Destinația există deja: {output_path}. Folosește --force explicit."
        )

    if dry_run:
        return {
            "archive": str(output_path),
            "dry_run": True,
            "optional_content": include,
        }

    from app.backup import DEFAULT_KEEP, create_backup

    existing_backup_count = len(
        list(BACKUP_DIR.glob("cloud-in-buzunar-*.tar.gz"))
    )
    core_backup = create_backup(
        keep=max(DEFAULT_KEEP, existing_backup_count + 1)
    )
    core_checksum = Path(f"{core_backup}.sha256")
    sources = build_source_list(core_backup, core_checksum, include)
    manifest = manifest_for_sources(sources, include)
    write_archive(output_path, sources, manifest)
    verified = verify_archive(output_path)
    return {
        "archive": str(output_path),
        "sha256": sha256_file(output_path),
        "file_count": len(verified["manifest"]["files"]),
        "optional_content": include,
    }


def validate_member_name(name):
    if not name or "\\" in name:
        raise MigrationError("Arhiva conține o cale invalidă.")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise MigrationError("Arhiva încearcă traversarea în afara destinației.")
    if name != "manifest.json" and not name.startswith("payload/"):
        raise MigrationError(f"Fișier neașteptat în arhivă: {name}")
    return path


def read_manifest(archive):
    try:
        member = archive.getmember("manifest.json")
    except KeyError as error:
        raise MigrationError("Manifestul migrării lipsește.") from error
    if not member.isfile() or member.size > 1024 * 1024:
        raise MigrationError("Manifestul migrării este invalid.")
    source = archive.extractfile(member)
    if source is None:
        raise MigrationError("Manifestul migrării nu poate fi citit.")
    try:
        manifest = json.loads(source.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MigrationError("Manifestul migrării este invalid.") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != FORMAT_NAME
        or manifest.get("version") != FORMAT_VERSION
        or not isinstance(manifest.get("files"), list)
    ):
        raise MigrationError("Format de migrare necunoscut sau incompatibil.")
    return manifest


def validate_manifest_files(manifest):
    expected = {}
    total_size = 0
    optional = manifest.get("optional_content")
    if not isinstance(optional, dict) or any(
        not isinstance(optional.get(name), bool) for name in OPTIONAL_TREES
    ):
        raise MigrationError("Manifestul nu declară corect conținutul opțional.")

    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise MigrationError("Manifestul conține o intrare invalidă.")
        path = entry.get("path")
        size = entry.get("size")
        checksum = entry.get("sha256")
        validate_member_name(path if isinstance(path, str) else "")
        if path == "manifest.json" or path in expected:
            raise MigrationError("Manifestul conține căi duplicate sau rezervate.")
        if (
            not isinstance(size, int)
            or size < 0
            or size > MAX_FILE_SIZE
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum)
        ):
            raise MigrationError(f"Metadate invalide pentru {path}.")
        total_size += size
        if total_size > MAX_TOTAL_SIZE:
            raise MigrationError("Conținutul migrării depășește limita de siguranță.")
        expected[path] = entry

    config_paths = {f"payload/config/{name}" for name in CONFIG_FILES}
    core_archives = []
    core_checksums = []
    for path in expected:
        if path in config_paths:
            continue
        if path.startswith("payload/core/"):
            relative = path.removeprefix("payload/core/")
            if "/" in relative:
                raise MigrationError(f"Cale principală invalidă: {path}")
            if relative.endswith(".tar.gz"):
                core_archives.append(relative)
                continue
            if relative.endswith(".tar.gz.sha256"):
                core_checksums.append(relative)
                continue
            raise MigrationError(f"Fișier principal neașteptat: {path}")

        matched_optional = False
        for name, (_, archive_root) in OPTIONAL_TREES.items():
            prefix = f"{archive_root}/"
            if path.startswith(prefix) and len(path) > len(prefix):
                if not optional[name]:
                    raise MigrationError(
                        f"Arhiva conține {name}, dar manifestul nu îl declară."
                    )
                matched_optional = True
                break
        if not matched_optional:
            raise MigrationError(f"Fișier nepermis în migrare: {path}")

    if len(core_archives) != 1 or core_checksums != [f"{core_archives[0]}.sha256"]:
        raise MigrationError("Migrarea trebuie să conțină exact backupul principal și checksumul său.")
    return expected


def validate_archive_structure(archive, expected):
    members = archive.getmembers()
    if len(members) > MAX_MEMBERS:
        raise MigrationError("Arhiva conține prea multe intrări.")
    names = set()
    actual_files = set()
    for member in members:
        validate_member_name(member.name)
        if member.name in names:
            raise MigrationError(f"Cale duplicată în arhivă: {member.name}")
        names.add(member.name)
        if not member.isfile():
            raise MigrationError("Arhiva conține linkuri, directoare sau fișiere speciale.")
        if member.name != "manifest.json":
            actual_files.add(member.name)
            entry = expected.get(member.name)
            if entry is None or member.size != entry["size"]:
                raise MigrationError(f"Dimensiune sau fișier neașteptat: {member.name}")
    if actual_files != set(expected):
        missing = sorted(set(expected) - actual_files)
        raise MigrationError(f"Fișiere lipsă din arhivă: {', '.join(missing[:3])}")


def extract_verified(archive, expected, destination):
    destination_root = destination.resolve()
    for member in archive.getmembers():
        if member.name == "manifest.json":
            continue
        path = validate_member_name(member.name)
        target = destination.joinpath(*path.parts).resolve()
        if destination_root not in target.parents:
            raise MigrationError("Destinație de extragere nesigură.")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise MigrationError(f"Fișierul nu poate fi citit: {member.name}")
        digest = hashlib.sha256()
        written = 0
        with source, target.open("xb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > expected[member.name]["size"]:
                    raise MigrationError(f"Fișier supradimensionat: {member.name}")
                digest.update(chunk)
                output.write(chunk)
        if written != expected[member.name]["size"] or not hmac.compare_digest(
            digest.hexdigest(), expected[member.name]["sha256"]
        ):
            raise MigrationError(f"Checksum invalid pentru {member.name}.")


def verify_archive(archive_path, extract_to=None):
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file() or archive_path.is_symlink():
        raise MigrationError(f"Arhiva exactă nu există sau nu este sigură: {archive_path}")
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            manifest = read_manifest(archive)
            expected = validate_manifest_files(manifest)
            validate_archive_structure(archive, expected)
            if extract_to is None:
                with tempfile.TemporaryDirectory(prefix="cloud-migration-verify-") as temporary:
                    extract_verified(archive, expected, Path(temporary))
            else:
                extract_verified(archive, expected, extract_to)
    except (tarfile.TarError, OSError) as error:
        if isinstance(error, MigrationError):
            raise
        raise MigrationError("Arhiva nu poate fi deschisă în siguranță.") from error
    return {"archive": str(archive_path), "manifest": manifest}


def atomic_copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.import-{os.getpid()}")
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def replace_tree(source, destination, work_directory):
    prepared = work_directory / f"prepared-{destination.name}"
    shutil.copytree(source, prepared)
    previous = work_directory / f"previous-{destination.name}"
    if destination.exists():
        destination.replace(previous)
    try:
        prepared.replace(destination)
    except Exception:
        if previous.exists() and not destination.exists():
            previous.replace(destination)
        raise


def require_confirmation(archive_path, yes, confirmation):
    expected = archive_path.name
    if yes:
        if confirmation != expected:
            raise MigrationError(
                f"Cu --yes trebuie și --confirm {expected!r}."
            )
        return
    typed = input(f"Scrie exact IMPORT {expected} pentru restaurare: ").strip()
    if typed != f"IMPORT {expected}":
        raise MigrationError("Confirmarea nu corespunde arhivei exacte.")


def locate_core_backup(extracted, manifest):
    entries = [
        entry["path"]
        for entry in manifest["files"]
        if entry["path"].startswith("payload/core/")
        and entry["path"].endswith(".tar.gz")
    ]
    if len(entries) != 1:
        raise MigrationError("Migrarea nu conține exact un backup principal.")
    backup = extracted.joinpath(*PurePosixPath(entries[0]).parts)
    checksum = Path(f"{backup}.sha256")
    if not checksum.is_file():
        raise MigrationError("Checksumul backupului principal lipsește.")
    return backup, checksum


def restore_export(archive_path, yes=False, confirmation=None, dry_run=False):
    archive_path = archive_path.expanduser().resolve()
    if not (DATA_DIR / "cloud-in-buzunar.sqlite3").is_file():
        raise MigrationError(
            "Inițializează mai întâi instalarea; baza locală necesară backupului de siguranță lipsește."
        )
    with tempfile.TemporaryDirectory(
        prefix="migration-import-", dir=DATA_DIR
    ) as temporary_name:
        temporary = Path(temporary_name)
        extracted = temporary / "extracted"
        extracted.mkdir()
        verified = verify_archive(archive_path, extract_to=extracted)
        manifest = verified["manifest"]
        if dry_run:
            return {"archive": str(archive_path), "dry_run": True, "verified": True}

        require_confirmation(archive_path, yes, confirmation)

        optional = manifest.get("optional_content", {})
        safety_include = {
            name: bool(optional.get(name)) for name in OPTIONAL_TREES
        }
        safety_path = default_export_path("pre-import-safety")
        safety = create_export(safety_path, safety_include)

        from app.backup import restore_backup

        core_backup, core_checksum = locate_core_backup(extracted, manifest)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        installed_backup = BACKUP_DIR / core_backup.name
        installed_checksum = Path(f"{installed_backup}.sha256")
        if installed_backup.exists() and sha256_file(installed_backup) != sha256_file(core_backup):
            raise MigrationError(
                f"Există deja un backup diferit cu numele {core_backup.name}."
            )
        atomic_copy_file(core_backup, installed_backup)
        atomic_copy_file(core_checksum, installed_checksum)
        restored = restore_backup(installed_backup.name)

        config_root = extracted / "payload" / "config"
        if config_root.is_dir():
            for source in iter_tree_files(config_root):
                relative = source.relative_to(config_root)
                atomic_copy_file(source, DATA_DIR / relative)

        for name, (relative_root, archive_root) in OPTIONAL_TREES.items():
            source = extracted.joinpath(*PurePosixPath(archive_root).parts)
            if optional.get(name) and source.is_dir():
                replace_tree(source, DATA_DIR / relative_root, temporary)

    return {
        "archive": str(archive_path),
        "safety_archive": safety["archive"],
        "application_safety_backup": restored["safety_backup"],
        "restored_backup": restored["restored_backup"],
    }


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Exportă, verifică și importă în siguranță CloudInBuzunar."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    export_parser = commands.add_parser("export", help="Creează o arhivă portabilă")
    export_parser.add_argument("--output", type=Path)
    export_parser.add_argument("--include-models", action="store_true")
    export_parser.add_argument("--include-media", action="store_true")
    export_parser.add_argument("--include-recordings", action="store_true")
    export_parser.add_argument("--force", action="store_true")
    export_parser.add_argument("--dry-run", action="store_true")

    verify_parser = commands.add_parser("verify", help="Verifică arhiva fără modificări")
    verify_parser.add_argument("archive", type=Path)

    import_parser = commands.add_parser("import", help="Restaurează o migrare verificată")
    import_parser.add_argument("archive", type=Path)
    import_parser.add_argument("--yes", action="store_true")
    import_parser.add_argument("--confirm")
    import_parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    arguments = parse_arguments(argv)
    try:
        if arguments.command == "export":
            include = {
                "models": arguments.include_models,
                "media": arguments.include_media,
                "recordings": arguments.include_recordings,
            }
            result = create_export(
                arguments.output or default_export_path(),
                include,
                force=arguments.force,
                dry_run=arguments.dry_run,
            )
        elif arguments.command == "verify":
            verified = verify_archive(arguments.archive)
            result = {
                "archive": verified["archive"],
                "verified": True,
                "file_count": len(verified["manifest"]["files"]),
                "optional_content": verified["manifest"].get("optional_content", {}),
            }
        else:
            result = restore_export(
                arguments.archive,
                yes=arguments.yes,
                confirmation=arguments.confirm,
                dry_run=arguments.dry_run,
            )
    except (MigrationError, FileNotFoundError, ValueError) as error:
        print(f"Eroare: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
