import jwt
import os
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

ALGORITHM = "HS256"

# ── Strict env-only secrets: fail loudly at import time if missing ────────────
_SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not _SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set or empty. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
if len(_SECRET_KEY) < 32:
    log.warning(
        "SECRET_KEY is shorter than 32 characters — use a longer random value in production."
    )

SECRET_KEY: str = _SECRET_KEY

_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
if not _ADMIN_PASSWORD:
    raise RuntimeError(
        "ADMIN_PASSWORD environment variable is not set or empty. "
        "Set a strong password in your .env file."
    )

ADMIN_PASSWORD: str = _ADMIN_PASSWORD


# ── User QR JWT (no expiry — rotate SECRET_KEY between events to invalidate) ──
def create_user_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "iat": datetime.now(timezone.utc),
        # No exp — QR codes are valid until SECRET_KEY changes or event ends.
        # Add exp=datetime.now(timezone.utc)+timedelta(hours=36) if you want
        # time-limited codes.
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_user_jwt(token: str) -> str | None:
    """Returns user_id (sub) or None if token is invalid/tampered."""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["sub"]},
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


# ── Admin session JWT (8-hour expiry) ─────────────────────────────────────────
def create_admin_session_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(hours=8),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_admin_session_token(token: str) -> bool:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("role") == "admin"
    except jwt.PyJWTError:
        return False


def verify_admin_password(plain: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    import hmac
    return hmac.compare_digest(plain.encode(), ADMIN_PASSWORD.encode())
