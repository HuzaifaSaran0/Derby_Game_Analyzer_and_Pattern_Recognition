"""Web login credentials — stored and changed via the web UI only."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
AUTH_FILE = ROOT / "data" / "web_auth.json"
SESSION_SECRET_FILE = ROOT / "data" / "session_secret"

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
PBKDF2_ROUNDS = 260_000

SESSION_USERNAME_KEY = "username"


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ROUNDS,
    )
    return digest.hex()


def _new_record(username: str, password: str) -> dict[str, str]:
    salt = os.urandom(16)
    return {
        "username": username,
        "salt": salt.hex(),
        "password_hash": _hash_password(password, salt),
    }


def load_auth_record() -> dict[str, str]:
    if not AUTH_FILE.is_file():
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = _new_record(DEFAULT_USERNAME, DEFAULT_PASSWORD)
        save_auth_record(record)
        return record
    with AUTH_FILE.open(encoding="utf-8") as handle:
        data = json.load(handle)
    username = str(data.get("username") or DEFAULT_USERNAME).strip()
    salt = str(data.get("salt") or "")
    password_hash = str(data.get("password_hash") or "")
    if not username or not salt or not password_hash:
        record = _new_record(DEFAULT_USERNAME, DEFAULT_PASSWORD)
        save_auth_record(record)
        return record
    return {
        "username": username,
        "salt": salt,
        "password_hash": password_hash,
    }


def ensure_auth_file() -> dict[str, str]:
    """Create default credentials on first run."""
    return load_auth_record()


def save_auth_record(record: dict[str, str]) -> None:
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "username": record["username"],
        "salt": record["salt"],
        "password_hash": record["password_hash"],
    }
    with AUTH_FILE.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def session_secret() -> str:
    if SESSION_SECRET_FILE.is_file():
        return SESSION_SECRET_FILE.read_text(encoding="utf-8").strip()
    SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    SESSION_SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


def verify_password(username: str, password: str) -> bool:
    record = load_auth_record()
    if username != record["username"]:
        return False
    salt = bytes.fromhex(record["salt"])
    expected = record["password_hash"]
    actual = _hash_password(password, salt)
    return hmac.compare_digest(actual, expected)


def authenticate(username: str, password: str) -> bool:
    username = username.strip()
    if not username or not password:
        return False
    return verify_password(username, password)


def change_password(
    username: str,
    current_password: str,
    new_password: str,
    *,
    new_username: str | None = None,
) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    record = load_auth_record()
    if username != record["username"]:
        return False, "Not signed in as the configured user."
    if not verify_password(username, current_password):
        return False, "Current password is incorrect."
    cleaned = new_password.strip()
    if len(cleaned) < 4:
        return False, "New password must be at least 4 characters."
    if cleaned == current_password:
        return False, "Choose a different password."
    next_username = (new_username or username).strip()
    if not next_username:
        return False, "Username cannot be empty."
    updated = _new_record(next_username, cleaned)
    save_auth_record(updated)
    return True, ""

