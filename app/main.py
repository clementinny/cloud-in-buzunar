import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, render_template
from werkzeug.utils import secure_filename

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
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
