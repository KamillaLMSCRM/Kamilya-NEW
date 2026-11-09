"""Pure source-section navigation for source-to-course comparison groups."""

from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, validate_practical_course
from app.modules.ai.v3.practical_source_semantics import source_semantics_final_rules


def build_source_comparison_groups(
    packet: PracticalSourcePacket, reading: dict[str, Any], course: dict[str, Any], *, max_rules: int,
    coalesce: bool = False,
) -> list[dict[str, Any]]:
    """Assign each source rule once; generated goals are not findings or verdicts."""
    if type(max_rules) is not int or not 1 <= max_rules <= 128:
        raise ValueError("source_comparison_group_budget_invalid")
    if type(coalesce) is not bool:
        raise ValueError("source_comparison_coalescing_invalid")
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
    return _coalesce_groups(groups, max_rules) if coalesce else groups


def _coalesce_groups(groups: list[dict[str, Any]], max_rules: int) -> list[dict[str, Any]]:
    """Share the same source/course once; retain every logical group and owned goal."""
    batches: list[list[dict[str, Any]]] = []
    for group in groups:
        if not batches or sum(len(row['rule_ids']) for row in batches[-1]) + len(group['rule_ids']) > max_rules:
            batches.append([])
        batches[-1].append(copy.deepcopy(group))
    result = []
    for batch in batches:
        result.append({
            'rule_ids': [key for row in batch for key in row['rule_ids']],
            'lesson_ids': list(dict.fromkeys(key for row in batch for key in row['lesson_ids'])),
            'scope': 'course_coverage' if any(row['scope'] == 'course_coverage' for row in batch) else 'linked_lessons',
            'source_section': '\n'.join(row['source_section'] for row in batch),
            'goals': [goal for row in batch for goal in row['goals']],
            'logical_groups': [{key: row[key] for key in ('rule_ids', 'lesson_ids', 'scope', 'source_section')}
                               for row in batch],
        })
    return result
