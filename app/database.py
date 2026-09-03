import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
DATABASE_PATH = DATA_DIR / "cloud-in-buzunar.sqlite3"

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
        connection.execute(AI_MESSAGE_SCHEMA)
        connection.execute(AI_MESSAGE_INDEX)
        connection.execute(MONITOR_SESSION_SCHEMA)
        connection.execute(MONITOR_SESSION_INDEX)
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
        connection.commit()

        return cursor.rowcount > 0
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
