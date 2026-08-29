import hashlib
import hmac
import secrets
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
from werkzeug.utils import secure_filename

from app.database import (
    find_user_by_id,
    find_user_by_username,
    initialize_database,
)

app = Flask(__name__)
DATA_DIR = Path.home() / "cloud-in-buzunar-data"
UPLOAD_DIR = DATA_DIR / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TOKEN_FILE = DATA_DIR / "api-token"

if not TOKEN_FILE.exists():
    raise RuntimeError(f"Missing API token: {TOKEN_FILE}")

API_TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()

if not API_TOKEN:
    raise RuntimeError("API token cannot be empty")

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


def require_api_token(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")
        scheme, separator, provided_token = authorization.partition(" ")

        token_is_valid = (
            separator != ""
            and scheme.lower() == "bearer"
            and hmac.compare_digest(
                provided_token.encode("utf-8"),
                API_TOKEN.encode("utf-8"),
            )
        )

        if not token_is_valid:
            return (
                jsonify({"error": "Unauthorized"}),
                401,
                {"WWW-Authenticate": "Bearer"},
            )

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
        return jsonify({"error": "Invalid credentials"}), 401

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

@app.post("/api/files")
@require_api_token
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "Missing form field: file"}), 400

    uploaded_file = request.files["file"]

    if uploaded_file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(uploaded_file.filename)

    if not filename:
        return jsonify({"error": "Invalid filename"}), 400

    destination = app.config["UPLOAD_DIR"] / filename

    if destination.exists():
        return jsonify({"error": "File already exists"}), 409

    uploaded_file.save(str(destination))

    return (
        jsonify(
            {
                "filename": filename,
                "size_bytes": destination.stat().st_size,
                "sha256": calculate_sha256(destination),
            }
        ),
        201,
    )
@app.get("/api/files")
@require_api_token
def list_files():
    files = []

    for path in sorted(app.config["UPLOAD_DIR"].iterdir()):
        if not path.is_file():
            continue

        file_info = path.stat()

        files.append(
            {
                "filename": path.name,
                "size_bytes": file_info.st_size,
                "modified_at": datetime.fromtimestamp(
                    file_info.st_mtime,
                    timezone.utc,
                ).isoformat(),
            }
        )

    return jsonify(
        {
            "count": len(files),
            "files": files,
        }
    )
@app.get("/api/files/<filename>")
@require_api_token
def download_file(filename):
    return send_from_directory(
        app.config["UPLOAD_DIR"],
        filename,
        as_attachment=True,
    )
@app.delete("/api/files/<filename>")
@require_api_token
def delete_file(filename):
    safe_name = secure_filename(filename)

    if not safe_name or safe_name != filename:
        return jsonify({"error": "Invalid filename"}), 400

    target = app.config["UPLOAD_DIR"] / safe_name

    if not target.is_file():
        return jsonify({"error": "File not found"}), 404

    try:
        target.unlink()
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

    return jsonify({"deleted": safe_name})
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
