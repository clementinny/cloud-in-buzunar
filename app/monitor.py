import json
import hashlib
import queue
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint,
    g,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)

from app.database import (
    arm_monitor_source,
    claim_monitor_recording_speech_analysis,
    clear_monitor_source,
    clear_monitor_session,
    create_monitor_session,
    create_monitor_pairing_code,
    create_monitor_recording,
    consume_monitor_pairing_code,
    delete_expired_monitor_recordings,
    delete_monitor_recording,
    find_user_by_id,
    find_monitor_device_by_token_hash,
    find_monitor_recording,
    get_active_monitor_source,
    get_active_monitor_session,
    get_monitor_recording_settings,
    list_monitor_recordings,
    reset_monitor_recording_speech_analysis,
    set_monitor_source_desired_state,
    set_monitor_recording_actual_mode,
    set_monitor_recording_speech_analysis,
    set_monitor_recording_settings,
    set_monitor_answer,
    touch_monitor_session,
    touch_monitor_viewer_session,
    update_monitor_source,
)
from app.speech_activity import (
    detect_speech_activity,
    speech_analysis_available,
)


monitor_blueprint = Blueprint("monitor", __name__)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAXIMUM_SDP_LENGTH = 200_000
SOURCE_STATES = {"armed", "starting", "live", "error"}
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECORDING_MODES = {"off", "audio", "video"}
RECORDING_RETENTION_HOURS = {24, 48}
DATA_DIR = Path.home() / "cloud-in-buzunar-data"
MONITOR_RECORDING_DIR = DATA_DIR / "monitor-recordings"
MONITOR_RECORDING_DIR.mkdir(parents=True, exist_ok=True)
MONITOR_RECORDING_DIR.chmod(0o700)
SPEECH_ANALYSIS_QUEUE = queue.Queue()


def run_speech_analysis_worker():
    while True:
        recording_id, file_name, duration = (
            SPEECH_ANALYSIS_QUEUE.get()
        )

        try:
            if not claim_monitor_recording_speech_analysis(recording_id):
                continue

            status, events = detect_speech_activity(
                MONITOR_RECORDING_DIR / file_name,
                duration,
            )
            set_monitor_recording_speech_analysis(
                recording_id,
                status,
                json.dumps(events),
            )
        except Exception:
            set_monitor_recording_speech_analysis(
                recording_id,
                "failed",
                "[]",
            )
        finally:
            SPEECH_ANALYSIS_QUEUE.task_done()


threading.Thread(
    target=run_speech_analysis_worker,
    name="monitor-speech-analysis",
    daemon=True,
).start()


def get_session_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user


def require_monitor_admin(view_function):
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


def hash_monitor_secret(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_bearer_token():
    authorization = request.headers.get("Authorization", "")

    if not authorization.startswith("Bearer "):
        return None

    token = authorization[7:].strip()
    return token or None


def require_monitor_source(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_session_user()

        if user is not None and user["role"] == "admin":
            g.monitor_source_user = user
            return view_function(*args, **kwargs)

        token = get_bearer_token()
        device = None

        if token is not None:
            device = find_monitor_device_by_token_hash(
                hash_monitor_secret(token)
            )

        if device is None:
            return jsonify(
                {"error": "Monitor device authentication required"}
            ), 401

        g.monitor_source_user = {
            "id": device["user_id"],
            "username": device["username"],
            "role": device["role"],
            "is_active": device["is_active"],
        }
        g.monitor_device = device
        return view_function(*args, **kwargs)

    return wrapped_view


def validate_session_id(value):
    if (
        not isinstance(value, str)
        or not SESSION_ID_PATTERN.fullmatch(value)
    ):
        raise ValueError("Invalid monitor session ID")

    return value


def validate_description(value, expected_type):
    if not isinstance(value, dict):
        raise ValueError("Invalid WebRTC description")

    description_type = value.get("type")
    sdp = value.get("sdp")

    if description_type != expected_type:
        raise ValueError(
            f"WebRTC description must be {expected_type}"
        )

    if not isinstance(sdp, str) or not sdp.strip():
        raise ValueError("WebRTC SDP cannot be empty")

    if len(sdp) > MAXIMUM_SDP_LENGTH:
        raise ValueError("WebRTC SDP is too large")

    return {
        "type": description_type,
        "sdp": sdp,
    }


def read_json_description(value):
    if not value:
        return None

    try:
        description = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None

    if not isinstance(description, dict):
        return None

    return description


def serialize_recording(recording):
    try:
        speech_events = json.loads(recording["speech_events_json"])
    except (TypeError, json.JSONDecodeError):
        speech_events = []

    if not isinstance(speech_events, list):
        speech_events = []

    return {
        "id": recording["id"],
        "mode": recording["mode"],
        "camera_facing": recording["camera_facing"],
        "container": recording["container"],
        "speech_status": recording["speech_status"],
        "speech_events": speech_events,
        "started_at": recording["started_at"],
        "ended_at": recording["ended_at"],
        "size_bytes": recording["size_bytes"],
        "play_url": (
            f"/api/monitor/recordings/{recording['id']}"
        ),
    }


def schedule_speech_analysis(recording):
    status = recording["speech_status"]

    if status not in {"pending", "unavailable"}:
        return

    if status == "unavailable" and not speech_analysis_available():
        return

    try:
        started_at = datetime.fromisoformat(recording["started_at"])
        ended_at = datetime.fromisoformat(recording["ended_at"])
    except (TypeError, ValueError):
        set_monitor_recording_speech_analysis(
            recording["id"],
            "failed",
            "[]",
        )
        return

    duration = max(0.0, (ended_at - started_at).total_seconds())
    SPEECH_ANALYSIS_QUEUE.put(
        (
            recording["id"],
            recording["file_name"],
            duration,
        )
    )


def prune_monitor_recordings(retention_hours=None):
    if retention_hours is None:
        settings = get_monitor_recording_settings()
        retention_hours = settings["retention_hours"]

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=retention_hours)
    ).isoformat()
    expired = delete_expired_monitor_recordings(cutoff)

    for recording in expired:
        (MONITOR_RECORDING_DIR / recording["file_name"]).unlink(
            missing_ok=True
        )


def parse_recording_timestamp(value, field_name):
    try:
        milliseconds = int(value)
        timestamp = datetime.fromtimestamp(
            milliseconds / 1000,
            timezone.utc,
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Invalid {field_name}") from error

    return timestamp


@monitor_blueprint.get("/monitor")
def monitor_page():
    return render_template("monitor.html")


@monitor_blueprint.get("/monitor/source")
def monitor_source_page():
    return render_template("monitor_source.html")


@monitor_blueprint.post("/api/monitor/devices/pairing-code")
@require_monitor_admin
def monitor_create_pairing_code():
    user = get_session_user()
    raw_code = "".join(
        secrets.choice(PAIRING_ALPHABET) for _ in range(8)
    )
    display_code = f"{raw_code[:4]}-{raw_code[4:]}"
    expires_at = create_monitor_pairing_code(
        hash_monitor_secret(raw_code),
        user["id"],
    )

    return jsonify(
        {
            "code": display_code,
            "expires_at": expires_at,
            "expires_in_seconds": 300,
        }
    ), 201


@monitor_blueprint.post("/api/monitor/devices/pair")
def monitor_pair_device():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    pairing_code = payload.get("code")
    device_name = payload.get("device_name")

    if not isinstance(pairing_code, str):
        return jsonify({"error": "Invalid pairing code"}), 400

    normalized_code = re.sub(
        r"[^A-Za-z0-9]",
        "",
        pairing_code,
    ).upper()

    if len(normalized_code) != 8:
        return jsonify({"error": "Invalid pairing code"}), 400

    if not isinstance(device_name, str):
        return jsonify({"error": "Invalid device name"}), 400

    safe_device_name = device_name.strip()[:80]

    if not safe_device_name:
        return jsonify({"error": "Invalid device name"}), 400

    token = secrets.token_urlsafe(32)
    device = consume_monitor_pairing_code(
        hash_monitor_secret(normalized_code),
        safe_device_name,
        hash_monitor_secret(token),
    )

    if device is None:
        return jsonify(
            {"error": "Pairing code is invalid or expired"}
        ), 401

    return jsonify(
        {
            "token": token,
            "device": device,
        }
    ), 201


@monitor_blueprint.get("/api/monitor/status")
@require_monitor_admin
def monitor_status():
    monitor_source = get_active_monitor_source()
    monitor_session = get_active_monitor_session()
    recording_settings = get_monitor_recording_settings()

    response = {
        "armed": monitor_source is not None,
        "active": monitor_session is not None,
        "source_state": None,
        "source_error": None,
        "recording": {
            "desired_mode": recording_settings["desired_mode"],
            "actual_mode": recording_settings["actual_mode"],
            "retention_hours": recording_settings["retention_hours"],
            "camera_facing": recording_settings["camera_facing"],
        },
    }

    if monitor_source is not None:
        response.update(
            {
                "source_state": monitor_source["actual_state"],
                "desired_state": monitor_source["desired_state"],
                "source_error": monitor_source["error_message"],
                "source": {
                    "id": monitor_source["user_id"],
                    "username": monitor_source["username"],
                },
                "camera_facing": monitor_source["camera_facing"],
                "source_updated_at": monitor_source["last_seen_at"],
            }
        )

    if monitor_session is None:
        return jsonify(response)

    response.update(
        {
            "session_id": monitor_session["session_id"],
            "offer": read_json_description(
                monitor_session["offer_json"]
            ),
            "viewer_connected": (
                monitor_session["answer_json"] is not None
            ),
            "updated_at": monitor_session[
                "source_updated_at"
            ],
        }
    )

    return jsonify(response)


@monitor_blueprint.post("/api/monitor/source/arm")
@require_monitor_source
def monitor_source_arm():
    user = g.monitor_source_user
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    try:
        source_id = validate_session_id(payload.get("source_id"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    camera_facing = payload.get("camera_facing")

    if camera_facing not in {"environment", "user"}:
        return jsonify({"error": "Invalid camera selection"}), 400

    arm_monitor_source(
        source_id,
        user["id"],
        camera_facing,
    )

    return jsonify(
        {
            "armed": True,
            "source_id": source_id,
            "desired_state": "armed",
        }
    ), 201


@monitor_blueprint.post("/api/monitor/source/poll")
@require_monitor_source
def monitor_source_poll():
    user = g.monitor_source_user
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    try:
        source_id = validate_session_id(payload.get("source_id"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    actual_state = payload.get("actual_state")

    if actual_state not in SOURCE_STATES:
        return jsonify({"error": "Invalid source state"}), 400

    error_message = payload.get("error")
    recording_mode = payload.get("recording_mode", "off")

    if recording_mode not in RECORDING_MODES:
        return jsonify({"error": "Invalid recording mode"}), 400

    if error_message is not None:
        if not isinstance(error_message, str):
            return jsonify({"error": "Invalid source error"}), 400

        error_message = error_message.strip()[:500] or None

    source = update_monitor_source(
        source_id,
        user["id"],
        actual_state,
        error_message,
    )

    if source is None:
        return jsonify({"armed": False}), 404

    set_monitor_recording_actual_mode(recording_mode)
    recording_settings = get_monitor_recording_settings()

    return jsonify(
        {
            "armed": True,
            "desired_state": source["desired_state"],
            "camera_facing": source["camera_facing"],
            "recording_mode": recording_settings["desired_mode"],
            "recording_camera_facing": recording_settings[
                "camera_facing"
            ],
            "retention_hours": recording_settings["retention_hours"],
        }
    )


@monitor_blueprint.delete(
    "/api/monitor/source/<source_id>"
)
@require_monitor_source
def monitor_source_disarm(source_id):
    user = g.monitor_source_user

    try:
        safe_source_id = validate_session_id(source_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    was_deleted = clear_monitor_source(
        safe_source_id,
        user["id"],
    )

    return jsonify(
        {
            "armed": False,
            "disarmed": was_deleted,
        }
    )


@monitor_blueprint.post("/api/monitor/control")
@require_monitor_admin
def monitor_control():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    desired_state = payload.get("state")

    if desired_state not in {"armed", "live"}:
        return jsonify({"error": "Invalid desired state"}), 400

    camera_facing = payload.get("camera_facing")

    if camera_facing is not None and camera_facing not in {
        "environment",
        "user",
    }:
        return jsonify({"error": "Invalid camera selection"}), 400

    source = set_monitor_source_desired_state(
        desired_state,
        camera_facing,
    )

    if source is None:
        return jsonify({"error": "No armed source available"}), 404

    return jsonify(
        {
            "armed": True,
            "desired_state": desired_state,
            "camera_facing": source["camera_facing"],
        }
    )


@monitor_blueprint.post("/api/monitor/recordings/control")
@require_monitor_admin
def monitor_recording_control():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    mode = payload.get("mode")
    retention_hours = payload.get("retention_hours")
    camera_facing = payload.get("camera_facing")

    if mode not in RECORDING_MODES:
        return jsonify({"error": "Invalid recording mode"}), 400

    if retention_hours not in RECORDING_RETENTION_HOURS:
        return jsonify({"error": "Invalid recording retention"}), 400

    if camera_facing not in {"environment", "user"}:
        return jsonify({"error": "Invalid camera selection"}), 400

    source = get_active_monitor_source()

    if source is None:
        return jsonify({"error": "No armed source available"}), 404

    if mode != "off" and (
        source["desired_state"] == "live"
        or source["actual_state"] in {"starting", "live"}
    ):
        return jsonify(
            {
                "error": (
                    "Oprește transmisia live înainte de înregistrare"
                )
            }
        ), 409

    set_monitor_source_desired_state("armed")
    settings = set_monitor_recording_settings(
        mode,
        retention_hours,
        camera_facing,
    )
    prune_monitor_recordings(retention_hours)

    return jsonify(
        {
            "desired_mode": settings["desired_mode"],
            "actual_mode": settings["actual_mode"],
            "retention_hours": settings["retention_hours"],
            "camera_facing": settings["camera_facing"],
        }
    )


@monitor_blueprint.post("/api/monitor/recordings")
@require_monitor_source
def monitor_upload_recording():
    uploaded_file = request.files.get("recording")
    mode = request.form.get("mode")
    camera_facing = request.form.get("camera_facing") or None
    container = request.form.get("container", "mp4")

    if uploaded_file is None:
        return jsonify({"error": "Missing recording file"}), 400

    if mode not in {"audio", "video"}:
        return jsonify({"error": "Invalid recording mode"}), 400

    if container not in {"mp4", "webm"}:
        return jsonify({"error": "Invalid recording container"}), 400

    if mode == "video" and camera_facing not in {
        "environment",
        "user",
    }:
        return jsonify({"error": "Invalid camera selection"}), 400

    if mode == "audio":
        camera_facing = None

    try:
        started_at = parse_recording_timestamp(
            request.form.get("started_at_ms"),
            "recording start",
        )
        ended_at = parse_recording_timestamp(
            request.form.get("ended_at_ms"),
            "recording end",
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    duration = (ended_at - started_at).total_seconds()

    if duration < 0 or duration > 15 * 60:
        return jsonify({"error": "Invalid recording duration"}), 400

    if container == "webm":
        extension = ".webm"
    else:
        extension = ".m4a" if mode == "audio" else ".mp4"
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    file_name = f"{timestamp}-{uuid.uuid4().hex}{extension}"
    final_path = MONITOR_RECORDING_DIR / file_name
    temporary_path = MONITOR_RECORDING_DIR / f".{file_name}.part"

    try:
        uploaded_file.save(temporary_path)
        size_bytes = temporary_path.stat().st_size

        if size_bytes == 0:
            temporary_path.unlink(missing_ok=True)
            return jsonify({"error": "Recording is empty"}), 400

        temporary_path.replace(final_path)
        recording_id = create_monitor_recording(
            g.monitor_source_user["id"],
            mode,
            camera_facing,
            file_name,
            started_at.isoformat(),
            ended_at.isoformat(),
            size_bytes,
            container,
        )
    except OSError:
        temporary_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        return jsonify({"error": "Recording could not be stored"}), 500

    recording = find_monitor_recording(recording_id)
    schedule_speech_analysis(recording)
    response = serialize_recording(recording)
    prune_monitor_recordings()
    return jsonify(response), 201


@monitor_blueprint.get("/api/monitor/recordings")
@require_monitor_admin
def monitor_list_recordings():
    prune_monitor_recordings()
    recordings = list_monitor_recordings()

    for recording in recordings:
        schedule_speech_analysis(recording)

    total_size = sum(recording["size_bytes"] for recording in recordings)
    return jsonify(
        {
            "count": len(recordings),
            "size_bytes": total_size,
            "recordings": [
                serialize_recording(recording)
                for recording in recordings
            ],
        }
    )


@monitor_blueprint.get("/api/monitor/recordings/<int:recording_id>")
@require_monitor_admin
def monitor_play_recording(recording_id):
    recording = find_monitor_recording(recording_id)

    if recording is None:
        return jsonify({"error": "Recording not found"}), 404

    recording_path = MONITOR_RECORDING_DIR / recording["file_name"]

    if not recording_path.is_file():
        return jsonify({"error": "Recording file not found"}), 404

    mimetype = f"{recording['mode']}/{recording['container']}"
    return send_file(
        recording_path,
        mimetype=mimetype,
        conditional=True,
    )


@monitor_blueprint.post(
    "/api/monitor/recordings/<int:recording_id>/speech/reanalyze"
)
@require_monitor_admin
def monitor_reanalyze_recording(recording_id):
    if not speech_analysis_available():
        return jsonify(
            {"error": "FFmpeg is not available on the server"}
        ), 503

    recording = find_monitor_recording(recording_id)

    if recording is None:
        return jsonify({"error": "Recording not found"}), 404

    recording_path = MONITOR_RECORDING_DIR / recording["file_name"]

    if not recording_path.is_file():
        return jsonify({"error": "Recording file not found"}), 404

    reset_monitor_recording_speech_analysis(recording_id)
    recording = find_monitor_recording(recording_id)
    schedule_speech_analysis(recording)

    return jsonify(
        {
            "recording_id": recording_id,
            "speech_status": "pending",
        }
    ), 202


@monitor_blueprint.delete("/api/monitor/recordings/<int:recording_id>")
@require_monitor_admin
def monitor_delete_recording(recording_id):
    recording = delete_monitor_recording(recording_id)

    if recording is None:
        return jsonify({"error": "Recording not found"}), 404

    (MONITOR_RECORDING_DIR / recording["file_name"]).unlink(
        missing_ok=True
    )
    return jsonify({"deleted": recording_id})


@monitor_blueprint.post("/api/monitor/offer")
@require_monitor_source
def monitor_offer():
    user = g.monitor_source_user
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    try:
        session_id = validate_session_id(
            payload.get("session_id")
        )
        offer = validate_description(
            payload.get("offer"),
            "offer",
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    create_monitor_session(
        session_id,
        user["id"],
        json.dumps(offer),
    )

    return jsonify(
        {
            "active": True,
            "session_id": session_id,
        }
    ), 201


@monitor_blueprint.post("/api/monitor/heartbeat")
@require_monitor_source
def monitor_heartbeat():
    user = g.monitor_source_user
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    try:
        session_id = validate_session_id(
            payload.get("session_id")
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    is_active = touch_monitor_session(
        session_id,
        user["id"],
    )

    return jsonify({"active": is_active})


@monitor_blueprint.get("/api/monitor/answer")
@require_monitor_source
def monitor_answer_status():
    try:
        session_id = validate_session_id(
            request.args.get("session_id")
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    monitor_session = get_active_monitor_session()

    if (
        monitor_session is None
        or monitor_session["session_id"] != session_id
    ):
        return jsonify(
            {
                "active": False,
                "answer": None,
            }
        )

    return jsonify(
        {
            "active": True,
            "answer": read_json_description(
                monitor_session["answer_json"]
            ),
        }
    )


@monitor_blueprint.post("/api/monitor/answer")
@require_monitor_admin
def monitor_answer():
    user = get_session_user()
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    try:
        session_id = validate_session_id(
            payload.get("session_id")
        )
        answer = validate_description(
            payload.get("answer"),
            "answer",
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    was_updated = set_monitor_answer(
        session_id,
        user["id"],
        json.dumps(answer),
    )

    if not was_updated:
        return jsonify(
            {"error": "Monitor session is no longer active"}
        ), 404

    return jsonify(
        {
            "active": True,
            "session_id": session_id,
        }
    )


@monitor_blueprint.post("/api/monitor/viewer/heartbeat")
@require_monitor_admin
def monitor_viewer_heartbeat():
    user = get_session_user()
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    try:
        session_id = validate_session_id(
            payload.get("session_id")
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    is_active = touch_monitor_viewer_session(
        session_id,
        user["id"],
    )

    return jsonify({"active": is_active})


@monitor_blueprint.delete(
    "/api/monitor/session/<session_id>"
)
@require_monitor_source
def monitor_stop(session_id):
    try:
        safe_session_id = validate_session_id(session_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    was_deleted = clear_monitor_session(safe_session_id)

    return jsonify(
        {
            "active": False,
            "stopped": was_deleted,
        }
    )
