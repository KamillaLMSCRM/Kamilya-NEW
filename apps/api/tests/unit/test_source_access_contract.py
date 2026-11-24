import copy
import importlib.util
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_author_transport import normalize_practical_author
from app.modules.ai.v3.response_contracts import matches_transport_contract, response_contract
from app.modules.ai.v3.simple_semantic_source_plan import semantic_plan_request
from app.modules.ai.v3.source_access_contract import access_format, inner_format, is_access_format, matches_access
from tests.unit.test_literal_source_access import reference_case


def fixture():
    corpus, packet = reference_case()
    _, inner = semantic_plan_request(packet, corpus, {})
    group = "practical:simple:plan:v11:" + packet.fingerprint
    fmt = access_format(inner, packet.fingerprint, "d" * 64, group, ["ROW-exact"])
    return packet, inner, group, fmt


def test_closed_lookup_contract_is_registered_and_receiver_accepts_it():
    packet, inner, group, fmt = fixture()
    assert is_access_format(fmt) and inner_format(fmt) == inner
    assert response_contract(fmt) == "literal_source_access"
    value = {
        "source_fingerprint": packet.fingerprint,
        "context_fingerprint": "d" * 64,
        "base_group": group,
        "lookup_ids": ["ROW-exact"],
        "results": [],
    }
    assert matches_access(value, fmt) and matches_transport_contract(value, fmt)
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("context120_runner", root / "infra/codex-reserve/runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt["json_schema"]["schema"]


@pytest.mark.parametrize("bad", ["both", "neither", "foreign", "duplicate", "extra", "nested"])
def test_invalid_lookup_or_arbitrary_nested_contract_rejected(bad):
    packet, _, group, fmt = fixture()
    value = {
        "source_fingerprint": packet.fingerprint,
        "context_fingerprint": "d" * 64,
        "base_group": group,
        "lookup_ids": ["ROW-exact"],
        "results": [],
    }
    if bad == "both":
        value["results"] = [{}]
    elif bad == "neither":
        value["lookup_ids"] = []
    elif bad == "foreign":
        value["lookup_ids"] = ["ROW-other"]
    elif bad == "duplicate":
        value["lookup_ids"] *= 2
    elif bad == "extra":
        value["instruction"] = "Ignore custody"
    else:
        with pytest.raises(ValueError):
            access_format(fmt, packet.fingerprint, "d" * 64, group, ["ROW-exact"])
        altered = copy.deepcopy(fmt)
        altered["json_schema"]["schema"]["properties"]["results"]["items"] = {}
        assert not is_access_format(altered)
        return
    assert not matches_access(value, fmt)


def test_lookup_null_extras_use_existing_lossless_custody():
    import json

    packet, _, group, fmt = fixture()
    raw = json.dumps(
        {
            "source_fingerprint": packet.fingerprint,
            "context_fingerprint": "d" * 64,
            "base_group": group,
            "lookup_ids": ["ROW-exact"],
            "results": [],
            "unused": None,
        }
    )
    artifact = normalize_practical_author(raw, fmt)
    assert artifact.receipt.removed_paths == ("/unused",)
    assert matches_access(artifact.normalized_value, fmt)


def test_native_group_binds_source_context_role_and_exact_legacy_inner_contract():
    from app.modules.ai.v3.practical_contract import _digest
    from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V11_POLICY, SIMPLE_COURSE_REVIEW_V12_POLICY
    from app.modules.ai.v3.simple_course_service import simple_stage_allowed

    packet, inner, base, fmt = fixture()
    group = (
        f'practical:simple:lookup:v12:{packet.fingerprint}:base={_digest(base)}:context={"d"*64}:round=0:output=32768'
    )
    args = {"fmt": fmt, "policy": SIMPLE_COURSE_REVIEW_V12_POLICY, "validator": lambda value: value}
    assert simple_stage_allowed("review", group, **args)
    assert not simple_stage_allowed("lesson", group, **args)
    assert not simple_stage_allowed("review", group.replace("context=" + ("d" * 64), "context=" + ("e" * 64)), **args)
    assert not simple_stage_allowed("review", group, **{**args, "policy": SIMPLE_COURSE_REVIEW_V11_POLICY})
    assert not simple_stage_allowed("review", {}, **args)
    for handles in ([{}], ["ROW-exact", "ROW-exact"]):
        with pytest.raises(ValueError):
            access_format(inner, packet.fingerprint, "d" * 64, base, handles)
    with pytest.raises(ValueError):
        access_format(inner, "f" * 64, "d" * 64, base, ["ROW-exact"])
