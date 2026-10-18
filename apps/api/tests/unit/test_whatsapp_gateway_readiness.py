from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.modules.integrations import wa_gateway_client as gateway


@pytest.mark.asyncio
@pytest.mark.parametrize("base,secret", [("", ""), ("https://gateway.example.test", "")])
async def test_unconfigured_gateway_fails_closed_before_token_or_network(base, secret):
    with (
        patch.object(gateway, "settings", SimpleNamespace(WA_GATEWAY_URL=base, KAMILYA_BACKEND_SECRET=secret)),
        patch.object(gateway.jwt, "encode") as encode,
        patch.object(gateway.httpx, "AsyncClient") as client,
    ):
        with pytest.raises(gateway.WAGatewayError) as exc:
            await gateway.get_status("synthetic-tenant")
    assert exc.value.status_code == 503
    encode.assert_not_called()
    client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null"])
async def test_malformed_success_response_is_translated_to_gateway_failure(body):
    response = httpx.Response(200, content=body, request=httpx.Request("GET", "https://gateway.example.test/status"))
    client = AsyncMock()
    client.request.return_value = response
    with (
        patch.object(gateway, "settings", SimpleNamespace(WA_GATEWAY_URL="https://gateway.example.test", KAMILYA_BACKEND_SECRET="synthetic-test-secret-not-for-production")),
        patch.object(gateway.httpx, "AsyncClient") as factory,
    ):
        factory.return_value.__aenter__.return_value = client
        with pytest.raises(gateway.WAGatewayError) as exc:
            await gateway.get_status("synthetic-tenant")
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_gateway_transport_failure_is_logged_without_payload_or_formatting_error(caplog):
    client = AsyncMock()
    client.request.side_effect = httpx.ConnectError("synthetic connection failure")
    with (
        patch.object(gateway, "settings", SimpleNamespace(WA_GATEWAY_URL="https://gateway.example.test", KAMILYA_BACKEND_SECRET="synthetic-test-secret-not-for-production")),
        patch.object(gateway.httpx, "AsyncClient") as factory,
    ):
        factory.return_value.__aenter__.return_value = client
        with pytest.raises(gateway.WAGatewayError) as exc:
            await gateway.get_status("synthetic-tenant")
    assert exc.value.status_code == 503
    assert "wa-gateway unreachable" in caplog.text
    assert "synthetic-tenant" not in caplog.text
