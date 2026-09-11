import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from app.database import (
    claim_file_share_download,
    create_file_share,
    find_file_share,
    find_user_by_id,
    list_file_shares,
    revoke_file_share,
)


share_links_blueprint = Blueprint("share_links", __name__)
LOGGER = logging.getLogger(__name__)
ALLOWED_EXPIRY_HOURS = {1, 6, 24, 72, 168, 720}
MAX_DOWNLOAD_LIMIT = 10_000


def token_digest(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def session_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user


def authenticated_user():
    user = session_user()

    if user is None:
        return None, (jsonify({"error": "Authentication required"}), 401)

    return user, None


def normalize_relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("Invalid file path")

    if "\\" in value or "\0" in value:
        raise ValueError("Invalid file path")

    path = PurePosixPath(value)

    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Invalid file path")

    return path.as_posix()


def resolve_shared_file(owner_user_id, relative_path):
    upload_root = Path(current_app.config["UPLOAD_DIR"]).resolve()
    owner_root = (upload_root / str(owner_user_id)).resolve()
    target = (owner_root / relative_path).resolve()

    if owner_root not in target.parents or not target.is_file():
        raise FileNotFoundError("File not found")

    return owner_root, target.relative_to(owner_root).as_posix()


def serialize_share(share):
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromisoformat(share["expires_at"])
    exhausted = (
        share["max_downloads"] is not None
        and share["download_count"] >= share["max_downloads"]
    )

    return {
        "id": share["id"],
        "owner": {
            "id": share["owner_user_id"],
            "username": share["owner_username"],
        },
        "created_by": share["creator_username"],
        "file_name": share["file_name"],
        "expires_at": share["expires_at"],
        "max_downloads": share["max_downloads"],
        "download_count": share["download_count"],
        "created_at": share["created_at"],
        "last_downloaded_at": share["last_downloaded_at"],
        "revoked": share["revoked_at"] is not None,
        "expired": expires_at <= now,
        "exhausted": exhausted,
    }


@share_links_blueprint.post("/api/shares")
def create_share_route():
    user, error = authenticated_user()

    if error is not None:
        return error

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    try:
        relative_path = normalize_relative_path(payload.get("path"))
        expiry_hours = int(payload.get("expiry_hours"))

        if expiry_hours not in ALLOWED_EXPIRY_HOURS:
            raise ValueError("Invalid expiry")

        max_downloads = payload.get("max_downloads")

        if max_downloads in (None, ""):
            max_downloads = None
        else:
            max_downloads = int(max_downloads)

            if not 1 <= max_downloads <= MAX_DOWNLOAD_LIMIT:
                raise ValueError("Invalid download limit")

        owner_user_id = user["id"]
        requested_owner = payload.get("owner_user_id")

        if requested_owner is not None:
            requested_owner = int(requested_owner)

            if requested_owner != user["id"] and user["role"] != "admin":
                return jsonify({"error": "Administrator access required"}), 403

            owner_user_id = requested_owner

        owner = find_user_by_id(owner_user_id)

        if owner is None:
            return jsonify({"error": "User not found"}), 404

        _, safe_path = resolve_shared_file(owner_user_id, relative_path)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid share settings"}), 400
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

    raw_token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
    ).isoformat()
    share_id = create_file_share(
        owner_user_id=owner_user_id,
        created_by_user_id=user["id"],
        token_hash=token_digest(raw_token),
        relative_path=safe_path,
        file_name=Path(safe_path).name,
        expires_at=expires_at,
        max_downloads=max_downloads,
    )
    LOGGER.info(
        "file_share_created share_id=%s owner_user_id=%s actor_user_id=%s",
        share_id,
        owner_user_id,
        user["id"],
    )

    return jsonify({
        "id": share_id,
        "file_name": Path(safe_path).name,
        "expires_at": expires_at,
        "max_downloads": max_downloads,
        "url": f"/s/{raw_token}",
    }), 201


@share_links_blueprint.get("/api/shares")
def list_shares_route():
    user, error = authenticated_user()

    if error is not None:
        return error

    requested_owner = request.args.get("owner_user_id")

    try:
        if user["role"] == "admin" and requested_owner is None:
            owner_user_id = None
        elif requested_owner is None:
            owner_user_id = user["id"]
        else:
            owner_user_id = int(requested_owner)

            if owner_user_id != user["id"] and user["role"] != "admin":
                return jsonify({"error": "Administrator access required"}), 403
    except ValueError:
        return jsonify({"error": "Invalid user"}), 400

    shares = [serialize_share(share) for share in list_file_shares(owner_user_id)]
    return jsonify({"count": len(shares), "shares": shares})


@share_links_blueprint.delete("/api/shares/<int:share_id>")
def revoke_share_route(share_id):
    user, error = authenticated_user()

    if error is not None:
        return error

    share = find_file_share(share_id)

    if share is None:
        return jsonify({"error": "Share not found"}), 404

    if share["owner_user_id"] != user["id"] and user["role"] != "admin":
        return jsonify({"error": "Access denied"}), 403

    revoke_file_share(share_id)
    LOGGER.info(
        "file_share_revoked share_id=%s actor_user_id=%s",
        share_id,
        user["id"],
    )
    return jsonify({"revoked": True, "id": share_id})


@share_links_blueprint.get("/s/<raw_token>")
def public_share_download(raw_token):
    if not 40 <= len(raw_token) <= 128:
        return jsonify({"error": "Link unavailable"}), 404

    share = claim_file_share_download(token_digest(raw_token))

    if share is None:
        return jsonify({"error": "Link unavailable"}), 404

    try:
        owner_root, safe_path = resolve_shared_file(
            share["owner_user_id"],
            share["relative_path"],
        )
    except (FileNotFoundError, OSError, ValueError):
        return jsonify({"error": "Link unavailable"}), 404

    LOGGER.info(
        "file_share_downloaded share_id=%s remote_addr=%s",
        share["id"],
        request.remote_addr or "unknown",
    )
    response = send_from_directory(
        owner_root,
        safe_path,
        as_attachment=True,
        download_name=share["file_name"],
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response
