from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.critical_journey_gate import load_contract  # noqa: E402

CONTRACT_PATH = REPO_ROOT / "docs" / "critical-journeys" / "corporate-readiness.json"


def test_corporate_journey_contract_covers_end_to_end_acceptance() -> None:
    (journey,) = load_contract(CONTRACT_PATH)

    assert journey.journey_id == "CORPORATE-READINESS-01"
    assert len(journey.required_tests) == 9
    assert len(journey.database_tests) == 9
    assert len(journey.runtime_gates) == 4

    joined = " ".join(journey.invariants).lower()
    for required_step in (
        "methodologist assigns",
        "failed mandatory quiz",
        "successful retry",
        "confirmation pdf",
        "signed scan",
        "methodologist can review",
        "evidence package includes",
        "manual reassignment",
        "mandatory training",
        "training-log rows and csv export",
        "dashboard statistics",
        "action center",
    ):
        assert required_step in joined
