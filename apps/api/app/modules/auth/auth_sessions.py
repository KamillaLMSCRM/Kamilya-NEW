"""In-memory auth sessions for Telegram bot login."""
import time
import random
from typing import Any

# In-memory store: code -> session data
auth_sessions: dict[str, dict[str, Any]] = {}

COOLDOWN_SECONDS = 25
CODE_TTL_SECONDS = 300  # 5 minutes


def generate_auth_code() -> tuple[str, float]:
    """Generate a 6-digit code with cooldown. Returns (code, expires_in)."""
    now = time.time()

    # Check cooldown: if a recent code exists, return it
    for existing_code, session in auth_sessions.items():
        if now - session["created_at"] < COOLDOWN_SECONDS:
            expires_in = max(0, int(session["expires_at"] - now))
            return existing_code, expires_in

    # Generate new 6-digit code
    code = f"{random.randint(100000, 999999)}"
    auth_sessions[code] = {
        "code": code,
        "created_at": now,
        "expires_at": now + CODE_TTL_SECONDS,
        "verified": False,
        "user_data": None,
    }
    return code, CODE_TTL_SECONDS


def verify_code(code: str, telegram_id: str, user_data: dict) -> bool:
    """Mark a code as verified with user data. Returns True if code found."""
    session = auth_sessions.get(code)
    if not session:
        return False
    if time.time() > session["expires_at"]:
        del auth_sessions[code]
        return False
    session["verified"] = True
    session["user_data"] = user_data
    return True


def check_code(code: str) -> dict:
    """Check code status. Returns dict with verified, access_token, user, error."""
    session = auth_sessions.get(code)

    if not session:
        return {"verified": False, "error": "not_found"}

    now = time.time()
    if now > session["expires_at"]:
        del auth_sessions[code]
        return {"verified": False, "error": "expired"}

    if not session["verified"]:
        return {"verified": False}

    # Verified - return user data and clean up
    user_data = session["user_data"]
    del auth_sessions[code]
    return {"verified": True, "user": user_data}
