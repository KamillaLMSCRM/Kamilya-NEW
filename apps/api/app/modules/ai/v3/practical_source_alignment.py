"""Source-reading alignment goals; these are not findings of course error."""

from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, validate_practical_course
from app.modules.ai.v3.practical_source_semantics import source_semantics_final_rules

SEMANTIC_FIELDS = ("actor", "action", "object", "modality", "conditions", "alternatives", "limits")
INSTRUCTION = (
    "Check whether the actual lesson wording still permits the earlier source interpretation. "
    "Clarify only if necessary to match the corrected source reading; otherwise leave the lesson byte-identical. "
    "This is an alignment goal, not a finding that the course contains an error."
)
COMPLETENESS_INSTRUCTION = (
    "Check whether this essential work rule is already adequately taught in the linked course content. "
    "Clarify only if the rule is materially missing; preserve adequate prose and representative questions. "
    "Do not require a separate lesson or question for every source detail. This is not a finding that the course contains an error."
)


def build_source_alignment_goals(
    packet: PracticalSourcePacket, reading: dict[str, Any], course: dict[str, Any]
) -> dict[str, Any]:
    """Map model-corrected source interpretations to source-linked lessons only."""
    final_rules = source_semantics_final_rules(packet, reading)
    current_course = validate_practical_course(course, packet)
    original = {row["rule_id"]: row for section in reading["original_reading"]["sections"] for row in section["rules"]}
    goals = []
    targets: list[str] = []
    unmapped: list[str] = []
    for row in final_rules:
        if not row["custody_valid"]:
            continue
        if row["status"] == "REVISE":
            original_rule = original.get(row["rule_id"])
            if original_rule is None:
                raise ValueError("source_alignment_original_rule_missing")
            after = row["rule"]
            if all(original_rule[field] == after[field] for field in SEMANTIC_FIELDS):
                continue
            before = {k: copy.deepcopy(v) for k, v in original_rule.items() if k not in ("rule_id", "custody_valid")}
            origin = "GRAMMAR_CORRECTION"
        elif row["status"] == "SUPPORTED" and row.get("provenance") == "SOURCE_COMPLETENESS_ADDITION":
            before = {}
            after = row["rule"]
            origin = "SOURCE_COMPLETENESS_ADDITION"
        else:
            continue
        refs = set(after["source_refs"])
        lesson_ids = [
            lesson["id"]
            for lesson in current_course["lessons"]
            if any(ref in refs for question in lesson["questions"] for ref in question["source_refs"])
        ]
        if not lesson_ids:
            unmapped.append(row["rule_id"])
        for lesson_id in lesson_ids:
            if lesson_id not in targets:
                targets.append(lesson_id)
        goals.append(
            {
                "rule_id": row["rule_id"],
                "lesson_ids": lesson_ids,
                "source_refs": list(after["source_refs"]),
                "before": before,
                "origin": origin,
                "after": copy.deepcopy(after),
                "reason": row["reason"],
                "instruction": INSTRUCTION if origin == "GRAMMAR_CORRECTION" else COMPLETENESS_INSTRUCTION,
            }
        )
    return {"goals": goals, "target_lesson_ids": targets, "unmapped_rule_ids": unmapped}
