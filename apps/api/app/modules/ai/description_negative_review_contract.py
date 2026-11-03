"""Pure negative-only description review contract; not a reviewer or receipt.

Call ``build_requests`` only after native candidate and source ownership validation.
Call ``resolve`` with its request and a reviewer response (or None on timeout).
The returned target/reason pairs are holds, never positive admission decisions.
There is no provider registration, checkpoint persistence, or authenticity claim.
"""
import hashlib
import json
from dataclasses import dataclass
from typing import Any

DESCRIPTION_REVIEW_POLICY = "description-negative-review-v4"

MAX_TARGETS = 96
MAX_SOURCE_CHARS = 200_000
MAX_DESCRIPTION_CHARS = 2_000
MAX_SOURCE_REFS = 256
MAX_ID_CHARS = 100
MAX_GROUPS = 32
MAX_COVERAGE_ENTRIES = 512


def _build_request(targets: list[dict[str, Any]], owned_sources: dict[str, str]) -> dict[str, Any]:
    """Build bounded target-owned review input from already validated native data."""
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS or not isinstance(owned_sources, dict):
        raise ValueError("description_review_invalid_input")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    used: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("description_review_invalid_input")
        tid, description, refs = target.get("id"), target.get("description"), target.get("source_refs")
        if (not isinstance(tid, str) or not tid or len(tid) > MAX_ID_CHARS or tid in seen or not isinstance(description, str)
                or not description or len(description) > MAX_DESCRIPTION_CHARS or not isinstance(refs, list)
                or not refs or len(refs) > MAX_SOURCE_REFS
                or any(not isinstance(ref, str) or not ref or len(ref) > MAX_ID_CHARS or ref not in owned_sources for ref in refs)
                or len(set(refs)) != len(refs)):
            raise ValueError("description_review_invalid_input")
        if any(not isinstance(owned_sources[ref], str) or not owned_sources[ref] for ref in refs):
            raise ValueError("description_review_invalid_input")
        seen.add(tid)
        used.update(refs)
        result.append({"id": tid, "description": description, "source_refs": sorted(refs)})
    if sum(len(row["source_refs"]) for row in result) > MAX_COVERAGE_ENTRIES:
        raise ValueError("description_review_input_too_large")
    if len(used) > MAX_SOURCE_REFS or sum(len(owned_sources[ref]) for ref in used) > MAX_SOURCE_CHARS:
        raise ValueError("description_review_input_too_large")
    return {"targets": result, "sources": [{"ref": ref, "text": owned_sources[ref]} for ref in sorted(used)]}


@dataclass(frozen=True)
class ReviewSnapshot:
    """Independent serialized input snapshot, not an authenticated receipt."""
    _canonical_json: str

    @property
    def requests(self) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(self._canonical_json))


def build_requests(targets: list[dict[str, Any]], owned_sources: dict[str, str]) -> ReviewSnapshot:
    """Partition by identical owner set; one target appears in exactly one request.

    The maximum number of requests is MAX_GROUPS. This is an input bound, not
    a provider or job budget; the caller must enforce its own execution budget.
    """
    # Validate the entire input before constructing any disclosable request.
    validated = _build_request(targets, owned_sources)
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in validated["targets"]:
        key = tuple(sorted(row["source_refs"]))
        grouped.setdefault(key, []).append(row)
    if len(grouped) > MAX_GROUPS:
        raise ValueError("description_review_too_many_groups")
    requests = [_build_request(sorted(grouped[key], key=lambda row: row["id"]), owned_sources)
                for key in sorted(grouped)]
    return ReviewSnapshot(json.dumps(requests, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def resolve_groups(snapshot: ReviewSnapshot, requests: tuple[dict[str, Any], ...], responses: dict[int, Any]) -> tuple[tuple[str, str], ...]:
    """Resolve all partitions; absent responses hold their whole partition."""
    if not isinstance(snapshot, ReviewSnapshot) or requests != snapshot.requests:
        raise ValueError("description_review_invalid_requests")
    if (not isinstance(responses, dict) or any(type(index) is not int or index < 0 or index >= len(requests)
                                               for index in responses)):
        return tuple(sorted((row["id"], "description_review_invalid")
                            for request in requests for row in request["targets"]))
    if not isinstance(requests, tuple) or not 1 <= len(requests) <= MAX_GROUPS:
        raise ValueError("description_review_invalid_requests")
    all_targets: list[dict[str, Any]] = []
    all_sources: dict[str, str] = {}
    try:
        for request in requests:
            if not isinstance(request, dict) or set(request) != {"targets", "sources"}:
                raise ValueError("invalid request")
            for source in request["sources"]:
                if set(source) != {"ref", "text"} or (source["ref"] in all_sources
                        and all_sources[source["ref"]] != source["text"]):
                    raise ValueError("invalid source")
                all_sources[source["ref"]] = source["text"]
            all_targets.extend(request["targets"])
        if build_requests(all_targets, all_sources).requests != requests:
            raise ValueError("invalid partition")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("description_review_invalid_requests") from exc
    holds: list[tuple[str, str]] = []
    for index, request in enumerate(requests):
        holds.extend(resolve(request, responses.get(index)))
    return tuple(sorted(holds))


def resolve(request: dict[str, Any], response: Any) -> tuple[tuple[str, str], ...]:
    """Return closed negative holds; None represents an unavailable review.

    The transport must separately bound raw response bytes before JSON parsing.
    A valid consistent vote merely removes this review's hold. It is not proof of
    correctness and cannot satisfy another gate. Offsets establish a literal owned
    source location, not that the alleged contradiction is semantically valid.
    """
    targets = {row["id"]: row for row in request["targets"]}
    sources = {row["ref"]: row["text"] for row in request["sources"]}
    held = {tid: "description_review_unavailable" for tid in targets}
    if response is None:
        return tuple(sorted(held.items()))
    if not isinstance(response, dict) or set(response) != {"rows"} or not isinstance(response["rows"], list) or len(response["rows"]) > MAX_TARGETS:
        return tuple((tid, "description_review_invalid") for tid in sorted(targets))
    seen = set()
    for row in response["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("target_id"), str) or row["target_id"] not in targets:
            return tuple((tid, "description_review_invalid") for tid in sorted(targets))
        tid = row["target_id"]
        if tid in seen:
            held[tid] = "description_review_invalid"
            continue
        seen.add(tid)
        if set(row) != {"target_id", "relation", "source_ref", "start", "end", "coverage"}:
            held[tid] = "description_review_invalid"
            continue
        relation, ref, start, end, coverage = (row[k] for k in ("relation", "source_ref", "start", "end", "coverage"))
        if relation == "consistent" and ref is None and start is None and end is None:
            expected = set(targets[tid]["source_refs"])
            valid = isinstance(coverage, list) and len(coverage) == len(expected)
            covered = set()
            if valid:
                for span in coverage:
                    if (not isinstance(span, dict) or set(span) != {"ref", "start", "end"}
                            or not isinstance(span["ref"], str) or span["ref"] not in expected
                            or span["ref"] in covered or type(span["start"]) is not int
                            or type(span["end"]) is not int or span["start"] != 0
                            or span["end"] != len(sources[span["ref"]])):
                        valid = False
                        break
                    covered.add(span["ref"])
            if valid and covered == expected:
                held.pop(tid, None)
            else:
                held[tid] = "description_review_invalid"
        elif relation == "unknown" and ref is None and start is None and end is None and coverage == []:
            held[tid] = "description_review_unknown"
        elif (relation == "contradiction" and isinstance(ref, str) and ref in targets[tid]["source_refs"]
              and ref in sources and coverage == [] and type(start) is int and type(end) is int and 0 <= start < end <= len(sources[ref])):
            held[tid] = "description_source_contradiction"
        else:
            held[tid] = "description_review_invalid"
    return tuple(sorted(held.items()))


def _passage_id(ref: str, text: str) -> str:
    """Identity of a full exact source passage; offsets are derived by server."""
    encoded = json.dumps([ref, text], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "P" + hashlib.sha256(encoded).hexdigest()


def build_requests_v3(targets: list[dict[str, Any]], owned_sources: dict[str, str]) -> ReviewSnapshot:
    """Each supplied passage covers exactly [0, len(source)) in codepoints."""
    base = build_requests(targets, owned_sources)
    groups = list(base.requests)
    for group in groups:
        for source in group["sources"]:
            source["passage_id"] = _passage_id(source["ref"], source["text"])
    return ReviewSnapshot(json.dumps(groups, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def resolve_groups_v3(snapshot: ReviewSnapshot, requests: tuple[dict[str, Any], ...],
                      responses: dict[int, Any]) -> tuple[tuple[str, str], ...]:
    """Resolve only after exact immutable grouping and full owner revalidation."""
    if not isinstance(snapshot, ReviewSnapshot) or requests != snapshot.requests:
        raise ValueError("description_review_invalid_requests")
    if not isinstance(requests, tuple) or not 1 <= len(requests) <= MAX_GROUPS:
        raise ValueError("description_review_invalid_requests")
    all_targets: list[dict[str, Any]] = []
    all_sources: dict[str, str] = {}
    try:
        for request in requests:
            if not isinstance(request, dict) or set(request) != {"targets", "sources"}:
                raise ValueError("invalid request")
            for source in request["sources"]:
                if (set(source) != {"ref", "text", "passage_id"}
                        or source["passage_id"] != _passage_id(source["ref"], source["text"])
                        or (source["ref"] in all_sources and all_sources[source["ref"]] != source["text"])):
                    raise ValueError("invalid source")
                all_sources[source["ref"]] = source["text"]
            all_targets.extend(request["targets"])
        if build_requests_v3(all_targets, all_sources).requests != requests:
            raise ValueError("invalid partition")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("description_review_invalid_requests") from exc
    if (not isinstance(responses, dict) or any(type(i) is not int or i < 0 or i >= len(requests)
                                                for i in responses)):
        return tuple(sorted((row["id"], "description_review_invalid")
                            for request in requests for row in request["targets"]))
    holds: list[tuple[str, str]] = []
    for index, request in enumerate(requests):
        holds.extend(_resolve_v3(request, responses.get(index)))
    return tuple(sorted(holds))


def _resolve_v3(request: dict[str, Any], response: Any) -> tuple[tuple[str, str], ...]:
    targets = {row["id"]: row for row in request["targets"]}
    passages = {row["passage_id"]: row["ref"] for row in request["sources"]}
    held = {tid: "description_review_unavailable" for tid in targets}
    if response is None:
        return tuple(sorted(held.items()))
    if (not isinstance(response, dict) or set(response) != {"rows"} or not isinstance(response["rows"], list)
            or len(response["rows"]) > MAX_TARGETS):
        return tuple((tid, "description_review_invalid") for tid in sorted(targets))
    seen: set[str] = set()
    for row in response["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("target_id"), str) or row["target_id"] not in targets:
            return tuple((tid, "description_review_invalid") for tid in sorted(targets))
        tid = row["target_id"]
        if tid in seen:
            held[tid] = "description_review_invalid"
            continue
        seen.add(tid)
        if set(row) != {"target_id", "relation", "reviewed_source_refs", "passage_ids"}:
            held[tid] = "description_review_invalid"
            continue
        relation, refs, ids = row["relation"], row["reviewed_source_refs"], row["passage_ids"]
        if (not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs)
                or len(refs) != len(set(refs)) or set(refs) != set(targets[tid]["source_refs"])
                or not isinstance(ids, list) or any(not isinstance(pid, str) for pid in ids)
                or len(ids) != len(set(ids))):
            held[tid] = "description_review_invalid"
        elif relation == "consistent" and not ids:
            held.pop(tid, None)  # Never an admission or semantic proof.
        elif relation == "unknown" and not ids:
            held[tid] = "description_review_unknown"
        elif (relation == "contradiction" and ids
                and all(pid in passages and passages[pid] in refs for pid in ids)):
            held[tid] = "description_source_contradiction"
        else:
            held[tid] = "description_review_invalid"
    return tuple(sorted(held.items()))
