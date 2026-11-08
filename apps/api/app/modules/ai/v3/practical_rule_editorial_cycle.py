"""Review all source rules in bounded output parts, with full shared context.

The part boundary limits returned evidence, never the source document or course.
No part can certify rules assigned to another part.
"""

from __future__ import annotations

import json
import math
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_rule_editorial_contract import (
    compile_rule_editorial_review,
    compile_rule_editorial_verification,
    rule_editorial_review_format,
    rule_editorial_verification_format,
)
from app.modules.ai.v3.practical_source_semantics import source_semantics_context, source_semantics_final_rules


def rule_parts(packet: Any, reading: dict[str, Any], max_rules: int) -> list[list[str]]:
    if type(max_rules) is not int or not 1 <= max_rules <= 128:
        raise ValueError("editorial_rule_part_budget_invalid")
    rules = source_semantics_final_rules(packet, reading)
    sections: list[list[str]] = []
    previous = None
    for row in rules:
        if previous != row["section"]:
            sections.append([])
            previous = row["section"]
        sections[-1].append(row["rule_id"])
    desired = max(1, math.ceil(len(rules) / max_rules))
    target = math.ceil(len(rules) / desired)
    parts: list[list[str]] = []
    current: list[str] = []
    for section in sections:
        for start in range(0, len(section), max_rules):
            block = section[start : start + max_rules]
            exceeds = len(current) + len(block) > max_rules
            closer_boundary = (
                len(parts) < desired - 1
                and current
                and abs(target - len(current)) <= abs(target - len(current) - len(block))
            )
            if current and (exceeds or closer_boundary):
                parts.append(current)
                current = []
            current.extend(block)
    if current:
        parts.append(current)
    expected = [r["rule_id"] for r in rules]
    if [key for part in parts for key in part] != expected:
        raise ValueError("editorial_rule_parts_incomplete")
    return parts


async def review_source_rules(
    packet: Any,
    reading: dict[str, Any],
    course: dict[str, Any],
    context: str,
    view: Any,
    call: Any,
    system: str,
    *,
    max_rules: int,
    prior: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parts = rule_parts(packet, reading, max_rules)
    owners = {key: index for index, part in enumerate(parts) for key in part}
    assignments: list[list[dict[str, Any]]] = [[] for _ in parts]
    for finding in prior or []:
        rule_id = finding.get("source_rule_id")
        if rule_id is not None and (not isinstance(rule_id, str) or rule_id not in owners):
            raise ValueError("editorial_prior_rule_identity_invalid")
        assignments[owners[rule_id] if isinstance(rule_id, str) else 0].append(finding)
    results = []
    raw_parts = []
    common = (
        context
        + source_semantics_context(reading, view)
        + "\nFULL_COURSE_WITH_KEYS_AND_EXPLANATIONS_JSON\n"
        + json.dumps(view.encode(course), ensure_ascii=False, sort_keys=True)
    )

    async def request_part(
        ids: list[str], assigned: list[dict[str, Any]], correction: list[dict[str, Any]] | None = None
    ) -> tuple[Any, Any]:
        content = common + "\nREQUIRED_SOURCE_RULE_IDS_JSON\n" + json.dumps(ids)
        if correction:
            content += "\nPRIOR_RULE_CHECKS_UNVERIFIED_JSON\n" + json.dumps(
                view.encode(correction), ensure_ascii=False, sort_keys=True
            )
        if prior is not None:
            content += "\nPRIOR_MATERIAL_FINDINGS_JSON\n" + json.dumps(
                view.encode(assigned), ensure_ascii=False, sort_keys=True
            )
            fmt = rule_editorial_verification_format(packet, course, reading, assigned, rule_ids=ids)
        else:
            fmt = rule_editorial_review_format(packet, course, reading, rule_ids=ids)

        def compile_response(value: Any, findings: Any = assigned, subset: Any = ids) -> Any:
            if prior is None:
                return compile_rule_editorial_review(value, packet, course, reading, rule_ids=subset)
            return compile_rule_editorial_verification(value, packet, course, reading, findings, rule_ids=subset)

        instruction = (
            "\nПроверь весь курс и исходник; source_rule_checks верни только и ровно для "
            "REQUIRED_SOURCE_RULE_IDS_JSON этого запроса. Остальные правила проверяются отдельными "
            "частями, не объявляй их проверенными. Для resolutions используй только переданные "
            "PRIOR_MATERIAL_FINDINGS_JSON. Короткие буквальные цитаты и краткие причины достаточны; "
            "не переписывай целиком уроки в доказательствах. Если переданы PRIOR_RULE_CHECKS_UNVERIFIED_JSON, "
            "курс ещё не менялся: исправь доказательства только этих проверок по фактическому тексту. "
            "Ошибка цитаты или condition_id не является ошибкой урока. Если само учебное утверждение "
            "неверно, назови его CONTRADICTED и предложи адресную правку; не ослабляй источник ради SUPPORTED."
        )
        group = (
            "practical:editorial:"
            + ("review" if prior is None else "verify")
            + ":v33:"
            + _digest([course, reading, ids, assigned, system, correction])
        )
        raw = await call(
            "review",
            group,
            [{"role": "system", "content": system + instruction}, {"role": "user", "content": content}],
            fmt,
            compile_response,
        )
        return compile_response(raw), raw

    for index, ids in enumerate(parts):
        assigned = assignments[index]
        result, raw = await request_part(ids, assigned)
        receipt = {"rule_ids": ids, "response": raw}
        invalid = [
            row
            for row in result["source_rule_checks"]
            if not row["verified"]
            and not set(row["verification_errors"]) & {"source_reading_unverified", "source_reading_disputed"}
        ]
        if invalid:
            invalid_ids = {row["rule_id"] for row in invalid}
            repair_prior = [row for row in assigned if row.get("source_rule_id") in invalid_ids]
            corrected, corrected_raw = await request_part([row["rule_id"] for row in invalid], repair_prior, invalid)
            replacement = {row["rule_id"]: row for row in corrected["source_rule_checks"]}
            result["source_rule_checks"] = [
                replacement.get(row["rule_id"], row) for row in result["source_rule_checks"]
            ]
            # Supersede only the invalid technical cards, never another finding.
            findings = {
                row["issue_id"]: row
                for row in result["review"]["findings"]
                if not (row.get("source_rule_id") in invalid_ids and row.get("rule_check_unverified"))
            }
            findings.update({row["issue_id"]: row for row in corrected["review"]["findings"]})
            result["review"]["findings"] = list(findings.values())
            resolutions_by_id = {row["issue_id"]: row for row in result["resolutions"]}
            resolutions_by_id.update({row["issue_id"]: row for row in corrected["resolutions"]})
            result["resolutions"] = list(resolutions_by_id.values())
            result["review"]["source_notes"].extend(corrected["review"]["source_notes"])
            for lesson, refs in corrected["review"]["narrative_sources"].items():
                result["review"]["narrative_sources"][lesson] = list(
                    dict.fromkeys([*result["review"]["narrative_sources"].get(lesson, []), *refs])
                )
            receipt["evidence_correction"] = corrected_raw
            # One addressed correction of a completed bad proof. No blind retry.
        results.append(result)
        raw_parts.append(receipt)
    checks = [row for result in results for row in result["source_rule_checks"]]
    expected = [key for part in parts for key in part]
    if len(checks) != len(expected) or {c["rule_id"] for c in checks} != set(expected):
        raise ValueError("editorial_rule_review_incomplete")
    resolutions = [row for result in results for row in result["resolutions"]]
    prior_ids = {row["issue_id"] for row in prior or []}
    if len(resolutions) != len(prior_ids) or {row["issue_id"] for row in resolutions} != prior_ids:
        raise ValueError("editorial_rule_resolutions_incomplete")
    findings = {row["issue_id"]: row for result in results for row in result["review"]["findings"]}
    notes = {_digest(row): row for result in results for row in result["review"]["source_notes"]}
    narrative: dict[str, list[str]] = {}
    for result in results:
        for lesson, refs in result["review"]["narrative_sources"].items():
            narrative[lesson] = list(dict.fromkeys([*narrative.get(lesson, []), *refs]))
    return {
        "review": {
            "source_fingerprint": packet.fingerprint,
            "course_fingerprint": _digest(course),
            "summary": "\n".join(result["review"]["summary"] for result in results),
            "findings": list(findings.values()),
            "source_notes": list(notes.values()),
            "narrative_sources": narrative,
        },
        "source_rule_checks": checks,
        "resolutions": resolutions,
        "raw_parts": raw_parts,
    }
