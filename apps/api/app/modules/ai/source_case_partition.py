"""Pure syntactic custody for a two-existing-target material source fork.

This module proves only exact source spans, immutable fields, and obligation
ledger conservation.  It never decides whether an elided actor, action, or
condition semantically applies to either branch.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Any, NoReturn

from app.modules.ai.source_coordinator_boundary import prove_source_coordinator_boundary

_MATERIAL_EFFECTS = frozenset(
    {
        "changes_timing",
        "changes_recipient",
        "changes_outcome",
    }
)
_DIMENSION_EFFECT = {
    "timing": "changes_timing",
    "outcome": "changes_outcome",
}
_OBLIGATION_FIELDS = {"id", "ref", "quote", "dimension", "target_ids", "evidence_level"}
_COORDINATOR_SEPARATOR = re.compile(
    r"^[^\S\r\n]*[,;][^\S\r\n]*(?:а|и|но|либо|или)"
    r"(?:[^\S\r\n]+(?:также|затем|потом|далее|в[^\S\r\n]+дальнейшем|после[^\S\r\n]+этого))?"
    r"[^\S\r\n]+",
    re.IGNORECASE,
)
_COORDINATOR_SUFFIX = re.compile(
    r"^[^\S\r\n]*(?:а|и|но|либо|или)"
    r"(?:[^\S\r\n]+(?:также|затем|потом|далее|в[^\S\r\n]+дальнейшем|после[^\S\r\n]+этого))?"
    r"[^\S\r\n]+",
    re.IGNORECASE,
)


class SourceCasePartitionError(ValueError):
    """A proposed pair cannot be proved from immutable source custody."""

    def __init__(self, code: str, *, unresolved_operational_spans: Sequence[str] = ()) -> None:
        self.code = code
        self.unresolved_operational_spans = tuple(unresolved_operational_spans)
        super().__init__("source_case_partition_" + code)


@dataclass(frozen=True)
class ApplicationPartitionCustody:
    """Server-derived antecedent receipt; source bytes only, never semantic credit."""

    kind: str
    application_id: str
    owner_handle: str
    native_qualifier_handle: str
    predecessor_handle: str
    source_ref: str
    source_sha256: str
    fork_quote: str
    quote: str
    owner_target_ids: tuple[str, ...]
    branch_target_ids: tuple[str, ...]
    native_graph_sha256: str
    prelude_receipt_sha256: str


def _fail(code: str, *, unresolved_operational_spans: Sequence[str] = ()) -> NoReturn:
    raise SourceCasePartitionError(
        code,
        unresolved_operational_spans=unresolved_operational_spans,
    )


def _single_component(target: Mapping[str, Any], source_ref: str) -> str | None:
    groups = target.get("answer_components")
    if (
        not isinstance(groups, list)
        or len(groups) != 1
        or not isinstance(groups[0], Mapping)
        or groups[0].get("ref") != source_ref
    ):
        return None
    terms = groups[0].get("terms")
    if (
        not isinstance(terms, list)
        or len(terms) != 1
        or not isinstance(terms[0], str)
        or not terms[0]
        or terms[0] != terms[0].strip()
    ):
        return None
    return terms[0]


def _target_ids(value: Any, *, allow_empty: bool = False) -> tuple[str, ...] | None:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(target_id, str) or not target_id for target_id in value)
        or len(set(value)) != len(value)
    ):
        return None
    return tuple(value)


def _ordinary_target(target: Mapping[str, Any], source_ref: str) -> bool:
    return (
        target.get("source_refs") == [source_ref]
        and not target.get("construction_mode")
        and not target.get("question_format")
        and _single_component(target, source_ref) is not None
    )


def _material_forks(target: Mapping[str, Any], source_ref: str) -> list[dict[str, str]]:
    bindings = target.get("governing_bindings")
    if not isinstance(bindings, list):
        return []
    return [
        dict(binding)
        for binding in bindings
        if (
            isinstance(binding, Mapping)
            and binding.get("ref") == source_ref
            and isinstance(binding.get("quote"), str)
            and isinstance(binding.get("role"), str)
            and binding.get("branch_effect") in _MATERIAL_EFFECTS
            and set(binding) == {"ref", "quote", "role", "branch_effect"}
        )
    ]


def _pair_obligation_contract(
    obligations: Sequence[Mapping[str, Any]],
    pair: tuple[str, str],
    source_ref: str,
    fork_effect: str,
    *,
    singleton: bool,
) -> tuple[list[Mapping[str, Any]], dict[str, str]] | None:
    pair_set = set(pair)
    related = [
        row
        for row in obligations
        if isinstance(row, Mapping)
        and _target_ids(row.get("target_ids")) is not None
        and set(_target_ids(row["target_ids"]) or ()) & pair_set
    ]
    if len(related) != 2:
        return None
    for row in related:
        links = _target_ids(row.get("target_ids"))
        if (
            set(row) != _OBLIGATION_FIELDS
            or not all(isinstance(row.get(field), str) and row.get(field) for field in ("id", "quote", "dimension"))
            or row.get("ref") != source_ref
            or row.get("evidence_level") != "operational_decision"
            or links is None
            or not set(links) <= pair_set
            or (singleton and len(links) != 1)
        ):
            return None
    dimension = related[0]["dimension"]
    if (
        len({row["id"] for row in related}) != 2
        or {row["dimension"] for row in related} != {dimension}
        or _DIMENSION_EFFECT.get(dimension) != fork_effect
    ):
        return None
    if singleton:
        matching = {str(row["id"]): str(row["target_ids"][0]) for row in related}
        return (related, matching) if set(matching.values()) == pair_set else None
    matches = []
    left, right = pair
    for first, second in ((left, right), (right, left)):
        if first in related[0]["target_ids"] and second in related[1]["target_ids"]:
            matches.append({str(related[0]["id"]): first, str(related[1]["id"]): second})
    return (related, matches[0]) if len(matches) == 1 else None


def _exact_complementary_selector_pair(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    source_ref: str,
    source_text: str,
    local_fork: str | None = None,
) -> tuple[dict[str, str], dict[str, str], tuple[dict[str, str], ...]] | None:
    """Prove two literal selectors differ only by the inside/outside operator."""
    left_forks = _material_forks(left, source_ref)
    right_forks = _material_forks(right, source_ref)
    if len(left_forks) != 1 or len(right_forks) != 1:
        return None
    left_fork, right_fork = left_forks[0], right_forks[0]
    if (
        left_fork["role"] != right_fork["role"]
        or left_fork["branch_effect"] != right_fork["branch_effect"]
    ):
        return None

    selector_container = local_fork if local_fork is not None else source_text

    def selector_parts(binding: Mapping[str, str]) -> tuple[tuple[str, str, str], ...]:
        quote = binding["quote"]
        if selector_container.count(quote) != 1:
            return ()
        return tuple(
            (quote[: match.start()], match.group().casefold(), quote[match.end() :])
            for match in re.finditer(r"(?<!\w)(внутри|вне|в)(?!\w)", quote, re.IGNORECASE)
        )

    complements: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (left_parts, right_parts)
        for left_parts in selector_parts(left_fork)
        for right_parts in selector_parts(right_fork)
        if (
            (left_parts[1], right_parts[1]) in {("внутри", "вне"), ("вне", "внутри"), ("в", "вне"), ("вне", "в")}
            and left_parts[0] == right_parts[0]
            and left_parts[2] == right_parts[2]
        )
    ]
    boundary_pattern = re.compile(
        r"(?<!\w)(?:(вне)[^\S\r\n]+([^\W\d_]+)|(в)[^\S\r\n]+([^\W\d_]+ах))(?!\w)",
        re.IGNORECASE,
    )

    def boundary_parts(binding: Mapping[str, str]) -> tuple[tuple[str, str, str, str], ...]:
        quote = binding["quote"]
        if selector_container.count(quote) != 1:
            return ()
        parts = []
        for match in boundary_pattern.finditer(quote):
            if match.group(1) is not None:
                parts.append((quote[: match.start()], "outside", match.group(2).casefold(), quote[match.end() :]))
            else:
                noun = match.group(4)
                parts.append((quote[: match.start()], "inside", noun[:-2].casefold(), quote[match.end() :]))
        return tuple(parts)

    complements.extend(
        (left_parts, right_parts)
        for left_parts in boundary_parts(left_fork)
        for right_parts in boundary_parts(right_fork)
        if (
            {left_parts[1], right_parts[1]} == {"inside", "outside"}
            and left_parts[0] == right_parts[0]
            and left_parts[2] == right_parts[2]
            and left_parts[3] == right_parts[3]
        )
    )
    if len(complements) != 1:
        return None

    def exact_bindings(target: Mapping[str, Any]) -> tuple[dict[str, str], ...] | None:
        bindings = target.get("governing_bindings")
        if not isinstance(bindings, list) or not bindings:
            return None
        exact: list[dict[str, str]] = []
        for binding in bindings:
            if (
                not isinstance(binding, Mapping)
                or set(binding) != {"ref", "quote", "role", "branch_effect"}
                or binding.get("ref") != source_ref
                or not isinstance(binding.get("quote"), str)
                or not binding["quote"]
                or binding["quote"] != binding["quote"].strip()
                or not isinstance(binding.get("role"), str)
                or not binding["role"]
                or not isinstance(binding.get("branch_effect"), str)
                or selector_container.count(binding["quote"]) != 1
            ):
                return None
            normalized = dict(binding)
            if normalized in exact:
                return None
            exact.append(normalized)
        return tuple(exact)

    left_bindings = exact_bindings(left)
    right_bindings = exact_bindings(right)
    if left_bindings is None or right_bindings is None:
        return None
    left_common = tuple(binding for binding in left_bindings if binding != left_fork)
    right_common = tuple(binding for binding in right_bindings if binding != right_fork)
    if left_common != right_common:
        return None
    return left_fork, right_fork, left_common


def _singleton_pair_ledger(
    obligations: Sequence[Mapping[str, Any]],
    pair: tuple[str, str],
    source_ref: str,
) -> tuple[str, list[Mapping[str, Any]], dict[str, str]] | None:
    """Derive one structural effect from an unchanged singleton obligation ledger."""
    matches = []
    for effect in sorted(set(_DIMENSION_EFFECT.values())):
        contract = _pair_obligation_contract(
            obligations,
            pair,
            source_ref,
            effect,
            singleton=True,
        )
        if contract is not None:
            related, matching = contract
            matches.append((effect, related, matching))
    return matches[0] if len(matches) == 1 else None


def _exact_shared_nonmaterial_bindings(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    source_ref: str,
    source_text: str,
) -> tuple[dict[str, str], ...] | None:
    """Keep identical existing premises visible without granting fork ownership."""
    normalized: list[tuple[dict[str, str], ...]] = []
    for target in (left, right):
        bindings = target.get("governing_bindings")
        if not isinstance(bindings, list) or not bindings:
            return None
        exact: list[dict[str, str]] = []
        for binding in bindings:
            if (
                not isinstance(binding, Mapping)
                or set(binding) != {"ref", "quote", "role", "branch_effect"}
                or binding.get("ref") != source_ref
                or not isinstance(binding.get("quote"), str)
                or not binding["quote"]
                or binding["quote"] != binding["quote"].strip()
                or source_text.count(binding["quote"]) != 1
                or not isinstance(binding.get("role"), str)
                or not binding["role"]
                or not isinstance(binding.get("branch_effect"), str)
                or not binding["branch_effect"]
                or binding["branch_effect"] in _MATERIAL_EFFECTS
            ):
                return None
            row = dict(binding)
            if row in exact:
                return None
            exact.append(row)
        normalized.append(tuple(exact))
    return normalized[0] if normalized[0] == normalized[1] else None


def _virtual_selector_target(
    *,
    source_ref: str,
    quote: str,
    effect: str,
) -> dict[str, Any]:
    return {
        "governing_bindings": [
            {
                "ref": source_ref,
                "quote": quote,
                "role": "structural_selector",
                "branch_effect": effect,
            }
        ]
    }


def _embedded_selector_terms(
    *,
    source_ref: str,
    complete: str,
    seed_component: str,
    peer_component: str,
    peer_source_body: str,
    effect: str,
) -> dict[str, Any] | None:
    """Split one literal first branch and one actor-elided source tail exactly."""
    if not peer_source_body or not peer_component.endswith(peer_source_body):
        return None
    actor_join = peer_component[: -len(peer_source_body)]
    actor = actor_join[:-1] if actor_join.endswith(" ") else ""
    if not actor or actor != actor.strip() or not seed_component.startswith(f"{actor} ") or complete.count(actor) != 1:
        return None
    seed_body = seed_component[len(actor) + 1 :]
    peer_body = peer_source_body
    boundary = re.compile(
        r"(?<!\w)(?:(вне)[^\S\r\n]+([^\W\d_]+)|(в)[^\S\r\n]+([^\W\d_]+ах))(?!\w)",
        re.IGNORECASE,
    )
    seed_matches = list(boundary.finditer(seed_body))
    peer_matches = list(boundary.finditer(peer_body))
    if len(seed_matches) != 1 or len(peer_matches) != 1:
        return None
    seed_match, peer_match = seed_matches[0], peer_matches[0]

    def operator(match: re.Match[str]) -> tuple[str, str]:
        if match.group(1) is not None:
            return "outside", match.group(2).casefold()
        return "inside", match.group(4)[:-2].casefold()

    seed_operator, peer_operator = operator(seed_match), operator(peer_match)
    if (
        {seed_operator[0], peer_operator[0]} != {"inside", "outside"}
        or seed_operator[1] != peer_operator[1]
        or seed_body[: seed_match.start()] != peer_body[: peer_match.start()]
    ):
        return None
    seed_suffix, peer_suffix = seed_body[seed_match.end() :], peer_body[peer_match.end() :]
    size = 0
    while size < min(len(seed_suffix), len(peer_suffix)) and seed_suffix[size] == peer_suffix[size]:
        size += 1
    shared_object = seed_suffix[:size].rstrip()
    if (
        not shared_object
        or not shared_object[0].isspace()
        or not shared_object[-1].isalnum()
        or any(not (character.isalnum() or character.isspace() or character in "-‑–—") for character in shared_object)
    ):
        return None
    seed_selector = seed_body[: seed_match.end()] + shared_object
    peer_selector = peer_body[: peer_match.end()] + shared_object

    def outcome(remainder: str) -> tuple[str, bool] | None:
        start = 0
        while start < len(remainder) and (
            remainder[start].isspace() or unicodedata.category(remainder[start]).startswith("P")
        ):
            start += 1
        value = remainder[start:]
        if start == 0 or not value or value != value.strip() or len(value) > 240 or not value[0].isalnum():
            return None
        punctuation = any(unicodedata.category(character).startswith("P") for character in remainder[:start])
        return value, punctuation

    seed_result = outcome(seed_body[len(seed_selector) :])
    peer_result = outcome(peer_body[len(peer_selector) :])
    if seed_result is None or peer_result is None or seed_result[1] == peer_result[1]:
        return None
    seed_outcome, peer_outcome = seed_result[0], peer_result[0]
    if any(complete.count(value) != 1 for value in (seed_selector, peer_selector, seed_outcome, peer_outcome)):
        return None
    if _exact_complementary_selector_pair(
        _virtual_selector_target(source_ref=source_ref, quote=seed_selector, effect=effect),
        _virtual_selector_target(source_ref=source_ref, quote=peer_selector, effect=effect),
        source_ref=source_ref,
        source_text=complete,
        local_fork=complete,
    ) is None:
        return None
    result: dict[str, Any] = {
        "actor": actor,
        "seed_selector": seed_selector,
        "peer_selector": peer_selector,
        "seed_outcome": seed_outcome,
        "peer_outcome": peer_outcome,
    }
    # A timing fork may elide one exact predicate from its second source branch.
    # This is deliberately a narrow byte boundary, not a lemma or a semantic
    # inference: one lexical token precedes one single-token first-branch timing,
    # and that predicate is absent from the peer's literal source body.
    predicate_match = re.fullmatch(
        r"(?P<predicate>[^\W\d_]+)[^\S\r\n]+(?P<outcome>.+)",
        seed_outcome,
        re.UNICODE,
    )
    if effect == "changes_timing" and predicate_match is not None:
        predicate = predicate_match.group("predicate")
        projected_seed = predicate_match.group("outcome")
        core = _meaningful_core(projected_seed)
        explicit_peer = re.match(
            rf"(?i:{re.escape(predicate)})(?!\w)[^\S\r\n]+",
            peer_outcome,
        )
        if explicit_peer is not None:
            result["predicate_mode"] = "explicit_in_both"
        elif (
            core
            and not any(character.isspace() for character in core)
            and all(character.isalnum() or character in "-‑–—" for character in core)
            and complete.count(predicate) == 1
            and not re.search(rf"(?<!\w){re.escape(predicate)}(?!\w)", peer_body, re.IGNORECASE)
        ):
            result.update(
                {
                    "shared_predicate": predicate,
                    "seed_outcome": projected_seed,
                    "predicate_mode": "elided_from_peer",
                }
            )
    if effect == "changes_timing" and "predicate_mode" not in result:
        return None
    return result


def _embedded_projection_receipt(
    *,
    source_ref: str,
    source_text: str,
    complete: str,
    terms: Mapping[str, Any],
    seed: Mapping[str, Any],
    peer: Mapping[str, Any],
    related: Sequence[Mapping[str, Any]],
    matching: Mapping[str, str],
) -> dict[str, Any] | None:
    """Freeze one exact elided-predicate projection; never approve its meaning."""
    if terms.get("predicate_mode") != "elided_from_peer" or source_text.count(complete) != 1:
        return None
    seed_id, peer_id = seed.get("id"), peer.get("id")
    if not isinstance(seed_id, str) or not isinstance(peer_id, str) or seed_id == peer_id:
        return None
    common = _exact_shared_nonmaterial_bindings(
        seed,
        peer,
        source_ref=source_ref,
        source_text=source_text,
    )
    if common is None:
        return None
    fork_start = source_text.index(complete)

    def owned_span(quote: Any) -> dict[str, Any] | None:
        if not isinstance(quote, str):
            return None
        relative = _span_once(complete, quote)
        if relative is None:
            return None
        return {
            "quote": quote,
            "start": fork_start + relative[0],
            "end": fork_start + relative[1],
        }

    actor = owned_span(terms.get("actor"))
    predicate = owned_span(terms.get("shared_predicate"))
    selector_rows = [
        owned_span(terms.get("seed_selector")),
        owned_span(terms.get("peer_selector")),
    ]
    outcome_rows = [
        owned_span(terms.get("seed_outcome")),
        owned_span(terms.get("peer_outcome")),
    ]
    if actor is None or predicate is None or any(row is None for row in (*selector_rows, *outcome_rows)):
        return None
    assert selector_rows[0] is not None and selector_rows[1] is not None
    assert outcome_rows[0] is not None and outcome_rows[1] is not None
    held_contexts: list[list[dict[str, Any]]] = []
    for target in (seed, peer):
        context = target.get("context")
        if not isinstance(context, list) or any(
            not isinstance(row, Mapping)
            or set(row) != {"ref", "text"}
            or row.get("ref") != source_ref
            or not isinstance(row.get("text"), str)
            or not row["text"]
            for row in context
        ):
            return None
        normalized = [dict(row) for row in context]
        if len(normalized) != len({json.dumps(row, ensure_ascii=False, sort_keys=True) for row in normalized}):
            return None
        held_contexts.append(normalized)
    common_rows: list[dict[str, Any]] = []
    for binding in common:
        quote = binding["quote"]
        if source_text.count(quote) != 1:
            return None
        start = source_text.index(quote)
        common_rows.append({**binding, "start": start, "end": start + len(quote)})
    owner_links = [
        {"obligation_id": str(row["id"]), "target_id": str(matching.get(str(row["id"]), ""))}
        for row in related
    ]
    if (
        len(owner_links) != 2
        or {row["target_id"] for row in owner_links} != {seed_id, peer_id}
        or any(not row["obligation_id"] or not row["target_id"] for row in owner_links)
    ):
        return None
    selectors = [
        {**selector_rows[0], "target_id": seed_id},
        {**selector_rows[1], "target_id": peer_id},
    ]
    outcomes = [
        {**outcome_rows[0], "target_id": seed_id},
        {**outcome_rows[1], "target_id": peer_id},
    ]
    projections = []
    for target_id, held_context, selector, outcome in zip(
        (seed_id, peer_id),
        held_contexts,
        selectors,
        outcomes,
        strict=True,
    ):
        projected_context = [actor["quote"], predicate["quote"], selector["quote"]]
        required_rows = [{"ref": source_ref, "text": value} for value in projected_context]
        appended_context = [row for row in required_rows if row not in held_context]
        expected_context = [*held_context, *appended_context]
        if not 3 <= len(expected_context) <= 8:
            return None
        projections.append(
            {
                "target_id": target_id,
                "held_context": held_context,
                "projected_context": projected_context,
                "appended_context": appended_context,
                "expected_context": expected_context,
                "answer": outcome["quote"],
            }
        )
    body: dict[str, Any] = {
        "kind": "embedded_selector_predicate_projection",
        "version": 1,
        "source_ref": source_ref,
        "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
        "fork_quote": complete,
        "fork_start": fork_start,
        "fork_end": fork_start + len(complete),
        "fork_sha256": hashlib.sha256(complete.encode()).hexdigest(),
        "actor": actor,
        "shared_predicate": {
            **predicate,
            "elided_target_ids": [peer_id],
        },
        "selectors": selectors,
        "outcomes": outcomes,
        "common_bindings": common_rows,
        "owner_links": owner_links,
        "projections": projections,
        "semantic_approval": False,
    }
    body["receipt_sha256"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return body


def _validate_embedded_projection(
    *,
    receipt: Any,
    source_ref: str,
    source_text: str,
    pair: tuple[str, str],
    obligation_ids: tuple[str, str],
    matching: Mapping[str, str],
    held_by_id: Mapping[str, Mapping[str, Any]],
    proposed_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    """Accept exactly the server-derived projection and no byte-cover substitute."""
    if not isinstance(receipt, Mapping):
        _fail("embedded_projection")
    body = dict(receipt)
    digest = body.pop("receipt_sha256", None)
    expected_digest = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    expected_links = [
        {"obligation_id": obligation_id, "target_id": matching[obligation_id]}
        for obligation_id in obligation_ids
    ]
    projections = receipt.get("projections")
    if (
        receipt.get("kind") != "embedded_selector_predicate_projection"
        or receipt.get("version") != 1
        or receipt.get("source_ref") != source_ref
        or receipt.get("source_sha256") != hashlib.sha256(source_text.encode()).hexdigest()
        or receipt.get("semantic_approval") is not False
        or digest != expected_digest
        or receipt.get("owner_links") != expected_links
        or not isinstance(projections, list)
        or len(projections) != 2
        or [row.get("target_id") for row in projections if isinstance(row, Mapping)] != list(pair)
    ):
        _fail("embedded_projection")
    for projection in projections:
        if not isinstance(projection, Mapping):
            _fail("embedded_projection")
        target_id = projection["target_id"]
        held = held_by_id.get(target_id)
        proposed = proposed_by_id.get(target_id)
        projected_context = projection.get("projected_context")
        appended_context = projection.get("appended_context")
        expected_context = projection.get("expected_context")
        if (
            held is None
            or proposed is None
            or projection.get("held_context") != held.get("context")
            or not isinstance(projected_context, list)
            or len(projected_context) != 3
            or any(not isinstance(value, str) or not value for value in projected_context)
            or not isinstance(appended_context, list)
            or not isinstance(expected_context, list)
        ):
            _fail("embedded_projection")
        required_rows = [{"ref": source_ref, "text": value} for value in projected_context]
        expected_appended = [row for row in required_rows if row not in projection["held_context"]]
        expected_final = [*projection["held_context"], *expected_appended]
        expected_answers = [{"ref": source_ref, "terms": [projection.get("answer")]}]
        if (
            appended_context != expected_appended
            or expected_context != expected_final
            or proposed.get("context") != expected_final
            or proposed.get("answer_components") != expected_answers
        ):
            _fail("embedded_projection")


def _embedded_elided_predicate_cohort(
    *,
    source_ref: str,
    source_text: str,
    seed_target_id: str,
    targets: Sequence[Mapping[str, Any]],
    obligations: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]] | None:
    """Re-derive the exact server projection from learner-visible target fields."""
    by_id = {row.get("id"): row for row in targets if isinstance(row, Mapping)}
    seed = by_id.get(seed_target_id)
    if seed is None or len(by_id) != len(targets) or not _ordinary_target(seed, source_ref):
        return None
    matches: list[tuple[list[Mapping[str, Any]], dict[str, Any]]] = []
    for peer_id, peer in by_id.items():
        if (
            peer_id == seed_target_id
            or not isinstance(peer_id, str)
            or not _ordinary_target(peer, source_ref)
            or _material_forks(seed, source_ref)
            or _material_forks(peer, source_ref)
        ):
            continue
        common = _exact_shared_nonmaterial_bindings(
            seed,
            peer,
            source_ref=source_ref,
            source_text=source_text,
        )
        ledger = _singleton_pair_ledger(
            obligations,
            (seed_target_id, peer_id),
            source_ref,
        )
        if common is None or ledger is None or ledger[0] != "changes_timing":
            continue
        effect = ledger[0]
        context_sets: list[set[str]] = []
        context_orders: list[list[str]] = []
        for target in (seed, peer):
            rows = target.get("context")
            if (
                not isinstance(rows, list)
                or not 3 <= len(rows) <= 8
                or any(
                    not isinstance(row, Mapping)
                    or set(row) != {"ref", "text"}
                    or row.get("ref") != source_ref
                    or not isinstance(row.get("text"), str)
                    or not row["text"]
                    or row["text"] != row["text"].strip()
                    for row in rows
                )
            ):
                context_sets = []
                break
            ordered = [str(row["text"]) for row in rows]
            if len(set(ordered)) != len(ordered):
                context_sets = []
                break
            context_orders.append(ordered)
            context_sets.append(set(ordered))
        if len(context_sets) != 2:
            continue
        shared = context_sets[0] & context_sets[1]
        if len(shared) < 2:
            continue
        seed_answer = _single_component(seed, source_ref)
        peer_answer = _single_component(peer, source_ref)
        if seed_answer is None or peer_answer is None:
            continue
        local_matches: list[dict[str, Any]] = []
        for actor in (value for value in context_orders[0] if value in shared):
            for predicate in (value for value in context_orders[0] if value in shared and value != actor):
                for seed_selector in (value for value in context_orders[0] if value not in {actor, predicate}):
                    for peer_selector in (value for value in context_orders[1] if value not in {actor, predicate}):
                        seed_component = f"{actor} {seed_selector} {predicate} {seed_answer}"
                        boundary = prove_source_coordinator_boundary(source_text, seed_component)
                        if boundary is None or source_text.count(seed_component) != 1:
                            continue
                        separator_tail_end = boundary.separator_end - boundary.component_end
                        if not 0 < separator_tail_end < len(boundary.raw_tail):
                            continue
                        peer_source_body = boundary.raw_tail[separator_tail_end:]
                        peer_component = f"{actor} {peer_source_body}"
                        complete = seed_component + boundary.raw_tail
                        terms = _embedded_selector_terms(
                            source_ref=source_ref,
                            complete=complete,
                            seed_component=seed_component,
                            peer_component=peer_component,
                            peer_source_body=peer_source_body,
                            effect=effect,
                        )
                        if (
                            terms is None
                            or terms.get("predicate_mode") != "elided_from_peer"
                            or terms.get("actor") != actor
                            or terms.get("shared_predicate") != predicate
                            or terms.get("seed_selector") != seed_selector
                            or terms.get("peer_selector") != peer_selector
                            or terms.get("seed_outcome") != seed_answer
                            or terms.get("peer_outcome") != peer_answer
                        ):
                            continue
                        local_matches.append(
                            {
                                "ref": source_ref,
                                "quote": complete,
                                "role": "structural_selector_pair",
                                "branch_effect": effect,
                                "structural_context_credit": (actor, predicate),
                                "structural_binding_credit": tuple(
                                    binding["quote"]
                                    for binding in common
                                    if (
                                        complete.count(binding["quote"]) == 1
                                        and binding["role"] in {"actor", "condition"}
                                        and binding["branch_effect"] in {"none", "scopes_action"}
                                    )
                                ),
                            }
                        )
        if len(local_matches) == 1:
            matches.append(([seed, peer], local_matches[0]))
    return matches[0] if len(matches) == 1 else None


def _embedded_reprojected_cohort(
    *,
    source_ref: str,
    source_text: str,
    seed_target_id: str,
    targets: Sequence[Mapping[str, Any]],
    obligations: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]] | None:
    """Adapt exact context selectors to the existing material-fork prover."""
    elided = _embedded_elided_predicate_cohort(
        source_ref=source_ref,
        source_text=source_text,
        seed_target_id=seed_target_id,
        targets=targets,
        obligations=obligations,
    )
    if elided is not None:
        return elided
    by_id = {row.get("id"): row for row in targets if isinstance(row, Mapping)}
    seed = by_id.get(seed_target_id)
    if seed is None or len(by_id) != len(targets) or not _ordinary_target(seed, source_ref):
        return None
    matches: list[tuple[list[Mapping[str, Any]], dict[str, Any]]] = []
    for peer_id, peer in by_id.items():
        if (
            peer_id == seed_target_id
            or not isinstance(peer_id, str)
            or not _ordinary_target(peer, source_ref)
            or _material_forks(seed, source_ref)
            or _material_forks(peer, source_ref)
            or _exact_shared_nonmaterial_bindings(
                seed,
                peer,
                source_ref=source_ref,
                source_text=source_text,
            ) is None
        ):
            continue
        ledger = _singleton_pair_ledger(
            obligations,
            (seed_target_id, peer_id),
            source_ref,
        )
        if ledger is None:
            continue
        effect, _, _ = ledger
        contexts: list[set[str]] = []
        for target in (seed, peer):
            rows = target.get("context")
            if (
                not isinstance(rows, list)
                or len(rows) != 2
                or any(
                    not isinstance(row, Mapping)
                    or set(row) != {"ref", "text"}
                    or row.get("ref") != source_ref
                    or not isinstance(row.get("text"), str)
                    or not row["text"]
                    or row["text"] != row["text"].strip()
                    for row in rows
                )
            ):
                contexts = []
                break
            texts = {str(row["text"]) for row in rows}
            if len(texts) != 2:
                contexts = []
                break
            contexts.append(texts)
        if len(contexts) != 2:
            continue
        shared = contexts[0] & contexts[1]
        seed_only = contexts[0] - shared
        peer_only = contexts[1] - shared
        if len(shared) != 1 or len(seed_only) != 1 or len(peer_only) != 1:
            continue
        actor = next(iter(shared))
        seed_selector = next(iter(seed_only))
        peer_selector = next(iter(peer_only))
        seed_answer = _single_component(seed, source_ref)
        peer_answer = _single_component(peer, source_ref)
        local_prefix = f"{actor} {seed_selector}"
        if (
            seed_answer is None
            or peer_answer is None
            or source_text.count(local_prefix) != 1
            or source_text.count(seed_answer) != 1
            or source_text.count(peer_answer) != 1
        ):
            continue
        local_start = source_text.index(local_prefix)
        local_end = source_text.index(peer_answer) + len(peer_answer)
        if local_start >= local_end:
            continue
        local_source = source_text[local_start:local_end]
        if "\r" in local_source or "\n" in local_source or source_text.count(local_source) != 1:
            continue
        selector_rows = (
            _virtual_selector_target(
                source_ref=source_ref,
                quote=seed_selector,
                effect=effect,
            )["governing_bindings"],
            _virtual_selector_target(
                source_ref=source_ref,
                quote=peer_selector,
                effect=effect,
            )["governing_bindings"],
        )
        adapted = [
            {**dict(target), "governing_bindings": selector_rows[index]}
            for index, target in enumerate((seed, peer))
        ]
        proved = _fork_cohort(
            source_ref=source_ref,
            source_text=local_source,
            seed_target_id=seed_target_id,
            targets=adapted,
            obligations=obligations,
        )
        if proved is None:
            continue
        cohort, fork = proved
        quote = str(fork["quote"])
        if not quote.startswith(f"{actor} "):
            quote = f"{actor} {quote}"
        if local_source != quote or source_text.count(quote) != 1:
            continue
        matches.append(
            (
                cohort,
                {
                    **fork,
                    "quote": quote,
                    "role": "structural_selector_pair",
                    "structural_context_credit": tuple(
                        dict.fromkeys((*fork.get("structural_context_credit", ()), actor))
                    ),
                },
            )
        )
    if len(matches) != 1:
        return None
    return matches[0]


def _complementary_ellipsis_discovery(
    *,
    source_ref: str,
    source_text: str,
    seed: Mapping[str, Any],
    peers: Sequence[Mapping[str, Any]],
    seed_component: str,
    physical_tail: str,
) -> tuple[Mapping[str, Any], dict[str, str]] | None:
    """Recognize one exact elided branch without approving inherited meaning."""
    matches: list[tuple[Mapping[str, Any], dict[str, str]]] = []
    complete = seed_component + physical_tail
    complete_start = source_text.index(complete)
    for peer in peers:
        seed_forks = _material_forks(seed, source_ref)
        peer_forks = _material_forks(peer, source_ref)
        if len(seed_forks) != 1 or len(peer_forks) != 1:
            continue
        seed_bindings = seed.get("governing_bindings")
        peer_bindings = peer.get("governing_bindings")
        if not isinstance(seed_bindings, list) or not isinstance(peer_bindings, list):
            continue
        seed_common = [dict(row) for row in seed_bindings if isinstance(row, Mapping) and dict(row) != seed_forks[0]]
        peer_common = [dict(row) for row in peer_bindings if isinstance(row, Mapping) and dict(row) != peer_forks[0]]
        if seed_common != peer_common:
            continue
        common_spans: list[tuple[int, int]] = []
        for binding in seed_common:
            quote = binding.get("quote")
            if not isinstance(quote, str) or source_text.count(quote) != 1:
                common_spans = []
                break
            start = source_text.index(quote)
            common_spans.append((start, start + len(quote)))
        if seed_common and not common_spans:
            continue
        local_start = min([complete_start, *(span[0] for span in common_spans)])
        local_end = max([complete_start + len(complete), *(span[1] for span in common_spans)])
        local_fork = source_text[local_start:local_end]
        selector_pair = _exact_complementary_selector_pair(
            seed,
            peer,
            source_ref=source_ref,
            source_text=source_text,
            local_fork=local_fork,
        )
        if selector_pair is None:
            continue
        seed_selector, peer_selector, common = selector_pair
        peer_component = _single_component(peer, source_ref)
        if peer_component is None or source_text.count(peer_component) != 0:
            continue

        # Fully enumerated synthetic shape: both projected components contain
        # the same exact actor and predicate, while the source tail owns the
        # peer outcome and a separately bound exact purpose.
        actor_bindings = [
            row for row in common if row["role"] == "actor" and row["branch_effect"] == "none"
        ]
        separator = _COORDINATOR_SEPARATOR.match(physical_tail)
        if separator is None:
            continue
        remainder = physical_tail[separator.end() :]
        if not remainder.startswith(peer_selector["quote"]):
            continue
        source_peer_suffix = remainder[len(peer_selector["quote"]) :]
        synthetic_shape = False
        if len(actor_bindings) == 1:
            actor = actor_bindings[0]["quote"]
            predicate_candidates = [
                row
                for row in common
                if row["role"] == "scope"
                and row["branch_effect"] == "none"
                and seed_component.startswith(f'{actor} {seed_selector["quote"]} {row["quote"]} ')
                and peer_component.startswith(f'{actor} {peer_selector["quote"]} {row["quote"]} ')
            ]
            if len(predicate_candidates) == 1:
                predicate = predicate_candidates[0]["quote"]
                seed_prefix = f'{actor} {seed_selector["quote"]} {predicate} '
                peer_prefix = f'{actor} {peer_selector["quote"]} {predicate} '
                seed_outcome = seed_component[len(seed_prefix) :]
                peer_outcome = peer_component[len(peer_prefix) :]
                purpose_candidates = [
                    row
                    for row in common
                    if row != predicate_candidates[0]
                    and row["role"] == "scope"
                    and row["branch_effect"] == "none"
                    and physical_tail.endswith(row["quote"])
                ]
                if (
                    seed_outcome
                    and peer_outcome
                    and seed_outcome == seed_outcome.strip()
                    and peer_outcome == peer_outcome.strip()
                    and source_text.count(seed_outcome) == 1
                    and source_text.count(peer_outcome) == 1
                    and len(purpose_candidates) == 1
                ):
                    purpose = purpose_candidates[0]["quote"]
                    outcome_at = source_peer_suffix.find(peer_outcome)
                    after_outcome = source_peer_suffix[outcome_at + len(peer_outcome) :] if outcome_at >= 0 else ""
                    purpose_at = after_outcome.find(purpose)
                    synthetic_shape = (
                        outcome_at >= 1
                        and _punctuation_or_space(source_peer_suffix[:outcome_at])
                        and purpose_at >= 1
                        and _punctuation_or_space(after_outcome[:purpose_at])
                        and after_outcome[purpose_at:] == purpose
                    )

        # Saved native shape: the peer component repeats only the exact actor
        # prefix and then copies the source-owned selector tail byte-for-byte.
        seed_selector_at = seed_component.find(seed_selector["quote"])
        peer_selector_at = peer_component.find(peer_selector["quote"])
        projected_tail_shape = False
        if seed_selector_at > 0 and peer_selector_at > 0:
            seed_actor = seed_component[:seed_selector_at].rstrip()
            peer_actor = peer_component[:peer_selector_at].rstrip()
            peer_suffix = peer_component[peer_selector_at + len(peer_selector["quote"]) :]
            projected_tail_shape = (
                bool(seed_actor)
                and seed_actor == peer_actor
                and local_fork.count(seed_actor) == 1
                and bool(seed_component[seed_selector_at + len(seed_selector["quote"]) :])
                and peer_suffix == source_peer_suffix
            )
        if not synthetic_shape and not projected_tail_shape:
            continue
        matches.append((peer, seed_selector))
    return matches[0] if len(matches) == 1 else None


def discover_existing_pair_partition_operation(
    *,
    source_ref: str,
    source_id: str,
    source_text: str,
    invalid_target_ids: Set[str],
    targets: Sequence[Mapping[str, Any]],
    obligations: Sequence[Mapping[str, Any]],
    seed_target_id: str,
    seed_component: str,
    physical_tail: str,
    metadata_context: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Discover one structural cohort without proposing its repaired meaning."""
    if (
        not all(isinstance(value, str) and value for value in (source_ref, source_id, source_text))
        or not isinstance(invalid_target_ids, Set)
        or not isinstance(targets, Sequence)
        or isinstance(targets, str | bytes)
        or not isinstance(obligations, Sequence)
        or isinstance(obligations, str | bytes)
        or not isinstance(seed_component, str)
        or not seed_component
        or seed_component != seed_component.strip()
        or not isinstance(physical_tail, str)
        or "\n" in physical_tail
        or "\r" in physical_tail
    ):
        return None
    boundary = prove_source_coordinator_boundary(source_text, seed_component)
    if boundary is None or boundary.raw_tail != physical_tail:
        return None
    complete = seed_component + physical_tail
    if source_text.count(seed_component) != 1 or source_text.count(complete) != 1:
        return None
    by_id = {
        target.get("id"): target
        for target in targets
        if isinstance(target, Mapping) and isinstance(target.get("id"), str)
    }
    if len(by_id) != len(targets):
        return None
    seed = by_id.get(seed_target_id)
    if (
        seed is None
        or seed_target_id not in invalid_target_ids
        or not _ordinary_target(seed, source_ref)
        or _single_component(seed, source_ref) != seed_component
    ):
        return None
    seed_forks = _material_forks(seed, source_ref)
    peer: Mapping[str, Any] | None = None
    embedded_selector_partition = False
    embedded_projection_receipt: dict[str, Any] | None = None
    legacy_fork = False
    if len(seed_forks) == 1:
        fork = seed_forks[0]
        fork_quote = fork["quote"]
        cohort = [
            target
            for target_id, target in by_id.items()
            if (
                target_id in invalid_target_ids
                and _ordinary_target(target, source_ref)
                and _material_forks(target, source_ref) == [fork]
            )
        ]
        legacy_fork = (
            0 < len(fork_quote) <= 4096
            and source_text.count(fork_quote) == 1
            and fork_quote.count(complete) == 1
            and len(cohort) == 2
            and seed in cohort
        )
        if legacy_fork:
            peer = next(target for target in cohort if target is not seed)
        else:
            complementary = _complementary_ellipsis_discovery(
                source_ref=source_ref,
                source_text=source_text,
                seed=seed,
                peers=[
                    target
                    for target_id, target in by_id.items()
                    if target_id != seed_target_id
                    and target_id in invalid_target_ids
                    and _ordinary_target(target, source_ref)
                ],
                seed_component=seed_component,
                physical_tail=physical_tail,
            )
            if complementary is None:
                return None
            peer, fork = complementary
    elif not seed_forks:
        separator_tail_end = boundary.separator_end - boundary.component_end
        if not 0 < separator_tail_end < len(physical_tail):
            return None
        peer_source_body = physical_tail[separator_tail_end:]
        matches: list[
            tuple[
                Mapping[str, Any],
                dict[str, Any],
                list[Mapping[str, Any]],
                dict[str, str],
                dict[str, Any] | None,
            ]
        ] = []
        for candidate_id, candidate in by_id.items():
            if (
                candidate_id == seed_target_id
                or candidate_id not in invalid_target_ids
                or not _ordinary_target(candidate, source_ref)
                or _material_forks(candidate, source_ref)
                or _exact_shared_nonmaterial_bindings(
                    seed,
                    candidate,
                    source_ref=source_ref,
                    source_text=source_text,
                ) is None
            ):
                continue
            pair = (seed_target_id, str(candidate_id))
            ledger = _singleton_pair_ledger(obligations, pair, source_ref)
            if ledger is None:
                continue
            effect, related, matching = ledger
            peer_component = _single_component(candidate, source_ref)
            if peer_component is None or source_text.count(peer_component) != 0:
                continue
            terms = _embedded_selector_terms(
                source_ref=source_ref,
                complete=complete,
                seed_component=seed_component,
                peer_component=peer_component,
                peer_source_body=peer_source_body,
                effect=effect,
            )
            if terms is None:
                continue
            adapted_seed = {
                **dict(seed),
                **_virtual_selector_target(
                    source_ref=source_ref,
                    quote=terms["seed_selector"],
                    effect=effect,
                ),
            }
            adapted_peer = {
                **dict(candidate),
                **_virtual_selector_target(
                    source_ref=source_ref,
                    quote=terms["peer_selector"],
                    effect=effect,
                ),
            }
            discovery_seed = seed_component
            discovery_tail = physical_tail
            if boundary.punctuation_owner == "component":
                discovery_seed = seed_component[:-1]
                discovery_tail = seed_component[-1] + physical_tail
            discovered = _complementary_ellipsis_discovery(
                source_ref=source_ref,
                source_text=source_text,
                seed=adapted_seed,
                peers=[adapted_peer],
                seed_component=discovery_seed,
                physical_tail=discovery_tail,
            )
            if discovered is None:
                continue
            projection_receipt = _embedded_projection_receipt(
                source_ref=source_ref,
                source_text=source_text,
                complete=complete,
                terms=terms,
                seed=seed,
                peer=candidate,
                related=related,
                matching=matching,
            )
            if terms.get("predicate_mode") == "elided_from_peer" and projection_receipt is None:
                continue
            matches.append(
                (
                    candidate,
                    {
                        "ref": source_ref,
                        "quote": complete,
                        "role": "structural_selector_pair",
                        "branch_effect": effect,
                    },
                    related,
                    matching,
                    projection_receipt,
                )
            )
        if len(matches) != 1:
            return None
        peer, fork, related, matching, embedded_projection_receipt = matches[0]
        embedded_selector_partition = True
    else:
        return None
    pair = (seed_target_id, str(peer["id"]))
    if not embedded_selector_partition:
        pair_contract = _pair_obligation_contract(
            obligations,
            pair,
            source_ref,
            fork["branch_effect"],
            singleton=not legacy_fork,
        )
        if pair_contract is None:
            return None
        related, matching = pair_contract
    metadata = []
    for value in metadata_context:
        if not isinstance(value, str) or not value or value != value.strip() or value in metadata:
            return None
        metadata.append(value)
    return {
        "kind": "lossless_component_partition",
        "scope": "existing_pair_case_reprojection",
        "source_ref": source_ref,
        "source_id": source_id,
        "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
        "fork_binding": fork,
        "target_ids": list(pair),
        "obligation_ids": [str(row["id"]) for row in related],
        "obligation_target_matching": matching,
        "seed_target_id": seed_target_id,
        "held_seed_component": seed_component,
        "physical_tail": physical_tail,
        "metadata_context": metadata,
        "allowed_target_changes": ["answer_components", "context"],
        "server_derives_obligation_quotes_and_links": True,
        **({"embedded_selector_partition": True} if embedded_selector_partition else {}),
        **(
            {"embedded_projection_receipt": embedded_projection_receipt}
            if embedded_projection_receipt is not None
            else {}
        ),
        "semantic_approval": False,
    }


def _fork_cohort(
    *,
    source_ref: str,
    source_text: str,
    seed_target_id: str,
    targets: Sequence[Mapping[str, Any]],
    obligations: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]] | None:
    by_id = {row.get("id"): row for row in targets if isinstance(row, Mapping) and isinstance(row.get("id"), str)}
    if len(by_id) != len(targets) or seed_target_id not in by_id:
        return None
    seed = by_id[seed_target_id]
    if not _ordinary_target(seed, source_ref):
        return None
    forks = _material_forks(seed, source_ref)
    if not forks:
        return _embedded_reprojected_cohort(
            source_ref=source_ref,
            source_text=source_text,
            seed_target_id=seed_target_id,
            targets=targets,
            obligations=obligations,
        )
    if len(forks) != 1:
        return None
    fork = forks[0]
    quote = fork["quote"]
    cohort = [
        row for row in targets if _ordinary_target(row, source_ref) and _material_forks(row, source_ref) == [fork]
    ]
    if 0 < len(quote) <= 4096 and source_text.count(quote) == 1 and len(cohort) == 2 and seed in cohort:
        return cohort, fork
    complementary: list[tuple[Mapping[str, Any], dict[str, str], str]] = []
    for peer in targets:
        if peer is seed or not _ordinary_target(peer, source_ref):
            continue
        common_bindings = [
            dict(binding)
            for binding in seed.get("governing_bindings", [])
            if isinstance(binding, Mapping) and dict(binding) not in forks
        ]
        anchors: list[tuple[int, int]] = []
        for binding in common_bindings:
            binding_quote = binding.get("quote")
            if not isinstance(binding_quote, str) or source_text.count(binding_quote) != 1:
                anchors = []
                break
            start = source_text.index(binding_quote)
            anchors.append((start, start + len(binding_quote)))
        if common_bindings and not anchors:
            continue
        for target in (seed, peer):
            answer = _single_component(target, source_ref)
            if answer is None or source_text.count(answer) != 1:
                anchors = []
                break
            start = source_text.index(answer)
            anchors.append((start, start + len(answer)))
            contexts = target.get("context")
            if not isinstance(contexts, list):
                anchors = []
                break
            for row in contexts:
                if not isinstance(row, Mapping) or row.get("ref") != source_ref:
                    continue
                text = row.get("text")
                if isinstance(text, str) and source_text.count(text) == 1:
                    context_start = source_text.index(text)
                    anchors.append((context_start, context_start + len(text)))
        if not anchors:
            continue
        local_start = min(span[0] for span in anchors)
        local_end = max(span[1] for span in anchors)
        local_fork = source_text[local_start:local_end]
        selector_pair = _exact_complementary_selector_pair(
            seed,
            peer,
            source_ref=source_ref,
            source_text=source_text,
            local_fork=local_fork,
        )
        if selector_pair is not None:
            complementary.append((peer, selector_pair[0], local_fork))
    if len(complementary) != 1:
        return None
    peer, seed_selector, quote = complementary[0]
    peer_selector = _material_forks(peer, source_ref)[0]
    seed_answer = _single_component(seed, source_ref)
    peer_answer = _single_component(peer, source_ref)
    seed_selector_span = _span_once(quote, seed_selector["quote"])
    peer_selector_span = _span_once(quote, peer_selector["quote"])
    seed_answer_span = _span_once(quote, seed_answer or "")
    peer_answer_span = _span_once(quote, peer_answer or "")
    if (
        not quote
        or len(quote) > 4096
        or seed_selector_span is None
        or peer_selector_span is None
        or seed_answer_span is None
        or peer_answer_span is None
        or not (
            seed_selector_span[1] <= seed_answer_span[0]
            < peer_selector_span[0]
            and peer_selector_span[1] <= peer_answer_span[0]
        )
    ):
        return None
    common_spans = [
        _span_once(quote, str(binding.get("quote", "")))
        for binding in seed.get("governing_bindings", [])
        if isinstance(binding, Mapping) and dict(binding) != seed_selector
    ]
    if any(span is None for span in common_spans):
        return None
    prior_end = max(
        (span[1] for span in common_spans if span is not None and span[1] <= seed_selector_span[0]),
        default=0,
    )
    contexts_by_target = []
    for target in (seed, peer):
        contexts = target.get("context")
        if not isinstance(contexts, list):
            return None
        contexts_by_target.append(
            {
                row["text"]
                for row in contexts
                if isinstance(row, Mapping)
                and row.get("ref") == source_ref
                and isinstance(row.get("text"), str)
            }
        )
    shared_contexts = set.intersection(*contexts_by_target)

    def exact_gap_owner(gap: str) -> str | None:
        matches = []
        for value in shared_contexts:
            span = _span_once(gap, value)
            if (
                span is not None
                and _punctuation_or_space(gap[: span[0]])
                and _punctuation_or_space(gap[span[1] :])
            ):
                matches.append(value)
        return matches[0] if len(matches) == 1 else None

    structural_contexts = tuple(
        exact_gap_owner(gap)
        for gap in (
            quote[prior_end : seed_selector_span[0]],
            quote[seed_selector_span[1] : seed_answer_span[0]],
            quote[peer_answer_span[1] :],
        )
    )
    if (
        any(value is None for value in structural_contexts)
        or len(set(structural_contexts)) != 3
        or any(quote.count(value) != 1 for value in structural_contexts if value is not None)
    ):
        structural_contexts = ()
    custody_fork = {
        "ref": source_ref,
        "quote": quote,
        "role": seed_selector["role"],
        "branch_effect": seed_selector["branch_effect"],
        "structural_context_credit": structural_contexts,
        "structural_binding_credit": tuple(
            binding["quote"]
            for binding in seed.get("governing_bindings", [])
            if (
                isinstance(binding, Mapping)
                and dict(binding) != seed_selector
                and binding in peer.get("governing_bindings", [])
                and binding.get("role") in {"actor", "condition"}
                and binding.get("branch_effect") in {"none", "scopes_action"}
            )
        ),
    }
    return [seed, peer], custody_fork


def _span_once(container: str, quote: str) -> tuple[int, int] | None:
    if not quote or container.count(quote) != 1:
        return None
    start = container.index(quote)
    return start, start + len(quote)


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _punctuation_or_space(value: str) -> bool:
    return all(character.isspace() or unicodedata.category(character).startswith("P") for character in value)


def _meaningful_core(value: str) -> str:
    start, end = 0, len(value)
    while start < end and (value[start].isspace() or unicodedata.category(value[start]).startswith("P")):
        start += 1
    while end > start and (value[end - 1].isspace() or unicodedata.category(value[end - 1]).startswith("P")):
        end -= 1
    return value[start:end]


def _application_partition_spans(*, fork_quote: str, source_text: str, source_ref: str,
        pair_targets: Sequence[Mapping[str, Any]], all_targets: Sequence[Mapping[str, Any]],
        answer_spans: Sequence[tuple[int, int]], context_spans: Sequence[tuple[int, int]],
        support_spans: Sequence[tuple[int, int]],
        receipts: tuple[ApplicationPartitionCustody, ...]) -> tuple[bool, tuple[tuple[int, int], ...]]:
    """Validate matching server receipts and return only their zero-credit byte spans."""
    if type(receipts) is not tuple or len(receipts) > 512 or any(not isinstance(row, ApplicationPartitionCustody) for row in receipts):
        return False, ()
    matching = [row for row in receipts if row.source_ref == source_ref and row.fork_quote == fork_quote]
    if not matching:
        return True, ()
    pair_ids = {str(target["id"]) for target in pair_targets}
    target_by_id = {str(target.get("id")): target for target in all_targets if isinstance(target, Mapping)}
    source_sha256 = hashlib.sha256(source_text.encode()).hexdigest()
    graph_hashes: set[str] = set()
    application_ids: set[str] = set()
    spans: list[tuple[int, int]] = []

    def valid_id(value: Any) -> bool:
        return isinstance(value, str) and bool(value) and len(value) <= 256

    def valid_sha256(value: Any) -> bool:
        return (isinstance(value, str) and len(value) == 64
                and all(character in "0123456789abcdef" for character in value))

    for receipt in matching:
        ids = (receipt.application_id, receipt.owner_handle, receipt.native_qualifier_handle,
               receipt.predecessor_handle, receipt.source_ref)
        if (receipt.kind != "antecedent_reference" or any(not valid_id(value) for value in ids)
                or receipt.owner_handle == receipt.predecessor_handle
                or receipt.source_sha256 != source_sha256
                or not valid_sha256(receipt.native_graph_sha256)
                or not valid_sha256(receipt.prelude_receipt_sha256)
                or receipt.application_id in application_ids
                or type(receipt.owner_target_ids) is not tuple or type(receipt.branch_target_ids) is not tuple
                or not receipt.owner_target_ids or len(receipt.owner_target_ids) > 96
                or any(not valid_id(value) for value in (*receipt.owner_target_ids, *receipt.branch_target_ids))
                or len(set(receipt.owner_target_ids)) != len(receipt.owner_target_ids)
                or len(set(receipt.branch_target_ids)) != len(receipt.branch_target_ids)
                or set(receipt.branch_target_ids) != pair_ids or not pair_ids <= set(receipt.owner_target_ids)
                or not isinstance(receipt.quote, str) or not receipt.quote or len(receipt.quote) > 4096
                or source_text.count(receipt.quote) != 1 or fork_quote.count(receipt.quote) != 1):
            return False, ()
        owners = [target_by_id.get(target_id) for target_id in receipt.owner_target_ids]
        expected = {"ref": source_ref, "quote": receipt.quote, "role": "scope", "branch_effect": "none"}
        if (any(owner is None or owner.get("source_refs") != [source_ref] for owner in owners)
                or any(not isinstance(owner.get("governing_bindings"), list)
                       or owner["governing_bindings"].count(expected) != 1 for owner in owners if owner is not None)):
            return False, ()
        span = _span_once(fork_quote, receipt.quote)
        if (span is None or not support_spans or span[1] > min(owned[0] for owned in support_spans)
                or any(_overlaps(span, owned) for owned in (*answer_spans, *context_spans, *support_spans))):
            return False, ()
        application_ids.add(receipt.application_id)
        graph_hashes.add(receipt.native_graph_sha256)
        spans.append(span)
    if len(graph_hashes) != 1:
        return False, ()
    return True, tuple(spans)


def _lossless_fork_coverage(
    *,
    fork_quote: str,
    source_text: str,
    pair_targets: Sequence[Mapping[str, Any]],
    all_targets: Sequence[Mapping[str, Any]],
    obligations: Sequence[Mapping[str, Any]],
    source_ref: str,
    metadata_context: frozenset[str],
    application_custody: tuple[ApplicationPartitionCustody, ...],
    structural_context_credit: frozenset[str] = frozenset(),
    structural_binding_credit: frozenset[str] = frozenset(),
) -> tuple[bool, str | None, tuple[str, ...], tuple[str, ...]]:
    covered = [False] * len(fork_quote)
    answer_spans: list[tuple[int, int]] = []
    context_spans: list[tuple[int, int]] = []
    support_spans: list[tuple[int, int]] = []

    def cover(span: tuple[int, int]) -> None:
        covered[span[0] : span[1]] = [True] * (span[1] - span[0])

    for target in pair_targets:
        answer = _single_component(target, source_ref)
        if answer is None or len(answer) > 240 or source_text.count(answer) != 1:
            return False, None, (), ()
        span = _span_once(fork_quote, answer)
        if span is None or any(_overlaps(span, previous) for previous in answer_spans):
            return False, None, (), ()
        answer_spans.append(span)
        cover(span)
    source_contexts_by_target: list[dict[str, tuple[int, int]]] = []
    for target in pair_targets:
        contexts = target.get("context")
        if not isinstance(contexts, list) or not contexts:
            return False, None, (), ()
        seen: list[dict[str, str]] = []
        source_contexts: dict[str, tuple[int, int]] = {}
        for row in contexts:
            if (
                not isinstance(row, Mapping)
                or set(row) != {"ref", "text"}
                or row.get("ref") != source_ref
                or not isinstance(row.get("text"), str)
                or not row["text"]
                or row["text"] != row["text"].strip()
            ):
                return False, None, (), ()
            normalized = {"ref": source_ref, "text": row["text"]}
            if normalized in seen:
                return False, None, (), ()
            seen.append(normalized)
            text = row["text"]
            if text in metadata_context:
                continue  # Exact metadata may be visible but never earns source coverage.
            span = _span_once(fork_quote, text)
            if span is None or any(_overlaps(span, answer_span) for answer_span in answer_spans):
                return False, None, (), ()
            source_contexts[text] = span
        source_contexts_by_target.append(source_contexts)
    shared_contexts = set.intersection(*(set(rows) for rows in source_contexts_by_target))
    all_context_spans = tuple({span for rows in source_contexts_by_target for span in rows.values()})
    for rows in source_contexts_by_target:
        for text, span in rows.items():
            if text in shared_contexts:
                if text in structural_context_credit:
                    cover(span)
                continue  # Visible in both targets, but earns zero custody credit.
            if any(_overlaps(span, previous) for previous in context_spans):
                return False, None, (), ()
            context_spans.append(span)
            cover(span)
    for quote in structural_binding_credit:
        span = _span_once(fork_quote, quote)
        if span is None or any(_overlaps(span, answer_span) for answer_span in answer_spans):
            return False, None, (), ()
        cover(span)

    pair_ids = {str(target["id"]) for target in pair_targets}
    target_by_id = {
        row.get("id"): row for row in all_targets if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    support_rows: dict[str, list[Mapping[str, Any]]] = {}
    for obligation in obligations:
        links = obligation.get("target_ids") if isinstance(obligation, Mapping) else None
        if (
            isinstance(links, list)
            and len(links) == 1
            and isinstance(links[0], str)
            and links[0] not in pair_ids
            and obligation.get("ref") == source_ref
            and obligation.get("evidence_level") == "operational_decision"
        ):
            support_rows.setdefault(links[0], []).append(obligation)
    support_ids: list[str] = []
    support_targets: list[Mapping[str, Any]] = []
    for target_id, support_obligations in support_rows.items():
        support_target = target_by_id.get(target_id)
        if support_target is None:
            continue
        answer = _single_component(support_target, source_ref)
        matching = [row for row in support_obligations if row.get("quote") == answer]
        if (
            not _ordinary_target(support_target, source_ref)
            or answer is None
            or len(answer) > 240
            or source_text.count(answer) != 1
            or len(matching) != 1
        ):
            continue
        span = _span_once(fork_quote, answer)
        if span is None:
            continue  # Unrelated operational targets outside this fork stay untouched.
        if any(_overlaps(span, answer_span) for answer_span in answer_spans) or any(
            _overlaps(span, previous) for previous in support_spans
        ):
            return False, None, (), ()
        support_spans.append(span)
        cover(span)
        support_ids.append(target_id)
        support_targets.append(support_target)
    for target in support_targets:
        bindings = target.get("governing_bindings")
        if not isinstance(bindings, list):
            return False, None, (), ()
        for binding in bindings:
            if (
                not isinstance(binding, Mapping)
                or set(binding) != {"ref", "quote", "role", "branch_effect"}
                or binding.get("ref") != source_ref
                or binding.get("branch_effect") not in {"none", "scopes_action"}
                or not isinstance(binding.get("role"), str)
                or not isinstance(binding.get("quote"), str)
                or source_text.count(binding["quote"]) != 1
            ):
                return False, None, (), ()
            span = _span_once(fork_quote, binding["quote"])
            if span is None:
                source_fork = _span_once(source_text, fork_quote)
                source_binding = _span_once(source_text, binding["quote"])
                if (source_fork is not None and source_binding is not None
                        and not _overlaps(source_fork, source_binding)):
                    # Valid same-source prerequisites outside this local fork
                    # remain visible/native-audited, but earn NO fork coverage.
                    # Crossing-boundary or ambiguous quotes remain unproved.
                    continue
                return False, None, (), ()
            if any(_overlaps(span, answer_span) for answer_span in answer_spans):
                return False, None, (), ()
            # Only shared premise qualifiers may close contextual custody.  Scope
            # bindings stay validated and visible, but never replace an assessed
            # operational component/O owner.
            shared_binding = all(isinstance(peer.get("governing_bindings"), list)
                                 and binding in peer["governing_bindings"] for peer in pair_targets)
            temporal_prelude = (
                binding["role"] == "timing"
                and binding["branch_effect"] == "scopes_action"
                and shared_binding
                and bool(support_spans)
                and span[1] <= min(owned[0] for owned in support_spans)
                and not any(_overlaps(span, owned) for owned in (*context_spans, *support_spans))
            )
            # An already explicit identical premise on EVERY peer has the same
            # source custody as its duplicate display context. This earns only
            # syntactic premise custody, never a goal/O or semantic approval.
            if (binding["role"] in {"actor", "condition"}
                    and (binding["quote"] in shared_contexts or shared_binding)) or temporal_prelude:
                if binding["quote"] not in shared_contexts:
                    if any(_overlaps(span, branch_context) for branch_context in context_spans):
                        return False, None, (), ()  # A branch selector cannot become global support.
                    if any(_overlaps(span, owned) for owned in support_spans):
                        continue  # Already owned operational bytes earn no extra premise coverage.
                cover(span)
    application_valid, application_spans = _application_partition_spans(
        fork_quote=fork_quote, source_text=source_text, source_ref=source_ref,
        pair_targets=pair_targets, all_targets=all_targets, answer_spans=answer_spans,
        context_spans=all_context_spans, support_spans=support_spans, receipts=application_custody,
    )
    if not application_valid:
        return False, None, (), ()
    for span in application_spans:
        cover(span)
    gaps: list[tuple[int, str]] = []
    start: int | None = None
    for index, owned in enumerate([*covered, True]):
        if not owned and start is None:
            start = index
        elif owned and start is not None:
            gaps.append((start, fork_quote[start:index]))
            start = None
    coordinator_gaps: list[str] = []
    unresolved: list[str] = []
    for gap_start, gap in gaps:
        if _punctuation_or_space(gap):
            continue
        separator = _COORDINATOR_SEPARATOR.match(gap)
        remainder = gap
        if separator is not None:
            coordinator_gaps.append(separator.group())
            remainder = gap[separator.end() :]
        elif gap_start > 0 and fork_quote[gap_start - 1] in ",;":
            suffix = _COORDINATOR_SUFFIX.match(gap)
            if suffix is not None:
                coordinator_gaps.append(fork_quote[gap_start - 1] + suffix.group())
                remainder = gap[suffix.end() :]
        if _punctuation_or_space(remainder):
            continue
        core = _meaningful_core(remainder)
        if core and any(character.isalnum() for character in core):
            unresolved.append(core)
            continue
        return False, None, (), ()
    if len(coordinator_gaps) != 1:
        return False, None, (), ()
    return True, coordinator_gaps[0], tuple(unresolved), tuple(sorted(support_ids))


def prove_existing_pair_partition_custody(
    *,
    source_ref: str,
    source_text: str,
    seed_target_id: str,
    targets: Sequence[Mapping[str, Any]],
    obligations: Sequence[Mapping[str, Any]],
    metadata_context: Sequence[str] = (),
    _application_custody: tuple[ApplicationPartitionCustody, ...] = (),
) -> dict[str, Any]:
    """Recompute custody and explicit support dependencies, never semantics."""
    invalid = {
        "valid": False,
        "syntactic_custody": False,
        "required_support_target_ids": [],
        "unresolved_operational_spans": [],
        "structural_separator": None,
        "semantic_approval": False,
    }
    if (
        not isinstance(source_ref, str)
        or not source_ref
        or not isinstance(source_text, str)
        or not source_text
        or isinstance(targets, str | bytes)
        or not isinstance(targets, Sequence)
        or isinstance(obligations, str | bytes)
        or not isinstance(obligations, Sequence)
    ):
        return invalid
    if (
        isinstance(metadata_context, str | bytes)
        or not isinstance(metadata_context, Sequence)
        or any(not isinstance(value, str) or not value or value != value.strip() for value in metadata_context)
        or len(set(metadata_context)) != len(metadata_context)
    ):
        return invalid
    metadata = frozenset(metadata_context)
    cohort_result = _fork_cohort(
        source_ref=source_ref,
        source_text=source_text,
        seed_target_id=seed_target_id,
        targets=targets,
        obligations=obligations,
    )
    if cohort_result is None:
        return invalid
    cohort, fork = cohort_result
    pair = (str(cohort[0]["id"]), str(cohort[1]["id"]))
    ledger = _pair_obligation_contract(obligations, pair, source_ref, fork["branch_effect"], singleton=True)
    if ledger is None:
        return invalid
    related, matching = ledger
    target_by_id = {str(row["id"]): row for row in cohort}
    if any(row["quote"] != _single_component(target_by_id[matching[row["id"]]], source_ref) for row in related):
        return invalid
    custody, separator, unresolved, required = _lossless_fork_coverage(
        fork_quote=fork["quote"],
        source_text=source_text,
        pair_targets=cohort,
        all_targets=targets,
        obligations=obligations,
        source_ref=source_ref,
        metadata_context=metadata,
        application_custody=_application_custody,
        structural_context_credit=frozenset(fork.get("structural_context_credit", ())),
        structural_binding_credit=frozenset(fork.get("structural_binding_credit", ())),
    )
    if not custody:
        return invalid
    return {
        "valid": not unresolved,
        "syntactic_custody": True,
        "required_support_target_ids": list(required),
        "unresolved_operational_spans": list(unresolved),
        "structural_separator": separator,
        "semantic_approval": False,
    }


def validate_existing_pair_partition_reprojection(
    *,
    operation: Mapping[str, Any],
    source_ref: str,
    source_id: str,
    source_text: str,
    held_targets: Sequence[Mapping[str, Any]],
    held_obligations: Sequence[Mapping[str, Any]],
    proposed_targets: Sequence[Mapping[str, Any]],
    proposed_obligations: Sequence[Mapping[str, Any]] | None = None,
    metadata_context: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate one atomic model proposal and derive its existing-ID ledger."""
    if (
        not all(isinstance(value, str) and value for value in (source_ref, source_id, source_text))
        or isinstance(metadata_context, str | bytes)
        or not isinstance(metadata_context, Sequence)
        or any(not isinstance(value, str) or not value for value in metadata_context)
    ):
        _fail("invalid_input")
    if not isinstance(operation, Mapping) or operation.get("kind") != "lossless_component_partition":
        _fail("invalid_operation")
    if operation.get("scope") != "existing_pair_case_reprojection":
        _fail("invalid_operation_scope")
    if (
        operation.get("source_ref") != source_ref
        or operation.get("source_id") != source_id
        or operation.get("source_sha256") != hashlib.sha256(source_text.encode()).hexdigest()
        or operation.get("metadata_context") != list(metadata_context)
        or operation.get("allowed_target_changes") != ["answer_components", "context"]
        or operation.get("semantic_approval") is not False
    ):
        _fail("stale_operation")
    pair_values = _target_ids(operation.get("target_ids"))
    obligation_values = _target_ids(operation.get("obligation_ids"))
    matching = operation.get("obligation_target_matching")
    if (
        pair_values is None
        or len(pair_values) != 2
        or obligation_values is None
        or len(obligation_values) != 2
        or not isinstance(matching, Mapping)
        or any(not isinstance(key, str) for key in matching)
        or any(not isinstance(value, str) for value in matching.values())
        or set(matching) != set(obligation_values)
        or set(matching.values()) != set(pair_values)
    ):
        _fail("invalid_operation_cohort")
    pair = (pair_values[0], pair_values[1])
    obligation_ids = (obligation_values[0], obligation_values[1])
    expected_operation = discover_existing_pair_partition_operation(
        source_ref=source_ref,
        source_id=source_id,
        source_text=source_text,
        invalid_target_ids=set(pair),
        targets=held_targets,
        obligations=held_obligations,
        seed_target_id=str(operation.get("seed_target_id")),
        seed_component=str(operation.get("held_seed_component")),
        physical_tail=str(operation.get("physical_tail")),
        metadata_context=metadata_context,
    )
    if expected_operation is None or dict(operation) != expected_operation:
        _fail("forged_or_stale_operation")
    held_by_id = {
        str(row["id"]): row for row in held_targets if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    proposed_by_id = {
        str(row["id"]): row for row in proposed_targets if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    if set(proposed_by_id) != set(pair) or len(proposed_by_id) != len(proposed_targets):
        _fail("partial_or_foreign_target_cohort")
    if not set(pair) <= set(held_by_id):
        _fail("unknown_target_cohort")
    for target_id in pair:
        before, after = held_by_id[target_id], proposed_by_id[target_id]
        if set(before) != set(after):
            _fail("changed_target_schema")
        for field in before:
            if field not in {"answer_components", "context"} and before[field] != after[field]:
                _fail("changed_immutable_target_field")
        old_context = before.get("context")
        new_context = after.get("context")
        if not isinstance(old_context, list) or not isinstance(new_context, list):
            _fail("invalid_context")
        if any(new_context.count(row) < old_context.count(row) for row in old_context):
            _fail("lost_held_context")
    if "embedded_projection_receipt" in operation:
        _validate_embedded_projection(
            receipt=operation["embedded_projection_receipt"],
            source_ref=source_ref,
            source_text=source_text,
            pair=pair,
            obligation_ids=obligation_ids,
            matching=matching,
            held_by_id=held_by_id,
            proposed_by_id=proposed_by_id,
        )
    old_obligations = {
        row.get("id"): row for row in held_obligations if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    if set(obligation_ids) - set(old_obligations):
        _fail("unknown_obligation_cohort")
    derived_by_id: dict[str, dict[str, Any]] = {}
    for obligation_id in obligation_ids:
        previous = old_obligations[obligation_id]
        target_id = matching[obligation_id]
        answer = _single_component(proposed_by_id[target_id], source_ref)
        if answer is None:
            _fail("invalid_answer_component")
        derived_by_id[obligation_id] = {
            **dict(previous),
            "quote": answer,
            "target_ids": [target_id],
        }
    derived = [derived_by_id[obligation_id] for obligation_id in obligation_ids]
    if proposed_obligations:
        supplied = {
            row.get("id"): row
            for row in proposed_obligations
            if isinstance(row, Mapping) and isinstance(row.get("id"), str)
        }
        if len(supplied) != len(proposed_obligations) or supplied != derived_by_id:
            _fail("provider_obligation_mismatch")
    merged = [derived_by_id.get(str(row.get("id")), dict(row)) for row in held_obligations]
    current_targets = [proposed_by_id.get(str(row.get("id")), row) for row in held_targets]
    if operation.get("embedded_selector_partition") is True:
        embedded = _embedded_reprojected_cohort(
            source_ref=source_ref,
            source_text=source_text,
            seed_target_id=str(operation.get("seed_target_id")),
            targets=[proposed_by_id[target_id] for target_id in pair],
            obligations=derived,
        )
        operation_fork = operation.get("fork_binding")
        if (
            embedded is None
            or not isinstance(operation_fork, Mapping)
            or embedded[1]["quote"] != operation_fork.get("quote")
            or embedded[1]["branch_effect"] != operation_fork.get("branch_effect")
            or {str(row["id"]) for row in embedded[0]} != set(pair)
        ):
            _fail("final_custody")
    proof = prove_existing_pair_partition_custody(
        source_ref=source_ref,
        source_text=source_text,
        seed_target_id=str(operation.get("seed_target_id")),
        targets=current_targets,
        obligations=merged,
        metadata_context=metadata_context,
    )
    if not proof["syntactic_custody"]:
        _fail("final_custody")
    if proof["unresolved_operational_spans"]:
        _fail("unresolved_operational_spans", unresolved_operational_spans=proof["unresolved_operational_spans"])
    return {
        "target_ids": list(pair),
        "derived_obligations": derived,
        "merged_obligations": merged,
        "required_support_target_ids": proof["required_support_target_ids"],
        "structural_separator": proof["structural_separator"],
        "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
        "semantic_approval": False,
    }


__all__ = [
    "SourceCasePartitionError",
    "discover_existing_pair_partition_operation",
    "prove_existing_pair_partition_custody",
    "validate_existing_pair_partition_reprojection",
]
