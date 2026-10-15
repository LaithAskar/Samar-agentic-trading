from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionUser:
    id: str
    email: str


def supabase_configured() -> bool:
    return bool(os.environ.get("SAMAR_SUPABASE_URL") and os.environ.get("SAMAR_SUPABASE_ANON_KEY"))


def hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return digest.hex()


def password_matches(password: str, salt_hex: str, expected_hex: str) -> bool:
    actual = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(actual, expected_hex)


def new_salt() -> str:
    return secrets.token_bytes(16).hex()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
