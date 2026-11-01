"""Durable request replay for lesson and critic responses; not quality approval."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import uuid4

from app.modules.ai.v3.extraction_checkpoint import ExtractionJournal, ExtractionOutcomeUnknownError


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


async def stage_once(
    journal: ExtractionJournal, *, stage: str, group_id: str, source_sha256: str,
    route_fingerprint: str, messages: list[dict[str, str]], response_format: dict[str, Any] | None,
    invoke: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    if stage not in {"lesson", "review", "repair"} or not group_id.strip():
        raise ValueError("v3_stage_identity_invalid")
    if not all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in (source_sha256, route_fingerprint)):
        raise ValueError("v3_stage_identity_invalid")
    plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": journal.tenant_id, "job_id": journal.job_id,
            "stage": stage, "group_id": group_id, "source_sha256": source_sha256,
            "route_fingerprint": route_fingerprint, "request_sha256": _digest([messages, response_format])}
    signature = _digest(plan)
    result_key, claim_key = f"v3-stage-result:{signature}", f"v3-stage-claim:{signature}"

    def validate(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("v3_stage_response_invalid")
        try:
            return cast(dict[str, Any], json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))
        except (TypeError, ValueError) as exc:
            raise ValueError("v3_stage_response_invalid") from exc

    async def load_result() -> dict[str, Any] | None:
        value = await journal.read_owned_value(result_key, plan)
        if value is None:
            return None
        if value.get("identity") != signature:
            raise ValueError("v3_stage_checkpoint_invalid")
        response = validate(value.get("response"))
        if value.get("response_sha256") != _digest(response):
            raise ValueError("v3_stage_checkpoint_invalid")
        return response

    prepared = await journal.prepare(result_key, plan)
    restored = await load_result()
    if restored is not None:
        return restored
    if prepared is not None:
        raise ValueError("v3_stage_result_unverified")
    claim = await journal.prepare(claim_key, plan)
    if claim is not None:
        restored = await load_result()
        if restored is not None:
            return restored
        raise ExtractionOutcomeUnknownError("v3_stage_previous_outcome_unknown")
    marker = {"identity": signature, "claim_token": uuid4().hex}
    await journal.save_value(claim_key, marker)
    if await journal.read_owned_value(claim_key, plan) != marker:
        raise ValueError("v3_stage_claim_unverified")
    response = validate(await invoke())
    await journal.save_value(result_key, {"identity": signature, "response": response, "response_sha256": _digest(response)})
    saved = await load_result()
    if saved is None:
        raise ValueError("v3_stage_result_unverified")
    return saved
