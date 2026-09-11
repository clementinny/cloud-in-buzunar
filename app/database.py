import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
DATABASE_PATH = DATA_DIR / "cloud-in-buzunar.sqlite3"


class RegistrationConflictError(ValueError):
    pass

USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
)
"""
LOGIN_ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    was_successful INTEGER NOT NULL
        CHECK (was_successful IN (0, 1)),
    attempted_at TEXT NOT NULL
)
"""
LOGIN_ATTEMPT_INDEX = """
CREATE INDEX IF NOT EXISTS login_attempts_lookup
ON login_attempts (
    username COLLATE NOCASE,
    ip_address,
    attempted_at
)
"""

AI_MESSAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
)
"""
AI_MESSAGE_INDEX = """
CREATE INDEX IF NOT EXISTS ai_messages_user_history
ON ai_messages (
    user_id,
    id
)
"""

REGISTRATION_REQUEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS registration_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""
REGISTRATION_ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS registration_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address TEXT NOT NULL,
    attempted_at TEXT NOT NULL
)
"""
REGISTRATION_ATTEMPT_INDEX = """
CREATE INDEX IF NOT EXISTS registration_attempts_lookup
ON registration_attempts (
    ip_address,
    attempted_at
)
"""

MONITOR_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_sessions (
    session_id TEXT PRIMARY KEY,
    source_user_id INTEGER NOT NULL,
    viewer_user_id INTEGER,
    offer_json TEXT NOT NULL,
    answer_json TEXT,
    created_at TEXT NOT NULL,
    source_updated_at TEXT NOT NULL,
    viewer_updated_at TEXT,
    FOREIGN KEY (source_user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,
    FOREIGN KEY (viewer_user_id)
        REFERENCES users(id)
        ON DELETE SET NULL
)
"""
MONITOR_SESSION_INDEX = """
CREATE INDEX IF NOT EXISTS monitor_sessions_source_activity
ON monitor_sessions (
    source_updated_at
)
"""

MONITOR_SOURCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_sources (
    source_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    desired_state TEXT NOT NULL
        CHECK (desired_state IN ('armed', 'live')),
    actual_state TEXT NOT NULL
        CHECK (
            actual_state IN (
                'armed',
                'starting',
                'live',
                'error'
            )
        ),
    camera_facing TEXT NOT NULL
        CHECK (camera_facing IN ('environment', 'user')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
)
"""
MONITOR_SOURCE_INDEX = """
CREATE INDEX IF NOT EXISTS monitor_sources_activity
ON monitor_sources (
    last_seen_at
)
"""

MONITOR_PAIRING_CODE_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_pairing_codes (
    code_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
)
"""

MONITOR_DEVICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    device_name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
)
"""

MONITOR_DEVICE_INDEX = """
CREATE INDEX IF NOT EXISTS monitor_devices_user
ON monitor_devices (
    user_id,
    revoked_at
)
"""

MONITOR_RECORDING_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_recording_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    desired_mode TEXT NOT NULL
        CHECK (desired_mode IN ('off', 'audio', 'video')),
    actual_mode TEXT NOT NULL
        CHECK (actual_mode IN ('off', 'audio', 'video')),
    retention_hours INTEGER NOT NULL
        CHECK (retention_hours IN (24, 48)),
    camera_facing TEXT NOT NULL DEFAULT 'environment'
        CHECK (camera_facing IN ('environment', 'user')),
    updated_at TEXT NOT NULL
)
"""

MONITOR_RECORDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('audio', 'video')),
    camera_facing TEXT
        CHECK (
            camera_facing IS NULL
            OR camera_facing IN ('environment', 'user')
        ),
    file_name TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    container TEXT NOT NULL DEFAULT 'mp4'
        CHECK (container IN ('mp4', 'webm')),
    speech_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            speech_status IN (
                'pending',
                'processing',
                'complete',
                'unavailable',
                'failed'
            )
        ),
    speech_events_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
)
"""

MONITOR_RECORDING_INDEX = """
CREATE INDEX IF NOT EXISTS monitor_recordings_timeline
ON monitor_recordings (
    ended_at DESC,
    id DESC
)
"""

def open_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def initialize_database():
    connection = open_database()

    try:
        connection.execute(USER_SCHEMA)
        connection.execute(LOGIN_ATTEMPT_SCHEMA)
        connection.execute(LOGIN_ATTEMPT_INDEX)
        connection.execute(REGISTRATION_REQUEST_SCHEMA)
        connection.execute(REGISTRATION_ATTEMPT_SCHEMA)
        connection.execute(REGISTRATION_ATTEMPT_INDEX)
        connection.execute(AI_MESSAGE_SCHEMA)
        connection.execute(AI_MESSAGE_INDEX)
        connection.execute(MONITOR_SESSION_SCHEMA)
        connection.execute(MONITOR_SESSION_INDEX)
        connection.execute(MONITOR_SOURCE_SCHEMA)
        connection.execute(MONITOR_SOURCE_INDEX)
        connection.execute(MONITOR_PAIRING_CODE_SCHEMA)
        connection.execute(MONITOR_DEVICE_SCHEMA)
        connection.execute(MONITOR_DEVICE_INDEX)
        connection.execute(MONITOR_RECORDING_SETTINGS_SCHEMA)
        recording_settings_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(monitor_recording_settings)"
            )
        }

        if "camera_facing" not in recording_settings_columns:
            connection.execute(
                """
                ALTER TABLE monitor_recording_settings
                ADD COLUMN camera_facing TEXT NOT NULL
                    DEFAULT 'environment'
                    CHECK (camera_facing IN ('environment', 'user'))
                """
            )

        connection.execute(
            """
            INSERT OR IGNORE INTO monitor_recording_settings (
                id,
                desired_mode,
                actual_mode,
                retention_hours,
                camera_facing,
                updated_at
            )
            VALUES (1, 'off', 'off', 48, 'environment', ?)
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.execute(MONITOR_RECORDING_SCHEMA)
        recording_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(monitor_recordings)"
            )
        }

        if "container" not in recording_columns:
            connection.execute(
                """
                ALTER TABLE monitor_recordings
                ADD COLUMN container TEXT NOT NULL
                    DEFAULT 'mp4'
                    CHECK (container IN ('mp4', 'webm'))
                """
            )

        if "speech_status" not in recording_columns:
            connection.execute(
                """
                ALTER TABLE monitor_recordings
                ADD COLUMN speech_status TEXT NOT NULL
                    DEFAULT 'pending'
                    CHECK (
                        speech_status IN (
                            'pending',
                            'processing',
                            'complete',
                            'unavailable',
                            'failed'
                        )
                    )
                """
            )

        if "speech_events_json" not in recording_columns:
            connection.execute(
                """
                ALTER TABLE monitor_recordings
                ADD COLUMN speech_events_json TEXT NOT NULL DEFAULT '[]'
                """
            )

        connection.execute(
            """
            UPDATE monitor_recordings
            SET speech_status = 'pending'
            WHERE speech_status = 'processing'
            """
        )

        connection.execute(MONITOR_RECORDING_INDEX)
        connection.commit()
    finally:
        connection.close()


def create_user(username, password, role="user"):
    normalized_username = username.strip()

    if not 3 <= len(normalized_username) <= 32:
        raise ValueError(
            "Username must contain between 3 and 32 characters"
        )

    if len(password) < 12:
        raise ValueError(
            "Password must contain at least 12 characters"
        )

    if role not in {"admin", "user"}:
        raise ValueError("Role must be admin or user")

    password_hash = generate_password_hash(password)
    created_at = datetime.now(timezone.utc).isoformat()

    connection = open_database()

    try:
        cursor = connection.execute(
            """
            INSERT INTO users (
                username,
                password_hash,
                role,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                normalized_username,
                password_hash,
                role,
                created_at,
            ),
        )
        connection.commit()

        return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Username already exists") from error
    finally:
        connection.close()


def find_user_by_username(username):
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                id,
                username,
                password_hash,
                role,
                is_active,
                created_at
            FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (username.strip(),),
        ).fetchone()
    finally:
        connection.close()
def find_user_by_id(user_id):
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                id,
                username,
                password_hash,
                role,
                is_active,
                created_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    finally:
        connection.close()


def list_users():
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                id,
                username,
                role,
                is_active,
                created_at
            FROM users
            ORDER BY username COLLATE NOCASE
            """
        ).fetchall()
    finally:
        connection.close()
def set_user_password(username, password):
    normalized_username = username.strip()

    if len(password) < 12:
        raise ValueError(
            "Password must contain at least 12 characters"
        )

    password_hash = generate_password_hash(password)
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?
            WHERE username = ? COLLATE NOCASE
            """,
            (
                password_hash, normalized_username,

            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("User not found")

        connection.commit()
    finally:
        connection.close()
def set_user_role(username, role):
    normalized_username = username.strip()

    if role not in {"admin", "user"}:
        raise ValueError("Role must be admin or user")

    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE users
            SET role = ?
            WHERE username = ? COLLATE NOCASE
            """,
            (
                role,
                normalized_username,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("User not found")

        connection.commit()
    finally:
        connection.close()
def set_user_active(username, is_active):
    normalized_username = username.strip()
    active_value = 1 if is_active else 0

    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE users
            SET is_active = ?
            WHERE username = ? COLLATE NOCASE
            """,
            (
                active_value,
                normalized_username,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("User not found")

        connection.commit()
    finally:
        connection.close()
def record_login_attempt(
    username,
    ip_address,
    was_successful,
):
    normalized_username = username.strip()[:64]
    normalized_ip_address = str(
        ip_address or "unknown"
    )[:64]
    attempted_at = datetime.now(timezone.utc).isoformat()

    connection = open_database()

    try:
        connection.execute(
            """
            INSERT INTO login_attempts (
                username,
                ip_address,
                was_successful,
                attempted_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                normalized_username,
                normalized_ip_address,
                1 if was_successful else 0,
                attempted_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()
def count_recent_failed_login_attempts(
    username,
    ip_address,
    window_minutes=10,
):
    normalized_username = username.strip()[:64]
    normalized_ip_address = str(
        ip_address or "unknown"
    )[:64]

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=window_minutes)
    ).isoformat()

    connection = open_database()

    try:
        result = connection.execute(
            """
            SELECT COUNT(*) AS failed_count
            FROM login_attempts
            WHERE username = ? COLLATE NOCASE
              AND ip_address = ?
              AND was_successful = 0
              AND attempted_at >= ?
            """,
            (
                normalized_username,
                normalized_ip_address,
                cutoff,
            ),
        ).fetchone()

        return result["failed_count"]
    finally:
        connection.close()


def list_ai_messages(user_id, limit=100):
    connection = open_database()

    try:
        if limit is None:
            return connection.execute(
                """
                SELECT
                    id,
                    user_id,
                    role,
                    content,
                    created_at
                FROM ai_messages
                WHERE user_id = ?
                ORDER BY id
                """,
                (user_id,),
            ).fetchall()

        safe_limit = max(1, min(int(limit), 500))

        return connection.execute(
            """
            SELECT
                id,
                user_id,
                role,
                content,
                created_at
            FROM (
                SELECT
                    id,
                    user_id,
                    role,
                    content,
                    created_at
                FROM ai_messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id
            """,
            (
                user_id,
                safe_limit,
            ),
        ).fetchall()
    finally:
        connection.close()


def append_ai_message(user_id, role, content):
    if role not in {"user", "assistant"}:
        raise ValueError("Invalid AI message role")

    if not isinstance(content, str):
        raise ValueError("AI message content must be text")

    normalized_content = content.strip()

    if not normalized_content:
        raise ValueError("AI message cannot be empty")

    created_at = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            INSERT INTO ai_messages (
                user_id,
                role,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                role,
                normalized_content,
                created_at,
            ),
        )
        connection.commit()

        return cursor.lastrowid
    finally:
        connection.close()


def clear_ai_messages(user_id):
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            DELETE FROM ai_messages
            WHERE user_id = ?
            """,
            (user_id,),
        )
        connection.commit()

        return cursor.rowcount
    finally:
        connection.close()


def validate_registration_username(username):
    normalized_username = username.strip()

    if not 3 <= len(normalized_username) <= 32:
        raise ValueError(
            "Numele trebuie să aibă între 3 și 32 de caractere."
        )

    allowed_characters = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789_.-"
    )

    if any(
        character not in allowed_characters
        for character in normalized_username
    ):
        raise ValueError(
            "Numele poate conține doar litere, cifre, punct, "
            "cratimă și underscore."
        )

    return normalized_username


def create_registration_request(username, password):
    normalized_username = validate_registration_username(username)

    if len(password) < 12:
        raise ValueError(
            "Parola trebuie să conțină cel puțin 12 caractere."
        )

    if len(password) > 128:
        raise ValueError(
            "Parola nu poate depăși 128 de caractere."
        )

    password_hash = generate_password_hash(password)
    created_at = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_user = connection.execute(
            """
            SELECT 1
            FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (normalized_username,),
        ).fetchone()

        if existing_user is not None:
            raise RegistrationConflictError(
                "Numele de utilizator nu este disponibil."
            )

        pending_count = connection.execute(
            "SELECT COUNT(*) FROM registration_requests"
        ).fetchone()[0]

        if pending_count >= 100:
            raise ValueError(
                "Sunt prea multe cereri în așteptare. "
                "Încearcă mai târziu."
            )

        cursor = connection.execute(
            """
            INSERT INTO registration_requests (
                username,
                password_hash,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                normalized_username,
                password_hash,
                created_at,
            ),
        )
        connection.commit()

        return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise RegistrationConflictError(
            "Există deja o cerere pentru acest utilizator."
        ) from error
    finally:
        connection.close()


def record_registration_attempt(ip_address):
    connection = open_database()

    try:
        connection.execute(
            """
            INSERT INTO registration_attempts (
                ip_address,
                attempted_at
            )
            VALUES (?, ?)
            """,
            (
                ip_address,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def count_recent_registration_attempts(
    ip_address,
    window_minutes=10,
):
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=window_minutes)
    ).isoformat()
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT COUNT(*)
            FROM registration_attempts
            WHERE ip_address = ?
              AND attempted_at >= ?
            """,
            (ip_address, cutoff),
        ).fetchone()[0]
    finally:
        connection.close()


def list_registration_requests():
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                id,
                username,
                created_at
            FROM registration_requests
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()
    finally:
        connection.close()


def approve_registration_request(request_id):
    connection = open_database()

    try:
        connection.execute("BEGIN IMMEDIATE")
        registration = connection.execute(
            """
            SELECT
                id,
                username,
                password_hash
            FROM registration_requests
            WHERE id = ?
            """,
            (request_id,),
        ).fetchone()

        if registration is None:
            raise ValueError("Cererea nu mai există.")

        cursor = connection.execute(
            """
            INSERT INTO users (
                username,
                password_hash,
                role,
                created_at
            )
            VALUES (?, ?, 'user', ?)
            """,
            (
                registration["username"],
                registration["password_hash"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.execute(
            "DELETE FROM registration_requests WHERE id = ?",
            (request_id,),
        )
        connection.commit()

        return {
            "id": cursor.lastrowid,
            "username": registration["username"],
            "role": "user",
        }
    except sqlite3.IntegrityError as error:
        raise RegistrationConflictError(
            "Numele de utilizator este deja folosit."
        ) from error
    finally:
        connection.close()


def reject_registration_request(request_id):
    connection = open_database()

    try:
        cursor = connection.execute(
            "DELETE FROM registration_requests WHERE id = ?",
            (request_id,),
        )

        if cursor.rowcount == 0:
            raise ValueError("Cererea nu mai există.")

        connection.commit()
    finally:
        connection.close()


def create_monitor_session(
    session_id,
    source_user_id,
    offer_json,
):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        connection.execute("DELETE FROM monitor_sessions")
        connection.execute(
            """
            INSERT INTO monitor_sessions (
                session_id,
                source_user_id,
                offer_json,
                created_at,
                source_updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                source_user_id,
                offer_json,
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_active_monitor_session(maximum_age_seconds=15):
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=maximum_age_seconds)
    ).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            DELETE FROM monitor_sessions
            WHERE source_updated_at < ?
            """,
            (cutoff,),
        )
        monitor_session = connection.execute(
            """
            SELECT
                monitor_sessions.session_id,
                monitor_sessions.source_user_id,
                monitor_sessions.viewer_user_id,
                monitor_sessions.offer_json,
                monitor_sessions.answer_json,
                monitor_sessions.created_at,
                monitor_sessions.source_updated_at,
                monitor_sessions.viewer_updated_at,
                users.username AS source_username
            FROM monitor_sessions
            JOIN users
              ON users.id = monitor_sessions.source_user_id
            ORDER BY monitor_sessions.created_at DESC
            LIMIT 1
            """
        ).fetchone()
        connection.commit()

        return monitor_session
    finally:
        connection.close()


def touch_monitor_session(session_id, source_user_id):
    now = datetime.now(timezone.utc).isoformat()
    viewer_cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=12)
    ).isoformat()
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE monitor_sessions
            SET source_updated_at = ?
            WHERE session_id = ?
              AND source_user_id = ?
            """,
            (
                now,
                session_id,
                source_user_id,
            ),
        )
        if cursor.rowcount == 0:
            connection.commit()
            return False

        connection.execute(
            """
            DELETE FROM monitor_sessions
            WHERE session_id = ?
              AND answer_json IS NOT NULL
              AND (
                  viewer_updated_at IS NULL
                  OR viewer_updated_at < ?
              )
            """,
            (
                session_id,
                viewer_cutoff,
            ),
        )
        active_session = connection.execute(
            """
            SELECT 1
            FROM monitor_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        connection.commit()

        return active_session is not None
    finally:
        connection.close()


def set_monitor_answer(
    session_id,
    viewer_user_id,
    answer_json,
):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE monitor_sessions
            SET
                viewer_user_id = ?,
                answer_json = ?,
                viewer_updated_at = ?
            WHERE session_id = ?
            """,
            (
                viewer_user_id,
                answer_json,
                now,
                session_id,
            ),
        )
        connection.commit()

        return cursor.rowcount > 0
    finally:
        connection.close()


def touch_monitor_viewer_session(
    session_id,
    viewer_user_id,
):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE monitor_sessions
            SET viewer_updated_at = ?
            WHERE session_id = ?
              AND viewer_user_id = ?
              AND answer_json IS NOT NULL
            """,
            (
                now,
                session_id,
                viewer_user_id,
            ),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def clear_monitor_session(session_id):
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            DELETE FROM monitor_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )
        connection.commit()

        return cursor.rowcount > 0
    finally:
        connection.close()


def arm_monitor_source(
    source_id,
    user_id,
    camera_facing,
):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        connection.execute("DELETE FROM monitor_sessions")
        connection.execute("DELETE FROM monitor_sources")
        connection.execute(
            """
            INSERT INTO monitor_sources (
                source_id,
                user_id,
                desired_state,
                actual_state,
                camera_facing,
                created_at,
                last_seen_at
            )
            VALUES (?, ?, 'armed', 'armed', ?, ?, ?)
            """,
            (
                source_id,
                user_id,
                camera_facing,
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_active_monitor_source(maximum_age_seconds=30):
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=maximum_age_seconds)
    ).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            DELETE FROM monitor_sources
            WHERE last_seen_at < ?
            """,
            (cutoff,),
        )
        source = connection.execute(
            """
            SELECT
                monitor_sources.source_id,
                monitor_sources.user_id,
                monitor_sources.desired_state,
                monitor_sources.actual_state,
                monitor_sources.camera_facing,
                monitor_sources.error_message,
                monitor_sources.created_at,
                monitor_sources.last_seen_at,
                users.username
            FROM monitor_sources
            JOIN users
              ON users.id = monitor_sources.user_id
            ORDER BY monitor_sources.created_at DESC
            LIMIT 1
            """
        ).fetchone()

        if source is None:
            connection.execute("DELETE FROM monitor_sessions")

        connection.commit()
        return source
    finally:
        connection.close()


def update_monitor_source(
    source_id,
    user_id,
    actual_state,
    error_message=None,
):
    now = datetime.now(timezone.utc).isoformat()
    heartbeat_cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=10)
    ).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            UPDATE monitor_sources
            SET
                actual_state = ?,
                error_message = ?,
                last_seen_at = ?
            WHERE source_id = ?
              AND user_id = ?
              AND (
                  actual_state != ?
                  OR COALESCE(error_message, '')
                     != COALESCE(?, '')
                  OR last_seen_at < ?
              )
            """,
            (
                actual_state,
                error_message,
                now,
                source_id,
                user_id,
                actual_state,
                error_message,
                heartbeat_cutoff,
            ),
        )

        source = connection.execute(
            """
            SELECT
                desired_state,
                camera_facing
            FROM monitor_sources
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()
        connection.commit()

        if source is None:
            return None

        return source
    finally:
        connection.close()


def set_monitor_source_desired_state(
    desired_state,
    camera_facing=None,
):
    source = get_active_monitor_source()

    if source is None:
        return None

    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        if camera_facing is None:
            camera_facing = source["camera_facing"]

        cursor = connection.execute(
            """
            UPDATE monitor_sources
            SET
                desired_state = ?,
                camera_facing = ?
            WHERE source_id = ?
            """,
            (
                desired_state,
                camera_facing,
                source["source_id"],
            ),
        )

        if desired_state == "armed":
            connection.execute("DELETE FROM monitor_sessions")

        connection.commit()

        if cursor.rowcount == 0:
            return None

        return {
            "source_id": source["source_id"],
            "desired_state": desired_state,
            "camera_facing": camera_facing,
            "updated_at": now,
        }
    finally:
        connection.close()


def clear_monitor_source(source_id, user_id):
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            DELETE FROM monitor_sources
            WHERE source_id = ?
              AND user_id = ?
            """,
            (
                source_id,
                user_id,
            ),
        )

        if cursor.rowcount > 0:
            connection.execute("DELETE FROM monitor_sessions")
            connection.execute(
                """
                UPDATE monitor_recording_settings
                SET
                    desired_mode = 'off',
                    actual_mode = 'off',
                    updated_at = ?
                WHERE id = 1
                """,
                (datetime.now(timezone.utc).isoformat(),),
            )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def get_monitor_recording_settings():
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                desired_mode,
                actual_mode,
                retention_hours,
                camera_facing,
                updated_at
            FROM monitor_recording_settings
            WHERE id = 1
            """
        ).fetchone()
    finally:
        connection.close()


def set_monitor_recording_settings(
    desired_mode,
    retention_hours,
    camera_facing,
):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            UPDATE monitor_recording_settings
            SET
                desired_mode = ?,
                retention_hours = ?,
                camera_facing = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                desired_mode,
                retention_hours,
                camera_facing,
                now,
            ),
        )
        connection.commit()
        return get_monitor_recording_settings()
    finally:
        connection.close()


def set_monitor_recording_actual_mode(actual_mode):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            UPDATE monitor_recording_settings
            SET
                actual_mode = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                actual_mode,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def create_monitor_recording(
    user_id,
    mode,
    camera_facing,
    file_name,
    started_at,
    ended_at,
    size_bytes,
    container="mp4",
):
    created_at = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            INSERT INTO monitor_recordings (
                user_id,
                mode,
                camera_facing,
                file_name,
                started_at,
                ended_at,
                size_bytes,
                container,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                mode,
                camera_facing,
                file_name,
                started_at,
                ended_at,
                size_bytes,
                container,
                created_at,
            ),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def list_monitor_recordings(limit=300):
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                id,
                user_id,
                mode,
                camera_facing,
                file_name,
                started_at,
                ended_at,
                size_bytes,
                container,
                speech_status,
                speech_events_json,
                created_at
            FROM monitor_recordings
            ORDER BY ended_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()


def find_monitor_recording(recording_id):
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                id,
                user_id,
                mode,
                camera_facing,
                file_name,
                started_at,
                ended_at,
                size_bytes,
                container,
                speech_status,
                speech_events_json,
                created_at
            FROM monitor_recordings
            WHERE id = ?
            """,
            (recording_id,),
        ).fetchone()
    finally:
        connection.close()


def claim_monitor_recording_speech_analysis(recording_id):
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE monitor_recordings
            SET speech_status = 'processing'
            WHERE id = ?
              AND speech_status IN ('pending', 'unavailable')
            """,
            (recording_id,),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def set_monitor_recording_speech_analysis(
    recording_id,
    status,
    speech_events_json,
):
    connection = open_database()

    try:
        connection.execute(
            """
            UPDATE monitor_recordings
            SET
                speech_status = ?,
                speech_events_json = ?
            WHERE id = ?
            """,
            (
                status,
                speech_events_json,
                recording_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def reset_monitor_recording_speech_analysis(recording_id):
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE monitor_recordings
            SET
                speech_status = 'pending',
                speech_events_json = '[]'
            WHERE id = ?
            """,
            (recording_id,),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete_monitor_recording(recording_id):
    connection = open_database()

    try:
        recording = connection.execute(
            """
            SELECT id, file_name
            FROM monitor_recordings
            WHERE id = ?
            """,
            (recording_id,),
        ).fetchone()

        if recording is None:
            return None

        connection.execute(
            "DELETE FROM monitor_recordings WHERE id = ?",
            (recording_id,),
        )
        connection.commit()
        return recording
    finally:
        connection.close()


def delete_expired_monitor_recordings(cutoff):
    connection = open_database()

    try:
        recordings = connection.execute(
            """
            SELECT id, file_name
            FROM monitor_recordings
            WHERE ended_at < ?
            """,
            (cutoff,),
        ).fetchall()

        if recordings:
            connection.executemany(
                "DELETE FROM monitor_recordings WHERE id = ?",
                ((recording["id"],) for recording in recordings),
            )

        connection.commit()
        return recordings
    finally:
        connection.close()


def create_monitor_pairing_code(code_hash, user_id, lifetime_seconds=300):
    now = datetime.now(timezone.utc)
    expires_at = (
        now + timedelta(seconds=lifetime_seconds)
    ).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            DELETE FROM monitor_pairing_codes
            WHERE user_id = ?
               OR expires_at < ?
            """,
            (user_id, now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO monitor_pairing_codes (
                code_hash,
                user_id,
                expires_at,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                code_hash,
                user_id,
                expires_at,
                now.isoformat(),
            ),
        )
        connection.commit()
        return expires_at
    finally:
        connection.close()


def consume_monitor_pairing_code(code_hash, device_name, token_hash):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        pairing_code = connection.execute(
            """
            SELECT
                monitor_pairing_codes.user_id,
                users.username,
                users.role,
                users.is_active
            FROM monitor_pairing_codes
            JOIN users
              ON users.id = monitor_pairing_codes.user_id
            WHERE monitor_pairing_codes.code_hash = ?
              AND monitor_pairing_codes.expires_at >= ?
            """,
            (code_hash, now),
        ).fetchone()

        if (
            pairing_code is None
            or not pairing_code["is_active"]
            or pairing_code["role"] != "admin"
        ):
            connection.execute(
                "DELETE FROM monitor_pairing_codes WHERE expires_at < ?",
                (now,),
            )
            connection.commit()
            return None

        connection.execute(
            "DELETE FROM monitor_pairing_codes WHERE code_hash = ?",
            (code_hash,),
        )
        cursor = connection.execute(
            """
            INSERT INTO monitor_devices (
                user_id,
                device_name,
                token_hash,
                created_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                pairing_code["user_id"],
                device_name,
                token_hash,
                now,
                now,
            ),
        )
        connection.commit()

        return {
            "id": cursor.lastrowid,
            "user_id": pairing_code["user_id"],
            "username": pairing_code["username"],
            "device_name": device_name,
        }
    finally:
        connection.close()


def find_monitor_device_by_token_hash(token_hash):
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        device = connection.execute(
            """
            SELECT
                monitor_devices.id,
                monitor_devices.user_id,
                monitor_devices.device_name,
                users.username,
                users.role,
                users.is_active
            FROM monitor_devices
            JOIN users
              ON users.id = monitor_devices.user_id
            WHERE monitor_devices.token_hash = ?
              AND monitor_devices.revoked_at IS NULL
            """,
            (token_hash,),
        ).fetchone()

        if (
            device is None
            or not device["is_active"]
            or device["role"] != "admin"
        ):
            return None

        connection.execute(
            """
            UPDATE monitor_devices
            SET last_seen_at = ?
            WHERE id = ?
            """,
            (now, device["id"]),
        )
        connection.commit()
        return device
    finally:
        connection.close()
