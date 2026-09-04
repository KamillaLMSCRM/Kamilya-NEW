from __future__ import annotations

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.modules.scorm.cmi_policy import CmiPolicyLimits


class ScormCommitBodyLimitMiddleware:
    """Bound SCORM commit bodies before FastAPI materializes and decodes them."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str,
        max_body_bytes: int | None = None,
    ) -> None:
        self._app = app
        self._max_body_bytes = max_body_bytes or CmiPolicyLimits().max_raw_bytes
        prefix = api_prefix.rstrip("/")
        self._commit_path = re.compile(rf"^{re.escape(prefix)}/scorm/attempts/[^/]+/commit/?$")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_commit_request(scope):
            await self._app(scope, receive, send)
            return

        declared_lengths = [
            value.decode("latin-1").strip()
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-length"
        ]
        if len(declared_lengths) > 1:
            await self._reject(scope, receive, send, 422, "invalid_content_length", "Invalid Content-Length")
            return
        if declared_lengths:
            try:
                declared_length = int(declared_lengths[0])
            except ValueError:
                await self._reject(scope, receive, send, 422, "invalid_content_length", "Invalid Content-Length")
                return
            if declared_length < 0:
                await self._reject(scope, receive, send, 422, "invalid_content_length", "Invalid Content-Length")
                return
            if declared_length > self._max_body_bytes:
                await self._reject(
                    scope,
                    receive,
                    send,
                    413,
                    "cmi_request_too_large",
                    "CMI request exceeds the allowed size",
                )
                return

        body_parts: list[bytes] = []
        actual_length = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            actual_length += len(body)
            if actual_length > self._max_body_bytes:
                await self._reject(
                    scope,
                    receive,
                    send,
                    413,
                    "cmi_request_too_large",
                    "CMI request exceeds the allowed size",
                )
                return
            body_parts.append(body)
            if not message.get("more_body", False):
                break

        replayed = False
        bounded_body = b"".join(body_parts)

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": bounded_body, "more_body": False}

        await self._app(scope, replay_receive, send)

    def _is_commit_request(self, scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and self._commit_path.fullmatch(scope.get("path", "")) is not None
        )

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"detail": {"code": code, "message": message}},
        )
        await response(scope, receive, send)
