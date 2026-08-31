import base64
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
TRANSMISSION_RPC_URL = (
    "http://127.0.0.1:9091/transmission/rpc"
)

FILE_VAULT_DIR = DATA_DIR / "uploads"
MEDIA_DIR = DATA_DIR / "media"

MAXIMUM_URL_LENGTH = 4096
MAXIMUM_TORRENT_FILE_SIZE = 10 * 1024 * 1024

class Aria2Error(Exception):
    pass


class TransmissionError(Exception):
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


def transmission_call(method, parameters=None):
    payload = {
        "jsonrpc": "2.0",
        "id": "cloud-in-buzunar",
        "method": method,
        "params": parameters or {},
    }
    session_id = None

    for attempt in range(2):
        headers = {
            "Content-Type": "application/json",
        }

        if session_id:
            headers["X-Transmission-Session-Id"] = session_id

        rpc_request = Request(
            TRANSMISSION_RPC_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(rpc_request, timeout=15) as response:
                result = json.loads(
                    response.read().decode("utf-8")
                )
        except HTTPError as error:
            if error.code == 409 and attempt == 0:
                session_id = error.headers.get(
                    "X-Transmission-Session-Id"
                )

                if session_id:
                    continue

            raise TransmissionError(
                "Transmission service is unavailable"
            ) from error
        except (
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            raise TransmissionError(
                "Transmission service is unavailable"
            ) from error

        if "error" in result:
            error_data = result["error"]

            if isinstance(error_data, dict):
                details = error_data.get("data") or {}
                message = (
                    details.get("error_string")
                    or error_data.get("message")
                    or "Unknown Transmission error"
                )
            else:
                message = str(error_data)

            raise TransmissionError(message)

        return result.get("result", {})

    raise TransmissionError(
        "Transmission session could not be established"
    )


def get_transmission_downloads():
    result = transmission_call(
        "torrent_get",
        {
            "fields": [
                "hash_string",
                "name",
                "status",
                "total_size",
                "size_when_done",
                "left_until_done",
                "percent_done",
                "rate_download",
                "rate_upload",
                "error",
                "error_string",
                "upload_ratio",
                "peers_connected",
            ]
        },
    )

    return result.get("torrents", [])


def serialize_transmission_download(download):
    status_number = int(download.get("status", 0))
    error_number = int(download.get("error", 0))
    status_labels = {
        0: "paused",
        1: "waiting",
        2: "checking",
        3: "waiting",
        4: "active",
        5: "waiting",
        6: "seeding",
    }

    status = status_labels.get(status_number, "waiting")

    if error_number:
        status = "error"

    total_bytes = int(
        download.get("size_when_done")
        or download.get("total_size")
        or 0
    )
    remaining_bytes = int(
        download.get("left_until_done", 0)
    )
    completed_bytes = max(
        total_bytes - remaining_bytes,
        0,
    )

    return {
        "engine": "transmission",
        "gid": download["hash_string"],
        "name": download.get("name", "Torrent"),
        "status": status,
        "total_bytes": total_bytes,
        "completed_bytes": completed_bytes,
        "download_speed": int(
            download.get("rate_download", 0)
        ),
        "upload_speed": int(
            download.get("rate_upload", 0)
        ),
        "progress": round(
            float(download.get("percent_done", 0)) * 100,
            1,
        ),
        "error_message": (
            download.get("error_string")
            if error_number
            else None
        ),
        "upload_ratio": float(
            download.get("upload_ratio", 0)
        ),
        "peers_connected": int(
            download.get("peers_connected", 0)
        ),
    }


def get_transmission_torrent(result):
    torrent = (
        result.get("torrent_added")
        or result.get("torrent_duplicate")
    )

    if not torrent:
        raise TransmissionError(
            "Transmission did not return the torrent"
        )

    return torrent


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
        "engine": "aria2",
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
    serialized_downloads = []
    services = {
        "aria2": "connected",
        "transmission": "connected",
    }

    try:
        serialized_downloads.extend(
            serialize_download(download)
            for download in get_all_downloads()
        )
    except Aria2Error:
        services["aria2"] = "unavailable"

    try:
        serialized_downloads.extend(
            serialize_transmission_download(download)
            for download in get_transmission_downloads()
        )
    except TransmissionError:
        services["transmission"] = "unavailable"

    if all(
        status == "unavailable"
        for status in services.values()
    ):
        return jsonify(
            {"error": "Download services are unavailable"}
        ), 503

    return jsonify(
        {
            "count": len(serialized_downloads),
            "downloads": serialized_downloads,
            "services": services,
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

    try:
        if urlsplit(download_url).scheme == "magnet":
            result = transmission_call(
                "torrent_add",
                {
                    "filename": download_url,
                    "download_dir": str(
                        destination_directory
                    ),
                    "paused": False,
                },
            )
            torrent = get_transmission_torrent(result)
            gid = torrent["hash_string"]
            engine = "transmission"
        else:
            options = {
                "dir": str(destination_directory),
                "continue": "true",
                "max-connection-per-server": "4",
                "split": "4",
                "min-split-size": "10M",
            }
            gid = aria2_call(
                "addUri",
                [download_url],
                options,
            )
            engine = "aria2"
    except (Aria2Error, TransmissionError) as error:
        return jsonify(
            {"error": str(error)}
        ), 503

    return jsonify(
        {
            "engine": engine,
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
    "/api/downloads/torrent"
)
@require_download_admin
def create_torrent_download():
    torrent_file = request.files.get("file")
    owner_id_value = request.form.get("owner_id")
    destination = request.form.get("destination")

    if torrent_file is None:
        return jsonify(
            {"error": "Missing torrent file"}
        ), 400

    if (
        not torrent_file.filename
        or not torrent_file.filename.lower().endswith(
            ".torrent"
        )
    ):
        return jsonify(
            {
                "error": (
                    "Trebuie selectat un fișier "
                    "cu extensia .torrent"
                )
            }
        ), 400

    try:
        owner_id = int(owner_id_value)
        owner = resolve_download_owner(owner_id)
        destination_directory = (
            resolve_download_directory(
                owner,
                destination,
            )
        )
    except (TypeError, ValueError) as error:
        return jsonify(
            {"error": str(error)}
        ), 400

    torrent_data = torrent_file.stream.read(
        MAXIMUM_TORRENT_FILE_SIZE + 1
    )

    if not torrent_data:
        return jsonify(
            {"error": "Torrent file is empty"}
        ), 400

    if (
        len(torrent_data)
        > MAXIMUM_TORRENT_FILE_SIZE
    ):
        return jsonify(
            {
                "error": (
                    "Fișierul torrent depășește "
                    "limita de 10 MB."
                )
            }
        ), 413

    encoded_torrent = base64.b64encode(
        torrent_data
    ).decode("ascii")

    try:
        result = transmission_call(
            "torrent_add",
            {
                "metainfo": encoded_torrent,
                "download_dir": str(
                    destination_directory
                ),
                "paused": False,
            },
        )
        torrent = get_transmission_torrent(result)
    except TransmissionError as error:
        return jsonify(
            {"error": str(error)}
        ), 503

    return jsonify(
        {
            "engine": "transmission",
            "gid": torrent["hash_string"],
            "torrent": torrent_file.filename,
            "owner": {
                "id": owner["id"],
                "username": owner["username"],
            },
            "destination": destination,
        }
    ), 201


def validate_torrent_hash(torrent_hash):
    normalized_hash = torrent_hash.lower()

    if (
        len(normalized_hash) != 40
        or any(
            character not in "0123456789abcdef"
            for character in normalized_hash
        )
    ):
        raise ValueError("Invalid torrent hash")

    return normalized_hash


@downloads_blueprint.post(
    "/api/downloads/transmission/<torrent_hash>/pause"
)
@require_download_admin
def pause_transmission_download(torrent_hash):
    try:
        torrent_hash = validate_torrent_hash(torrent_hash)
        transmission_call(
            "torrent_stop",
            {"ids": [torrent_hash]},
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except TransmissionError as error:
        return jsonify({"error": str(error)}), 409

    return jsonify(
        {"gid": torrent_hash, "status": "paused"}
    )


@downloads_blueprint.post(
    "/api/downloads/transmission/<torrent_hash>/resume"
)
@require_download_admin
def resume_transmission_download(torrent_hash):
    try:
        torrent_hash = validate_torrent_hash(torrent_hash)
        transmission_call(
            "torrent_start",
            {"ids": [torrent_hash]},
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except TransmissionError as error:
        return jsonify({"error": str(error)}), 409

    return jsonify(
        {"gid": torrent_hash, "status": "active"}
    )


@downloads_blueprint.delete(
    "/api/downloads/transmission/<torrent_hash>"
)
@require_download_admin
def remove_transmission_download(torrent_hash):
    try:
        torrent_hash = validate_torrent_hash(torrent_hash)
        transmission_call(
            "torrent_remove",
            {
                "ids": [torrent_hash],
                "delete_local_data": False,
            },
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except TransmissionError as error:
        return jsonify({"error": str(error)}), 409

    return jsonify({"removed": torrent_hash})


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
