"""Shared literal timing geometry and negative-only repair diagnostics.

The compiler and diagnostic collector cross this same seam.  Geometry never
establishes applicability, assessed credit, missing goals, or semantic approval.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, NoReturn

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.source_assessment_graph import SourceGraphError, _fields, _hash, _quote

_HARMLESS = frozenset(",.;:()[]{}«»\"'„“”‘’—–-…")


@dataclass(frozen=True)
class ApplicationPreludeClaim:
    """Server-derived application identity permitted only as literal byte custody."""

    owner_handle: str
    native_qualifier_handle: str
    predecessor_handle: str
    application_id: str
    ref: str
    predecessor_answer: str
    native_graph_sha256: str


@dataclass(frozen=True)
class TimingCaseGeometry:
    fork: str
    pair_spans: list[tuple[int, int, int, int]]
    action: dict[str, Any]
    prefix: str | None
    projection: dict[str, Any] | None


class TimingCaseValidationError(SourceGraphError):
    def __init__(self, code: str, finding: dict[str, Any]):
        super().__init__(code)
        self.findings = [finding]


def _occurrences(text: str, quote: str, *, offset: int = 0) -> list[dict[str, Any]]:
    """Bound displayed occurrences; count is reported separately without truncation."""
    spans: list[dict[str, Any]] = []
    cursor = 0
    while quote and len(spans) < 8:
        start = text.find(quote, cursor)
        if start < 0:
            break
        spans.append({"start": offset + start, "end": offset + start + len(quote), "quote": quote})
        cursor = start + len(quote)
    return spans


def _negative_receipt(frame: dict[str, Any], fact: SourceFact, code: str,
                      details: dict[str, Any]) -> dict[str, Any]:
    source = fact.value
    fork = frame.get("fork")
    fork = fork if isinstance(fork, str) else ""
    fork_start = source.index(fork) if fork and source.count(fork) == 1 else None
    pieces: list[tuple[str, Any]] = [("fork", fork)]
    if isinstance(frame.get("action"), dict):
        pieces.append(("action.answer", frame["action"].get("answer")))
    for collection in ("purposes", "branches"):
        rows = frame.get(collection)
        if isinstance(rows, list):
            for index, row in enumerate(rows[:12]):
                if isinstance(row, dict):
                    pieces.extend((f"{collection}[{index}].{field}", row.get(field))
                                  for field in (("selector", "answer") if collection == "branches" else ("answer",)))
    members = []
    for path, quote in pieces:
        if not isinstance(quote, str) or not quote or len(quote) > 65536:
            continue
        members.append({"json_path": path, "quote": quote, "source_count": source.count(quote),
            "fork_count": fork.count(quote), "source_spans": _occurrences(source, quote),
            "fork_spans": _occurrences(fork, quote, offset=fork_start) if fork_start is not None else []})
    return {"code": "timing_case_validation", "error_code": code, "frame_handle": frame.get("handle"),
        "ref": frame["ref"], "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "fork": {"json_path": "fork", "source_count": source.count(fork) if fork else 0,
                 "span": {"start": fork_start, "end": fork_start + len(fork)} if fork_start is not None else None},
        "members": members, "projection": details.get("projection", {}),
        "violations": details.get("violations", []), "branch_order": details.get("branch_order", []),
        "semantic_approval": False}


def _uncovered(text: str, start: int, end: int, coverage: list[tuple[int, int]],
               offset: int) -> list[dict[str, Any]]:
    segments, cursor = [], start
    for left, right in sorted(coverage):
        left, right = max(start, left), min(end, right)
        if left > cursor:
            segments.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        segments.append((cursor, end))
    return [{"start": offset + left, "end": offset + right, "quote": text[left:right]}
            for left, right in segments
            if any(not char.isspace() and char not in _HARMLESS for char in text[left:right])]


def _canonical_hash(value: Any) -> str:
    return _hash(value)


def _application_prelude_claims(frame: dict[str, Any], declarations: dict[str, dict[str, Any]],
        refs: dict[str, SourceFact], claims: tuple[ApplicationPreludeClaim, ...], *, fork: str,
        fork_start: int, action_start: int, forbidden: list[tuple[int, int]],
        details: dict[str, Any]) -> list[tuple[int, int, dict[str, Any], str]]:
    """Recheck trusted claim identities as source bytes; never infer an application."""
    code = "invalid_application_timing_prelude_claim"

    def fail() -> NoReturn:
        details["violations"] = [{"error_code": code,
                                  "json_paths": ["bindings", "fork", "action.answer"]}]
        raise SourceGraphError(code)

    if (type(claims) is not tuple or len(claims) > 96
            or any(not isinstance(claim, ApplicationPreludeClaim) for claim in claims)):
        fail()
    if not claims:
        return []
    frame_handle, bindings = frame.get("handle"), frame.get("bindings")
    if (not isinstance(frame_handle, str) or not frame_handle or len(frame_handle) > 96
            or not isinstance(bindings, list) or len(bindings) > 96
            or any(not isinstance(handle, str) for handle in bindings)):
        fail()
    application_ids: set[str] = set()
    graph_hashes: set[str] = set()
    source = refs[frame["ref"]].value
    validated: list[tuple[int, int, dict[str, Any], str]] = []
    for claim in claims:
        values = (claim.owner_handle, claim.native_qualifier_handle, claim.predecessor_handle,
                  claim.application_id, claim.ref, claim.predecessor_answer, claim.native_graph_sha256)
        if (any(not isinstance(value, str) or not value or len(value) > 320 for value in values)
                or len(claim.native_graph_sha256) != 64
                or any(char not in "0123456789abcdef" for char in claim.native_graph_sha256)
                or claim.owner_handle != frame_handle or claim.predecessor_handle == frame_handle
                or claim.ref != frame["ref"] or claim.application_id in application_ids
                or bindings.count(claim.native_qualifier_handle) != 1):
            fail()
        row = declarations.get(claim.native_qualifier_handle)
        if (not isinstance(row, dict)
                or row.get("handle") != claim.native_qualifier_handle
                or row.get("ref") != claim.ref or row.get("role") != "scope" or row.get("effect") != "none"
                or not isinstance(row.get("quote"), str)):
            fail()
        quote = row["quote"]
        try:
            _quote(claim.ref, claim.predecessor_answer, refs)
        except SourceGraphError:
            fail()
        if (not isinstance(quote, str) or not quote.strip() or len(quote) > 320
                or not any(not char.isspace() and char not in _HARMLESS for char in quote)
                or source.count(quote) != 1 or fork.count(quote) != 1):
            fail()
        source_start = source.index(quote)
        predecessor_start = source.index(claim.predecessor_answer)
        start, end = source_start - fork_start, source_start - fork_start + len(quote)
        if (not 0 <= start < end <= len(fork) or end > action_start
                or any(start < right and left < end for left, right in forbidden)):
            fail()
        application_ids.add(claim.application_id)
        graph_hashes.add(claim.native_graph_sha256)
        validated.append((start, end, {
            "application_id": claim.application_id,
            "owner_handle": claim.owner_handle,
            "native_qualifier_handle": claim.native_qualifier_handle,
            "predecessor_handle": claim.predecessor_handle,
            "ref": claim.ref,
            "quote": quote,
            "span": {"start": source_start, "end": source_start + len(quote)},
            "claim_sha256": _canonical_hash(asdict(claim)),
            "native_qualifier_sha256": _canonical_hash(row),
            "predecessor_answer_sha256": hashlib.sha256(claim.predecessor_answer.encode()).hexdigest(),
            "predecessor_span": {"start": predecessor_start,
                                 "end": predecessor_start + len(claim.predecessor_answer)},
            "semantic_approval": False,
        }, claim.native_graph_sha256))
    if len(graph_hashes) != 1:
        fail()
    return validated


def _prelude_custody(frame: dict[str, Any], declarations: dict[str, dict[str, Any]],
                     refs: dict[str, SourceFact], fork_start: int, action_start: int,
                     fork: str) -> tuple[list[tuple[int, int]], list[dict[str, Any]]]:
    covered: list[tuple[int, int]] = []
    diagnostics: list[dict[str, Any]] = []
    indices = {handle: index for index, handle in enumerate(declarations)}
    for handle in frame["bindings"]:
        row = declarations.get(handle)
        if not isinstance(row, dict):
            continue
        ref, quote = row.get("ref"), row.get("quote")
        fact = refs.get(ref) if isinstance(ref, str) else None
        count = fact.value.count(quote) if fact and isinstance(quote, str) and quote else 0
        source_start = fact.value.index(quote) if count == 1 and fact and isinstance(quote, str) else None
        start = source_start - fork_start if source_start is not None and ref == frame["ref"] else None
        end = start + len(quote) if start is not None and isinstance(quote, str) else None
        in_fork = start is not None and end is not None and 0 <= start < end <= len(fork)
        before_action = in_fork and end is not None and end <= action_start
        role_eligible = row.get("role") in ("actor", "condition") or (
            row.get("role") == "timing" and row.get("effect") == "scopes_action")
        eligible = bool(before_action and role_eligible)
        if eligible and start is not None and end is not None:
            covered.append((start, end))
        diagnostics.append({"handle": handle, "json_path": f"qualifiers[{indices[handle]}]",
            "ref": ref, "role": row.get("role"), "effect": row.get("effect"), "quote": quote,
            "source_count": count, "source_spans": _occurrences(fact.value, quote) if fact and isinstance(quote, str) else [],
            "in_fork": bool(in_fork), "before_action": bool(before_action),
            "eligible_for_projection_custody": eligible})
    return covered, diagnostics


def _geometry(frame: dict[str, Any], declarations: dict[str, dict[str, Any]],
              refs: dict[str, SourceFact], details: dict[str, Any], *,
              application_claims: tuple[ApplicationPreludeClaim, ...] | None = None) -> TimingCaseGeometry:
    def fail(code: str, *paths: str) -> None:
        details["violations"] = [{"error_code": code, "json_paths": list(paths)}]
        raise SourceGraphError(code)

    ref, fork, action = frame["ref"], frame["fork"], frame["action"]
    _quote(ref, fork, refs)
    _fields(action, {"label", "answer"}, "invalid_frame_atom_schema")
    if not isinstance(action["answer"], str) or not action["answer"].strip() or len(action["answer"]) > 320:
        fail("frame_answer_length_exceeded", "action.answer")
    _quote(ref, action["answer"], refs)
    if action["answer"] not in fork:
        fail("action_outside_declared_fork", "fork", "action.answer")
    if not isinstance(frame["purposes"], list) or len(frame["purposes"]) > 12:
        fail("invalid_case_purposes", "purposes")
    credit = [("action.answer", action["answer"])]
    for index, purpose in enumerate(frame["purposes"]):
        _fields(purpose, {"label", "answer"}, "invalid_frame_atom_schema")
        _quote(ref, purpose["answer"], refs)
        if purpose["answer"] not in fork:
            fail("purpose_outside_declared_fork", "fork", f"purposes[{index}].answer")
        credit.append((f"purposes[{index}].answer", purpose["answer"]))
    if not isinstance(frame["branches"], list) or not 2 <= len(frame["branches"]) <= 12:
        fail("invalid_timing_branches", "branches")
    selectors: set[str] = set()
    indexed_pairs = []
    invalid_paths = []
    for index, branch in enumerate(frame["branches"]):
        _fields(branch, {"label", "answer", "selector"}, "invalid_timing_branch_schema")
        selector, answer = branch["selector"], branch["answer"]
        for field, quote in (("selector", selector), ("answer", answer)):
            if not isinstance(quote, str) or not quote.strip() or fork.count(quote) != 1 or (field == "selector" and quote in selectors):
                invalid_paths.append(f"branches[{index}].{field}")
        if invalid_paths:
            continue
        start, astart = fork.index(selector), fork.index(answer)
        if start < astart + len(answer) and astart < start + len(selector):
            fail("timing_selector_answer_overlap", f"branches[{index}].selector", f"branches[{index}].answer")
        indexed_pairs.append((start, start + len(selector), astart, astart + len(answer), index))
        credit.append((f"branches[{index}].answer", answer))
        selectors.add(selector)
    if invalid_paths:
        fail("ambiguous_or_nonliteral_timing_branch", "fork", *invalid_paths)
    indexed_pairs.sort()
    details["branch_order"] = [{"branch_index": index, "selector_span": [start, end], "answer_span": [left, right]}
                               for start, end, left, right, index in indexed_pairs]
    pairs = [row[:4] for row in indexed_pairs]
    for order, (_, selector_end, answer_start, answer_end, index) in enumerate(indexed_pairs):
        next_selector = pairs[order + 1][0] if order + 1 < len(pairs) else len(fork)
        if selector_end > answer_start or answer_end > next_selector:
            fail("unpaired_timing_selector", f"branches[{index}].selector", f"branches[{index}].answer")
    spans = sorted((fork.index(quote), fork.index(quote) + len(quote), path) for path, quote in credit)
    for (_, end, path), (left, _, other) in zip(spans, spans[1:], strict=False):
        if end > left:
            fail("overlapping_timing_credit", path, other)
    nonaction = [(fork.index(quote), fork.index(quote) + len(quote), path) for path, quote in credit[1:]]
    for start, selector_end, _, _, index in indexed_pairs:
        for left, end, path in nonaction:
            if start < end and left < selector_end:
                fail("timing_selector_overlaps_credit", f"branches[{index}].selector", path)
    action_start = fork.index(action["answer"])
    action_end = action_start + len(action["answer"])
    overlaps = [index for index, (start, end, _, _) in enumerate(pairs) if start < action_end and action_start < end]
    if overlaps and (overlaps != [0] or action_start > pairs[0][0] or action_end < pairs[0][1]):
        fail("invalid_action_selector_scope", "action.answer", "branches")
    if not overlaps:
        return TimingCaseGeometry(fork, pairs, dict(action), None, None)
    selector_start, selector_end = pairs[0][:2]
    raw_answer = action["answer"]
    before_selector = raw_answer[:selector_start - action_start]
    after_selector = raw_answer[selector_end - action_start:]
    prefix, predicate = before_selector.rstrip(), after_selector.lstrip()
    prefix_end = action_start + len(prefix)
    predicate_start, predicate_end = action_end - len(predicate), action_end
    source = refs[ref].value
    fork_start = source.index(fork)

    def absolute(start: int, end: int) -> dict[str, Any]:
        return {"start": fork_start + start, "end": fork_start + end, "quote": fork[start:end]}

    prelude_spans, bound = _prelude_custody(frame, declarations, refs, fork_start, action_start, fork)
    base_unowned_pre = _uncovered(fork, 0, action_start, prelude_spans, fork_start)
    application_spans: list[tuple[int, int, dict[str, Any], str]] = []
    if application_claims is not None:
        forbidden = [(fork.index(quote), fork.index(quote) + len(quote)) for _, quote in credit]
        forbidden.extend((start, end) for start, end, _, _ in pairs)
        application_spans = _application_prelude_claims(
            frame, declarations, refs, application_claims, fork=fork, fork_start=fork_start,
            action_start=action_start, forbidden=forbidden, details=details,
        )
        prelude_spans.extend((start, end) for start, end, _, _ in application_spans)
    first_answer_start = min(span[2] for span in pairs)
    unowned_pre = _uncovered(fork, 0, action_start, prelude_spans, fork_start)
    unowned_post = _uncovered(fork, predicate_end, first_answer_start, [], fork_start)
    details["projection"] = {"original_action": absolute(action_start, action_end),
        "prefix": absolute(action_start, prefix_end), "first_selector": absolute(selector_start, selector_end),
        "predicate": absolute(predicate_start, predicate_end), "unowned_prelude_spans": unowned_pre,
        "unowned_suffix_spans": unowned_post, "declarations": bound}
    if (raw_answer != raw_answer.strip() or not prefix or not predicate
            or before_selector[len(prefix):].strip() or after_selector[:-len(predicate)].strip()
            or prefix_end > selector_start or selector_end > predicate_start or unowned_pre or unowned_post):
        fail("invalid_timing_action_projection", "action.answer", "fork", "bindings")
    _quote(ref, prefix, refs)
    _quote(ref, predicate, refs)
    projection = {"protocol": "timing-action-interruption-v1", "semantic_approval": False,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "fork_span": {"start": fork_start, "end": fork_start + len(fork)},
        **{key: details["projection"][key] for key in ("original_action", "prefix", "first_selector", "predicate")}}
    used_claims = [row for start, end, row, _ in application_spans
                   if any(start < segment["end"] - fork_start and segment["start"] - fork_start < end
                          for segment in base_unowned_pre)]
    if used_claims:
        projection["application_prelude_custody"] = {
            "protocol": "application-timing-prelude-custody-v1", "semantic_approval": False,
            "native_graph_sha256": application_spans[0][3],
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "frame_sha256": _canonical_hash(frame),
            "claims": sorted(used_claims, key=lambda row: row["application_id"]),
        }
    return TimingCaseGeometry(fork, pairs, {"label": action["label"], "answer": predicate}, prefix, projection)


def validate_timing_case(frame: dict[str, Any], declarations: dict[str, dict[str, Any]],
                         refs: dict[str, SourceFact]) -> TimingCaseGeometry:
    details: dict[str, Any] = {}
    try:
        return _geometry(frame, declarations, refs, details)
    except SourceGraphError as exc:
        raise TimingCaseValidationError(str(exc), _negative_receipt(frame, refs[frame["ref"]], str(exc), details)) from exc


def _validate_application_timing_case(frame: dict[str, Any], declarations: dict[str, dict[str, Any]],
        refs: dict[str, SourceFact], claims: tuple[ApplicationPreludeClaim, ...]) -> TimingCaseGeometry:
    """Private application-local byte custody; callers establish claim inventory identity."""
    details: dict[str, Any] = {}
    try:
        return _geometry(frame, declarations, refs, details, application_claims=claims)
    except SourceGraphError as exc:
        raise TimingCaseValidationError(
            str(exc), _negative_receipt(frame, refs[frame["ref"]], str(exc), details),
        ) from exc


def timing_case_findings(frame: Any, declarations: Any, refs: dict[str, SourceFact]) -> list[dict[str, Any]]:
    if (not isinstance(frame, dict) or frame.get("kind") != "timing_case"
            or not isinstance(frame.get("ref"), str) or frame["ref"] not in refs
            or not isinstance(declarations, dict)):
        return []
    try:
        validate_timing_case(frame, declarations, refs)
    except TimingCaseValidationError as exc:
        return exc.findings
    except (KeyError, TypeError, ValueError, AttributeError):
        return []  # Malformed/unsupported data is still rejected by canonical compilation.
    return []
