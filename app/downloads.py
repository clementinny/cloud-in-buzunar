import json
from functools import wraps
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    session,
)

from app.database import find_user_by_id


downloads_blueprint = Blueprint(
    "downloads",
    __name__,
)

DATA_DIR = Path.home() / "cloud-in-buzunar-data"
ARIA2_DIR = DATA_DIR / "aria2"
ARIA2_SECRET_FILE = ARIA2_DIR / "rpc-secret"
ARIA2_RPC_URL = "http://127.0.0.1:6800/jsonrpc"

FILE_VAULT_DIR = DATA_DIR / "uploads"
MEDIA_DIR = DATA_DIR / "media"

MAXIMUM_URL_LENGTH = 4096


class Aria2Error(Exception):
    pass


def get_session_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user


def require_download_admin(view_function):
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


def get_aria2_secret():
    try:
        secret = ARIA2_SECRET_FILE.read_text(
            encoding="utf-8"
        ).strip()
    except OSError as error:
        raise Aria2Error(
            "Aria2 RPC secret cannot be read"
        ) from error

    if not secret:
        raise Aria2Error(
            "Aria2 RPC secret is empty"
        )

    return secret


def aria2_call(method, *parameters):
    payload = {
        "jsonrpc": "2.0",
        "id": "cloud-in-buzunar",
        "method": f"aria2.{method}",
        "params": [
            f"token:{get_aria2_secret()}",
            *parameters,
        ],
    }

    rpc_request = Request(
        ARIA2_RPC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(
            rpc_request,
            timeout=15,
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise Aria2Error(
            "Download service is unavailable"
        ) from error

    if "error" in result:
        message = result["error"].get(
            "message",
            "Unknown aria2 error",
        )
        raise Aria2Error(message)

    return result.get("result")


def validate_download_url(value):
    if not isinstance(value, str):
        raise ValueError("URL must be text")

    normalized_url = value.strip()

    if not normalized_url:
        raise ValueError("URL cannot be empty")

    if len(normalized_url) > MAXIMUM_URL_LENGTH:
        raise ValueError("URL is too long")

    parsed_url = urlsplit(normalized_url)

    if parsed_url.scheme == "magnet":
        if not normalized_url.startswith(
            "magnet:?xt="
        ):
            raise ValueError("Invalid magnet link")

        return normalized_url

    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
    ):
        raise ValueError(
            "Only HTTP, HTTPS and magnet links are accepted"
        )

    return normalized_url


def resolve_download_owner(owner_id):
    if owner_id is None:
        return get_session_user()

    if (
        isinstance(owner_id, bool)
        or not isinstance(owner_id, int)
    ):
        raise ValueError("Invalid owner ID")

    owner = find_user_by_id(owner_id)

    if owner is None:
        raise ValueError("User not found")

    return owner


def resolve_download_directory(owner, destination):
    if destination == "files":
        directory = FILE_VAULT_DIR / str(owner["id"])
    elif destination == "media":
        directory = MEDIA_DIR / str(owner["id"])
    else:
        raise ValueError(
            "Destination must be files or media"
        )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory.resolve()


def get_download_name(download):
    bittorrent = download.get("bittorrent") or {}
    torrent_information = bittorrent.get("info") or {}
    torrent_name = torrent_information.get("name")

    if torrent_name:
        return torrent_name

    files = download.get("files") or []

    if files:
        file_path = files[0].get("path")

        if file_path:
            return Path(file_path).name

        uris = files[0].get("uris") or []

        if uris:
            uri = uris[0].get("uri", "")
            parsed_uri = urlsplit(uri)

            if parsed_uri.path:
                return Path(parsed_uri.path).name

    return download.get("gid", "Download")


def serialize_download(download):
    total_length = int(
        download.get("totalLength", 0)
    )
    completed_length = int(
        download.get("completedLength", 0)
    )

    progress = 0

    if total_length > 0:
        progress = round(
            completed_length / total_length * 100,
            1,
        )

    return {
        "gid": download["gid"],
        "name": get_download_name(download),
        "status": download.get("status"),
        "total_bytes": total_length,
        "completed_bytes": completed_length,
        "download_speed": int(
            download.get("downloadSpeed", 0)
        ),
        "upload_speed": int(
            download.get("uploadSpeed", 0)
        ),
        "progress": progress,
        "error_message": download.get(
            "errorMessage"
        ),
    }


def get_all_downloads():
    fields = [
        "gid",
        "status",
        "totalLength",
        "completedLength",
        "downloadSpeed",
        "uploadSpeed",
        "errorMessage",
        "files",
        "bittorrent",
    ]

    active = aria2_call(
        "tellActive",
        fields,
    )
    waiting = aria2_call(
        "tellWaiting",
        0,
        100,
        fields,
    )
    stopped = aria2_call(
        "tellStopped",
        0,
        100,
        fields,
    )

    return [
        *active,
        *waiting,
        *stopped,
    ]


def validate_gid(gid):
    if (
        len(gid) != 16
        or any(
            character not in "0123456789abcdef"
            for character in gid
        )
    ):
        raise ValueError("Invalid download ID")

    return gid


@downloads_blueprint.get("/downloads")
def downloads_page():
    return render_template("downloads.html")


@downloads_blueprint.get("/api/downloads")
@require_download_admin
def list_downloads():
    try:
        downloads = get_all_downloads()
    except Aria2Error as error:
        return jsonify(
            {"error": str(error)}
        ), 503

    serialized_downloads = [
        serialize_download(download)
        for download in downloads
    ]

    return jsonify(
        {
            "count": len(serialized_downloads),
            "downloads": serialized_downloads,
        }
    )


@downloads_blueprint.post("/api/downloads")
@require_download_admin
def create_download():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Expected JSON body"}
        ), 400

    try:
        download_url = validate_download_url(
            payload.get("url")
        )
        owner = resolve_download_owner(
            payload.get("owner_id")
        )
        destination_directory = (
            resolve_download_directory(
                owner,
                payload.get("destination"),
            )
        )
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400

    options = {
        "dir": str(destination_directory),
        "continue": "true",
        "max-connection-per-server": "4",
        "split": "4",
        "min-split-size": "10M",
    }

    try:
        gid = aria2_call(
            "addUri",
            [download_url],
            options,
        )
    except Aria2Error as error:
        return jsonify(
            {"error": str(error)}
        ), 503

    return jsonify(
        {
            "gid": gid,
            "owner": {
                "id": owner["id"],
                "username": owner["username"],
            },
            "destination": payload.get(
                "destination"
            ),
        }
    ), 201


@downloads_blueprint.post(
    "/api/downloads/<gid>/pause"
)
@require_download_admin
def pause_download(gid):
    try:
        validate_gid(gid)
        aria2_call("pause", gid)
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400
    except Aria2Error as error:
        return jsonify(
            {"error": str(error)}
        ), 409

    return jsonify({"gid": gid, "status": "paused"})


@downloads_blueprint.post(
    "/api/downloads/<gid>/resume"
)
@require_download_admin
def resume_download(gid):
    try:
        validate_gid(gid)
        aria2_call("unpause", gid)
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400
    except Aria2Error as error:
        return jsonify(
            {"error": str(error)}
        ), 409

    return jsonify({"gid": gid, "status": "active"})


@downloads_blueprint.delete(
    "/api/downloads/<gid>"
)
@require_download_admin
def remove_download(gid):
    try:
        validate_gid(gid)

        status = aria2_call(
            "tellStatus",
            gid,
            ["status"],
        )

        if status["status"] in {
            "active",
            "waiting",
            "paused",
        }:
            aria2_call("forceRemove", gid)
        else:
            aria2_call(
                "removeDownloadResult",
                gid,
            )
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400
    except Aria2Error as error:
        return jsonify(
            {"error": str(error)}
        ), 409

    return jsonify({"removed": gid})
