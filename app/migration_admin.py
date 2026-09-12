import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from flask import Blueprint, jsonify, request, send_file

from app.system_status import require_status_admin


migration_admin_blueprint = Blueprint("migration_admin", __name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
MIGRATION_SCRIPT = PROJECT_DIR / "scripts" / "cloud-migrate.py"
MIGRATION_DIR = Path.home() / "cloud-in-buzunar-migrations"
MIGRATION_NAME_PATTERN = re.compile(
    r"^cloud-in-buzunar-migration-\d{8}T\d{6}Z\.tar\.gz$"
)
EXPORT_LOCK = Lock()


def load_migration_module():
    specification = importlib.util.spec_from_file_location(
        "cloud_in_buzunar_migration_admin_runtime",
        MIGRATION_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("Modulul de migrare nu poate fi încărcat.")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def resolve_migration_path(name):
    if not isinstance(name, str) or not MIGRATION_NAME_PATTERN.fullmatch(name):
        raise ValueError("Numele migrării este invalid.")

    root = MIGRATION_DIR.resolve()
    candidate = root / name
    if candidate.is_symlink():
        raise FileNotFoundError("Arhiva de migrare nu există.")
    archive = candidate.resolve()
    if archive.parent != root or not archive.is_file():
        raise FileNotFoundError("Arhiva de migrare nu există.")
    return archive


def migration_record(archive):
    checksum_path = Path(f"{archive}.sha256")
    checksum = None
    if checksum_path.is_file() and not checksum_path.is_symlink():
        fields = checksum_path.read_text(encoding="utf-8").strip().split()
        if (
            len(fields) == 2
            and fields[1] == archive.name
            and re.fullmatch(r"[0-9a-fA-F]{64}", fields[0])
        ):
            checksum = fields[0].lower()

    details = archive.stat()
    return {
        "name": archive.name,
        "size_bytes": details.st_size,
        "created_at": datetime.fromtimestamp(
            details.st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        "sha256": checksum,
    }


def list_migrations():
    if not MIGRATION_DIR.is_dir():
        return []
    archives = [
        path
        for path in MIGRATION_DIR.glob("cloud-in-buzunar-migration-*.tar.gz")
        if path.is_file()
        and not path.is_symlink()
        and MIGRATION_NAME_PATTERN.fullmatch(path.name)
    ]
    archives.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [migration_record(path) for path in archives]


def parse_export_options(payload):
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("Corpul cererii trebuie să fie JSON.")

    allowed = {"models", "media", "recordings"}
    if set(payload) - allowed:
        raise ValueError("Cererea conține opțiuni necunoscute.")
    if any(not isinstance(payload.get(name, False), bool) for name in allowed):
        raise ValueError("Opțiunile migrării trebuie să fie adevărat sau fals.")
    return {name: payload.get(name, False) for name in allowed}


@migration_admin_blueprint.get("/api/admin/migrations")
@require_status_admin
def admin_list_migrations():
    migrations = list_migrations()
    return jsonify({"count": len(migrations), "migrations": migrations})


@migration_admin_blueprint.post("/api/admin/migrations")
@require_status_admin
def admin_create_migration():
    try:
        include = parse_export_options(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    if not EXPORT_LOCK.acquire(blocking=False):
        return jsonify({"error": "Un export este deja în desfășurare."}), 409

    try:
        module = load_migration_module()
        result = module.create_export(module.default_export_path(), include)
        archive = resolve_migration_path(Path(result["archive"]).name)
    except (OSError, RuntimeError, ValueError) as error:
        return jsonify({"error": f"Exportul a eșuat: {error}"}), 500
    finally:
        EXPORT_LOCK.release()

    return jsonify({"status": "created", "migration": migration_record(archive)}), 201


@migration_admin_blueprint.get(
    "/api/admin/migrations/<string:migration_name>/download"
)
@require_status_admin
def admin_download_migration(migration_name):
    try:
        archive = resolve_migration_path(migration_name)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 404

    response = send_file(
        archive,
        as_attachment=True,
        download_name=archive.name,
        mimetype="application/gzip",
        conditional=True,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@migration_admin_blueprint.get(
    "/api/admin/migrations/<string:migration_name>/checksum"
)
@require_status_admin
def admin_download_migration_checksum(migration_name):
    try:
        archive = resolve_migration_path(migration_name)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 404

    checksum_path = Path(f"{archive}.sha256")
    if not checksum_path.is_file() or checksum_path.is_symlink():
        return jsonify({"error": "Checksumul migrării lipsește."}), 404

    response = send_file(
        checksum_path,
        as_attachment=True,
        download_name=checksum_path.name,
        mimetype="text/plain",
        conditional=True,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
