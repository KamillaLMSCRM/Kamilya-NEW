"""WhatsApp gateway client — talks to wa-gateway microservice over HTTPS.

Architecture:
  Kamilya backend (Render) ──HTTPS+JWT──► wa-gateway (VPS 173.249.51.164)
                                            │
                                            └──► WhatsApp servers (Meta)

Kamilya is a middleware, NOT a provider. The tenant owns:
  - Their WhatsApp number
  - The Baileys session (creds.json on gateway disk)
  - All risks (Meta ban, number change, etc.)

This client just forwards HTTP requests with a short-lived service JWT.
No business logic here — that's in channel_router.py.
"""

import logging
from typing import Any
import httpx
import jwt
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class WAGatewayError(Exception):
    """Base error for wa-gateway client."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"wa-gateway {status_code}: {detail}")


def _mint_service_jwt() -> str:
    """Mint a short-lived service JWT for wa-gateway authentication.

    The gateway verifies HS256 with KAMILYA_BACKEND_SECRET. 5-minute TTL
    means each call gets a fresh token — we never store long-lived tokens
    in the gateway.
    """
    return jwt.encode(
        {
            "sub": "kamilya-backend",
            "role": "service",
        },
        settings.KAMILYA_BACKEND_SECRET,
        algorithm="HS256",
        expires_in=300,
    )


def _gateway_url(path: str) -> str:
    """Build absolute URL to wa-gateway. Raises if not configured."""
    base = settings.WA_GATEWAY_URL
    if not base:
        raise WAGatewayError(
            503,
            "WA_GATEWAY_URL not configured on backend. "
            "Add it to Render env to enable WhatsApp integration."
        )
    return f"{base.rstrip('/')}{path}"


async def _call(method: str, path: str, **kwargs) -> dict[str, Any]:
    """Authenticated call to wa-gateway with error translation.

    Centralized so each public function is a one-liner that just declares
    the path. Errors from the gateway bubble up as WAGatewayError with
    the gateway's status code — caller decides whether to retry, surface
    to user, etc.
    """
    headers = {**(kwargs.pop("headers", {}) or {}), "Authorization": f"Bearer {_mint_service_jwt()}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.request(method, _gateway_url(path), headers=headers, **kwargs)
    except httpx.RequestError as e:
        # Connection refused, DNS failure, timeout — gateway is down
        logger.error({"err": str(e), "path": path}, "wa-gateway unreachable")
        raise WAGatewayError(503, f"wa-gateway unreachable: {e.__class__.__name__}")

    if not r.is_success:
        try:
            detail = r.json().get("detail", r.text[:200])
        except Exception:
            detail = r.text[:200]
        logger.warning({"status": r.status_code, "path": path, "detail": detail},
                       "wa-gateway returned error")
        raise WAGatewayError(r.status_code, detail)

    # 204 No Content — return empty dict
    if r.status_code == 204 or not r.content:
        return {}

    return r.json()


# ── Public API ─────────────────────────────────────────────────────────────


async def init_session(tenant_id: str) -> dict:
    """Start a WhatsApp session for tenant. Returns QR code (PNG base64)
    if not yet connected, or { status: connected, phone_number } if
    already paired.

    Idempotent — calling twice in a row returns the same state. The QR
    expires after ~50s on WhatsApp's side; UI must poll /status and call
    /init again when QR disappears.
    """
    return await _call("POST", f"/v1/sessions/{tenant_id}/start")


async def get_status(tenant_id: str) -> dict:
    """Current session state. Always returns — even when no session exists.

    Response shape:
      { status: 'not_started' | 'persisted' | 'initializing' |
                'qr_pending' | 'connected' | 'disconnected' | 'logged_out',
        phone_number: str | null,
        qr: base64 PNG | null,
        qr_expires_at: ISO8601 | null }
    """
    return await _call("GET", f"/v1/sessions/{tenant_id}/status")


async def logout(tenant_id: str) -> dict:
    """Destroy session + clear creds.json. Tenant will need to re-scan QR."""
    return await _call("POST", f"/v1/sessions/{tenant_id}/logout")


async def send_message(tenant_id: str, to_phone: str, message: str) -> dict:
    """Send a WhatsApp text message to a phone number (E.164).

    Returns { message_id, status: 'sent', to_jid }. The gateway does NOT
    block on delivery confirmation — read/delivered events come back via
    webhook later and are persisted in invitation_deliveries by another
    handler (see delivery_webhook.py).
    """
    return await _call(
        "POST", f"/v1/sessions/{tenant_id}/send",
        json={"to": to_phone, "message": message},
    )


async def self_test(tenant_id: str) -> dict:
    """Send a test message to the tenant's own phone number.
    Useful for HR to verify integration is working.
    Raises WAGatewayError(409, ...) if session not connected.
    """
    return await _call("POST", f"/v1/sessions/{tenant_id}/test")