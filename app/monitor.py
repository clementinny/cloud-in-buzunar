import json
import re
from functools import wraps

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    session,
)

from app.database import (
    clear_monitor_session,
    create_monitor_session,
    find_user_by_id,
    get_active_monitor_session,
    set_monitor_answer,
    touch_monitor_session,
)


monitor_blueprint = Blueprint("monitor", __name__)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAXIMUM_SDP_LENGTH = 200_000


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


@monitor_blueprint.get("/monitor")
def monitor_page():
    return render_template("monitor.html")


@monitor_blueprint.get("/monitor/source")
def monitor_source_page():
    return render_template("monitor_source.html")


@monitor_blueprint.get("/api/monitor/status")
@require_monitor_admin
def monitor_status():
    monitor_session = get_active_monitor_session()

    if monitor_session is None:
        return jsonify({"active": False})

    return jsonify(
        {
            "active": True,
            "session_id": monitor_session["session_id"],
            "source": {
                "id": monitor_session["source_user_id"],
                "username": monitor_session["source_username"],
            },
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


@monitor_blueprint.post("/api/monitor/offer")
@require_monitor_admin
def monitor_offer():
    user = get_session_user()
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
@require_monitor_admin
def monitor_heartbeat():
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

    is_active = touch_monitor_session(
        session_id,
        user["id"],
    )

    return jsonify({"active": is_active})


@monitor_blueprint.get("/api/monitor/answer")
@require_monitor_admin
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


@monitor_blueprint.delete(
    "/api/monitor/session/<session_id>"
)
@require_monitor_admin
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
