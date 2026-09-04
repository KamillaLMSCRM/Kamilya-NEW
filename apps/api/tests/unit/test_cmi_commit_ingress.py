from __future__ import annotations

import json
from typing import cast

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Scope

from app.modules.scorm.cmi_ingress import ScormCommitBodyLimitMiddleware


def _app(*, max_body_bytes: int = 16) -> tuple[FastAPI, list[bytes]]:
    app = FastAPI()
    received: list[bytes] = []

    @app.post("/api/v1/scorm/attempts/{attempt_id}/commit")
    async def commit(attempt_id: str, request: Request) -> dict[str, str]:
        del attempt_id
        received.append(await request.body())
        return {"status": "saved"}

    @app.post("/api/v1/unrelated")
    async def unrelated(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"size": len(body)}

    app.add_middleware(
        ScormCommitBodyLimitMiddleware,
        api_prefix="/api/v1",
        max_body_bytes=max_body_bytes,
    )
    return app, received


@pytest.mark.asyncio
async def test_ingress_rejects_oversized_declared_body_before_route() -> None:
    app, received = _app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/scorm/attempts/attempt-1/commit",
            content=b"{}",
            headers={"Content-Length": "17"},
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "cmi_request_too_large"
    assert received == []


@pytest.mark.asyncio
async def test_ingress_rejects_oversized_chunked_body_before_route() -> None:
    downstream_called = False
    sent: list[Message] = []
    incoming = iter(
        [
            {"type": "http.request", "body": b"12345678", "more_body": True},
            {"type": "http.request", "body": b"901234567", "more_body": False},
        ]
    )

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_called
        del scope, receive, send
        downstream_called = True

    async def receive() -> Message:
        return cast(Message, next(incoming))

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = ScormCommitBodyLimitMiddleware(
        downstream,
        api_prefix="/api/v1",
        max_body_bytes=16,
    )
    scope = cast(
        Scope,
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/scorm/attempts/attempt-1/commit",
            "headers": [],
        },
    )

    await middleware(scope, receive, send)

    assert downstream_called is False
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["detail"]["code"] == "cmi_request_too_large"


@pytest.mark.asyncio
async def test_ingress_rejects_invalid_declared_length_before_route() -> None:
    app, received = _app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/scorm/attempts/attempt-1/commit",
            content=b"{}",
            headers={"Content-Length": "invalid"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_content_length"
    assert received == []


@pytest.mark.asyncio
async def test_ingress_replays_bounded_body_unchanged() -> None:
    app, received = _app()
    body = b'{"cmi":{}}'

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/scorm/attempts/attempt-1/commit", content=body)

    assert response.status_code == 200
    assert received == [body]


@pytest.mark.asyncio
async def test_ingress_does_not_limit_unrelated_route() -> None:
    app, _received = _app()
    body = b"x" * 32

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/unrelated", content=body)

    assert response.status_code == 200
    assert response.json() == {"size": len(body)}


def test_main_registers_scorm_commit_ingress_limit() -> None:
    from app.main import app

    assert any(item.cls is ScormCommitBodyLimitMiddleware for item in app.user_middleware)
