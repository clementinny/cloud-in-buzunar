import hashlib
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

app = Flask(__name__)
DATA_DIR = Path.home() / "cloud-in-buzunar-data"
UPLOAD_DIR = DATA_DIR / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.config["UPLOAD_DIR"] = UPLOAD_DIR
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()

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
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
