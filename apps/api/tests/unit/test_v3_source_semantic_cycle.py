import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_semantic_cycle import prepare_source_semantics
from app.modules.ai.v3.practical_source_semantics import compile_source_semantics, source_semantics_final_rules
from tests.unit.test_v3_source_semantics import packet, reading, verification


@pytest.mark.asyncio
async def test_source_only_two_stages_receipts_and_binding():
    p = packet()
    view = PracticalModelView(p)
    raw = reading(p)
    compiled = compile_source_semantics(raw, p)
    checks = verification(p, compiled)
    calls = []

    async def call(name, group, messages, fmt, validator):
        calls.append((name, group, messages, fmt))
        if len(calls) == 1:
            value = raw
        elif len(calls) == 2:
            value = checks
        else:
            value = {
                "source_fingerprint": p.fingerprint,
                "verified_reading_fingerprint": fmt["json_schema"]["schema"]["properties"][
                    "verified_reading_fingerprint"
                ]["enum"][0],
                "additional_rules": [],
            }
        validator(copy.deepcopy(value))
        return copy.deepcopy(value)

    context = "SOURCE-ONLY-TEXT\nCONFIRMED-REFERENCE-DECISION"
    result = await prepare_source_semantics(p, context, view, call)
    assert len(calls) == 3 and all(c[0] == "review" for c in calls)
    assert calls[0][1] == "practical:source-semantics:read:v33:" + p.fingerprint
    assert calls[1][1] == "practical:source-semantics:verify:v33:" + compiled["reading_fingerprint"]
    assert result["original_reading"]["original"] == raw and result["raw_checks"] == checks
    assert result["reading_fingerprint"] == _digest(raw) and source_semantics_final_rules(p, result)
    assert all(x["reason"] == "Condition modifies the credit." for x in result["interpretations"])
    for _, _, messages, _ in calls:
        body = json.dumps(messages, ensure_ascii=False)
        assert context in messages[1]["content"] and "COURSE_JSON" not in body and "answer_keys" not in body
        assert "CONFIRMED-REFERENCE-DECISION" in body
    assert "SRC1" in calls[1][2][1]["content"]
    assert "R1" in calls[1][2][1]["content"]


@pytest.mark.asyncio
async def test_unknown_transport_not_retried():
    p = packet()
    calls = []

    async def call(*args):
        calls.append(args)
        raise TimeoutError("unknown transport")

    with pytest.raises(TimeoutError):
        await prepare_source_semantics(p, "source", PracticalModelView(p), call)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_bad_custody_does_not_become_owner_ambiguity_or_destroy_sibling():
    p = packet()
    view = PracticalModelView(p)
    raw = reading(p)
    raw["sections"][0]["rules"][0]["source_quote"] = "not an actual source quote"
    compiled = compile_source_semantics(raw, p)
    checks = verification(p, compiled)
    checks["rule_checks"][0].update(status="SOURCE_AMBIGUITY", source_question="Which meaning?")
    calls = []

    async def call(name, group, messages, fmt, validator):
        calls.append(group)
        if len(calls) == 1:
            value = raw
        elif len(calls) == 2:
            value = checks
        else:
            value = {
                "source_fingerprint": p.fingerprint,
                "verified_reading_fingerprint": fmt["json_schema"]["schema"]["properties"][
                    "verified_reading_fingerprint"
                ]["enum"][0],
                "additional_rules": [],
            }
        validator(value)
        return copy.deepcopy(value)

    result = await prepare_source_semantics(p, "source plus approved context", view, call)
    assert result["interpretations"][0]["status"] == "UNVERIFIED"
    assert result["interpretations"][0]["source_question"] == ""
    assert result["interpretations"][1]["status"] == "SUPPORTED"
    assert result["uncertainties"] == compiled["uncertainties"]


@pytest.mark.asyncio
async def test_bad_second_receipt_fails_without_retry():
    p = packet()
    raw = reading(p)
    compiled = compile_source_semantics(raw, p)
    checks = verification(p, compiled)
    checks["reading_fingerprint"] = "0" * 64
    calls = []

    async def call(name, group, messages, fmt, validator):
        calls.append(group)
        value = raw if len(calls) == 1 else checks
        validator(value)
        return value

    with pytest.raises(ValueError):
        await prepare_source_semantics(p, "source", PracticalModelView(p), call)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_grammar_stage_refuses_additions_without_calling_completeness():
    p = packet()
    view = PracticalModelView(p)
    raw = reading(p)
    compiled = compile_source_semantics(raw, p)
    checks = verification(p, compiled)
    checks["additional_rules"] = [{"section": "forbidden", "rule": raw["sections"][0]["rules"][0]}]
    calls = []

    async def call(name, group, messages, fmt, validator):
        calls.append(group)
        value = raw if len(calls) == 1 else checks
        validator(value)
        return value

    with pytest.raises(ValueError, match="source_grammar_additions_forbidden"):
        await prepare_source_semantics(p, "source", view, call)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unknown_completeness_outcome_not_retried():
    p = packet()
    raw = reading(p)
    compiled = compile_source_semantics(raw, p)
    checks = verification(p, compiled)
    calls = []

    async def call(name, group, messages, fmt, validator):
        calls.append(group)
        if len(calls) == 3:
            raise TimeoutError("unknown completeness outcome")
        value = raw if len(calls) == 1 else checks
        validator(value)
        return value

    with pytest.raises(TimeoutError):
        await prepare_source_semantics(p, "source", PracticalModelView(p), call)
    assert len(calls) == 3 and ":complete:v33:" in calls[-1]
