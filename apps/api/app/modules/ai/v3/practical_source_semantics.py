"""Source-only semantic readings. Literal custody does not prove semantic truth."""

from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _digest, _validate_packet
from app.modules.ai.v3.practical_editorial_contract import _obj

READ_NAME = "v3_practical_source_semantics_v1"
VERIFY_NAME = "v3_practical_source_semantics_verify_v3"


def _rule(refs: list[str]) -> dict[str, Any]:
    t = {"type": "string"}
    return _obj(
        {
            "source_refs": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": refs}},
            "source_quote": t,
            "actor": t,
            "action": t,
            "object": t,
            "conditions": {"type": "array", "items": _obj({"applies_to": t, "expression": t})},
            "modality": t,
            "alternatives": {"type": "array", "items": t},
            "limits": {"type": "array", "items": t},
        }
    )


def _read_format(refs: list[str], fingerprint: str) -> dict[str, Any]:
    if (
        not refs
        or len(set(refs)) != len(refs)
        or any(type(x) is not str or not x for x in refs)
        or not isinstance(fingerprint, str)
        or len(fingerprint) != 64
    ):
        raise ValueError("source_semantics_format_invalid")
    t = {"type": "string"}
    links = {"type": "array", "minItems": 1, "items": {"type": "string", "enum": refs}}
    schema = _obj(
        {
            "source_fingerprint": {"type": "string", "enum": [fingerprint]},
            "sections": {
                "type": "array",
                "minItems": 1,
                "items": _obj({"section": t, "rules": {"type": "array", "items": _rule(refs)}}),
            },
            "uncertainties": {"type": "array", "items": _obj({"source_refs": links, "source_quote": t, "question": t})},
        }
    )
    return {"type": "json_schema", "json_schema": {"name": READ_NAME, "strict": True, "schema": schema}}


def source_semantics_format(packet: PracticalSourcePacket) -> dict[str, Any]:
    _validate_packet(packet)
    return _read_format([b.block_id for b in packet.blocks if b.text.strip()], packet.fingerprint)


def is_source_semantics_format(fmt: Any) -> bool:
    try:
        p = fmt["json_schema"]["schema"]["properties"]
        refs = p["uncertainties"]["items"]["properties"]["source_refs"]["items"]["enum"]
        return bool(fmt == _read_format(refs, p["source_fingerprint"]["enum"][0]))
    except (KeyError, TypeError, IndexError, ValueError, RecursionError):
        return False


def _rule_fields(rule: dict[str, Any]) -> bool:
    return (
        bool(rule["modality"].strip())
        and bool(rule["action"].strip() or rule["object"].strip())
        and len(rule["source_refs"]) == len(set(rule["source_refs"]))
        and all(c["applies_to"].strip() and c["expression"].strip() for c in rule["conditions"])
        and all(x.strip() for x in rule["alternatives"] + rule["limits"])
    )


def matches_source_semantics(value: Any, fmt: Any) -> bool:
    try:
        return bool(
            is_source_semantics_format(fmt)
            and _matches(value, fmt["json_schema"]["schema"])
            and all(s["section"].strip() and all(_rule_fields(r) for r in s["rules"]) for s in value["sections"])
            and all(
                u["question"].strip() and len(u["source_refs"]) == len(set(u["source_refs"]))
                for u in value["uncertainties"]
            )
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def _custody(row: dict[str, Any], packet: PracticalSourcePacket) -> bool:
    blocks = {b.block_id: b.text for b in packet.blocks}
    return bool(
        row["source_quote"].strip() and any(row["source_quote"] in blocks.get(ref, "") for ref in row["source_refs"])
    )


def compile_source_semantics(value: Any, packet: PracticalSourcePacket) -> dict[str, Any]:
    if not matches_source_semantics(value, source_semantics_format(packet)):
        raise ValueError("source_semantics_response_invalid")
    original = copy.deepcopy(value)
    sections = []
    index = 0
    for section in original["sections"]:
        rules = []
        for rule in section["rules"]:
            index += 1
            rules.append({"rule_id": f"R{index}", **copy.deepcopy(rule), "custody_valid": _custody(rule, packet)})
        sections.append({"section": section["section"], "rules": rules})
    uncertainties = [{**copy.deepcopy(u), "custody_valid": _custody(u, packet)} for u in original["uncertainties"]]
    return {
        "source_fingerprint": packet.fingerprint,
        "reading_fingerprint": _digest(original),
        "original": original,
        "sections": sections,
        "uncertainties": uncertainties,
    }


def _verify_format(refs: list[str], source_fp: str, reading_fp: str, ids: list[str]) -> dict[str, Any]:
    if not ids or len(ids) != len(set(ids)) or any(type(x) is not str or not x for x in ids):
        raise ValueError("source_semantics_verification_identity_invalid")
    _read_format(refs, source_fp)
    if type(reading_fp) is not str or len(reading_fp) != 64:
        raise ValueError("source_semantics_verification_identity_invalid")
    check = _obj(
        {
            "rule_id": {"type": "string", "enum": ids},
            "status": {"type": "string", "enum": ["SUPPORTED", "REVISE", "SOURCE_AMBIGUITY"]},
            "reason": {"type": "string"},
            "replacement": {"type": "array", "maxItems": 1, "items": _rule(refs)},
            "source_question": {"type": "string"},
        }
    )
    additional_rule = _rule(refs)
    additional_rule["properties"]["source_refs"]["items"].pop("enum")
    schema = _obj(
        {
            "source_fingerprint": {"type": "string", "enum": [source_fp]},
            "reading_fingerprint": {"type": "string", "enum": [reading_fp]},
            "rule_checks": {"type": "array", "minItems": len(ids), "maxItems": len(ids), "items": check},
            "additional_rules": {
                "type": "array",
                "items": _obj({"section": {"type": "string"}, "rule": additional_rule}),
            },
        }
    )
    return {"type": "json_schema", "json_schema": {"name": VERIFY_NAME, "strict": True, "schema": schema}}


def _bound_reading(packet: PracticalSourcePacket, reading: dict[str, Any]) -> list[str]:
    _validate_packet(packet)
    try:
        if compile_source_semantics(reading["original"], packet) != reading:
            raise ValueError
        return [r["rule_id"] for s in reading["sections"] for r in s["rules"]]
    except (KeyError, TypeError, ValueError):
        raise ValueError("source_semantics_reading_identity_invalid") from None


def source_semantics_verification_format(packet: PracticalSourcePacket, reading: dict[str, Any]) -> dict[str, Any]:
    return _verify_format(
        [b.block_id for b in packet.blocks if b.text.strip()],
        packet.fingerprint,
        reading["reading_fingerprint"],
        _bound_reading(packet, reading),
    )


def is_source_semantics_verification_format(fmt: Any) -> bool:
    try:
        p = fmt["json_schema"]["schema"]["properties"]
        cp = p["rule_checks"]["items"]["properties"]
        refs = cp["replacement"]["items"]["properties"]["source_refs"]["items"]["enum"]
        return bool(
            fmt
            == _verify_format(
                refs, p["source_fingerprint"]["enum"][0], p["reading_fingerprint"]["enum"][0], cp["rule_id"]["enum"]
            )
        )
    except (KeyError, TypeError, IndexError, ValueError, RecursionError):
        return False


def matches_source_semantics_verification(value: Any, fmt: Any) -> bool:
    try:
        if not is_source_semantics_verification_format(fmt):
            return False
        if not _matches(value, fmt["json_schema"]["schema"]):
            return False
        ids = fmt["json_schema"]["schema"]["properties"]["rule_checks"]["items"]["properties"]["rule_id"]["enum"]
        checks = value["rule_checks"]
        if {r["rule_id"] for r in checks} != set(ids) or len(checks) != len(ids):
            return False
        if any(not row["section"].strip() or not _rule_fields(row["rule"]) for row in value["additional_rules"]):
            return False
        for row in checks:
            if not row["reason"].strip():
                return False
            status, replacement, question = row["status"], row["replacement"], row["source_question"]
            if status == "SUPPORTED" and (replacement or question.strip()):
                return False
            if status == "REVISE" and (len(replacement) != 1 or not _rule_fields(replacement[0]) or question.strip()):
                return False
            if status == "SOURCE_AMBIGUITY" and (replacement or not question.strip()):
                return False
        return True
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def _resolve_interpretation_quote(
    rule: dict[str, Any], packet: PracticalSourcePacket
) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    """Resolve quote custody only; never judge or rewrite the rule's meaning."""
    effective = copy.deepcopy(rule)
    blocks = {block.block_id: block.text for block in packet.blocks if block.text.strip()}
    refs = rule["source_refs"]
    if not refs or any(ref not in blocks for ref in refs):
        return effective, False, {}
    if _custody(rule, packet):
        return effective, True, {}
    effective["source_quote"] = blocks[refs[0]]
    return (
        effective,
        True,
        {
            "model_quote_valid": False,
            "quote_origin": "FIRST_OWNED_SOURCE_BLOCK",
            "generated_source_quote": rule["source_quote"],
        },
    )


def compile_source_semantics_verification(
    value: Any, packet: PracticalSourcePacket, reading: dict[str, Any]
) -> dict[str, Any]:
    if not matches_source_semantics_verification(value, source_semantics_verification_format(packet, reading)):
        raise ValueError("source_semantics_verification_response_invalid")
    checks = {r["rule_id"]: r for r in value["rule_checks"]}
    interpretations = []
    for section in reading["sections"]:
        for original in section["rules"]:
            check = checks[original["rule_id"]]
            status = check["status"]
            original_rule = {k: copy.deepcopy(v) for k, v in original.items() if k not in ("rule_id", "custody_valid")}
            chosen = check["replacement"][0] if status == "REVISE" else original_rule
            metadata: dict[str, Any]
            if status == "SOURCE_AMBIGUITY":
                effective, valid, metadata = original_rule, original["custody_valid"], {}
            else:
                effective, valid, metadata = _resolve_interpretation_quote(chosen, packet)
            interpretations.append(
                {
                    "section": section["section"],
                    "rule_id": original["rule_id"],
                    "rule": copy.deepcopy(effective if valid else original_rule),
                    "status": status if valid else "UNVERIFIED",
                    "custody_valid": valid,
                    "reason": check["reason"],
                    "source_question": check["source_question"] if valid else "",
                    **metadata,
                }
            )
    for index, added in enumerate(value["additional_rules"], start=len(interpretations) + 1):
        effective, valid, metadata = _resolve_interpretation_quote(added["rule"], packet)
        interpretations.append(
            {
                "section": added["section"],
                "rule_id": f"R{index}",
                "rule": effective,
                "status": "SUPPORTED" if valid else "UNVERIFIED",
                "custody_valid": valid,
                "reason": "Additional rule identified by independent source verification.",
                "source_question": "",
                "provenance": "SOURCE_VERIFIER_ADDITION",
                **metadata,
            }
        )
    uncertainties = copy.deepcopy(reading["uncertainties"])
    verified_fingerprint = _digest([packet.fingerprint, reading["reading_fingerprint"], interpretations, uncertainties])
    return {
        "source_fingerprint": packet.fingerprint,
        "reading_fingerprint": reading["reading_fingerprint"],
        "verified_reading_fingerprint": verified_fingerprint,
        "original_reading": copy.deepcopy(reading),
        "raw_checks": copy.deepcopy(value),
        "interpretations": interpretations,
        "uncertainties": uncertainties,
    }


COMPLETENESS_NAME = "v3_practical_source_completeness_v1"


def _completeness_format(refs: list[str], source_fp: str, verified_fp: str) -> dict[str, Any]:
    _read_format(refs, source_fp)
    if type(verified_fp) is not str or len(verified_fp) != 64:
        raise ValueError("source_completeness_identity_invalid")
    schema = _obj(
        {
            "source_fingerprint": {"type": "string", "enum": [source_fp]},
            "verified_reading_fingerprint": {"type": "string", "enum": [verified_fp]},
            "additional_rules": {"type": "array", "items": _obj({"section": {"type": "string"}, "rule": _rule(refs)})},
        }
    )
    return {"type": "json_schema", "json_schema": {"name": COMPLETENESS_NAME, "strict": True, "schema": schema}}


def source_completeness_format(packet: PracticalSourcePacket, verified: dict[str, Any]) -> dict[str, Any]:
    source_semantics_final_rules(packet, verified)
    if "completeness_lineage" in verified:
        raise ValueError("source_completeness_already_applied")
    return _completeness_format(
        [b.block_id for b in packet.blocks if b.text.strip()],
        packet.fingerprint,
        verified["verified_reading_fingerprint"],
    )


def is_source_completeness_format(fmt: Any) -> bool:
    try:
        props = fmt["json_schema"]["schema"]["properties"]
        refs = props["additional_rules"]["items"]["properties"]["rule"]["properties"]["source_refs"]["items"]["enum"]
        return bool(
            fmt
            == _completeness_format(
                refs, props["source_fingerprint"]["enum"][0], props["verified_reading_fingerprint"]["enum"][0]
            )
        )
    except (KeyError, TypeError, IndexError, ValueError, RecursionError):
        return False


def matches_source_completeness(value: Any, fmt: Any) -> bool:
    try:
        return bool(
            is_source_completeness_format(fmt)
            and _matches(value, fmt["json_schema"]["schema"])
            and all(row["section"].strip() and _rule_fields(row["rule"]) for row in value["additional_rules"])
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def compile_source_completeness(value: Any, packet: PracticalSourcePacket, verified: dict[str, Any]) -> dict[str, Any]:
    if not matches_source_completeness(value, source_completeness_format(packet, verified)):
        raise ValueError("source_completeness_response_invalid")
    result = copy.deepcopy(verified)
    interpretations = result["interpretations"]
    for index, added in enumerate(value["additional_rules"], start=len(interpretations) + 1):
        effective, valid, metadata = _resolve_interpretation_quote(added["rule"], packet)
        interpretations.append(
            {
                "section": added["section"],
                "rule_id": f"R{index}",
                "rule": effective,
                "status": "SUPPORTED" if valid else "UNVERIFIED",
                "custody_valid": valid,
                "reason": "Additional rule identified by independent source completeness review.",
                "source_question": "",
                "provenance": "SOURCE_COMPLETENESS_ADDITION",
                **metadata,
            }
        )
    result["verified_reading_fingerprint"] = _digest(
        [packet.fingerprint, result["reading_fingerprint"], interpretations, result["uncertainties"]]
    )
    result["completeness_lineage"] = {"previous": copy.deepcopy(verified), "raw": copy.deepcopy(value)}
    return result


def source_condition_id(rule_id: str, index: int) -> str:
    """Stable condition label scoped to a rule and its bound reading."""
    if type(rule_id) is not str or not rule_id or type(index) is not int or index < 0:
        raise ValueError("source_condition_identity_invalid")
    return f"{rule_id}.C{index + 1}"


def source_semantics_context(result: dict[str, Any], model_view: Any = None) -> str:
    compact = {
        "source_fingerprint": result["source_fingerprint"],
        "reading_fingerprint": result["verified_reading_fingerprint"],
        "original_reading_fingerprint": result["reading_fingerprint"],
        "interpretations": [
            {
                **{
                    k: copy.deepcopy(v)
                    for k, v in item.items()
                    if k not in ("rule", "generated_source_quote", "model_quote_valid", "quote_origin")
                },
                "rule": {k: copy.deepcopy(v) for k, v in item["rule"].items() if k != "source_quote"},
            }
            for item in result["interpretations"]
        ],
        "uncertainties": [
            {k: copy.deepcopy(v) for k, v in row.items() if k != "source_quote"} for row in result["uncertainties"]
        ],
    }
    for item in compact["interpretations"]:
        item["rule"]["conditions"] = [
            {"condition_id": source_condition_id(item["rule_id"], index), **condition}
            for index, condition in enumerate(item["rule"]["conditions"])
        ]
    if model_view is not None:
        compact = model_view.encode(compact)
    return (
        "\nINDEPENDENT_PRE_COURSE_READING_JSON\n"
        + json.dumps(compact, ensure_ascii=False, sort_keys=True)
        + "\nIndependent pre-course interpretation, not source authority. Original source and confirmed decisions govern; literal custody is not semantic proof.\n"
    )


def source_semantics_final_rules(packet: PracticalSourcePacket, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return identity-checked rules and all verifier reasons, not certified facts."""
    try:
        if "completeness_lineage" in result:
            lineage = result["completeness_lineage"]
            expected = compile_source_completeness(lineage["raw"], packet, lineage["previous"])
        else:
            expected = compile_source_semantics_verification(result["raw_checks"], packet, result["original_reading"])
        if expected != result:
            raise ValueError
        return copy.deepcopy(result["interpretations"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("source_semantics_result_identity_invalid") from None
