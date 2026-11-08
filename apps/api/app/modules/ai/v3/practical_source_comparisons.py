"""Pure source-section navigation for source-to-course comparison groups."""

from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, validate_practical_course
from app.modules.ai.v3.practical_source_semantics import source_semantics_final_rules


def build_source_comparison_groups(
    packet: PracticalSourcePacket, reading: dict[str, Any], course: dict[str, Any], *, max_rules: int
) -> list[dict[str, Any]]:
    """Assign each source rule once; generated goals are not findings or verdicts."""
    if type(max_rules) is not int or not 1 <= max_rules <= 128:
        raise ValueError("source_comparison_group_budget_invalid")
    rules = source_semantics_final_rules(packet, reading)
    current = validate_practical_course(course, packet)
    lesson_ids = [lesson["id"] for lesson in current["lessons"]]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rules:
        goal = {
            **copy.deepcopy(row),
            "source_refs": list(row["rule"]["source_refs"]),
            "comparison_status": "UNVERIFIED",
        }
        buckets.setdefault(row["section"], []).append(goal)
    groups: list[dict[str, Any]] = []
    for section, goals in buckets.items():
        refs = {ref for goal in goals for ref in goal["source_refs"]}
        owners = [
            lesson["id"]
            for lesson in current["lessons"]
            if any(ref in refs for question in lesson["questions"] for ref in question["source_refs"])
        ]
        scope = "linked_lessons" if owners else "course_coverage"
        selected = owners if owners else lesson_ids
        for offset in range(0, len(goals), max_rules):
            part = goals[offset : offset + max_rules]
            groups.append(
                {
                    "rule_ids": [goal["rule_id"] for goal in part],
                    "lesson_ids": list(selected),
                    "scope": scope,
                    "source_section": section,
                    "goals": part,
                }
            )
    return groups
