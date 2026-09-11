from functools import wraps

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.database import (
    count_unread_messages,
    create_private_message,
    find_active_message_contact,
    find_user_by_id,
    get_private_conversation,
    list_message_contacts,
)


messaging_blueprint = Blueprint("messaging", __name__)


def get_session_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user


def require_message_user(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_session_user()

        if user is None:
            return jsonify(
                {"error": "Authentication required"}
            ), 401

        return view_function(*args, **kwargs)

    return wrapped_view


def serialize_contact(contact):
    last_message = contact["last_message"]

    if last_message and len(last_message) > 160:
        last_message = f"{last_message[:157]}..."

    return {
        "id": contact["id"],
        "username": contact["username"],
        "role": contact["role"],
        "unread_count": int(contact["unread_count"]),
        "last_message": last_message,
        "last_message_at": contact["last_message_at"],
    }


def serialize_message(message, user_id):
    return {
        "id": message["id"],
        "sender_id": message["sender_id"],
        "recipient_id": message["recipient_id"],
        "content": message["content"],
        "created_at": message["created_at"],
        "read_at": message["read_at"],
        "is_mine": message["sender_id"] == user_id,
    }


@messaging_blueprint.get("/messages")
def messages_page():
    if get_session_user() is None:
        return redirect(url_for("dashboard"))

    return render_template("messages.html")


@messaging_blueprint.get("/api/messages/contacts")
@require_message_user
def message_contacts():
    user = get_session_user()
    contacts = [
        serialize_contact(contact)
        for contact in list_message_contacts(user["id"])
    ]

    return jsonify(
        {
            "count": len(contacts),
            "contacts": contacts,
        }
    )


@messaging_blueprint.get("/api/messages/unread")
@require_message_user
def unread_message_count():
    user = get_session_user()

    return jsonify(
        {"unread_count": count_unread_messages(user["id"])}
    )


@messaging_blueprint.get(
    "/api/messages/conversations/<int:contact_id>"
)
@require_message_user
def message_conversation(contact_id):
    user = get_session_user()
    after_value = request.args.get("after_id")
    after_id = None

    if after_value is not None:
        try:
            after_id = int(after_value)
        except ValueError:
            return jsonify({"error": "Invalid message ID"}), 400

        if after_id < 0:
            return jsonify({"error": "Invalid message ID"}), 400

    try:
        contact, messages = get_private_conversation(
            user["id"],
            contact_id,
            after_id=after_id,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404

    return jsonify(
        {
            "contact": {
                "id": contact["id"],
                "username": contact["username"],
                "role": contact["role"],
            },
            "messages": [
                serialize_message(message, user["id"])
                for message in messages
            ],
        }
    )


@messaging_blueprint.post(
    "/api/messages/conversations/<int:contact_id>"
)
@require_message_user
def send_message(contact_id):
    user = get_session_user()
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    if contact_id == user["id"]:
        return jsonify(
            {"error": "Nu îți poți trimite mesaje singur."}
        ), 400

    if find_active_message_contact(contact_id) is None:
        return jsonify(
            {"error": "Utilizatorul nu este disponibil."}
        ), 404

    try:
        message = create_private_message(
            user["id"],
            contact_id,
            payload.get("content"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(
        {"message": serialize_message(message, user["id"])}
    ), 201
