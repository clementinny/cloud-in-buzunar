import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

from app.message_crypto import (
    decrypt_message_content,
    encrypt_message_content,
)


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

PRIVATE_MESSAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS private_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    CHECK (sender_id != recipient_id),
    FOREIGN KEY (sender_id)
        REFERENCES users(id)
        ON DELETE CASCADE,
    FOREIGN KEY (recipient_id)
        REFERENCES users(id)
        ON DELETE CASCADE
)
"""
PRIVATE_MESSAGE_CONVERSATION_INDEX = """
CREATE INDEX IF NOT EXISTS private_messages_conversation
ON private_messages (
    sender_id,
    recipient_id,
    id
)
"""
PRIVATE_MESSAGE_UNREAD_INDEX = """
CREATE INDEX IF NOT EXISTS private_messages_unread
ON private_messages (
    recipient_id,
    read_at,
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

SYSTEM_METRIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    cpu_usage_percent REAL,
    gpu_usage_percent REAL,
    battery_temperature_c REAL,
    cpu_temperature_c REAL,
    gpu_temperature_c REAL,
    skin_temperature_c REAL,
    thermal_severity INTEGER,
    battery_percent INTEGER,
    voltage_v REAL,
    current_a REAL,
    power_w REAL
)
"""

SYSTEM_METRIC_INDEX = """
CREATE INDEX IF NOT EXISTS system_metrics_timeline
ON system_metrics (recorded_at, id)
"""

FILE_SHARE_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL,
    created_by_user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    max_downloads INTEGER
        CHECK (max_downloads IS NULL OR max_downloads > 0),
    download_count INTEGER NOT NULL DEFAULT 0
        CHECK (download_count >= 0),
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    last_downloaded_at TEXT,
    FOREIGN KEY (owner_user_id)
        REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id)
        REFERENCES users(id) ON DELETE CASCADE
)
"""
FILE_SHARE_TOKEN_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS file_shares_token
ON file_shares (token_hash)
"""
FILE_SHARE_OWNER_INDEX = """
CREATE INDEX IF NOT EXISTS file_shares_owner
ON file_shares (owner_user_id, created_at DESC)
"""

SYSTEM_ALERT_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_alert_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    alert_server INTEGER NOT NULL DEFAULT 1
        CHECK (alert_server IN (0, 1)),
    alert_charger INTEGER NOT NULL DEFAULT 1
        CHECK (alert_charger IN (0, 1)),
    alert_battery INTEGER NOT NULL DEFAULT 1
        CHECK (alert_battery IN (0, 1)),
    alert_thermal INTEGER NOT NULL DEFAULT 1
        CHECK (alert_thermal IN (0, 1)),
    alert_storage INTEGER NOT NULL DEFAULT 1
        CHECK (alert_storage IN (0, 1)),
    alert_services INTEGER NOT NULL DEFAULT 1
        CHECK (alert_services IN (0, 1)),
    battery_low_percent INTEGER NOT NULL DEFAULT 25
        CHECK (battery_low_percent BETWEEN 5 AND 80),
    storage_warning_percent INTEGER NOT NULL DEFAULT 90
        CHECK (storage_warning_percent BETWEEN 50 AND 99),
    thermal_warning_c REAL NOT NULL DEFAULT 42
        CHECK (thermal_warning_c BETWEEN 30 AND 60),
    cooldown_minutes INTEGER NOT NULL DEFAULT 60
        CHECK (cooldown_minutes BETWEEN 5 AND 1440),
    updated_at TEXT NOT NULL
)
"""

SYSTEM_ALERT_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'critical', 'info')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('triggered', 'repeated', 'resolved', 'test')),
    created_at TEXT NOT NULL
)
"""

SYSTEM_ALERT_EVENT_INDEX = """
CREATE INDEX IF NOT EXISTS system_alert_events_timeline
ON system_alert_events (created_at DESC, id DESC)
"""

SYSTEM_ALERT_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_alert_states (
    alert_key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_alerted_at TEXT NOT NULL,
    resolved_at TEXT
)
"""

SYSTEM_ALERT_DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_alert_deliveries (
    device_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    acknowledged_at TEXT NOT NULL,
    PRIMARY KEY (device_id, event_id),
    FOREIGN KEY (device_id)
        REFERENCES monitor_devices(id) ON DELETE CASCADE,
    FOREIGN KEY (event_id)
        REFERENCES system_alert_events(id) ON DELETE CASCADE
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
        connection.execute(PRIVATE_MESSAGE_SCHEMA)
        private_message_table_sql = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'private_messages'
            """
        ).fetchone()["sql"]

        if "length(content) BETWEEN 1 AND 2000" in (
            private_message_table_sql
        ):
            connection.execute(
                "DROP INDEX IF EXISTS private_messages_conversation"
            )
            connection.execute(
                "DROP INDEX IF EXISTS private_messages_unread"
            )
            connection.execute(
                """
                ALTER TABLE private_messages
                RENAME TO private_messages_legacy
                """
            )
            connection.execute(PRIVATE_MESSAGE_SCHEMA)
            connection.execute(
                """
                INSERT INTO private_messages (
                    id,
                    sender_id,
                    recipient_id,
                    content,
                    created_at,
                    read_at
                )
                SELECT
                    id,
                    sender_id,
                    recipient_id,
                    content,
                    created_at,
                    read_at
                FROM private_messages_legacy
                """
            )
            connection.execute(
                "DROP TABLE private_messages_legacy"
            )

        connection.execute(PRIVATE_MESSAGE_CONVERSATION_INDEX)
        connection.execute(PRIVATE_MESSAGE_UNREAD_INDEX)
        unencrypted_messages = connection.execute(
            """
            SELECT id, content
            FROM private_messages
            WHERE content NOT LIKE 'aes256ctr-hmacsha256:v1:%'
            """
        ).fetchall()

        for message in unencrypted_messages:
            connection.execute(
                """
                UPDATE private_messages
                SET content = ?
                WHERE id = ?
                """,
                (
                    encrypt_message_content(message["content"]),
                    message["id"],
                ),
            )
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
        connection.execute(SYSTEM_METRIC_SCHEMA)
        connection.execute(SYSTEM_METRIC_INDEX)
        connection.execute(FILE_SHARE_SCHEMA)
        connection.execute(FILE_SHARE_TOKEN_INDEX)
        connection.execute(FILE_SHARE_OWNER_INDEX)
        connection.execute(SYSTEM_ALERT_SETTINGS_SCHEMA)
        connection.execute(
            """
            INSERT OR IGNORE INTO system_alert_settings (
                id,
                updated_at
            )
            VALUES (1, ?)
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.execute(SYSTEM_ALERT_EVENT_SCHEMA)
        connection.execute(SYSTEM_ALERT_EVENT_INDEX)
        connection.execute(SYSTEM_ALERT_STATE_SCHEMA)
        connection.execute(SYSTEM_ALERT_DELIVERY_SCHEMA)
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


def record_system_metric(metric):
    recorded_at = metric.get("recorded_at") or datetime.now(
        timezone.utc
    ).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            INSERT INTO system_metrics (
                recorded_at,
                cpu_usage_percent,
                gpu_usage_percent,
                battery_temperature_c,
                cpu_temperature_c,
                gpu_temperature_c,
                skin_temperature_c,
                thermal_severity,
                battery_percent,
                voltage_v,
                current_a,
                power_w
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recorded_at,
                metric.get("cpu_usage_percent"),
                metric.get("gpu_usage_percent"),
                metric.get("battery_temperature_c"),
                metric.get("cpu_temperature_c"),
                metric.get("gpu_temperature_c"),
                metric.get("skin_temperature_c"),
                metric.get("thermal_severity"),
                metric.get("battery_percent"),
                metric.get("voltage_v"),
                metric.get("current_a"),
                metric.get("power_w"),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return recorded_at


def list_system_metrics(hours=24, limit=3000):
    hours = min(168, max(1, int(hours)))
    limit = min(5000, max(2, int(limit)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    connection = open_database()

    try:
        rows = connection.execute(
            """
            SELECT
                recorded_at,
                cpu_usage_percent,
                gpu_usage_percent,
                battery_temperature_c,
                cpu_temperature_c,
                gpu_temperature_c,
                skin_temperature_c,
                thermal_severity,
                battery_percent,
                voltage_v,
                current_a,
                power_w
            FROM system_metrics
            WHERE recorded_at >= ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        metrics = [dict(row) for row in rows]

        if len(metrics) <= limit:
            return metrics

        last_index = len(metrics) - 1
        selected_indexes = {
            round(index * last_index / (limit - 1))
            for index in range(limit)
        }
        return [metrics[index] for index in sorted(selected_indexes)]
    finally:
        connection.close()


def prune_system_metrics(keep_hours=168):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(24, keep_hours))
    connection = open_database()

    try:
        cursor = connection.execute(
            "DELETE FROM system_metrics WHERE recorded_at < ?",
            (cutoff.isoformat(),),
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def get_system_alert_settings():
    connection = open_database()

    try:
        row = connection.execute(
            """
            SELECT
                enabled,
                alert_server,
                alert_charger,
                alert_battery,
                alert_thermal,
                alert_storage,
                alert_services,
                battery_low_percent,
                storage_warning_percent,
                thermal_warning_c,
                cooldown_minutes,
                updated_at
            FROM system_alert_settings
            WHERE id = 1
            """
        ).fetchone()

        if row is None:
            raise RuntimeError("System alert settings are not initialized")

        result = dict(row)

        for field in (
            "enabled",
            "alert_server",
            "alert_charger",
            "alert_battery",
            "alert_thermal",
            "alert_storage",
            "alert_services",
        ):
            result[field] = bool(result[field])

        return result
    finally:
        connection.close()


def update_system_alert_settings(settings):
    updated_at = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        connection.execute(
            """
            UPDATE system_alert_settings
            SET
                enabled = ?,
                alert_server = ?,
                alert_charger = ?,
                alert_battery = ?,
                alert_thermal = ?,
                alert_storage = ?,
                alert_services = ?,
                battery_low_percent = ?,
                storage_warning_percent = ?,
                thermal_warning_c = ?,
                cooldown_minutes = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                int(settings["enabled"]),
                int(settings["alert_server"]),
                int(settings["alert_charger"]),
                int(settings["alert_battery"]),
                int(settings["alert_thermal"]),
                int(settings["alert_storage"]),
                int(settings["alert_services"]),
                settings["battery_low_percent"],
                settings["storage_warning_percent"],
                settings["thermal_warning_c"],
                settings["cooldown_minutes"],
                updated_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return get_system_alert_settings()


def _insert_system_alert_event(connection, condition, event_type, created_at):
    cursor = connection.execute(
        """
        INSERT INTO system_alert_events (
            alert_key,
            category,
            severity,
            title,
            message,
            event_type,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            condition["alert_key"],
            condition["category"],
            condition["severity"],
            condition["title"],
            condition["message"],
            event_type,
            created_at,
        ),
    )
    return cursor.lastrowid


def record_system_alert_event(condition, event_type="test", now=None):
    created_at = (now or datetime.now(timezone.utc)).isoformat()
    connection = open_database()

    try:
        event_id = _insert_system_alert_event(
            connection,
            condition,
            event_type,
            created_at,
        )
        connection.commit()
        return event_id
    finally:
        connection.close()


def sync_system_alert_conditions(conditions, cooldown_minutes, now=None):
    current_time = now or datetime.now(timezone.utc)
    current_iso = current_time.isoformat()
    cooldown = timedelta(minutes=max(5, int(cooldown_minutes)))
    current_conditions = {
        condition["alert_key"]: condition
        for condition in conditions
    }
    generated_events = []
    connection = open_database()

    try:
        connection.execute("BEGIN IMMEDIATE")
        active_rows = {
            row["alert_key"]: row
            for row in connection.execute(
                """
                SELECT *
                FROM system_alert_states
                WHERE is_active = 1
                """
            ).fetchall()
        }

        for alert_key, condition in current_conditions.items():
            previous = active_rows.get(alert_key)
            event_type = None

            if previous is None:
                event_type = "triggered"
                first_seen_at = current_iso
            else:
                first_seen_at = previous["first_seen_at"]
                last_alerted_at = datetime.fromisoformat(
                    previous["last_alerted_at"]
                )

                if current_time - last_alerted_at >= cooldown:
                    event_type = "repeated"

            alerted_at = current_iso if event_type else (
                previous["last_alerted_at"]
            )
            connection.execute(
                """
                INSERT INTO system_alert_states (
                    alert_key,
                    category,
                    severity,
                    title,
                    message,
                    is_active,
                    first_seen_at,
                    last_seen_at,
                    last_alerted_at,
                    resolved_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL)
                ON CONFLICT(alert_key) DO UPDATE SET
                    category = excluded.category,
                    severity = excluded.severity,
                    title = excluded.title,
                    message = excluded.message,
                    is_active = 1,
                    first_seen_at = excluded.first_seen_at,
                    last_seen_at = excluded.last_seen_at,
                    last_alerted_at = excluded.last_alerted_at,
                    resolved_at = NULL
                """,
                (
                    alert_key,
                    condition["category"],
                    condition["severity"],
                    condition["title"],
                    condition["message"],
                    first_seen_at,
                    current_iso,
                    alerted_at,
                ),
            )

            if event_type:
                event_id = _insert_system_alert_event(
                    connection,
                    condition,
                    event_type,
                    current_iso,
                )
                generated_events.append(
                    {"id": event_id, "event_type": event_type, **condition}
                )

        for alert_key, previous in active_rows.items():
            if alert_key in current_conditions:
                continue

            resolved_condition = {
                "alert_key": alert_key,
                "category": previous["category"],
                "severity": "info",
                "title": f"Rezolvat: {previous['title']}",
                "message": "Problema nu mai este detectată.",
            }
            connection.execute(
                """
                UPDATE system_alert_states
                SET is_active = 0, resolved_at = ?, last_seen_at = ?
                WHERE alert_key = ?
                """,
                (current_iso, current_iso, alert_key),
            )
            event_id = _insert_system_alert_event(
                connection,
                resolved_condition,
                "resolved",
                current_iso,
            )
            generated_events.append(
                {
                    "id": event_id,
                    "event_type": "resolved",
                    **resolved_condition,
                }
            )

        connection.commit()
        return generated_events
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_system_alert_events(limit=100, device_id=None):
    limit = min(500, max(1, int(limit)))
    connection = open_database()

    try:
        parameters = []
        delivery_filter = ""

        if device_id is not None:
            delivery_filter = """
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM system_alert_deliveries
                    WHERE system_alert_deliveries.device_id = ?
                      AND system_alert_deliveries.event_id = system_alert_events.id
                )
            """
            parameters.append(int(device_id))

        parameters.append(limit)
        rows = connection.execute(
            f"""
            SELECT
                id,
                alert_key,
                category,
                severity,
                title,
                message,
                event_type,
                created_at
            FROM system_alert_events
            {delivery_filter}
            ORDER BY id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
    finally:
        connection.close()


def list_active_system_alerts():
    connection = open_database()

    try:
        rows = connection.execute(
            """
            SELECT
                alert_key,
                category,
                severity,
                title,
                message,
                first_seen_at,
                last_seen_at,
                last_alerted_at
            FROM system_alert_states
            WHERE is_active = 1
            ORDER BY first_seen_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def acknowledge_system_alert_events(device_id, event_ids):
    acknowledged_at = datetime.now(timezone.utc).isoformat()
    unique_ids = sorted({int(event_id) for event_id in event_ids})
    connection = open_database()

    try:
        before = connection.total_changes

        for event_id in unique_ids:
            connection.execute(
                """
                INSERT OR IGNORE INTO system_alert_deliveries (
                    device_id,
                    event_id,
                    acknowledged_at
                )
                SELECT ?, id, ?
                FROM system_alert_events
                WHERE id = ?
                """,
                (device_id, acknowledged_at, event_id),
            )

        connection.commit()
        return connection.total_changes - before
    finally:
        connection.close()


def prune_system_alert_events(keep_days=30):
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=max(7, int(keep_days))
    )
    connection = open_database()

    try:
        cursor = connection.execute(
            "DELETE FROM system_alert_events WHERE created_at < ?",
            (cutoff.isoformat(),),
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


def list_message_contacts(user_id):
    connection = open_database()

    try:
        contacts = connection.execute(
            """
            SELECT
                users.id,
                users.username,
                users.role,
                COALESCE(
                    SUM(
                        CASE
                            WHEN messages.recipient_id = ?
                             AND messages.sender_id = users.id
                             AND messages.read_at IS NULL
                            THEN 1
                            ELSE 0
                        END
                    ),
                    0
                ) AS unread_count,
                MAX(messages.id) AS last_message_id,
                (
                    SELECT recent.content
                    FROM private_messages AS recent
                    WHERE (
                        recent.sender_id = ?
                        AND recent.recipient_id = users.id
                    ) OR (
                        recent.sender_id = users.id
                        AND recent.recipient_id = ?
                    )
                    ORDER BY recent.id DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT recent.created_at
                    FROM private_messages AS recent
                    WHERE (
                        recent.sender_id = ?
                        AND recent.recipient_id = users.id
                    ) OR (
                        recent.sender_id = users.id
                        AND recent.recipient_id = ?
                    )
                    ORDER BY recent.id DESC
                    LIMIT 1
                ) AS last_message_at
            FROM users
            LEFT JOIN private_messages AS messages
                ON (
                    messages.sender_id = ?
                    AND messages.recipient_id = users.id
                ) OR (
                    messages.sender_id = users.id
                    AND messages.recipient_id = ?
                )
            WHERE users.is_active = 1
              AND users.id != ?
            GROUP BY users.id, users.username, users.role
            ORDER BY
                last_message_id IS NULL,
                last_message_id DESC,
                users.username COLLATE NOCASE
            """,
            (
                user_id,
                user_id,
                user_id,
                user_id,
                user_id,
                user_id,
                user_id,
                user_id,
            ),
        ).fetchall()

        serialized_contacts = []

        for contact in contacts:
            serialized_contact = dict(contact)
            last_message = serialized_contact["last_message"]

            if last_message is not None:
                serialized_contact["last_message"] = (
                    decrypt_message_content(last_message)
                )

            serialized_contacts.append(serialized_contact)

        return serialized_contacts
    finally:
        connection.close()


def find_active_message_contact(contact_id):
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT
                id,
                username,
                role
            FROM users
            WHERE id = ?
              AND is_active = 1
            """,
            (contact_id,),
        ).fetchone()
    finally:
        connection.close()


def count_unread_messages(user_id):
    connection = open_database()

    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS unread_count
            FROM private_messages
            WHERE recipient_id = ?
              AND read_at IS NULL
            """,
            (user_id,),
        ).fetchone()

        return int(row["unread_count"])
    finally:
        connection.close()


def create_private_message(sender_id, recipient_id, content):
    if sender_id == recipient_id:
        raise ValueError("Nu îți poți trimite mesaje singur.")

    if not isinstance(content, str):
        raise ValueError("Mesajul trebuie să fie text.")

    normalized_content = content.strip()

    if not normalized_content:
        raise ValueError("Mesajul nu poate fi gol.")

    if len(normalized_content) > 2000:
        raise ValueError(
            "Mesajul nu poate depăși 2000 de caractere."
        )

    connection = open_database()

    try:
        recipient = connection.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
              AND is_active = 1
            """,
            (recipient_id,),
        ).fetchone()

        if recipient is None:
            raise ValueError("Utilizatorul nu este disponibil.")

        created_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO private_messages (
                sender_id,
                recipient_id,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                sender_id,
                recipient_id,
                encrypt_message_content(normalized_content),
                created_at,
            ),
        )
        connection.commit()

        message = connection.execute(
            """
            SELECT
                id,
                sender_id,
                recipient_id,
                content,
                created_at,
                read_at
            FROM private_messages
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        serialized_message = dict(message)
        serialized_message["content"] = normalized_content

        return serialized_message
    finally:
        connection.close()


def get_private_conversation(
    user_id,
    contact_id,
    after_id=None,
    limit=100,
):
    if user_id == contact_id:
        raise ValueError("Conversația nu este disponibilă.")

    connection = open_database()

    try:
        contact = connection.execute(
            """
            SELECT
                id,
                username,
                role
            FROM users
            WHERE id = ?
              AND is_active = 1
            """,
            (contact_id,),
        ).fetchone()

        if contact is None:
            raise ValueError("Utilizatorul nu este disponibil.")

        connection.execute(
            """
            UPDATE private_messages
            SET read_at = ?
            WHERE sender_id = ?
              AND recipient_id = ?
              AND read_at IS NULL
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                contact_id,
                user_id,
            ),
        )

        parameters = [
            user_id,
            contact_id,
            contact_id,
            user_id,
        ]

        if after_id is None:
            query = """
                SELECT *
                FROM (
                    SELECT
                        id,
                        sender_id,
                        recipient_id,
                        content,
                        created_at,
                        read_at
                    FROM private_messages
                    WHERE (
                        sender_id = ? AND recipient_id = ?
                    ) OR (
                        sender_id = ? AND recipient_id = ?
                    )
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
            """
            parameters.append(limit)
        else:
            query = """
                SELECT
                    id,
                    sender_id,
                    recipient_id,
                    content,
                    created_at,
                    read_at
                FROM private_messages
                WHERE (
                    (
                        sender_id = ? AND recipient_id = ?
                    ) OR (
                        sender_id = ? AND recipient_id = ?
                    )
                )
                  AND id > ?
                ORDER BY id ASC
                LIMIT ?
            """
            parameters.extend((after_id, limit))

        messages = connection.execute(
            query,
            parameters,
        ).fetchall()
        connection.commit()

        decrypted_messages = []

        for message in messages:
            decrypted_message = dict(message)
            decrypted_message["content"] = (
                decrypt_message_content(message["content"])
            )
            decrypted_messages.append(decrypted_message)

        return contact, decrypted_messages
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


def create_file_share(
    owner_user_id,
    created_by_user_id,
    token_hash,
    relative_path,
    file_name,
    expires_at,
    max_downloads=None,
):
    created_at = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            INSERT INTO file_shares (
                owner_user_id,
                created_by_user_id,
                token_hash,
                relative_path,
                file_name,
                expires_at,
                max_downloads,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_user_id,
                created_by_user_id,
                token_hash,
                relative_path,
                file_name,
                expires_at,
                max_downloads,
                created_at,
            ),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def list_file_shares(owner_user_id=None):
    connection = open_database()

    try:
        parameters = ()
        where_clause = ""

        if owner_user_id is not None:
            where_clause = "WHERE file_shares.owner_user_id = ?"
            parameters = (owner_user_id,)

        return connection.execute(
            f"""
            SELECT
                file_shares.id,
                file_shares.owner_user_id,
                file_shares.created_by_user_id,
                file_shares.file_name,
                file_shares.expires_at,
                file_shares.max_downloads,
                file_shares.download_count,
                file_shares.created_at,
                file_shares.revoked_at,
                file_shares.last_downloaded_at,
                owners.username AS owner_username,
                creators.username AS creator_username
            FROM file_shares
            JOIN users AS owners
              ON owners.id = file_shares.owner_user_id
            JOIN users AS creators
              ON creators.id = file_shares.created_by_user_id
            {where_clause}
            ORDER BY file_shares.created_at DESC, file_shares.id DESC
            """,
            parameters,
        ).fetchall()
    finally:
        connection.close()


def find_file_share(share_id):
    connection = open_database()

    try:
        return connection.execute(
            """
            SELECT *
            FROM file_shares
            WHERE id = ?
            """,
            (share_id,),
        ).fetchone()
    finally:
        connection.close()


def revoke_file_share(share_id):
    revoked_at = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        cursor = connection.execute(
            """
            UPDATE file_shares
            SET revoked_at = COALESCE(revoked_at, ?)
            WHERE id = ?
            """,
            (revoked_at, share_id),
        )
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def claim_file_share_download(token_hash):
    """Atomically validate a share and reserve one download."""
    now = datetime.now(timezone.utc).isoformat()
    connection = open_database()

    try:
        connection.execute("BEGIN IMMEDIATE")
        share = connection.execute(
            """
            SELECT file_shares.*
            FROM file_shares
            JOIN users
              ON users.id = file_shares.owner_user_id
            WHERE file_shares.token_hash = ?
              AND file_shares.revoked_at IS NULL
              AND file_shares.expires_at > ?
              AND users.is_active = 1
              AND (
                  file_shares.max_downloads IS NULL
                  OR file_shares.download_count
                     < file_shares.max_downloads
              )
            """,
            (token_hash, now),
        ).fetchone()

        if share is None:
            connection.rollback()
            return None

        cursor = connection.execute(
            """
            UPDATE file_shares
            SET download_count = download_count + 1,
                last_downloaded_at = ?
            WHERE id = ?
              AND revoked_at IS NULL
              AND expires_at > ?
              AND (
                  max_downloads IS NULL
                  OR download_count < max_downloads
              )
            """,
            (now, share["id"], now),
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

        connection.commit()
        return share
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
