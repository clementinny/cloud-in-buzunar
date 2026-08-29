import sqlite3
from datetime import datetime, timezone
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


def open_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    return connection


def initialize_database():
    connection = open_database()

    try:
        connection.execute(USER_SCHEMA)
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
