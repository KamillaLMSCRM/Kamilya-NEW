"""Low-cardinality operational events with identifiers for incident lookup."""

import logging
import re
from contextvars import ContextVar
from os import getenv
from time import perf_counter
from uuid import UUID, uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
request_id: ContextVar[str | None] = ContextVar("operation_request_id", default=None)
task_trace: ContextVar[tuple[str, float] | None] = ContextVar("operation_task_trace", default=None)
_SAFE_LABEL = re.compile(r"[a-z][a-z0-9_.]{0,95}\Z", re.ASCII)


def stable_label(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_LABEL.fullmatch(value) else None


def uuid_label(value: object) -> str | None:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str) and len(value) == 36:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return None


def operation_event(event: str, *, level: int = logging.INFO, **fields: str | int | bool | None) -> None:
    # Call sites supply only static labels, validated identifiers and counters.
    # Keep the fields in the message for text-format Celery and the admin buffer.
    release = getenv("RELEASE_SHA") or getenv("RENDER_GIT_COMMIT") or ""
    if re.fullmatch(r"[a-f0-9]{40}", release):
        fields["release_sha"] = release
    if correlation_id := request_id.get():
        fields["request_id"] = correlation_id
    if active_task := task_trace.get():
        fields["task_id"] = active_task[0]
    details = " ".join(f"{name}={value}" for name, value in fields.items() if value is not None)
    logger.log(level, "%s %s", event, details)


class RequestOperationLog:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = str(uuid4())
        scope["operation_request_id"] = correlation_id
        token = request_id.set(correlation_id)
        started = perf_counter()
        status = 500
        cause_class = None

        async def observe(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, observe)
        except BaseException as error:
            cause_class = type(error).__name__
            raise
        finally:
            route = getattr(scope.get("route"), "path", None)
            if route is None or route.rsplit("/", 1)[-1] not in {"health", "healthz"} or status >= 400 or cause_class:
                path_params = scope.get("path_params", {})
                operation_event(
                    "api.request.finished",
                    level=logging.WARNING if status >= 400 or cause_class else logging.INFO,
                    method=scope["method"] if scope["method"] in {
                        "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE",
                    } else "OTHER",
                    route=route or "unmatched",
                    status=status,
                    duration_ms=round((perf_counter() - started) * 1000),
                    document_id=uuid_label(path_params.get("doc_id") or path_params.get("document_id")),
                    job_id=uuid_label(path_params.get("job_id")),
                    error_code=scope.get("operation_error_code"),
                    cause_class=cause_class,
                )
            request_id.reset(token)
