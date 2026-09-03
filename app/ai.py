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

from app.database import (
    append_ai_message,
    clear_ai_messages,
    find_user_by_id,
    list_ai_messages,
)
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
HISTORY_DISPLAY_LIMIT = 100

SYSTEM_MESSAGE = """
Rol:
Ești CloudInBuzunar, un asistent AI privat care rulează local.

Limbă și stil:
Răspunde în limba română, exceptând cazul în care utilizatorul
cere explicit altă limbă. Răspunde direct, natural și concis.

Context și memorie:
Mesajele furnizate după această instrucțiune reprezintă istoricul
real al conversației. Folosește informațiile și preferințele
comunicate explicit de utilizator. Pentru informațiile personale,
mesajele utilizatorului au prioritate față de răspunsurile
anterioare ale asistentului. Dacă informațiile se contrazic,
folosește afirmația cea mai recentă a utilizatorului.

Când utilizatorul spune „ține minte” urmat de o informație,
confirmă scurt informația. Dacă este întrebat ulterior despre ea,
răspunde direct din istoricul primit. Nu afirma că nu ai acces la
un mesaj care este prezent în conversație.

Acuratețe:
Nu inventa nume, date, citate, evenimente, surse sau capabilități.
Pentru cunoștințe generale nesigure, spune clar „Nu sunt sigur”
și separă incertitudinea de faptele cunoscute. Nu pretinde acces
la internet, cameră, microfon sau fișiere dacă aplicația nu ți-a
furnizat explicit acele date.

Exemplu de comportament:
Utilizator: „Ține minte că mașina mea preferată este Bugatti.”
Asistent: „Am reținut: mașina ta preferată este Bugatti.”
Utilizator: „Care este mașina mea preferată?”
Asistent: „Mașina ta preferată este Bugatti.”
""".strip()

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


def validate_user_message(value):
    if not isinstance(value, str):
        raise ValueError("Message content must be text")

    normalized_content = value.strip()

    if not normalized_content:
        raise ValueError("Message cannot be empty")

    if len(normalized_content) > MAXIMUM_MESSAGE_CHARACTERS:
        raise ValueError("Message is too long")

    return normalized_content


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


@ai_blueprint.get("/api/ai/history")
@require_ai_login
def ai_history():
    user = get_session_user()
    stored_messages = list_ai_messages(
        user["id"],
        limit=HISTORY_DISPLAY_LIMIT,
    )

    return jsonify(
        {
            "messages": [
                {
                    "role": message["role"],
                    "content": message["content"],
                    "created_at": message["created_at"],
                }
                for message in stored_messages
            ]
        }
    )


@ai_blueprint.delete("/api/ai/history")
@require_ai_login
def ai_clear_history():
    user = get_session_user()
    deleted_count = clear_ai_messages(user["id"])

    return jsonify({"deleted": deleted_count})


@ai_blueprint.post("/api/ai/chat")
@require_ai_login
def ai_chat():
    user = get_session_user()
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Expected JSON body"}
        ), 400

    try:
        user_message = validate_user_message(
            payload.get("message")
        )
    except ValueError as error:
        return jsonify(
            {"error": str(error)}
        ), 400

    append_ai_message(
        user["id"],
        "user",
        user_message,
    )

    stored_messages = list_ai_messages(
        user["id"],
        limit=MAXIMUM_MESSAGES,
    )
    messages = [
        {
            "role": message["role"],
            "content": message["content"],
        }
        for message in stored_messages
    ]

    llama_payload = {
        "model": get_active_profile()["model_id"],
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_MESSAGE,
            },
            *messages,
        ],
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "repeat_penalty": 1.05,
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
            timeout=300,
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

    append_ai_message(
        user["id"],
        "assistant",
        content,
    )

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
