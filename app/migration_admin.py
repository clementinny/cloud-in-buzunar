import importlib.util
import hashlib
import hmac
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from flask import Blueprint, jsonify, request, send_file

from app.database import initialize_database
from app.system_status import require_status_admin


migration_admin_blueprint = Blueprint("migration_admin", __name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
MIGRATION_SCRIPT = PROJECT_DIR / "scripts" / "cloud-migrate.py"
MIGRATION_DIR = Path.home() / "cloud-in-buzunar-migrations"
SERVICE_SCRIPT = PROJECT_DIR / "scripts" / "cloud-services.sh"
MIGRATION_LOG = (
    Path.home() / "cloud-in-buzunar-data" / "logs" / "migration-admin.log"
)
MAX_MIGRATION_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024
MAX_MIGRATION_REQUEST_BYTES = MAX_MIGRATION_UPLOAD_BYTES + 2 * 1024 * 1024
MIGRATION_NAME_PATTERN = re.compile(
    r"^cloud-in-buzunar-migration-\d{8}T\d{6}Z\.tar\.gz$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
MIGRATION_LOCK = Lock()


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


def prepare_migration_directory():
    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    try:
        MIGRATION_DIR.chmod(0o700)
    except OSError:
        pass


def store_uploaded_archive(upload, expected_checksum=None):
    name = Path(upload.filename or "").name
    if upload.filename != name or not MIGRATION_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Selectează o arhivă CloudInBuzunar cu numele original."
        )
    if expected_checksum:
        fields = expected_checksum.strip().split()
        if len(fields) not in (1, 2):
            raise ValueError("Checksumul SHA-256 are un format invalid.")
        if len(fields) == 2 and fields[1].lstrip("*") != name:
            raise ValueError("Checksumul aparține altei arhive.")
        expected_checksum = fields[0].lower()
        if not SHA256_PATTERN.fullmatch(expected_checksum):
            raise ValueError(
                "Checksumul SHA-256 trebuie să aibă 64 de caractere hexazecimale."
            )

    prepare_migration_directory()
    temporary = MIGRATION_DIR / f".{name}.upload-{uuid.uuid4().hex}"
    digest = hashlib.sha256()
    written = 0
    try:
        with temporary.open("xb") as destination:
            while True:
                chunk = upload.stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_MIGRATION_UPLOAD_BYTES:
                    raise ValueError("Arhiva depășește limita de 8 GB.")
                digest.update(chunk)
                destination.write(chunk)
        if written == 0:
            raise ValueError("Arhiva încărcată este goală.")
        checksum = digest.hexdigest()
        if expected_checksum and not hmac.compare_digest(checksum, expected_checksum):
            raise ValueError("Checksumul SHA-256 nu corespunde arhivei încărcate.")
        return temporary, name, checksum
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def install_verified_archive(temporary, name, checksum):
    destination = MIGRATION_DIR / name
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError("Destinația arhivei nu este sigură.")
        existing_checksum = sha256_file(destination)
        if not hmac.compare_digest(existing_checksum, checksum):
            raise FileExistsError("Există deja o arhivă diferită cu același nume.")
        temporary.unlink(missing_ok=True)
    else:
        temporary.replace(destination)
        try:
            destination.chmod(0o600)
        except OSError:
            pass

    checksum_path = Path(f"{destination}.sha256")
    checksum_path.write_text(f"{checksum}  {name}\n", encoding="utf-8")
    try:
        checksum_path.chmod(0o600)
    except OSError:
        pass
    return destination


def run_service_command(command):
    return subprocess.run(
        [str(SERVICE_SCRIPT), command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    ).returncode == 0


def schedule_migration_restart():
    MIGRATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with MIGRATION_LOG.open("ab") as log:
        subprocess.Popen(
            [str(SERVICE_SCRIPT), "migration-restart"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )


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

    if not MIGRATION_LOCK.acquire(blocking=False):
        return jsonify({"error": "O operație de migrare este deja în desfășurare."}), 409

    try:
        module = load_migration_module()
        result = module.create_export(module.default_export_path(), include)
        archive = resolve_migration_path(Path(result["archive"]).name)
    except (OSError, RuntimeError, ValueError) as error:
        return jsonify({"error": f"Exportul a eșuat: {error}"}), 500
    finally:
        MIGRATION_LOCK.release()

    return jsonify({"status": "created", "migration": migration_record(archive)}), 201


@migration_admin_blueprint.post("/api/admin/migrations/imports")
@require_status_admin
def admin_upload_migration():
    request.max_content_length = MAX_MIGRATION_REQUEST_BYTES
    upload = request.files.get("archive")
    if upload is None:
        return jsonify({"error": "Selectează arhiva portabilă."}), 400
    expected_checksum = request.form.get("sha256", "")

    if not MIGRATION_LOCK.acquire(blocking=False):
        return jsonify({"error": "O operație de migrare este deja în desfășurare."}), 409

    temporary = None
    try:
        temporary, name, checksum = store_uploaded_archive(
            upload,
            expected_checksum,
        )
        module = load_migration_module()
        verified = module.verify_archive(temporary)
        archive = install_verified_archive(temporary, name, checksum)
        temporary = None
        manifest = verified["manifest"]
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except FileExistsError as error:
        return jsonify({"error": str(error)}), 409
    except Exception as error:
        return jsonify({"error": f"Verificarea arhivei a eșuat: {error}"}), 400
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        MIGRATION_LOCK.release()

    return jsonify(
        {
            "status": "verified",
            "migration": migration_record(archive),
            "manifest": {
                "created_at": manifest.get("created_at"),
                "file_count": len(manifest.get("files", [])),
                "optional_content": manifest.get("optional_content", {}),
            },
        }
    ), 201


@migration_admin_blueprint.post(
    "/api/admin/migrations/<string:migration_name>/restore"
)
@require_status_admin
def admin_restore_migration(migration_name):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Corpul cererii trebuie să fie JSON."}), 400
    if payload.get("confirmation") != migration_name:
        return jsonify(
            {"error": "Confirmarea nu corespunde numelui exact al arhivei."}
        ), 400
    try:
        archive = resolve_migration_path(migration_name)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 404

    if not MIGRATION_LOCK.acquire(blocking=False):
        return jsonify({"error": "O operație de migrare este deja în desfășurare."}), 409

    watchdog_stopped = False
    try:
        watchdog_stopped = run_service_command("watchdog-stop")
        module = load_migration_module()
        result = module.restore_export(
            archive,
            yes=True,
            confirmation=migration_name,
        )
        initialize_database()
        schedule_migration_restart()
    except Exception as error:
        if watchdog_stopped:
            run_service_command("watchdog-start")
        return jsonify({"error": f"Restaurarea a eșuat: {error}"}), 500
    finally:
        MIGRATION_LOCK.release()

    return jsonify(
        {
            "status": "restored",
            "restart_scheduled": True,
            "safety_archive": Path(result["safety_archive"]).name,
            "application_safety_backup": result["application_safety_backup"],
            "restored_backup": result["restored_backup"],
        }
    )


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
