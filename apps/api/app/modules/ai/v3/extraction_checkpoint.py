"""Job-bound replay for one extraction request; no semantic approval implied."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast
from uuid import uuid4

from app.modules.ai.v3.source_units import SourceUnit


class ExtractionOutcomeUnknownError(RuntimeError):
    """An earlier provider request may have run; do not silently repeat it."""


class ExtractionJournal(Protocol):
    tenant_id: str
    job_id: str

    async def prepare(self, key: str, payload: dict[str, Any]) -> dict[str, Any] | None: ...
    async def save_value(self, key: str, value: dict[str, Any]) -> None: ...
    async def read_owned_value(self, key: str, expected_plan: dict[str, Any]) -> dict[str, Any] | None: ...


_IDENTITY_KEYS = frozenset({
    "tenant_id", "job_id", "document_id", "source_revision", "source_sha256",
    "unit_sha256", "context_sha256", "prompt_sha256", "route_fingerprint", "unit_start", "unit_end",
})
_DIGEST_KEYS = frozenset({"source_sha256", "unit_sha256", "context_sha256", "prompt_sha256", "route_fingerprint"})


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_extraction_identity(
    *, tenant_id: str, job_id: str, document_id: str, source_revision: str,
    source_text: str, unit: SourceUnit, context: str, messages: list[dict[str, str]],
    route_fingerprint: str,
) -> dict[str, str]:
    """Compute custody from the actual source slice and model messages."""
    if not (0 <= unit.start < unit.end <= len(source_text)) or source_text[unit.start:unit.end] != unit.text:
        raise ValueError("v3_extraction_source_span_invalid")
    if not isinstance(context, str) or not isinstance(messages, list):
        raise ValueError("v3_extraction_request_invalid")
    return {
        "tenant_id": tenant_id, "job_id": job_id, "document_id": document_id,
        "source_revision": source_revision,
        "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "unit_sha256": hashlib.sha256(unit.text.encode("utf-8")).hexdigest(),
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "prompt_sha256": _digest(messages), "route_fingerprint": route_fingerprint,
        "unit_start": str(unit.start), "unit_end": str(unit.end),
    }


def _validate_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("rules"), list):
        raise ValueError("v3_extraction_response_invalid")
    try:
        normalized = cast(dict[str, Any], json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))
    except (TypeError, ValueError) as exc:
        raise ValueError("v3_extraction_response_invalid") from exc
    for rule in normalized["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("v3_extraction_rule_invalid")
        for name in ("rule_id", "statement"):
            if not isinstance(rule.get(name), str) or not rule[name].strip():
                raise ValueError("v3_extraction_rule_invalid")
        if rule.get("source_quote") is None:
            rule["source_quote"] = ""
        if "source_quote" in rule and not isinstance(rule["source_quote"], str):
            raise ValueError("v3_extraction_rule_invalid")
        for name in ("conditions", "exceptions", "actors"):
            if name in rule and rule[name] is None:
                rule[name] = []
            if name in rule and (not isinstance(rule[name], list) or any(not isinstance(v, str) for v in rule[name])):
                raise ValueError("v3_extraction_rule_invalid")
        for name in ("section", "title", "timing", "consequences", "doc_id", "source_revision"):
            if name in rule and rule[name] is None:
                rule[name] = ""
            if name in rule and not isinstance(rule[name], str):
                raise ValueError("v3_extraction_rule_invalid")
    return normalized


async def extract_once(
    journal: ExtractionJournal,
    identity: Mapping[str, str],
    invoke: Callable[[], Awaitable[dict[str, Any]]],
    *, direct_client: Any = None, direct_messages: list[dict[str, str]] | None = None,
    direct_max_output_tokens: int = 8192,
) -> dict[str, Any]:
    """Claim, invoke and durably replay one exact request without blind retries.

    `journal` must provide immutable compare-and-set saves, exact plan identity,
    tenant/job isolation, and ownership-checked transactions. A committed claim
    without a committed result is ambiguous even when the request may not have
    reached the provider. No LLM call is made until the claim is read back.
    """
    if set(identity) != _IDENTITY_KEYS or any(not isinstance(v, str) or not v.strip() for v in identity.values()):
        raise ValueError("v3_extraction_identity_invalid")
    if any(not re.fullmatch(r"[0-9a-f]{64}", identity[key]) for key in _DIGEST_KEYS):
        raise ValueError("v3_extraction_identity_invalid")
    if not all(re.fullmatch(r"0|[1-9][0-9]*", identity[key]) for key in ("unit_start", "unit_end")):
        raise ValueError("v3_extraction_identity_invalid")
    if int(identity["unit_start"]) >= int(identity["unit_end"]):
        raise ValueError("v3_extraction_identity_invalid")
    if identity["tenant_id"] != journal.tenant_id or identity["job_id"] != journal.job_id:
        raise ValueError("v3_extraction_owner_mismatch")

    plan = {"schema": "v3-rule-extraction-checkpoint-v1", "identity": dict(identity)}
    signature = _digest(plan)
    result_key, claim_key = f"v3-result:{signature}", f"v3-claim:{signature}"

    async def load_result() -> dict[str, Any] | None:
        value = await journal.read_owned_value(result_key, plan)
        if value is None:
            return None
        if value.get("identity") != signature or not isinstance(value.get("response_sha256"), str):
            raise ValueError("v3_extraction_checkpoint_invalid")
        response = _validate_response(value.get("response"))
        if _digest(response) != value["response_sha256"]:
            raise ValueError("v3_extraction_checkpoint_invalid")
        return response

    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal

    if isinstance(journal, PendingStageJournal) and type(journal) is not PendingStageJournal:
        raise ValueError("pending_journal_type_invalid")
    if type(journal) is PendingStageJournal:
        def validate_value(value: dict[str, Any]) -> dict[str, Any]:
            if value.get("identity") != signature or not isinstance(value.get("response_sha256"), str):
                raise ValueError("v3_extraction_checkpoint_invalid")
            response = _validate_response(value.get("response"))
            if _digest(response) != value["response_sha256"]:
                raise ValueError("v3_extraction_checkpoint_invalid")
            return response
        if direct_client is not None:
            if direct_messages is None:
                raise ValueError("direct_owned_messages_required")
            from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage

            return await run_direct_owned_stage(journal=journal, client=direct_client, plan=plan,
                result_key=result_key, claim_key=claim_key, validate_value=validate_value,
                validate_response=_validate_response, messages=direct_messages, max_output_tokens=direct_max_output_tokens)
        return await journal.run_pending(plan=plan, result_key=result_key, claim_key=claim_key,
                                         validate_value=validate_value, validate_response=_validate_response, invoke=invoke)

    if direct_client is not None:
        raise ValueError("direct_owned_journal_required")
    prepared_result = await journal.prepare(result_key, plan)
    restored = await load_result()
    if prepared_result is not None and restored is None:
        raise ValueError("v3_extraction_result_unverified")
    if restored is not None:
        return restored
    claim = await journal.prepare(claim_key, plan)
    if claim is not None:
        restored = await load_result()
        if restored is not None:
            return restored
        raise ExtractionOutcomeUnknownError("v3_extraction_previous_outcome_unknown")

    token = uuid4().hex
    marker = {"identity": signature, "claim_token": token}
    await journal.save_value(claim_key, marker)
    if await journal.read_owned_value(claim_key, plan) != marker:
        raise ValueError("v3_extraction_claim_unverified")
    response = _validate_response(await invoke())
    await journal.save_value(result_key, {"identity": signature, "response": response, "response_sha256": _digest(response)})
    saved = await load_result()
    if saved is None:
        raise ValueError("v3_extraction_result_unverified")
    return saved
