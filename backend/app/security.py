import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()


def normalize_phone(phone: str) -> str:
    digits = "".join(character for character in phone if character.isdigit())
    if digits.startswith("84"):
        national_number = digits[2:]
        # Accept both +849... and the commonly entered +8409... form while
        # storing a single Vietnamese national representation.
        digits = (
            national_number
            if national_number.startswith("0")
            else f"0{national_number}"
        )
    if not digits.startswith("0") or not 9 <= len(digits) <= 11:
        raise ValueError("invalid_phone")
    return digits


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    settings = get_settings()
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ValueError("invalid_token")
    return subject


def generate_numeric_code(length: int = 6) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def derive_numeric_code(identifier: str, purpose: str, length: int = 6) -> str:
    pepper = get_settings().otp_pepper.encode()
    digest = hmac.new(
        pepper, f"{purpose}:{identifier}".encode(), hashlib.sha256
    ).digest()
    value = int.from_bytes(digest[:8], "big") % (10**length)
    return f"{value:0{length}d}"


def code_digest(code: str) -> str:
    pepper = get_settings().otp_pepper.encode()
    return hmac.new(pepper, code.encode(), hashlib.sha256).hexdigest()


def verify_code(code: str, digest: str) -> bool:
    return hmac.compare_digest(code_digest(code), digest)
