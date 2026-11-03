"""Unwired citation-location contract; caller owns packet and reviewer provenance.

A successful location check removes no hold and confers no semantic approval.
Snapshots and profile identities are consistency mechanisms, not authentication.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

PROFILE = "case-context-citation-v1"
MAX_PASSAGES = 512
MAX_REQUEST_BYTES = 262144
MAX_CONTEXT = 4096
MAX_QUOTE = 2048
MAX_REVIEW_REQUEST_BYTES = 262144
MAX_QUESTIONS = 24
MAX_TARGETS = 64
MAX_CITATIONS_PER_TARGET = 64


@dataclass(frozen=True)
class Address:
    target_id: str
    binding_index: int
    source_ref: str
    start: int
    end: int
    quote: str
    working: str


@dataclass(frozen=True)
class Snapshot:
    """Immutable captured wire and addresses from a caller-owned validated packet."""
    profile: str
    packet_identity: str
    inventory_json: str
    addresses: tuple[Address | None, ...]
    keys: tuple[tuple[str, int], ...]

    def request(self) -> dict[str, Any]:
        return {"profile": self.profile, "sources": json.loads(self.inventory_json)}


@dataclass(frozen=True)
class InvocationReceipt:
    """Process-local invocation record, not a persisted or authenticated token."""
    run: object
    role: str
    request_identity: str
    packet_identity: str
    response: Any


def _unique(text: str, value: str) -> int | None:
    if not value:
        return None
    i = text.find(value)
    return i if i >= 0 and text.find(value, i + 1) < 0 else None


def critic_payload(snapshot: Snapshot, packet: Any, questions: Any, *, role: str) -> dict[str, Any]:
    """Build a bounded location-review view, never an admission or semantic receipt.

    Caller supplies process-owned validated authored candidates; no expected
    binding, source offset, answer key, or previous critic output is accepted.
    The question bytes themselves remain visible, as they are to learners.
    This is not a replacement for the native critic's full semantic payload.
    """
    from app.modules.ai.lesson_cycle import Candidate, _passages

    if not isinstance(snapshot, Snapshot) or capture(packet) != snapshot:
        raise ValueError("citation_snapshot_changed")
    if role not in {"review", "counter"}:
        raise ValueError("citation_role_invalid")
    if not isinstance(questions, list | tuple) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise ValueError("citation_questions_invalid")
    known_targets = {target.target_id for target in packet.targets}
    rows = []
    ids: set[str] = set()
    for question in questions:
        if (not isinstance(question, Candidate) or not isinstance(question.question_id, str)
                or not question.question_id or question.question_id in ids
                or not question.target_ids or len(set(question.target_ids)) != len(question.target_ids)
                or not set(question.target_ids) <= known_targets
                or not isinstance(question.text, str) or not question.text
                or not isinstance(question.options, tuple) or not question.options
                or any(not isinstance(option, str) or not option for option in question.options)):
            raise ValueError("citation_questions_invalid")
        ids.add(question.question_id)
        rows.append({"question_id": question.question_id, "target_ids": list(question.target_ids),
                     "text": question.text, "options": list(question.options), "intent": question.intent})
    _, lesson_passages = _passages(packet)
    view = {"task": "lesson_assessment_review" if role == "review" else "lesson_assessment_counterexample",
            "citation_profile": PROFILE, "sources": snapshot.request()["sources"],
            "lesson": {"id": packet.lesson_id, "title": packet.title,
                       "passages": [{"ref": ref, "text": text} for ref, text in lesson_passages.items()]},
            "questions": rows}
    wire = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(wire.encode("utf-8")) > MAX_REVIEW_REQUEST_BYTES:
        raise ValueError("citation_request_too_large")
    # Binding is local consistency data; this digest authenticates neither packet nor critic.
    view["citation_request_identity"] = hashlib.sha256(
        (snapshot.packet_identity + "\0" + wire).encode("utf-8")).hexdigest()
    if len(json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) > MAX_REVIEW_REQUEST_BYTES:
        raise ValueError("citation_request_too_large")
    return view


def preauthor_payload(snapshot: Snapshot, packet: Any, target_ids: tuple[str, ...], *, role: str) -> dict[str, Any]:
    """Experimental owner-separated inventory, with no expected binding hints."""
    from app.modules.ai.lesson_cycle import _passages

    if not isinstance(snapshot, Snapshot) or capture(packet) != snapshot:
        raise ValueError("citation_snapshot_changed")
    if role not in {"review", "counter"}:
        raise ValueError("citation_role_invalid")
    if (not isinstance(target_ids, tuple) or not 0 < len(target_ids) <= MAX_TARGETS
            or any(not isinstance(tid, str) or not tid for tid in target_ids)
            or len(set(target_ids)) != len(target_ids)):
        raise ValueError("citation_targets_invalid")
    targets = {target.target_id: target for target in packet.targets}
    if not set(target_ids) <= set(targets):
        raise ValueError("citation_targets_invalid")
    owner_sets = {frozenset(targets[tid].source_ids) for tid in target_ids}
    if len(owner_sets) != 1 or not next(iter(owner_sets)):
        raise ValueError("citation_owner_groups_must_match")
    passages, _ = _passages(packet)
    rows = []
    for tid in target_ids:
        target = targets[tid]
        owned = set(target.source_ids)
        if not owned:
            raise ValueError("citation_targets_invalid")
        rows.append({"target_id": tid, "description": target.description, "sources": [
            {"source_ref": ref, "text": text} for ref, (owner, text) in passages.items() if owner in owned
        ]})
    view = {"task": f"case_citation_{role}", "citation_profile": PROFILE, "targets": rows}
    raw = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    view["citation_request_identity"] = hashlib.sha256((snapshot.packet_identity + "\0" + raw).encode()).hexdigest()
    if len(json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) > MAX_REVIEW_REQUEST_BYTES:
        raise ValueError("citation_request_too_large")
    return view


def occurrence_ambiguity_targets(snapshot: Snapshot, packet: Any) -> frozenset[str]:
    """Classify locally addressable repeated quotes; never remove a native hold."""
    from app.modules.ai.lesson_cycle import _author_protocol, _passages

    if not isinstance(snapshot, Snapshot) or capture(packet) != snapshot:
        raise ValueError("citation_snapshot_changed")
    passages, _ = _passages(packet)
    result = set()
    for target in packet.targets:
        if _author_protocol(packet, target) != "case_application":
            continue
        keys = [index for index, key in enumerate(snapshot.keys) if key[0] == target.target_id]
        if not keys or any(snapshot.addresses[index] is None for index in keys):
            continue
        for index in keys:
            address = snapshot.addresses[index]
            assert address is not None
            passage = passages[address.source_ref][1]
            if _unique(passage, address.quote) is None:
                result.add(target.target_id)
                break
    return frozenset(result)


def preauthor_holds(snapshot: Snapshot, packet: Any, target_ids: tuple[str, ...],
                    review: InvocationReceipt, counter: InvocationReceipt, *, run: object) -> dict[str, str]:
    """Check distinct role records owned by this run; success is location only."""
    try:
        expected = [preauthor_payload(snapshot, packet, target_ids, role=role)["citation_request_identity"]
                    for role in ("review", "counter")]
        valid = (isinstance(review, InvocationReceipt) and isinstance(counter, InvocationReceipt)
                 and review is not counter and review.run is run and counter.run is run
                 and review.role == "review" and counter.role == "counter"
                 and review.packet_identity == counter.packet_identity == snapshot.packet_identity
                 and [review.request_identity, counter.request_identity] == expected)
    except Exception:
        valid = False
    if not valid:
        return {tid: "citation_reviewer_unverified" for tid in target_ids}
    held: dict[str, str] = {}
    requested = set(target_ids)
    for response in (review.response, counter.response):
        if (not isinstance(response, dict) or set(response) != {"targets"}
                or not isinstance(response["targets"], list) or len(response["targets"]) > MAX_TARGETS):
            return {tid: "citation_unverified" for tid in target_ids}
        rows = response["targets"]
        if any(not isinstance(row, dict) or not isinstance(row.get("target_id"), str)
               or row["target_id"] not in requested for row in rows):
            return {tid: "citation_unverified" for tid in target_ids}
        for tid in target_ids:
            selected = [row for row in rows if row["target_id"] == tid]
            if len(selected) != 1 or set(selected[0]) != {"target_id", "citations"}:
                held[tid] = "citation_unverified"
                continue
            citations = selected[0]["citations"]
            keys = [key for key in snapshot.keys if key[0] == tid]
            if (not keys or len(keys) > MAX_CITATIONS_PER_TARGET or not isinstance(citations, list)
                    or len(citations) != len(keys)):
                held[tid] = "citation_unverified"
                continue
            unmatched = set(keys)
            for citation in citations:
                matches = [key for key in unmatched if _selection_matches(snapshot, key, citation)]
                if len(matches) != 1:
                    held[tid] = "citation_unverified"
                    break
                unmatched.remove(matches[0])
            if unmatched:
                held[tid] = "citation_unverified"
    return held


def capture(packet: Any) -> Snapshot:
    """Capture validated packet, with no expected-binding data in request()."""
    from app.modules.ai.lesson_cycle import _passages, _validate_packet

    _validate_packet(packet)
    passages, _ = _passages(packet)
    inventory = [{"source_ref": ref, "text": text} for ref, (_, text) in passages.items()]
    wire = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(inventory) > MAX_PASSAGES or len(wire.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("citation_inventory_too_large")
    keys: list[tuple[str, int]] = []
    addresses: list[Address | None] = []
    for target in packet.targets:
        for index, binding in enumerate(target.qualification_bindings):
            keys.append((target.target_id, index))
            addresses.append(_address(packet, target, binding, index, passages))
    identity = hashlib.sha256(json.dumps({"profile": PROFILE, "packet": asdict(packet)},
        ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return Snapshot(PROFILE, identity, wire, tuple(addresses), tuple(keys))


def _address(packet: Any, target: Any, binding: Any, index: int, passages: dict[str, Any]) -> Address | None:
    if not isinstance(binding, dict) or sum(row == binding for row in target.qualification_bindings) != 1:
        return None
    owner, start, end, quote = (binding.get(k) for k in ("source_id", "quote_start", "quote_end", "quote"))
    sources = [(i, source) for i, source in enumerate(packet.sources, 1) if source.source_id == owner]
    if (owner not in target.source_ids or len(sources) != 1 or type(start) is not int or type(end) is not int
            or not isinstance(quote, str) or not quote or len(quote) > MAX_QUOTE):
        return None
    source_index, source = sources[0]
    original, working = source.original_text or source.text, source.text
    if (not isinstance(original, str) or not isinstance(working, str)
            or not 0 <= start < end <= len(original) or original[start:end] != quote):
        return None
    if len(original) <= len(working):
        offset = _unique(working, original)
        if offset is None:
            return None
        left, right = offset + start, offset + end
    else:
        offset = _unique(original, working)
        if offset is None or not offset <= start < end <= offset + len(working):
            return None
        left, right = start - offset, end - offset
    if working[left:right] != quote:
        return None
    for line in re.finditer(r"[^\n]+", working):
        raw = line.group()
        lo = line.start() + len(raw) - len(raw.lstrip())
        hi = line.start() + len(raw.rstrip())
        if lo <= left < right <= hi:
            part = len(re.split(r"\n+", working[:line.start()]))
            ref = f"S{source_index}P{part}"
            if passages.get(ref) != (owner, raw.strip()):
                return None
            return Address(target.target_id, index, ref, left - lo, right - lo, quote, working)
    return None


def _selection_matches(snapshot: Snapshot, key: tuple[str, int], selection: Any) -> bool:
    if snapshot.keys.count(key) != 1:
        return False
    address = snapshot.addresses[snapshot.keys.index(key)]
    if address is None or not isinstance(selection, dict) or set(selection) != {"source_ref", "quote", "context"}:
        return False
    if (selection["source_ref"] != address.source_ref or selection["quote"] != address.quote
            or not isinstance(selection["context"], str) or not 0 < len(selection["context"]) <= MAX_CONTEXT):
        return False
    passages = {row["source_ref"]: row["text"] for row in json.loads(snapshot.inventory_json)}
    context = selection["context"]
    context_at = _unique(passages[address.source_ref], context)
    quote_at = _unique(context, address.quote)
    return (context_at is not None and _unique(address.working, context) is not None and quote_at is not None
            and context_at + quote_at == address.start
            and context_at + quote_at + len(address.quote) == address.end)


def hold(snapshot: Snapshot, current_packet: Any, target_id: str, binding_index: int,
         review: Any, counter: Any, *, verify_independence: Callable[..., bool] | None = None) -> str | None:
    """Return a negative reason or None (location only; never admission)."""
    try:
        if not isinstance(snapshot, Snapshot) or capture(current_packet) != snapshot:
            return "citation_snapshot_changed"
        try:
            independent = callable(verify_independence) and verify_independence(review, counter, current_packet) is True
        except Exception:
            independent = False
        if not independent:
            return "citation_reviewer_unverified"
        if not isinstance(target_id, str) or not target_id or type(binding_index) is not int:
            return "citation_source_unbound"
        key = (target_id, binding_index)
        if snapshot.keys.count(key) != 1:
            return "citation_source_unbound"
        address = snapshot.addresses[snapshot.keys.index(key)]
        if address is None:
            return "citation_source_unbound"
        if not all(_selection_matches(snapshot, key, selection) for selection in (review, counter)):
            return "citation_unverified"
        return None
    except (TypeError, ValueError, KeyError, AttributeError):
        return "citation_snapshot_changed"
