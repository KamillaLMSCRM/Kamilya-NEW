"""Authorization regression coverage for AI job HTTP and WebSocket access."""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import UTC, datetime
from inspect import signature
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch
from uuid import uuid4

import pytest
import uvicorn
import websockets
from fastapi import FastAPI, HTTPException, WebSocketDisconnect
from fastapi.testclient import TestClient
from websockets.exceptions import ConnectionClosed

AI_JOB_HANDLERS = (
    "generate_course",
    "list_jobs",
    "get_job",
    "cancel_generation",
)


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        ("methodologist", True),
        ("superadmin", True),
        ("admin", False),
        ("org_admin", False),
        ("student", False),
    ],
)
@pytest.mark.asyncio
async def test_ai_job_role_matrix(role: str, allowed: bool):
    from app.modules.ai.router import require_ai_job_access

    user = SimpleNamespace(role=role)
    if allowed:
        assert await require_ai_job_access(user) is user
    else:
        with pytest.raises(HTTPException) as caught:
            await require_ai_job_access(user)
        assert caught.value.status_code == 403


@pytest.mark.parametrize("handler_name", AI_JOB_HANDLERS)
def test_each_ai_job_http_handler_uses_the_shared_guard(handler_name: str):
    from app.modules.ai import router as ai_router

    handler = getattr(ai_router, handler_name)
    dependency = signature(handler).parameters["user"].default.dependency

    assert dependency is ai_router.require_ai_job_access


@pytest.mark.asyncio
async def test_active_role_not_primary_role_controls_ai_job_access():
    from app.core.auth import _ActiveRoleUser
    from app.modules.ai.router import require_ai_job_access

    primary_admin = SimpleNamespace(role="admin")
    active_methodologist = _ActiveRoleUser(primary_admin, "methodologist")
    assert await require_ai_job_access(active_methodologist) is active_methodologist

    primary_methodologist = SimpleNamespace(role="methodologist")
    active_admin = _ActiveRoleUser(primary_methodologist, "admin")
    with pytest.raises(HTTPException) as caught:
        await require_ai_job_access(active_admin)
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_generate_course_keeps_document_analysis_tenant_scoped():
    from app.modules.ai.router import generate_course
    from app.modules.ai.schemas import AIGenerateRequest

    tenant_id = uuid4()
    document_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    db = AsyncMock()
    request = AIGenerateRequest(documents=[document_id])
    not_found = HTTPException(
        status_code=404,
        detail={"code": "documents_not_found", "document_ids": [str(document_id)]},
    )

    with patch(
        "app.modules.ai.source_analysis.analyze_document_set",
        new=AsyncMock(side_effect=not_found),
    ) as analyze:
        with pytest.raises(HTTPException) as caught:
            await generate_course(request, db=db, user=user)

    assert caught.value.status_code == 404
    analyze.assert_awaited_once_with(db, tenant_id, [document_id])


@pytest.mark.asyncio
async def test_list_jobs_filters_tenant_methodologist_but_not_platform_superadmin():
    from app.modules.ai.router import list_jobs

    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    tenant_db = SimpleNamespace(execute=AsyncMock(return_value=result))
    tenant_user = SimpleNamespace(tenant_id=uuid4(), role="methodologist")
    await list_jobs(db=tenant_db, user=tenant_user)
    tenant_statement = str(tenant_db.execute.await_args.args[0])
    assert "ai_jobs.tenant_id" in tenant_statement

    platform_db = SimpleNamespace(execute=AsyncMock(return_value=result))
    platform_user = SimpleNamespace(tenant_id=None, role="superadmin")
    await list_jobs(db=platform_db, user=platform_user)
    platform_statement = str(platform_db.execute.await_args.args[0])
    assert "WHERE ai_jobs.tenant_id" not in platform_statement


@pytest.mark.parametrize("handler_name", ("get_job", "cancel_generation"))
@pytest.mark.asyncio
async def test_cross_tenant_job_id_is_not_found(handler_name: str):
    from app.modules.ai import router as ai_router

    tenant_id = uuid4()
    user = SimpleNamespace(tenant_id=tenant_id, role="methodologist")
    db = AsyncMock()
    lookup = AsyncMock(return_value=None)

    with patch.object(ai_router, "get_ai_job", lookup):
        with pytest.raises(HTTPException) as caught:
            await getattr(ai_router, handler_name)("other-tenant-job", db=db, user=user)

    assert caught.value.status_code == 404
    lookup.assert_awaited_once_with(db, "other-tenant-job", tenant_id=str(tenant_id))


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.is_open = True
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.session.is_open = False
        return False


def _terminal_job(job_id: str = "job-1"):
    return SimpleNamespace(
        id=job_id,
        status="completed",
        stage="completed",
        progress=100,
        message="Done",
        created_at=datetime.now(UTC),
        course_id=None,
    )


def _running_job(job_id: str = "job-1"):
    return SimpleNamespace(
        id=job_id,
        status="running",
        stage="outline",
        progress=25,
        message="Working",
        created_at=datetime.now(UTC),
        course_id=None,
    )


@pytest.mark.asyncio
async def test_websocket_rejects_disallowed_active_role_without_job_lookup():
    from app.modules.ai import router as ai_router

    websocket = AsyncMock()
    active_admin = SimpleNamespace(role="admin", tenant_id=uuid4())

    with (
        patch("app.core.db.async_session_factory", return_value=_SessionContext(AsyncMock())),
        patch.object(ai_router, "get_current_user", AsyncMock(return_value=active_admin)),
        patch.object(ai_router, "get_current_active_user", AsyncMock(return_value=active_admin)),
    ):
        await ai_router.job_progress_ws(websocket, "job-1", token="valid-token")

    websocket.accept.assert_awaited_once()
    websocket.close.assert_awaited_once_with(code=4003, reason="AI job access denied")


@pytest.mark.asyncio
async def test_websocket_cross_tenant_job_is_not_found_without_disclosure():
    from app.modules.ai import router as ai_router

    websocket = AsyncMock()
    tenant_id = uuid4()
    methodologist = SimpleNamespace(role="methodologist", tenant_id=tenant_id)
    lookup = AsyncMock(return_value=None)

    with (
        patch("app.core.db.async_session_factory", return_value=_SessionContext(AsyncMock())),
        patch.object(ai_router, "get_current_user", AsyncMock(return_value=methodologist)),
        patch.object(ai_router, "get_current_active_user", AsyncMock(return_value=methodologist)),
        patch.object(ai_router, "get_ai_job", lookup),
    ):
        await ai_router.job_progress_ws(websocket, "other-tenant-job", token="valid-token")

    lookup.assert_awaited_once_with(
        ANY,
        "other-tenant-job",
        tenant_id=str(tenant_id),
    )
    websocket.accept.assert_awaited_once()
    websocket.close.assert_awaited_once_with(code=4004, reason="Job not found")


@pytest.mark.parametrize(
    ("role", "tenant_id"),
    (("methodologist", uuid4()), ("superadmin", None)),
)
@pytest.mark.asyncio
async def test_websocket_allows_canonical_roles(role: str, tenant_id):
    from app.modules.ai import router as ai_router

    websocket = AsyncMock()
    user = SimpleNamespace(role=role, tenant_id=tenant_id)
    job = _terminal_job()
    lookup = AsyncMock(return_value=job)

    with (
        patch("app.core.db.async_session_factory", return_value=_SessionContext(AsyncMock())),
        patch.object(ai_router, "get_current_user", AsyncMock(return_value=user)),
        patch.object(ai_router, "get_current_active_user", AsyncMock(return_value=user)),
        patch.object(ai_router, "get_ai_job", lookup),
    ):
        await ai_router.job_progress_ws(websocket, job.id, token="valid-token")

    lookup.assert_awaited_once_with(
        ANY,
        job.id,
        tenant_id=str(tenant_id) if tenant_id else None,
    )
    websocket.accept.assert_awaited_once()
    websocket.send_json.assert_awaited_once()


@pytest.mark.parametrize(
    ("role", "tenant_id", "expected_context"),
    (
        ("methodologist", uuid4(), "tenant"),
        ("superadmin", None, "platform_superadmin"),
    ),
)
@pytest.mark.asyncio
async def test_websocket_reestablishes_security_context_for_each_poll(
    role: str,
    tenant_id,
    expected_context: str,
):
    from app.modules.ai import router as ai_router

    websocket = AsyncMock()
    user = SimpleNamespace(role=role, tenant_id=tenant_id)
    handshake_session = SimpleNamespace(name="handshake")
    polling_session = SimpleNamespace(name="poll")
    sessions = (handshake_session, polling_session)

    async def authenticate(*, credentials, db):
        db.security_context = expected_context
        return user

    async def lookup(db, job_id, *, tenant_id):
        if getattr(db, "security_context", None) != expected_context:
            return None
        if db is handshake_session:
            return _running_job(job_id)
        return _terminal_job(job_id)

    async def wait_without_session(_seconds):
        assert not any(getattr(session, "is_open", False) for session in sessions)

    with (
        patch(
            "app.core.db.async_session_factory",
            side_effect=[_SessionContext(session) for session in sessions],
        ),
        patch.object(ai_router, "get_current_user", AsyncMock(side_effect=authenticate)) as auth,
        patch.object(ai_router, "get_current_active_user", AsyncMock(return_value=user)),
        patch.object(ai_router, "get_ai_job", AsyncMock(side_effect=lookup)),
        patch.object(ai_router.asyncio, "sleep", AsyncMock(side_effect=wait_without_session)),
    ):
        await ai_router.job_progress_ws(websocket, "job-1", token="valid-token")

    assert [call.kwargs["db"] for call in auth.await_args_list] == list(sessions)
    assert [session.security_context for session in sessions] == [
        expected_context,
        expected_context,
    ]
    assert not any(getattr(session, "is_open", False) for session in sessions)
    assert websocket.send_json.await_args_list[-1].args[0]["status"] == "completed"


@pytest.mark.parametrize(
    ("token", "role", "expected_code", "expected_reason"),
    (
        (None, None, 4001, "Missing token"),
        ("valid-token", "admin", 4003, "AI job access denied"),
        ("valid-token", "methodologist", 4004, "Job not found"),
    ),
)
def test_websocket_client_observes_application_close_codes(
    token: str | None,
    role: str | None,
    expected_code: int,
    expected_reason: str,
):
    from app.modules.ai import router as ai_router

    test_app = FastAPI()
    test_app.add_api_websocket_route(
        "/v1/ai/ws/jobs/{job_id}",
        ai_router.job_progress_ws,
    )
    user = SimpleNamespace(role=role, tenant_id=uuid4())
    lookup = AsyncMock(return_value=None)
    path = "/v1/ai/ws/jobs/job-1"
    if token:
        path = f"{path}?token={token}"

    with (
        patch("app.core.db.async_session_factory", return_value=_SessionContext(AsyncMock())),
        patch.object(ai_router, "get_current_user", AsyncMock(return_value=user)),
        patch.object(ai_router, "get_current_active_user", AsyncMock(return_value=user)),
        patch.object(ai_router, "get_ai_job", lookup),
        TestClient(test_app) as client,
    ):
        with client.websocket_connect(path) as websocket:
            error_message = websocket.receive_json()
            with pytest.raises(WebSocketDisconnect) as caught:
                websocket.receive_json()

    assert error_message == {
        "type": "error",
        "code": expected_code,
        "message": expected_reason,
    }
    assert caught.value.code == expected_code
    assert caught.value.reason == expected_reason
    if expected_code != 4004:
        lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_websocket_tcp_client_observes_application_close_codes():
    """Exercise Uvicorn's real WebSocket protocol rather than TestClient ASGI events."""
    from app.modules.ai import router as ai_router

    test_app = FastAPI()
    test_app.add_api_websocket_route(
        "/v1/ai/ws/jobs/{job_id}",
        ai_router.job_progress_ws,
    )
    admin = SimpleNamespace(role="admin", tenant_id=uuid4())
    methodologist = SimpleNamespace(role="methodologist", tenant_id=uuid4())

    async def authenticate(*, credentials, db):
        if credentials.credentials == "admin-token":
            return admin
        return methodologist

    lookup = AsyncMock(return_value=None)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            test_app,
            host="127.0.0.1",
            port=port,
            lifespan="off",
            log_level="critical",
            ws="websockets",
        )
    )
    server.install_signal_handlers = lambda: None

    with (
        patch("app.core.db.async_session_factory", return_value=_SessionContext(AsyncMock())),
        patch.object(ai_router, "get_current_user", AsyncMock(side_effect=authenticate)),
        patch.object(ai_router, "get_current_active_user", AsyncMock(side_effect=lambda user, db: user)),
        patch.object(ai_router, "get_ai_job", lookup),
    ):
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(200):
                if server.started:
                    break
                if server_task.done():
                    await server_task
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Uvicorn did not start")

            cases = (
                ("", 4001, "Missing token"),
                ("?token=admin-token", 4003, "AI job access denied"),
                ("?token=methodologist-token", 4004, "Job not found"),
            )
            for query, expected_code, expected_reason in cases:
                uri = f"ws://127.0.0.1:{port}/v1/ai/ws/jobs/job-1{query}"
                async with websockets.connect(uri) as websocket:
                    error_message = json.loads(await websocket.recv())
                    with pytest.raises(ConnectionClosed) as caught:
                        await websocket.recv()

                assert error_message == {
                    "type": "error",
                    "code": expected_code,
                    "message": expected_reason,
                }
                assert caught.value.rcvd is not None
                assert caught.value.rcvd.code == expected_code
                assert caught.value.rcvd.reason == expected_reason
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=5)
            listener.close()

    lookup.assert_awaited_once_with(
        ANY,
        "job-1",
        tenant_id=str(methodologist.tenant_id),
    )
