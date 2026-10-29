"""Fail-closed learner-premise rendering and qualification preservation receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

NATURAL_SCENARIO_FORM = "natural_scenario"
NATURAL_SCENARIO_LABEL = "Ситуация: "
NATURAL_SCENARIO_QUESTION = "Какой вариант применим в описанной ситуации?"
QUALIFICATION_RELATIONS = frozenset({
    "equivalent", "entailed_specialization", "broader", "unknown",
})
PRESERVED_QUALIFICATION_RELATIONS = frozenset({"equivalent", "entailed_specialization"})


def render_natural_scenario(premise: str) -> str:
    """Render authored learner prose inside a server-owned neutral envelope."""
    return f"{NATURAL_SCENARIO_LABEL}{premise}\n{NATURAL_SCENARIO_QUESTION}"


def natural_scenario_premise_range(text: str, premise: str) -> tuple[int, int] | None:
    prefix = NATURAL_SCENARIO_LABEL + premise + "\n"
    if not premise or text != prefix + NATURAL_SCENARIO_QUESTION:
        return None
    return len(NATURAL_SCENARIO_LABEL), len(NATURAL_SCENARIO_LABEL) + len(premise)


def visible_candidate_sha256(text: str, options: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(
        {"text": text, "options": list(options)}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _ordered_bindings(bindings: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(sorted(bindings, key=lambda row: (
        str(row.get("source_id", "")), row.get("quote_start", -1), str(row.get("facet_id", "")),
    )))


def qualification_wire_specs(bindings: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Expose short call-local IDs while retaining canonical source evidence server-side."""
    return tuple({
        "binding_id": f"B{index}",
        "source_quote": binding["quote"],
        "role": binding["role"],
        "branch_effect": binding["branch_effect"],
    } for index, binding in enumerate(_ordered_bindings(bindings), 1))


def premise_wire_fragments(text: str, premise: str) -> tuple[dict[str, str], ...]:
    """Address the complete visible premise without asking critics to copy it.

    This is a citation address, not a semantic verdict or a new source. Using one
    lossless fragment avoids heuristic sentence boundaries and remains identical
    to the already permitted exact whole-premise quote. Each binding still needs
    its own independent applicability relation and reason from both critics.
    """
    if natural_scenario_premise_range(text, premise) is None:
        raise ValueError("lesson_cycle_qualification_realizations_invalid")
    return ({"ref": "P1", "text": premise},)


def canonicalize_qualification_realizations(
    rows: Any,
    bindings: Sequence[dict[str, Any]],
    text: str,
    premise: str,
    options: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Validate one critic's semantic receipt and restore canonical facet ownership."""
    ordered = _ordered_bindings(bindings)
    aliases = {f"B{index}": binding for index, binding in enumerate(ordered, 1)}
    premise_range = natural_scenario_premise_range(text, premise)
    if premise_range is None or not isinstance(rows, list) or len(rows) != len(aliases):
        raise ValueError("lesson_cycle_qualification_realizations_invalid")
    fragments = {row["ref"]: row["text"] for row in premise_wire_fragments(text, premise)}
    seen: set[str] = set()
    canonical: list[dict[str, Any]] = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {
                "binding_id", "relation", "preserved", "premise_spans", "reason"}):
            raise ValueError("lesson_cycle_qualification_realizations_invalid")
        binding_id = row["binding_id"]
        reason = row["reason"]
        spans = row["premise_spans"]
        relation = row["relation"]
        if (not isinstance(binding_id, str) or binding_id not in aliases or binding_id in seen
                or not isinstance(relation, str) or relation not in QUALIFICATION_RELATIONS
                or type(row["preserved"]) is not bool
                or row["preserved"] is not (relation in PRESERVED_QUALIFICATION_RELATIONS)
                or not isinstance(reason, str) or not 0 < len(reason.strip()) <= len(reason) <= 300
                or not isinstance(spans, list) or (row["preserved"] and not spans)):
            raise ValueError("lesson_cycle_qualification_realizations_invalid")
        normalized_spans = []
        for span in spans:
            if (not isinstance(span, dict) or set(span) != {"ref"}
                    or not isinstance(span["ref"], str) or span["ref"] not in fragments):
                raise ValueError("lesson_cycle_qualification_realizations_invalid")
            quote = fragments[span["ref"]]
            if not isinstance(quote, str) or not quote or premise.count(quote) != 1:
                raise ValueError("lesson_cycle_qualification_realizations_invalid")
            start = premise_range[0] + premise.index(quote)
            end = start + len(quote)
            normalized_spans.append({"start": start, "end": end, "quote": quote})
        if len({(span["start"], span["end"]) for span in normalized_spans}) != len(normalized_spans):
            raise ValueError("lesson_cycle_qualification_realizations_invalid")
        binding = aliases[binding_id]
        canonical.append({
            "facet_id": binding["facet_id"],
            "source_id": binding["source_id"],
            "source_quote": binding["quote"],
            "role": binding["role"],
            "branch_effect": binding["branch_effect"],
            "candidate_sha256": visible_candidate_sha256(text, options),
            "premise_spans": normalized_spans,
            "relation": relation,
            "preserved": row["preserved"],
            "reason": reason,
        })
        seen.add(binding_id)
    if seen != set(aliases):
        raise ValueError("lesson_cycle_qualification_realizations_invalid")
    return tuple(canonical)


def qualification_realizations_valid(
    rows: Any,
    bindings: Sequence[dict[str, Any]],
    text: str,
    premise: str,
    options: Sequence[str],
) -> bool:
    """Revalidate stored canonical receipts during admission and checkpoint readback."""
    ordered = _ordered_bindings(bindings)
    premise_range = natural_scenario_premise_range(text, premise)
    if premise_range is None or not isinstance(rows, list | tuple) or len(rows) != len(ordered):
        return False
    expected = {binding["facet_id"]: binding for binding in ordered}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "facet_id", "source_id", "source_quote", "role", "branch_effect",
            "candidate_sha256", "premise_spans", "relation", "preserved", "reason",
        }:
            return False
        facet_id = row["facet_id"]
        binding = expected.get(facet_id) if isinstance(facet_id, str) else None
        if (binding is None or facet_id in seen or row["source_id"] != binding["source_id"]
                or row["source_quote"] != binding["quote"] or row["role"] != binding["role"]
                or row["branch_effect"] != binding["branch_effect"]
                or not isinstance(row["relation"], str)
                or row["relation"] not in PRESERVED_QUALIFICATION_RELATIONS
                or row["preserved"] is not True
                or row["candidate_sha256"] != visible_candidate_sha256(text, options)
                or not isinstance(row["reason"], str)
                or not 0 < len(row["reason"].strip()) <= len(row["reason"]) <= 300
                or not isinstance(row["premise_spans"], list) or not row["premise_spans"]):
            return False
        for span in row["premise_spans"]:
            if not isinstance(span, dict) or set(span) != {"start", "end", "quote"}:
                return False
            start, end, quote = span["start"], span["end"], span["quote"]
            if (type(start) is not int or type(end) is not int or not isinstance(quote, str) or not quote
                    or not premise_range[0] <= start < end <= premise_range[1]
                    or text[start:end] != quote or premise.count(quote) != 1):
                return False
        if len({(span["start"], span["end"]) for span in row["premise_spans"]}) != len(row["premise_spans"]):
            return False
        seen.add(facet_id)
    return seen == set(expected)


def qualification_repair_failures(
    rows: Any,
    bindings: Sequence[dict[str, Any]],
    text: str,
    premise: str,
    options: Sequence[str],
) -> tuple[dict[str, str], ...]:
    """Return only complete, candidate-bound negative qualification evidence."""
    ordered = _ordered_bindings(bindings)
    premise_range = natural_scenario_premise_range(text, premise)
    if premise_range is None or not isinstance(rows, list | tuple) or len(rows) != len(ordered):
        return ()
    expected = {
        binding["facet_id"]: (f"B{index}", binding)
        for index, binding in enumerate(ordered, 1)
    }
    seen: set[str] = set()
    failures: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "facet_id", "source_id", "source_quote", "role", "branch_effect",
            "candidate_sha256", "premise_spans", "relation", "preserved", "reason",
        }:
            return ()
        facet_id = row["facet_id"]
        resolved = expected.get(facet_id) if isinstance(facet_id, str) else None
        if resolved is None or facet_id in seen:
            return ()
        binding_id, binding = resolved
        spans = row["premise_spans"]
        if (row["source_id"] != binding["source_id"] or row["source_quote"] != binding["quote"]
                or row["role"] != binding["role"] or row["branch_effect"] != binding["branch_effect"]
                or not isinstance(row["relation"], str) or row["relation"] not in QUALIFICATION_RELATIONS
                or type(row["preserved"]) is not bool
                or row["preserved"] is not (row["relation"] in PRESERVED_QUALIFICATION_RELATIONS)
                or row["candidate_sha256"] != visible_candidate_sha256(text, options)
                or not isinstance(row["reason"], str)
                or not 0 < len(row["reason"].strip()) <= len(row["reason"]) <= 300
                or not isinstance(spans, list) or (row["preserved"] and not spans)):
            return ()
        for span in spans:
            if not isinstance(span, dict) or set(span) != {"start", "end", "quote"}:
                return ()
            start, end, quote = span["start"], span["end"], span["quote"]
            if (type(start) is not int or type(end) is not int or not isinstance(quote, str) or not quote
                    or not premise_range[0] <= start < end <= premise_range[1]
                    or text[start:end] != quote or premise.count(quote) != 1):
                return ()
        if len({(span["start"], span["end"]) for span in spans}) != len(spans):
            return ()
        if not row["preserved"]:
            failures.append({
                "binding_id": binding_id,
                "source_quote": binding["quote"],
                "relation": row["relation"],
                "reason": row["reason"],
            })
        seen.add(facet_id)
    return tuple(failures) if seen == set(expected) else ()
