import json
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    session,
)

from app.database import find_user_by_id
from app.ai_runtime import (
    AiRuntimeError,
    MODEL_PROFILES,
    get_active_profile,
    get_runtime_status,
    switch_model,
)


ai_blueprint = Blueprint("ai", __name__)

LLAMA_HEALTH_URL = "http://127.0.0.1:8081/health"
LLAMA_CHAT_URL = (
    "http://127.0.0.1:8081/v1/chat/completions"
)

MAXIMUM_MESSAGES = 10
MAXIMUM_MESSAGE_CHARACTERS = 2000
MAXIMUM_TOTAL_CHARACTERS = 6000
MAXIMUM_RESPONSE_TOKENS = 256

SYSTEM_MESSAGE = (
    "Ești asistentul AI local al aplicației CloudInBuzunar. "
    "Răspunde implicit în limba română, clar, practic și concis. "
    "Nu inventa nume, date, citate, evenimente sau funcții. "
    "Dacă nu ești sigur, spune clar acest lucru și recomandă "
    "verificarea informației. Separă faptele cunoscute de "
    "presupuneri. Nu pretinde că ai acces la internet sau la "
    "fișierele serverului dacă acestea nu au fost oferite "
    "explicit în conversație."
)


class AiServiceError(Exception):
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


def require_ai_login(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_session_user()

        if user is None:
            return jsonify(
                {"error": "Authentication required"}
            ), 401

        return view_function(*args, **kwargs)

    return wrapped_view


def require_ai_admin(view_function):
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


def serialize_model_profiles():
    return [
        {
            "mode": mode,
            "label": profile["short_label"],
            "description": profile["description"],
        }
        for mode, profile in MODEL_PROFILES.items()
    ]


def read_llama_response(rpc_request, timeout):
    try:
        with urlopen(
            rpc_request,
            timeout=timeout,
        ) as response:
            return json.loads(
                response.read().decode("utf-8")
            )
    except HTTPError as error:
        raise AiServiceError(
            f"AI service returned HTTP {error.code}"
        ) from error
    except (
        URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise AiServiceError(
            "AI service is unavailable"
        ) from error


def validate_messages(value):
    if not isinstance(value, list) or not value:
        raise ValueError("Messages must be a non-empty list")

    if len(value) > MAXIMUM_MESSAGES:
        value = value[-MAXIMUM_MESSAGES:]

    messages = []
    total_characters = 0

    for message in value:
        if not isinstance(message, dict):
            raise ValueError("Invalid message")

        role = message.get("role")
        content = message.get("content")

        if role not in {"user", "assistant"}:
            raise ValueError("Invalid message role")

        if not isinstance(content, str):
            raise ValueError("Message content must be text")

        normalized_content = content.strip()

        if not normalized_content:
            raise ValueError("Message cannot be empty")

        if (
            len(normalized_content)
            > MAXIMUM_MESSAGE_CHARACTERS
        ):
            raise ValueError("Message is too long")

        total_characters += len(normalized_content)

        if total_characters > MAXIMUM_TOTAL_CHARACTERS:
            raise ValueError(
                "Conversation is too long; clear older messages"
            )

        messages.append(
            {
                "role": role,
                "content": normalized_content,
            }
        )

    if messages[-1]["role"] != "user":
        raise ValueError(
            "The final message must belong to the user"
        )

    return messages


@ai_blueprint.get("/ai")
def ai_page():
    return render_template("ai.html")


@ai_blueprint.get("/api/ai/status")
@require_ai_login
def ai_status():
    user = get_session_user()
    status = get_runtime_status()

    return jsonify(
        {
            **status,
            "can_manage": user["role"] == "admin",
            "available_models": serialize_model_profiles(),
        }
    )


@ai_blueprint.post("/api/ai/model")
@require_ai_admin
def ai_switch_model():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    mode = payload.get("mode")

    if mode not in MODEL_PROFILES:
        return jsonify(
            {"error": "Mode must be rapid or quality"}
        ), 400

    try:
        status = switch_model(mode)
    except AiRuntimeError as error:
        return jsonify({"error": str(error)}), 503

    return jsonify(status)


@ai_blueprint.post("/api/ai/chat")
@require_ai_login
def ai_chat():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Expected JSON body"}
        ), 400

    try:
        messages = validate_messages(
            payload.get("messages")
        )
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400

    llama_payload = {
        "model": get_active_profile()["model_id"],
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_MESSAGE,
            },
            *messages,
        ],
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": MAXIMUM_RESPONSE_TOKENS,
        "stream": False,
    }

    rpc_request = Request(
        LLAMA_CHAT_URL,
        data=json.dumps(llama_payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        result = read_llama_response(
            rpc_request,
            timeout=120,
        )
        content = result["choices"][0]["message"][
            "content"
        ].strip()
    except (
        AiServiceError,
        KeyError,
        IndexError,
        AttributeError,
    ) as error:
        return jsonify(
            {"error": str(error) or "Invalid AI response"}
        ), 503

    usage = result.get("usage") or {}
    timings = result.get("timings") or {}

    return jsonify(
        {
            "message": {
                "role": "assistant",
                "content": content,
            },
            "usage": {
                "prompt_tokens": usage.get(
                    "prompt_tokens",
                    0,
                ),
                "completion_tokens": usage.get(
                    "completion_tokens",
                    0,
                ),
                "tokens_per_second": timings.get(
                    "predicted_per_second",
                    0,
                ),
            },
        }
    )
