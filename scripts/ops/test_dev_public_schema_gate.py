from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("dev_public_schema_gate.py")
SPEC = importlib.util.spec_from_file_location("dev_public_schema_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_decide_schema_action_accepts_an_exact_public_revision() -> None:
    assert MODULE.decide_schema_action("0164", "0164", apply=False) == "verified"


def test_decide_schema_action_requires_explicit_apply_for_an_older_revision() -> None:
    with pytest.raises(MODULE.GateBlocked, match="schema_upgrade_required:0163:0164"):
        MODULE.decide_schema_action("0163", "0164", apply=False)

    assert MODULE.decide_schema_action("0163", "0164", apply=True) == "upgrade"


def test_safe_report_contains_no_database_identity_or_credentials() -> None:
    report = MODULE.safe_report(
        status="PASS",
        current_revision="0164",
        expected_revision="0164",
        applied=False,
        project_ref="abcdefghijklmnop",
    )

    assert report == {
        "status": "PASS",
        "target": "canonical_supabase_dev_public_schema",
        "current_revision": "0164",
        "expected_revision": "0164",
        "applied": False,
        "project_ref_sha256": "f39dac6cbaba535e2c207cd0cd8f154974223c848f727f98b3564cea569b41cf",
    }
    assert "host" not in report
    assert "url" not in report
