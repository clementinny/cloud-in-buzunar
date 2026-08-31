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
