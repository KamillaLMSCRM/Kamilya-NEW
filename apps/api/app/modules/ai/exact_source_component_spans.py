"""Resolve explicitly selected exact answer components; never infer truth/key.

This alternative map protocol accepts only a fully literal ordinary answer.
Legacy/explicit maps are never repaired, narrowed or replaced by this compiler.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from itertools import islice
from typing import Any

from app.modules.ai.assessment_components import (
    MAX_CANDIDATE_TEXT_CHARS,
    MAX_COMPONENT_TEXT_CHARS,
    MAX_REQUIREMENTS,
    MAX_SOURCE_PASSAGE_CHARS,
    MAX_SOURCE_PASSAGES,
    ComponentRequirement,
    OwnedComponent,
)
from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE


def _literal_pattern(phrase: str) -> re.Pattern[str]:
    parts = re.split(r"[" + re.escape(SOURCE_HORIZONTAL_SPACE) + r"]+", phrase)
    pattern = (r"(?<!\w)" if phrase[0].isalnum() else "") + (
        r"[" + re.escape(SOURCE_HORIZONTAL_SPACE) + r"]+"
    ).join(re.escape(part) for part in parts) + (r"(?!\w)" if phrase[-1].isalnum() else "")
    return re.compile(pattern, re.IGNORECASE)


def _unique_span(phrase: str, text: str) -> tuple[int, int]:
    matches = list(islice(_literal_pattern(phrase).finditer(text), 2))
    if len(matches) != 1:
        raise ValueError("exact_component_occurrence_not_unique")
    return matches[0].span()


def resolve_exact_source_answer_rows(
    requirements: Sequence[ComponentRequirement], rows: Any, *, answer: str,
    source_passages: Mapping[str, tuple[str, str]], key_source_ids: set[str] | frozenset[str],
) -> Any:
    """Compile only a complete, explicitly selected, single-owner literal map.

    Every nonpunctuation answer token must belong to one nonoverlapping source
    component (apart from the AND connector between them). Thus a preceding
    permission, negation or trailing new condition cannot hide outside a span.
    All semantic/discrimination/education gates still run after construction.
    """
    if not isinstance(rows, list | tuple) or not any(
        isinstance(row, dict) and "exact_source_answer" in row for row in rows
    ):
        return rows
    if (not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_CANDIDATE_TEXT_CHARS
            or not 1 <= len(requirements) == len(rows) <= MAX_REQUIREMENTS
            or not 1 <= len(source_passages) <= MAX_SOURCE_PASSAGES):
        raise ValueError("exact_component_bounds")
    if any(not isinstance(passage, tuple) or len(passage) != 2 or not isinstance(passage[0], str)
           or not isinstance(passage[1], str) or not 0 < len(passage[1]) <= MAX_SOURCE_PASSAGE_CHARS
           for passage in source_passages.values()):
        raise ValueError("exact_component_source_shape")
    if any(not isinstance(requirement, ComponentRequirement) for requirement in requirements):
        raise ValueError("exact_component_requirement_shape")
    indexed = {requirement.component_id: requirement for requirement in requirements}
    if len(indexed) != len(requirements):
        raise ValueError("exact_component_duplicate_requirement")
    result = []
    spans = []
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {
            "target_id", "component_id", "source_ref", "exact_source_answer"
        } or row["exact_source_answer"] is not True
                or not isinstance(row["component_id"], str) or not isinstance(row["source_ref"], str)):
            raise ValueError("exact_component_selector_shape")
        cid = row["component_id"]
        requirement = indexed.get(cid)
        if (requirement is None or cid in seen or row["target_id"] != requirement.target_id
                or requirement.full_set or len(requirement.alternatives) != 1):
            raise ValueError("exact_component_identity_or_group")
        seen.add(cid)
        component = requirement.alternatives[0]
        passage = source_passages.get(row["source_ref"])
        if (not isinstance(component, OwnedComponent) or not isinstance(component.source_id, str)
                or not isinstance(passage, tuple) or len(passage) != 2 or passage[0] != component.source_id
                or component.source_id not in key_source_ids or not isinstance(passage[1], str)
                or not 0 < len(passage[1]) <= MAX_SOURCE_PASSAGE_CHARS
                or not isinstance(component.text, str) or not component.text.strip()
                or len(component.text) > MAX_COMPONENT_TEXT_CHARS or component.text not in passage[1]):
            raise ValueError("exact_component_source_owner")
        pattern = _literal_pattern(component.text)
        occurrences = list(islice((reference for reference, (owner, text) in source_passages.items()
            if owner == component.source_id for _ in pattern.finditer(text)), 2))
        if occurrences != [row["source_ref"]]:
            raise ValueError("exact_component_original_occurrence_not_unique")
        start, end = _unique_span(component.text, answer)
        spans.append((start, end))
        result.append({"target_id": row["target_id"], "component_id": cid, "source_ref": row["source_ref"],
            "realizations": [{"part": "answer", "role": "discriminating_answer", "quote": answer[start:end]}]})
    previous = 0
    separators = "[" + re.escape(SOURCE_HORIZONTAL_SPACE) + r"\r\n,;:.]*"
    for span_index, (start, end) in enumerate(sorted(spans)):
        if start < previous:
            raise ValueError("exact_component_overlapping_spans")
        gap = answer[previous:start]
        # AND is licensed by the source-owned required component groups; no OR,
        # new subject, modal, value, condition, prohibition or unknown token.
        gap_pattern = separators + (r"(?:\bи\b" + separators + ")?" if span_index else "")
        if re.fullmatch(gap_pattern, gap, flags=re.IGNORECASE) is None:
            raise ValueError("exact_component_unmapped_envelope")
        previous = end
    if re.fullmatch(separators, answer[previous:]) is None:
        raise ValueError("exact_component_unmapped_envelope")
    return result
