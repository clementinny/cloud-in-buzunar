import json
import secrets
import shutil
import threading
import mimetypes
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
)

from app.database import find_user_by_id


media_blueprint = Blueprint("media", __name__)

DATA_DIR = Path.home() / "cloud-in-buzunar-data"
MEDIA_DIR = DATA_DIR / "media"
MAX_MEDIA_UPLOAD_SIZE = 100 * 1024 * 1024
MAX_MEDIA_FILE_SIZE = 50 * 1024 * 1024 * 1024
MAX_MEDIA_CHUNK_SIZE = 20 * 1024 * 1024
MINIMUM_FREE_SPACE = 512 * 1024 * 1024

MEDIA_UPLOAD_TEMP_DIR = MEDIA_DIR / ".uploads"
MEDIA_UPLOAD_TEMP_DIR.mkdir(
    parents=True,
    exist_ok=True,
)
MEDIA_UPLOAD_TEMP_DIR.chmod(0o700)

MEDIA_UPLOAD_LOCK = threading.Lock()


MEDIA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.chmod(0o700)


def get_session_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user


def require_media_login(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_session_user()

        if user is None:
            return jsonify(
                {"error": "Authentication required"}
            ), 401

        return view_function(*args, **kwargs)

    return wrapped_view


def get_user_media_dir(user):
    user_media_dir = MEDIA_DIR / str(user["id"])

    user_media_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return user_media_dir


def resolve_media_path(user, relative_path=""):
    user_media_dir = get_user_media_dir(user).resolve()

    requested_path = (
        user_media_dir / relative_path
    ).resolve()

    if (
        requested_path != user_media_dir
        and user_media_dir not in requested_path.parents
    ):
        raise ValueError("Path escapes the media library")

    return requested_path


def validate_media_name(name):
    if not isinstance(name, str):
        raise ValueError("Invalid filename")

    normalized_name = name.strip()

    if not normalized_name:
        raise ValueError("Filename cannot be empty")

    if normalized_name in {".", ".."}:
        raise ValueError("Invalid filename")

    if (
        "/" in normalized_name
        or "\\" in normalized_name
        or "\0" in normalized_name
    ):
        raise ValueError(
            "Filename contains invalid characters"
        )

    if len(normalized_name.encode("utf-8")) > 200:
        raise ValueError("Filename is too long")

    return normalized_name

def get_user_upload_temp_dir(user):
    temporary_directory = (
        MEDIA_UPLOAD_TEMP_DIR / str(user["id"])
    )

    temporary_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return temporary_directory


def get_upload_paths(user, upload_id):
    if (
        len(upload_id) != 32
        or any(
            character not in "0123456789abcdef"
            for character in upload_id
        )
    ):
        raise ValueError("Invalid upload ID")

    temporary_directory = get_user_upload_temp_dir(user)

    part_path = temporary_directory / (
        f"{upload_id}.part"
    )
    metadata_path = temporary_directory / (
        f"{upload_id}.json"
    )

    return part_path, metadata_path


def read_upload_metadata(user, upload_id):
    part_path, metadata_path = get_upload_paths(
        user,
        upload_id,
    )

    if (
        not part_path.is_file()
        or not metadata_path.is_file()
    ):
        raise FileNotFoundError("Upload not found")

    try:
        metadata = json.loads(
            metadata_path.read_text(
                encoding="utf-8"
            )
        )
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(
            "Invalid upload metadata"
        ) from error

    return metadata, part_path, metadata_path


def check_available_space(path, required_bytes):
    available_bytes = shutil.disk_usage(path).free

    if (
        available_bytes
        < required_bytes + MINIMUM_FREE_SPACE
    ):
        raise OSError(
            "Nu există suficient spațiu liber."
        )


def detect_media_type(path):
    mime_type, _ = mimetypes.guess_type(path.name)

    if mime_type is None:
        return None, None

    if mime_type.startswith("image/"):
        return "image", mime_type

    if mime_type.startswith("audio/"):
        return "audio", mime_type

    if mime_type.startswith("video/"):
        return "video", mime_type

    return None, mime_type


def serialize_media_file(path, user_root):
    media_type, mime_type = detect_media_type(path)
    file_info = path.stat()

    return {
        "name": path.name,
        "path": path.relative_to(
            user_root
        ).as_posix(),
        "media_type": media_type,
        "mime_type": mime_type,
        "size_bytes": file_info.st_size,
        "modified_at": file_info.st_mtime,
    }

@media_blueprint.post("/api/media/uploads")
@require_media_login
def initialize_large_media_upload():
    user = get_session_user()
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Expected JSON body"}
        ), 400

    filename = payload.get("filename")
    file_size = payload.get("size")
    fingerprint = payload.get("fingerprint")

    try:
        filename = validate_media_name(filename)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    if (
        isinstance(file_size, bool)
        or not isinstance(file_size, int)
        or file_size <= 0
    ):
        return jsonify(
            {"error": "Invalid file size"}
        ), 400

    if file_size > MAX_MEDIA_FILE_SIZE:
        return jsonify(
            {
                "error": (
                    "Fișierul depășește limita "
                    "de 50 GB."
                )
            }
        ), 413

    if (
        not isinstance(fingerprint, str)
        or not fingerprint
        or len(fingerprint) > 500
    ):
        return jsonify(
            {"error": "Invalid file fingerprint"}
        ), 400

    media_type, mime_type = detect_media_type(
        Path(filename)
    )

    if media_type is None:
        return jsonify(
            {"error": "Unsupported media file"}
        ), 415

    user_root = get_user_media_dir(user).resolve()
    destination = user_root / filename

    if destination.exists():
        return jsonify(
            {
                "error": (
                    "Există deja un fișier "
                    "cu acest nume."
                )
            }
        ), 409

    temporary_directory = get_user_upload_temp_dir(
        user
    )

    with MEDIA_UPLOAD_LOCK:
        for metadata_path in temporary_directory.glob(
            "*.json"
        ):
            try:
                metadata = json.loads(
                    metadata_path.read_text(
                        encoding="utf-8"
                    )
                )
            except (json.JSONDecodeError, OSError):
                continue

            if (
                metadata.get("filename") != filename
                or metadata.get("size") != file_size
                or metadata.get("fingerprint")
                != fingerprint
            ):
                continue

            upload_id = metadata_path.stem
            part_path = temporary_directory / (
                f"{upload_id}.part"
            )

            if not part_path.is_file():
                metadata_path.unlink(
                    missing_ok=True
                )
                continue

            received_bytes = part_path.stat().st_size

            if received_bytes > file_size:
                part_path.unlink(missing_ok=True)
                metadata_path.unlink(
                    missing_ok=True
                )
                continue

            try:
                check_available_space(
                    user_root,
                    file_size - received_bytes,
                )
            except OSError as error:
                return jsonify(
                    {"error": str(error)}
                ), 507

            return jsonify(
                {
                    "upload_id": upload_id,
                    "received_bytes": received_bytes,
                    "size": file_size,
                    "resumed": True,
                }
            )

        try:
            check_available_space(
                user_root,
                file_size,
            )
        except OSError as error:
            return jsonify(
                {"error": str(error)}
            ), 507

        upload_id = secrets.token_hex(16)
        part_path, metadata_path = get_upload_paths(
            user,
            upload_id,
        )

        metadata = {
            "filename": filename,
            "size": file_size,
            "fingerprint": fingerprint,
            "media_type": media_type,
            "mime_type": mime_type,
        }

        part_path.touch(exist_ok=False)
        part_path.chmod(0o600)

        metadata_path.write_text(
            json.dumps(
                metadata,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        metadata_path.chmod(0o600)

    return jsonify(
        {
            "upload_id": upload_id,
            "received_bytes": 0,
            "size": file_size,
            "resumed": False,
        }
    ), 201


@media_blueprint.put(
    "/api/media/uploads/<upload_id>"
)
@require_media_login
def upload_media_chunk(upload_id):
    user = get_session_user()

    try:
        expected_offset = int(
            request.headers.get(
                "X-Upload-Offset",
                "",
            )
        )
    except ValueError:
        return jsonify(
            {"error": "Invalid upload offset"}
        ), 400

    chunk = request.get_data(cache=False)

    if not chunk:
        return jsonify(
            {"error": "Empty upload chunk"}
        ), 400

    if len(chunk) > MAX_MEDIA_CHUNK_SIZE:
        return jsonify(
            {"error": "Upload chunk is too large"}
        ), 413

    try:
        metadata, part_path, _ = (
            read_upload_metadata(
                user,
                upload_id,
            )
        )
    except FileNotFoundError:
        return jsonify(
            {"error": "Upload not found"}
        ), 404
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400

    with MEDIA_UPLOAD_LOCK:
        current_size = part_path.stat().st_size
        total_size = metadata["size"]

        if expected_offset != current_size:
            return jsonify(
                {
                    "error": "Upload offset mismatch",
                    "expected_offset": current_size,
                }
            ), 409

        if current_size + len(chunk) > total_size:
            return jsonify(
                {"error": "Upload exceeds file size"}
            ), 400

        try:
            check_available_space(
                part_path.parent,
                len(chunk),
            )
        except OSError as error:
            return jsonify(
                {"error": str(error)}
            ), 507

        with part_path.open("ab") as partial_file:
            partial_file.write(chunk)
            partial_file.flush()

        received_bytes = part_path.stat().st_size

    return jsonify(
        {
            "upload_id": upload_id,
            "received_bytes": received_bytes,
            "size": metadata["size"],
        }
    )


@media_blueprint.post(
    "/api/media/uploads/<upload_id>/complete"
)
@require_media_login
def complete_media_upload(upload_id):
    user = get_session_user()

    try:
        metadata, part_path, metadata_path = (
            read_upload_metadata(
                user,
                upload_id,
            )
        )
    except FileNotFoundError:
        return jsonify(
            {"error": "Upload not found"}
        ), 404
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400

    with MEDIA_UPLOAD_LOCK:
        expected_size = metadata["size"]
        received_size = part_path.stat().st_size

        if received_size != expected_size:
            return jsonify(
                {
                    "error": "Upload is incomplete",
                    "received_bytes": received_size,
                    "expected_bytes": expected_size,
                }
            ), 409

        user_root = get_user_media_dir(
            user
        ).resolve()

        destination = (
            user_root / metadata["filename"]
        )

        if destination.exists():
            return jsonify(
                {
                    "error": (
                        "Există deja un fișier "
                        "cu acest nume."
                    )
                }
            ), 409

        part_path.replace(destination)
        metadata_path.unlink(missing_ok=True)

    return jsonify(
        serialize_media_file(
            destination,
            user_root,
        )
    ), 201


@media_blueprint.get("/media")
def media_page():
    return render_template("media.html")


@media_blueprint.get("/api/media")
@require_media_login
def list_media():
    user = get_session_user()
    user_root = get_user_media_dir(user).resolve()

    files = []

    for path in user_root.iterdir():
        if path.is_symlink() or not path.is_file():
            continue

        media_type, _ = detect_media_type(path)

        if media_type is None:
            continue

        files.append(
            serialize_media_file(path, user_root)
        )

    files.sort(
        key=lambda item: item["modified_at"],
        reverse=True,
    )

    return jsonify(
        {
            "count": len(files),
            "files": files,
        }
    )


@media_blueprint.post("/api/media")
@require_media_login
def upload_media():
    user = get_session_user()

    if (
        request.content_length is not None
        and request.content_length
        > MAX_MEDIA_UPLOAD_SIZE
    ):
        return jsonify(
            {
                "error": (
                    "Fișierul depășește limita "
                    "de 100 MB."
                )
            }
        ), 413

    if "file" not in request.files:
        return jsonify(
            {"error": "Missing form field: file"}
        ), 400

    uploaded_file = request.files["file"]

    try:
        filename = validate_media_name(
            uploaded_file.filename
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    temporary_path = Path(filename)
    media_type, mime_type = detect_media_type(
        temporary_path
    )

    if media_type is None:
        return jsonify(
            {
                "error": (
                    "Sunt acceptate numai "
                    "fotografii, fișiere audio "
                    "și fișiere video."
                )
            }
        ), 415

    user_root = get_user_media_dir(user).resolve()
    destination = user_root / filename

    if destination.exists():
        return jsonify(
            {
                "error": (
                    "Există deja un fișier "
                    "cu acest nume."
                )
            }
        ), 409

    uploaded_file.save(str(destination))

    result = serialize_media_file(
        destination,
        user_root,
    )

    result["mime_type"] = mime_type

    return jsonify(result), 201


@media_blueprint.get(
    "/api/media/<path:relative_path>"
)
@require_media_login
def stream_media(relative_path):
    user = get_session_user()

    try:
        target = resolve_media_path(
            user,
            relative_path,
        )
    except (ValueError, OSError):
        return jsonify(
            {"error": "Invalid media path"}
        ), 400

    if not target.is_file():
        return jsonify(
            {"error": "Media file not found"}
        ), 404

    media_type, _ = detect_media_type(target)

    if media_type is None:
        return jsonify(
            {"error": "Unsupported media file"}
        ), 415

    download_requested = (
        request.args.get("download") == "1"
    )

    return send_from_directory(
        str(target.parent),
        target.name,
        as_attachment=download_requested,
        download_name=target.name,
        conditional=True,
    )


@media_blueprint.delete(
    "/api/media/<path:relative_path>"
)
@require_media_login
def delete_media(relative_path):
    user = get_session_user()

    try:
        target = resolve_media_path(
            user,
            relative_path,
        )
    except (ValueError, OSError):
        return jsonify(
            {"error": "Invalid media path"}
        ), 400

    if not target.is_file():
        return jsonify(
            {"error": "Media file not found"}
        ), 404

    deleted_name = target.name
    target.unlink()

    return jsonify(
        {
            "deleted": deleted_name,
        }
    )
