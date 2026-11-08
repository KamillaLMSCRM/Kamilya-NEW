"""Per-source-rule editorial checks; literal evidence custody is not semantic proof."""

from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_contract import _obj, _review_format, compile_editorial_review
from app.modules.ai.v3.practical_editorial_verification import _format as _verification_base
from app.modules.ai.v3.practical_editorial_verification import compile_editorial_verification
from app.modules.ai.v3.practical_source_semantics import source_condition_id, source_semantics_final_rules

READ_NAME = "v3_practical_rule_editorial_review_v3"
VERIFY_NAME = "v3_practical_rule_editorial_verification_v3"


def _compact(schema: Any) -> None:
    if isinstance(schema, dict):
        props = schema.get("properties", {})
        if "narrative_sources" in props:
            for entry in props["narrative_sources"]["properties"].values():
                entry["items"].pop("enum", None)
        if "source_refs" in props:
            props["source_refs"]["items"].pop("enum", None)
        if "kind" in props and props["kind"].get("enum") == ["source"] and "id" in props:
            props["id"].pop("enum", None)
        for item in schema.values():
            _compact(item)
    elif isinstance(schema, list):
        for item in schema:
            _compact(item)


def _format(
    source_fp: str,
    course_fp: str,
    reading_fp: str,
    lessons: list[str],
    questions: list[str],
    rule_ids: list[str],
    issue_ids: list[str] | None,
) -> dict[str, Any]:
    if (
        not rule_ids
        or len(set(rule_ids)) != len(rule_ids)
        or any(type(x) is not str or not x for x in rule_ids)
        or type(reading_fp) is not str
        or len(reading_fp) != 64
    ):
        raise ValueError("rule_editorial_format_invalid")
    base = _review_format(["source_placeholder"], lessons, questions, source_fp, course_fp)
    if issue_ids is not None:
        base = _verification_base(base, issue_ids)
    _compact(base)
    if issue_ids == []:
        base["json_schema"]["schema"]["properties"]["resolutions"]["items"]["properties"]["issue_id"].pop("enum", None)
    base["json_schema"]["name"] = VERIFY_NAME if issue_ids is not None else READ_NAME
    schema = base["json_schema"]["schema"]
    props = schema["properties"]
    text = {"type": "string"}
    props["reading_fingerprint"] = {"type": "string", "enum": [reading_fp]}
    props["source_rule_checks"] = {
        "type": "array",
        "minItems": len(rule_ids),
        "maxItems": len(rule_ids),
        "items": _obj(
            {
                "rule_id": {"type": "string", "enum": rule_ids},
                "status": {
                    "type": "string",
                    "enum": ["SUPPORTED", "CONTRADICTED", "INCOMPLETE", "NOT_APPLICABLE", "SOURCE_READING_DISPUTED"],
                },
                "lesson_quotes": {
                    "type": "array",
                    "items": _obj({"lesson_id": {"type": "string", "enum": lessons}, "quote": text}),
                },
                "condition_checks": {
                    "type": "array",
                    "items": _obj(
                        {
                            "condition_id": {"type": "string"},
                            "taught_applies_to": text,
                            "taught_expression": text,
                            "scope_equivalent": {"type": "string", "enum": ["YES", "NO"]},
                            "reason": text,
                        }
                    ),
                },
                "reason": text,
                "correction": text,
                "severity": {"type": "string", "enum": ["material", "advisory"]},
            }
        ),
    }
    schema["required"].extend(["reading_fingerprint", "source_rule_checks"])
    return base


def _identity(
    packet: Any, course: dict[str, Any], reading: dict[str, Any]
) -> tuple[str, str, str, list[str], list[str], list[str]]:
    rules = source_semantics_final_rules(packet, reading)
    return (
        packet.fingerprint,
        _digest(course),
        reading["verified_reading_fingerprint"],
        [lesson["id"] for lesson in course["lessons"]],
        [question["id"] for lesson in course["lessons"] for question in lesson["questions"]],
        [r["rule_id"] for r in rules],
    )


def _scoped_identity(
    packet: Any, course: dict[str, Any], reading: dict[str, Any], rule_ids: list[str] | None
) -> tuple[str, str, str, list[str], list[str], list[str]]:
    identity = _identity(packet, course, reading)
    if rule_ids is None:
        return identity
    if (
        type(rule_ids) is not list
        or not rule_ids
        or any(type(x) is not str or not x for x in rule_ids)
        or len(rule_ids) != len(set(rule_ids))
        or not set(rule_ids) <= set(identity[-1])
    ):
        raise ValueError("rule_editorial_subset_invalid")
    return (identity[0], identity[1], identity[2], identity[3], identity[4], list(rule_ids))


def rule_editorial_review_format(
    packet: Any, course: dict[str, Any], reading: dict[str, Any], *, rule_ids: list[str] | None = None
) -> dict[str, Any]:
    return _format(*_scoped_identity(packet, course, reading, rule_ids), None)


def rule_editorial_verification_format(
    packet: Any,
    course: dict[str, Any],
    reading: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    rule_ids: list[str] | None = None,
) -> dict[str, Any]:
    return _format(
        *_scoped_identity(packet, course, reading, rule_ids),
        [r["issue_id"] for r in findings if r["severity"] == "material"],
    )


def _is_format(fmt: Any, verification: bool) -> bool:
    try:
        p = fmt["json_schema"]["schema"]["properties"]
        targets = p["findings"]["items"]["properties"]["target"]["anyOf"]
        ids = p["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
        issues = p["resolutions"]["items"]["properties"]["issue_id"].get("enum", []) if verification else None
        return bool(
            fmt
            == _format(
                p["source_fingerprint"]["enum"][0],
                p["course_fingerprint"]["enum"][0],
                p["reading_fingerprint"]["enum"][0],
                targets[1]["properties"]["id"]["enum"],
                targets[2]["properties"]["id"]["enum"],
                ids,
                issues,
            )
        )
    except (KeyError, IndexError, TypeError, ValueError, RecursionError):
        return False


def is_rule_editorial_review_format(fmt: Any) -> bool:
    return _is_format(fmt, False)


def is_rule_editorial_verification_format(fmt: Any) -> bool:
    return _is_format(fmt, True)


def _matches_result(value: Any, fmt: Any, verification: bool) -> bool:
    try:
        if not _is_format(fmt, verification):
            return False
        if not _matches(value, fmt["json_schema"]["schema"]):
            return False
        ids = fmt["json_schema"]["schema"]["properties"]["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
        checks = value["source_rule_checks"]
        if len(checks) != len(ids) or {c["rule_id"] for c in checks} != set(ids):
            return False
        if not all(
            c["reason"].strip() and (c["correction"].strip() or c["status"] in ("SUPPORTED", "NOT_APPLICABLE"))
            for c in checks
        ):
            return False
        if verification:
            expected = fmt["json_schema"]["schema"]["properties"]["resolutions"]["items"]["properties"]["issue_id"].get(
                "enum", []
            )
            if len(value["resolutions"]) != len(expected) or {x["issue_id"] for x in value["resolutions"]} != set(
                expected
            ):
                return False
        return True
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def matches_rule_editorial_review(value: Any, fmt: Any) -> bool:
    return _matches_result(value, fmt, False)


def matches_rule_editorial_verification(value: Any, fmt: Any) -> bool:
    return _matches_result(value, fmt, True)


def _compile_checks(
    value: Any, course: dict[str, Any], rules: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {r["rule_id"]: r for r in rules}
    lessons = {lesson["id"]: lesson["content"] for lesson in course["lessons"]}
    results = []
    findings = []
    for check in value["source_rule_checks"]:
        rule = by_id[check["rule_id"]]
        quotes = check["lesson_quotes"]
        status = check["status"]
        errors = []
        if any(not q["quote"].strip() or q["quote"] not in lessons[q["lesson_id"]] for q in quotes):
            errors.append("lesson_quote_invalid")
        if status == "SUPPORTED" and not quotes:
            errors.append("lesson_quote_missing")
        conditions = check["condition_checks"]
        expected = {source_condition_id(check["rule_id"], index) for index in range(len(rule["rule"]["conditions"]))}
        indices = [x["condition_id"] for x in conditions]
        if (status in ("SUPPORTED", "CONTRADICTED", "INCOMPLETE") or conditions) and (
            len(indices) != len(set(indices)) or set(indices) != expected
        ):
            errors.append("condition_ids_invalid")
        if any(not x["reason"].strip() for x in conditions):
            errors.append("condition_reason_missing")
        if status == "SUPPORTED" and any(
            x["scope_equivalent"] != "YES" or not x["taught_applies_to"].strip() or not x["taught_expression"].strip()
            for x in conditions
        ):
            errors.append("condition_scope_unverified")
        # Irrelevant uncertainty need not be guessed to teach an unaffected rule.
        # The driver still separately adjudicates the evidenced source proposal.
        admissible_irrelevance = rule["status"] == "SOURCE_AMBIGUITY" and status == "NOT_APPLICABLE"
        if not rule["custody_valid"] or (rule["status"] not in ("SUPPORTED", "REVISE") and not admissible_irrelevance):
            errors.append("source_reading_unverified")
        if status == "SOURCE_READING_DISPUTED":
            errors.append("source_reading_disputed")
        result = {**copy.deepcopy(check), "verified": not errors, "verification_errors": errors}
        results.append(result)
        if status in ("CONTRADICTED", "INCOMPLETE") or errors:
            targets = [
                {"kind": "lesson", "id": lesson_id} for lesson_id in dict.fromkeys(q["lesson_id"] for q in quotes)
            ]
            if not targets:
                targets = [{"kind": "course", "id": "course"}]
            for target in targets:
                row = {
                    "domain": "content",
                    "severity": "material" if errors else check["severity"],
                    "target": target,
                    "problem": "Source rule check requires review: " + status,
                    "basis": check["reason"],
                    "correction": check["correction"],
                    "source_refs": list(rule["rule"]["source_refs"]),
                    "source_rule_id": check["rule_id"],
                    "rule_check_unverified": bool(errors),
                }
                # A new explanation of the same open rule is not a new defect.
                # Evidence failures remain distinct from confirmed content defects.
                row["issue_id"] = (
                    "issue-"
                    + _digest(
                        {
                            "source_rule_id": check["rule_id"],
                            "target": target,
                            "rule_check_unverified": bool(errors),
                        }
                    )[:20]
                )
                findings.append(row)
    return results, findings


def _compile(
    value: Any,
    packet: Any,
    course: dict[str, Any],
    reading: dict[str, Any],
    prior: list[dict[str, Any]] | None,
    rule_ids: list[str] | None,
) -> dict[str, Any]:
    fmt = (
        rule_editorial_review_format(packet, course, reading, rule_ids=rule_ids)
        if prior is None
        else rule_editorial_verification_format(packet, course, reading, prior, rule_ids=rule_ids)
    )
    if not _matches_result(value, fmt, prior is not None):
        raise ValueError("rule_editorial_response_invalid")
    base = {k: copy.deepcopy(v) for k, v in value.items() if k not in ("reading_fingerprint", "source_rule_checks")}
    result: dict[str, Any]
    if prior is None:
        result = {"review": compile_editorial_review(base, packet, course), "resolutions": []}
    else:
        result = compile_editorial_verification(base, packet, course, prior)
    checks, findings = _compile_checks(value, course, source_semantics_final_rules(packet, reading))
    result["review"]["findings"].extend(findings)
    bad_ids = {
        x["rule_id"]
        for x in checks
        if not x["verified"] or x["status"] in ("CONTRADICTED", "INCOMPLETE", "SOURCE_READING_DISPUTED")
    }
    if prior is not None:
        prior_by_id = {x["issue_id"]: x for x in prior}
        for row in result["resolutions"]:
            rule_id = prior_by_id[row["issue_id"]].get("source_rule_id")
            if rule_id and rule_id not in {item["rule_id"] for item in checks}:
                row["verified"] = False
                row["verification_errors"].append("current_rule_not_checked_in_subset")
            elif rule_id in bad_ids:
                row["verified"] = False
                row["verification_errors"].append("current_rule_check_open")
    result["source_rule_checks"] = checks
    return result


def compile_rule_editorial_review(
    value: Any, packet: Any, course: dict[str, Any], reading: dict[str, Any], *, rule_ids: list[str] | None = None
) -> dict[str, Any]:
    return _compile(value, packet, course, reading, None, rule_ids)


def compile_rule_editorial_verification(
    value: Any,
    packet: Any,
    course: dict[str, Any],
    reading: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    rule_ids: list[str] | None = None,
) -> dict[str, Any]:
    return _compile(value, packet, course, reading, findings, rule_ids)
