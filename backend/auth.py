"""Local user storage and signed session helpers for LinguaFlow."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import pbkdf2_hmac, sha256
import base64
import json
from pathlib import Path
import hmac
import os
import secrets
import sqlite3


ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.getenv("LINGUAFLOW_DATABASE", str(ROOT / "data" / "linguaflow.db")))
SESSION_SECRET_PATH = DATABASE_PATH.parent / "session-secret.bin"
PASSWORD_ITERATIONS = 310_000


def _connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def initialize_database() -> None:
    with _connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                can_access_settings INTEGER NOT NULL DEFAULT 0,
                can_manage_filters INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        if "can_access_settings" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN can_access_settings INTEGER NOT NULL DEFAULT 0")
        if "can_manage_filters" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN can_manage_filters INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                prefix TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                memory_id TEXT,
                can_read INTEGER NOT NULL DEFAULT 1,
                can_write INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(api_keys)").fetchall()}
        if "memory_id" not in columns:
            connection.execute("ALTER TABLE api_keys ADD COLUMN memory_id TEXT")
        if "can_read" not in columns:
            connection.execute("ALTER TABLE api_keys ADD COLUMN can_read INTEGER NOT NULL DEFAULT 1")
        if "can_write" not in columns:
            connection.execute("ALTER TABLE api_keys ADD COLUMN can_write INTEGER NOT NULL DEFAULT 0")
        connection.execute("CREATE INDEX IF NOT EXISTS api_keys_prefix ON api_keys(prefix)")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, name)
            )
            """
        )
        exists = connection.execute("SELECT 1 FROM users WHERE username = ?", ("admin",)).fetchone()
        if not exists:
            connection.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
                ("admin", hash_password("admin"), datetime.now(UTC).isoformat()),
            )


def authenticate(username: str, password: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT id, username, password_hash, is_admin, can_access_settings, can_manage_filters FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"]), "can_access_settings": bool(row["can_access_settings"]), "can_manage_filters": bool(row["can_manage_filters"])}


def list_users() -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, username, is_admin, can_access_settings, can_manage_filters, created_at FROM users ORDER BY is_admin DESC, username COLLATE NOCASE"
        ).fetchall()
    return [dict(row) | {"is_admin": bool(row["is_admin"]), "can_access_settings": bool(row["can_access_settings"]), "can_manage_filters": bool(row["can_manage_filters"])} for row in rows]


def get_user(user_id: int) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT id, username, is_admin, can_access_settings, can_manage_filters, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return dict(row) | {"is_admin": bool(row["is_admin"]), "can_access_settings": bool(row["can_access_settings"]), "can_manage_filters": bool(row["can_manage_filters"])}


def update_user_access(user_id: int, can_access_settings: bool, can_manage_filters: bool, password: str | None = None) -> dict:
    if password is not None and not 8 <= len(password) <= 256:
        raise ValueError("Новый пароль должен содержать от 8 до 256 символов.")
    with _connection() as connection:
        if password:
            cursor = connection.execute("UPDATE users SET password_hash = ?, can_access_settings = ?, can_manage_filters = ? WHERE id = ?", (hash_password(password), int(can_access_settings), int(can_manage_filters), user_id))
        else:
            cursor = connection.execute("UPDATE users SET can_access_settings = ?, can_manage_filters = ? WHERE id = ?", (int(can_access_settings), int(can_manage_filters), user_id))
        if not cursor.rowcount:
            raise ValueError("Пользователь не найден.")
    return get_user(user_id) or {}


def create_user(username: str, password: str, is_admin: bool = False) -> dict:
    name = username.strip()
    if not 3 <= len(name) <= 80:
        raise ValueError("Имя пользователя должно содержать от 3 до 80 символов.")
    if not 8 <= len(password) <= 256:
        raise ValueError("Пароль должен содержать не менее 8 символов.")
    if any(char.isspace() for char in name):
        raise ValueError("Имя пользователя не должно содержать пробелы.")
    try:
        with _connection() as connection:
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (name, hash_password(password), int(is_admin), datetime.now(UTC).isoformat()),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Пользователь с таким именем уже существует.") from error
    return {"id": user_id, "username": name, "is_admin": is_admin, "can_access_settings": False, "can_manage_filters": False}


def _session_secret() -> bytes:
    if SESSION_SECRET_PATH.is_file():
        return SESSION_SECRET_PATH.read_bytes()
    SESSION_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    try:
        with SESSION_SECRET_PATH.open("xb") as file:
            file.write(secret)
    except FileExistsError:
        return SESSION_SECRET_PATH.read_bytes()
    return secret


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session(user: dict) -> str:
    expires_at = int(datetime.now(UTC).timestamp()) + 60 * 60 * 12
    payload = json.dumps(
        {"id": user["id"], "username": user["username"], "is_admin": user["is_admin"], "can_access_settings": user.get("can_access_settings", False), "can_manage_filters": user.get("can_manage_filters", False), "exp": expires_at},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _encode(payload)
    signature = hmac.new(_session_secret(), encoded.encode("ascii"), "sha256").digest()
    return f"{encoded}.{_encode(signature)}"


def read_session(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(_session_secret(), encoded.encode("ascii"), "sha256").digest()
        if not hmac.compare_digest(expected, _decode(signature)):
            return None
        payload = json.loads(_decode(encoded))
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            return None
        return {"id": int(payload["id"]), "username": str(payload["username"]), "is_admin": bool(payload["is_admin"]), "can_access_settings": bool(payload.get("can_access_settings", False)), "can_manage_filters": bool(payload.get("can_manage_filters", False))}
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _public_key(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "prefix": row["prefix"],
        "memory_id": row["memory_id"], "created_at": row["created_at"],
        "last_used_at": row["last_used_at"], "can_read": bool(row["can_read"]),
        "can_write": bool(row["can_write"]),
    }


def _validate_api_key(name: str, can_read: bool, can_write: bool, secret: str | None = None) -> tuple[str, str | None]:
    label = name.strip()
    if not 1 <= len(label) <= 100:
        raise ValueError("Название ключа должно содержать от 1 до 100 символов.")
    if not can_read and not can_write:
        raise ValueError("Выберите хотя бы одно право: чтение или запись.")
    value = secret.strip() if secret is not None else None
    if value is not None and (not value.startswith("lf_tm_") or len(value) < 20 or any(char.isspace() for char in value)):
        raise ValueError("Ключ должен начинаться с lf_tm_ и не содержать пробелов.")
    return label, value


def create_api_key(user_id: int, name: str, memory_id: str | None = None, can_read: bool = True,
                   can_write: bool = False, secret: str | None = None) -> tuple[dict, str]:
    label, raw_key = _validate_api_key(name, can_read, can_write, secret)
    raw_key = raw_key or "lf_tm_" + secrets.token_urlsafe(32)
    digest = sha256(raw_key.encode("utf-8")).hexdigest()
    now = datetime.now(UTC).isoformat()
    try:
        with _connection() as connection:
            cursor = connection.execute(
                "INSERT INTO api_keys(user_id, name, key_hash, prefix, created_at, memory_id, can_read, can_write) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, label, digest, raw_key[:14], now, memory_id, int(can_read), int(can_write)),
            )
            row = connection.execute("SELECT * FROM api_keys WHERE id = ?", (cursor.lastrowid,)).fetchone()
    except sqlite3.IntegrityError as error:
        raise ValueError("Такой API-ключ уже существует.") from error
    return _public_key(row), raw_key


def update_api_key_admin(key_id: int, name: str, memory_id: str | None, can_read: bool,
                         can_write: bool, secret: str | None = None) -> tuple[dict, str | None]:
    label, raw_key = _validate_api_key(name, can_read, can_write, secret)
    fields = "name = ?, memory_id = ?, can_read = ?, can_write = ?"
    values: list[object] = [label, memory_id, int(can_read), int(can_write)]
    if raw_key:
        fields += ", key_hash = ?, prefix = ?"
        values.extend([sha256(raw_key.encode("utf-8")).hexdigest(), raw_key[:14]])
    values.append(key_id)
    try:
        with _connection() as connection:
            cursor = connection.execute(f"UPDATE api_keys SET {fields} WHERE id = ?", values)
            if not cursor.rowcount:
                raise ValueError("API-ключ не найден.")
            row = connection.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    except sqlite3.IntegrityError as error:
        raise ValueError("Такой API-ключ уже существует.") from error
    return _public_key(row), raw_key

def list_api_keys(user_id: int) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM api_keys WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    return [_public_key(row) for row in rows]


def revoke_api_key(user_id: int, key_id: int) -> bool:
    with _connection() as connection:
        return bool(connection.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id)).rowcount)


def list_all_api_keys() -> list[dict]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM api_keys ORDER BY id DESC").fetchall()
    return [_public_key(row) for row in rows]


def revoke_api_key_admin(key_id: int) -> bool:
    with _connection() as connection:
        return bool(connection.execute("DELETE FROM api_keys WHERE id = ?", (key_id,)).rowcount)


def authenticate_api_key(raw_key: str | None) -> dict | None:
    if not raw_key or not raw_key.startswith("lf_tm_"):
        return None
    digest = sha256(raw_key.encode("utf-8")).hexdigest()
    user_id = None
    with _connection() as connection:
        rows = connection.execute("SELECT key_hash, user_id, memory_id, can_read, can_write FROM api_keys WHERE prefix = ?", (raw_key[:14],)).fetchall()
        for row in rows:
            if hmac.compare_digest(row["key_hash"], digest):
                connection.execute("UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?", (datetime.now(UTC).isoformat(), row["key_hash"]))
                user_id, memory_id, can_read, can_write = row["user_id"], row["memory_id"], bool(row["can_read"]), bool(row["can_write"])
                break
    user = get_user(user_id) if user_id is not None else None
    if user is not None:
        user["api_key_memory_id"] = memory_id
        user["api_key_can_read"] = can_read
        user["api_key_can_write"] = can_write
    return user
