"""Secret-free readiness for the implemented private official Codex CLI connector.

No workstation credentials, CLI execution, login, inference or provisioning.
Settings alone are not proof of provider eligibility or runtime health.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from app.core.config import Settings, get_settings

ReserveReason = Literal[
    "not_configured", "authorization_required", "unavailable", "protocol_mismatch", "ready"
]
PROTOCOL = "kamilya-chatgpt-reserve-v1"
READINESS_DEADLINE_SECONDS = 4.0


class ChatGPTReserveReadiness(BaseModel):
    ready: bool
    reason: ReserveReason
    checked_at: datetime


def configuration_blocker(settings: Settings | None = None) -> ReserveReason | None:
    """Pure configuration inspection: no network, credential reads or login."""
    s = settings if settings is not None else get_settings()
    if not s.CHATGPT_RESERVE_URL or not s.CHATGPT_RESERVE_TOKEN or not s.CHATGPT_RESERVE_MODEL:
        return "not_configured"
    if s.CHATGPT_RESERVE_AUTH_MODE != "codex_cli":
        return "authorization_required"
    try:
        url = urlsplit(s.CHATGPT_RESERVE_URL)
        address = ipaddress.ip_address(url.hostname or "")
        # Literal RFC1918/ULA/loopback only: no DNS rebinding, link-local metadata,
        # credentials in URLs, query injection or public model/token destinations.
        private = address.is_loopback or any(
            address in network
            for network in (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
                ipaddress.ip_network("fc00::/7"),
            )
            if address.version == network.version
        )
        if (
            not private or url.scheme not in {"http", "https"}
            or url.username is not None or url.password is not None
            or url.query or url.fragment or url.path not in {"", "/", "/v1", "/v1/"}
            or url.port == 0
        ):
            return "not_configured"
    except ValueError:
        return "not_configured"
    return None


async def check_readiness() -> ChatGPTReserveReadiness:
    """Explicit bounded non-generative readiness; do not reflect upstream data."""
    s = get_settings()
    reason = configuration_blocker(s)
    if reason is None:
        reason = "unavailable"
        try:
            # Wall-clock bound also stops a gateway which slowly streams forever.
            async with asyncio.timeout(READINESS_DEADLINE_SECONDS):
                async with httpx.AsyncClient(
                    timeout=3.0, follow_redirects=False, trust_env=False,
                ) as client:
                    base = s.CHATGPT_RESERVE_URL.rstrip("/")
                    if not base.endswith("/v1"):
                        base += "/v1"
                    async with client.stream(
                        "GET", f"{base}/readiness",
                        headers={"Authorization": f"Bearer {s.CHATGPT_RESERVE_TOKEN}"},
                    ) as response:
                        if response.status_code == 401:
                            reason = "authorization_required"
                        elif response.status_code == 403:
                            reason = "not_configured"
                        elif response.status_code == 200:
                            body = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=8193):
                                body.extend(chunk)
                                if len(body) > 8192:
                                    break
                            if len(body) > 8192:
                                reason = "protocol_mismatch"
                            else:
                                data = json.loads(body)
                                if (
                                    isinstance(data, dict)
                                    and data.get("protocol") == PROTOCOL
                                    and data.get("authorization") == "codex_cli"
                                    and data.get("model") == s.CHATGPT_RESERVE_MODEL
                                    and data.get("ready") is True
                                ):
                                    reason = "ready"
                                else:
                                    reason = "protocol_mismatch"
        except (ValueError, httpx.HTTPError, TimeoutError):
            # Never log credentials, response bodies, URLs, or provider errors.
            reason = "unavailable"
    return ChatGPTReserveReadiness(
        ready=reason == "ready", reason=reason, checked_at=datetime.now(UTC),
    )
