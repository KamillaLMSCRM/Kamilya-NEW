"""Source-bound paid-request intent and completed-result custody."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.modules.ai.managed_luna_client import ManagedLunaCompletedJsonError

POLICY = "source-review-request-custody-v2"


class RequestOutcomeUnknown(ValueError):  # noqa: N818 - compact module-local outcome
    def __init__(self, key: str) -> None:
        super().__init__("source_review_provider_outcome_unknown")
        self.key = key


class BeforePostDeferred(Exception):  # noqa: N818 - compact module-local outcome
    """The request was not sent because the current turn has insufficient time."""


class RequestRejected(Exception):  # noqa: N818 - compact module-local outcome
    """A provider returned an explicit non-success response."""


class CompletedResponseRejected(ValueError):  # noqa: N818 - compact module-local outcome
    """A complete response failed envelope or schema validation."""

    def __init__(self, receipt: dict[str, Any]) -> None:
        super().__init__("source_review_invalid_response")
        self.receipt = receipt


def identity(*, tenant: str, document: str, original_sha: str, selected_sha: str,
             policy: str, route: str, messages: list[dict[str, Any]]) -> str:
    payload = [POLICY, tenant, document, original_sha, selected_sha, policy, route, messages]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def choose_attempt(key: str, retained: Mapping[str, dict[str, Any]], acknowledgement: dict[str, Any] | None,
                   failure: Any, root_queue: Any, preceding: Any) -> str:
    """Reuse a completed reply; new attempts require exact acknowledgement or explicit rejection retry."""
    prefix = f"{POLICY}:{key}:"
    completed = [(name[len(prefix):-len(":completed")], value) for name, value in retained.items()
                 if name.startswith(prefix) and name.endswith(":completed")
                 and value.get("status") in {"ok", "invalid_json", "response_rejected"}]
    if completed:
        return completed[-1][0]
    if acknowledgement and failure is not None and failure.payload.get("unknown_request_key") == key:
        return str(acknowledgement["request_id"])
    pending = [name[len(prefix):-len(":intent")] for name in retained if name.startswith(prefix)
               and name.endswith(":intent") and name[:-len(":intent")] + ":completed" not in retained]
    if pending:
        return pending[-1]
    rejected = any(name.startswith(prefix) and name.endswith(":completed") and value.get("status") == "rejected"
                   for name, value in retained.items())
    if (root_queue.request_id is not None and preceding is not None
            and preceding.payload.get("code") == "source_review_provider_unavailable"
            and rejected):
        return str(root_queue.request_id)
    return "initial"


async def invoke_once(*, key: str, attempt: str, retained: Mapping[str, dict[str, Any]],
                      save: Callable[[str, dict[str, Any]], Awaitable[None]],
                      before_post: Callable[[], None],
                      invoke: Callable[[], Awaitable[tuple[object, dict[str, Any] | None]]],
                      usage: Callable[[str, dict[str, Any] | None], None]) -> object:
    """Replay exact completed results; a bare durable intent always fences another POST."""
    base = f"{POLICY}:{key}:{attempt}"
    completed = retained.get(base + ":completed")
    if completed is not None:
        if completed.get("identity") != key or completed.get("attempt") != attempt:
            raise ValueError("source_review_custody_invalid")
        status = completed.get("status")
        if status not in {"ok", "invalid_json", "rejected", "response_rejected"} or "usage" not in completed:
            raise ValueError("source_review_custody_invalid")
        usage(base, completed["usage"])
        if status == "invalid_json":
            raise ManagedLunaCompletedJsonError("managed_luna_response_invalid")
        if status == "rejected":
            raise RequestRejected("source_review_provider_rejected")
        if status == "response_rejected":
            receipt = completed.get("rejection")
            if not isinstance(receipt, dict):
                raise ValueError("source_review_custody_invalid")
            raise CompletedResponseRejected(receipt)
        if "value" not in completed:
            raise ValueError("source_review_custody_invalid")
        return completed["value"]
    if base + ":intent" in retained:
        raise RequestOutcomeUnknown(key)
    before_post()
    await save(base + ":intent", {"identity": key, "attempt": attempt, "state": "started"})
    result: dict[str, Any]
    try:
        value, receipt = await invoke()
    except ManagedLunaCompletedJsonError:
        result = {"identity": key, "attempt": attempt, "status": "invalid_json", "usage": None}
        await save(base + ":completed", result)
        usage(base, None)
        raise
    except CompletedResponseRejected as exc:
        result = {"identity": key, "attempt": attempt, "status": "response_rejected",
                  "usage": None, "rejection": exc.receipt}
        await save(base + ":completed", result)
        usage(base, None)
        raise
    except RequestRejected:
        result = {"identity": key, "attempt": attempt, "status": "rejected", "usage": None}
        await save(base + ":completed", result)
        usage(base, None)
        raise
    except Exception as exc:
        raise RequestOutcomeUnknown(key) from exc
    result = {"identity": key, "attempt": attempt, "status": "ok", "value": value, "usage": receipt}
    await save(base + ":completed", result)
    usage(base, receipt)
    return value
