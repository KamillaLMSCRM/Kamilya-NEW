import logging
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.celery_app import _log_task_end, _log_task_start
from app.core.errors import register_error_handlers
from app.core.operation_log import RequestOperationLog, operation_event, request_id, task_trace

DOCUMENT_ID = "8441a03a-fab3-4f64-a37c-0becc416c387"
TASK_ID = "995eb8d5-3bc8-4a9e-a4b6-3e6665b5b916"


def test_request_correlation_records_route_and_error_without_request_content(caplog):
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RequestOperationLog)

    @app.post("/documents/{doc_id}/editorial-review/{opaque}")
    async def review(doc_id: UUID, opaque: str):
        operation_event("source_review.test")
        raise HTTPException(409, detail={"code": "source_review_revision_conflict"})

    with caplog.at_level(logging.INFO, logger="app.core.operation_log"):
        result = TestClient(app).post(
            f"/documents/{DOCUMENT_ID}/editorial-review/path-canary?secret=query-canary",
            headers={"Authorization": "Bearer auth-canary", "X-Request-ID": "forged-canary"},
            json={"text": "body-canary"},
        )

    assert result.status_code == 409
    correlation = UUID(result.headers["x-request-id"])
    assert caplog.text.count(f"request_id={correlation}") == 2
    assert "route=/documents/{doc_id}/editorial-review/{opaque}" in caplog.text
    assert "error_code=source_review_revision_conflict" in caplog.text
    assert f"document_id={DOCUMENT_ID}" in caplog.text
    assert "canary" not in caplog.text
    assert request_id.get() is None


def test_unhandled_request_has_correlation_response(caplog):
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RequestOperationLog)

    @app.get("/failure")
    async def crash():
        raise RuntimeError()

    result = TestClient(app, raise_server_exceptions=False).get("/failure")
    assert result.status_code == 500
    assert f"request_id={UUID(result.headers['x-request-id'])}" in caplog.text
    assert "cause_class=RuntimeError" in caplog.text


def test_worker_correlates_events_and_does_not_include_task_payload(caplog):
    task = SimpleNamespace(name="documents.editorial_review", request=SimpleNamespace(retries=1))
    with caplog.at_level(logging.INFO, logger="app.core.operation_log"):
        _log_task_start(TASK_ID, task, args=["input-canary"])
        operation_event("source_review.result.saved", document_id=DOCUMENT_ID)
        _log_task_end(task, "FAILURE", retval="output-canary")
    assert caplog.text.count(f"task_id={TASK_ID}") == 3
    assert "outcome=failure" in caplog.text
    assert "canary" not in caplog.text
    assert task_trace.get() is None
