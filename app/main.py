import hashlib
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
)
from werkzeug.security import check_password_hash

from app.database import (
    find_user_by_id,
    find_user_by_username,
    initialize_database,
    count_recent_failed_login_attempts,
    record_login_attempt,
    list_users,
)

app = Flask(__name__)
DATA_DIR = Path.home() / "cloud-in-buzunar-data"
UPLOAD_DIR = DATA_DIR / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)





SECRET_KEY_FILE = DATA_DIR / "flask-secret-key"

if not SECRET_KEY_FILE.exists():
    SECRET_KEY_FILE.write_text(
        secrets.token_hex(32),
        encoding="utf-8",
    )
    SECRET_KEY_FILE.chmod(0o600)

FLASK_SECRET_KEY = SECRET_KEY_FILE.read_text(
    encoding="utf-8"
).strip()

if not FLASK_SECRET_KEY:
    raise RuntimeError("Flask secret key cannot be empty")

initialize_database()

app.config.update(
    SECRET_KEY=FLASK_SECRET_KEY,
    SESSION_COOKIE_NAME="cloud_in_buzunar_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

app.config["UPLOAD_DIR"] = UPLOAD_DIR
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()

def get_user_upload_dir(user):
    user_upload_dir = (
        app.config["UPLOAD_DIR"] / str(user["id"])
    )

    user_upload_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return user_upload_dir


def resolve_user_path(user, relative_path=""):
    user_upload_dir = get_user_upload_dir(user).resolve()

    requested_path = (
        user_upload_dir / relative_path
    ).resolve()

    if (
        requested_path != user_upload_dir
        and user_upload_dir not in requested_path.parents
    ):
        raise ValueError("Path escapes the user vault")

    return requested_path

def validate_entry_name(name):
    if not isinstance(name, str):
        raise ValueError("Name must be text")

    normalized_name = name.strip()

    if not normalized_name:
        raise ValueError("Name cannot be empty")

    if normalized_name in {".", ".."}:
        raise ValueError("Invalid name")

    if (
        "/" in normalized_name
        or "\\" in normalized_name
        or "\0" in normalized_name
    ):
        raise ValueError("Name contains invalid characters")

    if len(normalized_name.encode("utf-8")) > 200:
        raise ValueError("Name is too long")

    return normalized_name

def build_directory_listing(user, relative_path=""):
    current_directory = resolve_user_path(
        user,
        relative_path,
    )

    if not current_directory.is_dir():
        raise FileNotFoundError("Folder not found")

    user_root = get_user_upload_dir(user).resolve()

    current_path = current_directory.relative_to(
        user_root
    ).as_posix()

    if current_path == ".":
        current_path = ""

    parent_path = None

    if current_directory != user_root:
        parent_path = current_directory.parent.relative_to(
            user_root
        ).as_posix()

        if parent_path == ".":
            parent_path = ""

    children = [
        path
        for path in current_directory.iterdir()
        if not path.is_symlink()
        and (path.is_dir() or path.is_file())
    ]

    children.sort(
        key=lambda path: (
            not path.is_dir(),
            path.name.casefold(),
        )
    )

    entries = []

    for path in children:
        file_info = path.stat()

        entry = {
            "name": path.name,
            "path": path.relative_to(
                user_root
            ).as_posix(),
            "type": (
                "folder"
                if path.is_dir()
                else "file"
            ),
            "modified_at": datetime.fromtimestamp(
                file_info.st_mtime,
                timezone.utc,
            ).isoformat(),
        }

        if path.is_file():
            entry["size_bytes"] = file_info.st_size

        entries.append(entry)

    return {
        "path": current_path,
        "parent_path": parent_path,
        "count": len(entries),
        "entries": entries,
    }

def send_vault_file(user, relative_path):
    target = resolve_user_path(
        user,
        relative_path,
    )

    if not target.is_file():
        raise FileNotFoundError("File not found")

    user_root = get_user_upload_dir(user).resolve()
    safe_relative_path = target.relative_to(
        user_root
    ).as_posix()

    return send_from_directory(
        user_root,
        safe_relative_path,
        as_attachment=True,
    )


def get_session_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user


def require_login(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_session_user()

        if user is None:
            return jsonify(
                {"error": "Authentication required"}
            ), 401

        return view_function(*args, **kwargs)

    return wrapped_view


def require_admin(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_session_user()

        if user is None:
            return jsonify(
                {"error": "Authentication required"}
            ), 401

        if user["role"] != "admin":
            return jsonify(
                {"error": "Administrator access required"}
            ), 403

        return view_function(*args, **kwargs)

    return wrapped_view

@app.get("/")
def dashboard():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(
        {
            "service": "CloudInBuzunar",
            "status": "online",
            "time": datetime.now(timezone.utc).isoformat(),
        }
    )

def serialize_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    }


@app.post("/api/auth/login")
def login():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    username = payload.get("username", "")
    password = payload.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "Invalid credentials"}), 401

    client_ip = request.remote_addr or "unknown"

    failed_attempts = count_recent_failed_login_attempts(
        username,
        client_ip,
        window_minutes=10,
    )

    if failed_attempts >= 5:
        return (
            jsonify(
                {
                    "error": (
                        "Too many login attempts. "
                        "Try again later."
                    )
                }
            ),
            429,
        )
    user = find_user_by_username(username)

    credentials_are_valid = (
        user is not None
        and user["is_active"]
        and check_password_hash(
            user["password_hash"],
            password,
        )
    )

    if not credentials_are_valid:
        record_login_attempt(
            username,
            client_ip,
            was_successful=False,
        )
        return jsonify({"error": "Invalid credentials"}), 401
    record_login_attempt(
        username,
        client_ip,
        was_successful=True,
    )

    session.clear()
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True

    return jsonify({"user": serialize_user(user)})


@app.post("/api/auth/logout")
def logout():
    session.clear()

    return jsonify({"status": "logged_out"})


@app.get("/api/auth/me")
def current_session():
    user_id = session.get("user_id")
    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return jsonify({"error": "Authentication required"}), 401

    return jsonify({"user": serialize_user(user)})

def create_vault_folder(user):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    parent_path = payload.get("path", "")
    folder_name = payload.get("name", "")

    if not isinstance(parent_path, str):
        return jsonify({"error": "Invalid parent path"}), 400

    try:
        safe_name = validate_entry_name(folder_name)
        parent_directory = resolve_user_path(
            user,
            parent_path,
        )
    except (ValueError, OSError) as error:
        return jsonify({"error": str(error)}), 400

    if not parent_directory.is_dir():
        return jsonify(
            {"error": "Parent folder not found"}
        ), 404

    new_directory = parent_directory / safe_name

    try:
        new_directory.mkdir()
    except FileExistsError:
        return jsonify(
            {"error": "A file or folder already has this name"}
        ), 409

    user_root = get_user_upload_dir(user).resolve()
    relative_path = new_directory.relative_to(
        user_root
    ).as_posix()

    return (
        jsonify(
            {
                "name": safe_name,
                "path": relative_path,
                "type": "folder",
            }
        ),
        201,
    )

@app.post("/api/folders")
@require_login
def create_folder():
    user = get_session_user()

    return create_vault_folder(user)


@app.post(
    "/api/admin/vaults/<int:user_id>/folders"
)
@require_admin
def admin_create_folder(user_id):
    target_user = find_user_by_id(user_id)

    if target_user is None:
        return jsonify(
            {"error": "User not found"}
        ), 404

    return create_vault_folder(target_user)


def upload_vault_file(user):
    relative_path = request.form.get("path", "")

    try:
        current_directory = resolve_user_path(
            user,
            relative_path,
        )
    except (ValueError, OSError):
        return jsonify({"error": "Invalid path"}), 400

    if not current_directory.is_dir():
        return jsonify(
            {"error": "Folder not found"}
        ), 404

    if "file" not in request.files:
        return jsonify(
            {"error": "Missing form field: file"}
        ), 400

    uploaded_file = request.files["file"]

    try:
        filename = validate_entry_name(
            uploaded_file.filename
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    destination = current_directory / filename

    if destination.exists():
        return jsonify(
            {"error": "File already exists"}
        ), 409

    uploaded_file.save(str(destination))

    user_root = get_user_upload_dir(user).resolve()
    file_path = destination.relative_to(
        user_root
    ).as_posix()

    return (
        jsonify(
            {
                "name": filename,
                "path": file_path,
                "type": "file",
                "size_bytes": destination.stat().st_size,
                "sha256": calculate_sha256(destination),
            }
        ),
        201,
    )

@app.post("/api/files")
@require_login
def upload_file():
    user = get_session_user()

    return upload_vault_file(user)


@app.post(
    "/api/admin/vaults/<int:user_id>/files"
)
@require_admin
def admin_upload_file(user_id):
    target_user = find_user_by_id(user_id)

    if target_user is None:
        return jsonify(
            {"error": "User not found"}
        ), 404

    return upload_vault_file(target_user)

@app.get("/api/files")
@require_login
def list_files():
    user = get_session_user()
    relative_path = request.args.get("path", "")

    try:
        listing = build_directory_listing(
            user,
            relative_path,
        )
    except FileNotFoundError:
        return jsonify(
            {"error": "Folder not found"}
        ), 404
    except (ValueError, OSError):
        return jsonify(
            {"error": "Invalid path"}
        ), 400

    return jsonify(listing)


@app.get("/api/files/<path:relative_path>")
@require_login
def download_file(relative_path):
    user = get_session_user()

    try:
        return send_vault_file(
            user,
            relative_path,
        )
    except FileNotFoundError:
        return jsonify(
            {"error": "File not found"}
        ), 404
    except (ValueError, OSError):
        return jsonify(
            {"error": "Invalid path"}
        ), 400


def delete_vault_file(user, relative_path):
    try:
        target = resolve_user_path(
            user,
            relative_path,
        )
    except (ValueError, OSError):
        return jsonify({"error": "Invalid path"}), 400

    if not target.is_file():
        return jsonify(
            {"error": "File not found"}
        ), 404

    user_root = get_user_upload_dir(user).resolve()
    deleted_path = target.relative_to(
        user_root
    ).as_posix()

    try:
        target.unlink()
    except FileNotFoundError:
        return jsonify(
            {"error": "File not found"}
        ), 404

    return jsonify(
        {
            "deleted": target.name,
            "path": deleted_path,
        }
    )

@app.delete("/api/files/<path:relative_path>")
@require_login
def delete_file(relative_path):
    user = get_session_user()

    return delete_vault_file(
        user,
        relative_path,
    )


@app.delete(
    "/api/admin/vaults/<int:user_id>/files/"
    "<path:relative_path>"
)
@require_admin
def admin_delete_file(user_id, relative_path):
    target_user = find_user_by_id(user_id)

    if target_user is None:
        return jsonify(
            {"error": "User not found"}
        ), 404

    return delete_vault_file(
        target_user,
        relative_path,
    )

def delete_vault_folder(user, relative_path):
    try:
        target = resolve_user_path(
            user,
            relative_path,
        )
    except (ValueError, OSError):
        return jsonify(
            {"error": "Invalid path"}
        ), 400

    user_root = get_user_upload_dir(user).resolve()

    if target == user_root:
        return jsonify(
            {"error": "The vault root cannot be deleted"}
        ), 400

    if not target.is_dir():
        return jsonify(
            {"error": "Folder not found"}
        ), 404

    deleted_path = target.relative_to(
        user_root
    ).as_posix()
    deleted_name = target.name

    try:
        shutil.rmtree(target)
    except FileNotFoundError:
        return jsonify(
            {"error": "Folder not found"}
        ), 404
    except OSError:
        return jsonify(
            {"error": "Folder could not be deleted"}
        ), 500

    return jsonify(
        {
            "deleted": deleted_name,
            "path": deleted_path,
            "type": "folder",
        }
    )


@app.delete("/api/folders/<path:relative_path>")
@require_login
def delete_folder(relative_path):
    user = get_session_user()

    return delete_vault_folder(
        user,
        relative_path,
    )


@app.delete(
    "/api/admin/vaults/<int:user_id>/folders/"
    "<path:relative_path>"
)
@require_admin
def admin_delete_folder(user_id, relative_path):
    target_user = find_user_by_id(user_id)

    if target_user is None:
        return jsonify(
            {"error": "User not found"}
        ), 404

    return delete_vault_folder(
        target_user,
        relative_path,
    )


@app.get("/api/admin/vaults")
@require_admin
def admin_list_vaults():
    vaults = []

    for user in list_users():
        listing = build_directory_listing(user)

        vaults.append(
            {
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "role": user["role"],
                    "is_active": bool(
                        user["is_active"]
                    ),
                },
                "entry_count": listing["count"],
            }
        )

    return jsonify(
        {
            "count": len(vaults),
            "vaults": vaults,
        }
    )


@app.get(
    "/api/admin/vaults/<int:user_id>/files"
)
@require_admin
def admin_list_files(user_id):
    target_user = find_user_by_id(user_id)

    if target_user is None:
        return jsonify(
            {"error": "User not found"}
        ), 404

    relative_path = request.args.get("path", "")

    try:
        listing = build_directory_listing(
            target_user,
            relative_path,
        )
    except FileNotFoundError:
        return jsonify(
            {"error": "Folder not found"}
        ), 404
    except (ValueError, OSError):
        return jsonify(
            {"error": "Invalid path"}
        ), 400

    listing["owner"] = {
        "id": target_user["id"],
        "username": target_user["username"],
        "role": target_user["role"],
        "is_active": bool(
            target_user["is_active"]
        ),
    }

    return jsonify(listing)


@app.get(
    "/api/admin/vaults/<int:user_id>/files/"
    "<path:relative_path>"
)
@require_admin
def admin_download_file(user_id, relative_path):
    target_user = find_user_by_id(user_id)

    if target_user is None:
        return jsonify(
            {"error": "User not found"}
        ), 404

    try:
        return send_vault_file(
            target_user,
            relative_path,
        )
    except FileNotFoundError:
        return jsonify(
            {"error": "File not found"}
        ), 404
    except (ValueError, OSError):
        return jsonify(
            {"error": "Invalid path"}
        ), 400

def rename_vault_entry(user, relative_path):
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Expected JSON body"}
        ), 400

    try:
        new_name = validate_entry_name(
            payload.get("name", "")
        )
        target = resolve_user_path(
            user,
            relative_path,
        )
    except (ValueError, OSError) as error:
        return jsonify(
            {"error": str(error)}
        ), 400

    user_root = get_user_upload_dir(user).resolve()

    if target == user_root:
        return jsonify(
            {"error": "The vault root cannot be renamed"}
        ), 400

    if not target.exists():
        return jsonify(
            {"error": "File or folder not found"}
        ), 404

    if target.is_dir():
        entry_type = "folder"
    elif target.is_file():
        entry_type = "file"
    else:
        return jsonify(
            {"error": "Unsupported entry type"}
        ), 400

    old_path = target.relative_to(
        user_root
    ).as_posix()

    destination = target.parent / new_name

    if destination == target:
        return jsonify(
            {
                "old_path": old_path,
                "name": target.name,
                "path": old_path,
                "type": entry_type,
            }
        )

    if destination.exists():
        return jsonify(
            {"error": "A file or folder already has this name"}
        ), 409

    try:
        target.rename(destination)
    except FileNotFoundError:
        return jsonify(
            {"error": "File or folder not found"}
        ), 404
    except OSError:
        return jsonify(
            {"error": "Entry could not be renamed"}
        ), 500

    new_path = destination.relative_to(
        user_root
    ).as_posix()

    return jsonify(
        {
            "old_path": old_path,
            "name": destination.name,
            "path": new_path,
            "type": entry_type,
        }
    )


@app.patch("/api/entries/<path:relative_path>")
@require_login
def rename_entry(relative_path):
    user = get_session_user()

    return rename_vault_entry(
        user,
        relative_path,
    )


@app.patch(
    "/api/admin/vaults/<int:user_id>/entries/"
    "<path:relative_path>"
)
@require_admin
def admin_rename_entry(user_id, relative_path):
    target_user = find_user_by_id(user_id)

    if target_user is None:
        return jsonify(
            {"error": "User not found"}
        ), 404

    return rename_vault_entry(
        target_user,
        relative_path,
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
