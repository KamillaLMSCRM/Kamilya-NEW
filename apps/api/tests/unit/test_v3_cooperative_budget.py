import math

import pytest

from app.modules.ai.v3.cooperative_budget import CooperativeBudget, PreclaimYieldError


def test_count_and_claim_deadlines_have_distinct_reserves():
    budget = CooperativeBudget.start(now=1000.0)
    budget.before_count(now=1420.0)
    with pytest.raises(PreclaimYieldError):
        budget.before_count(now=1420.001)
    budget.before_claim(now=1480.0)
    with pytest.raises(PreclaimYieldError):
        budget.before_claim(now=1480.001)


def test_nonfinite_clock_fails_closed():
    with pytest.raises(ValueError):
        CooperativeBudget.start(now=math.nan)
    with pytest.raises(PreclaimYieldError):
        CooperativeBudget.start(now=0.0).before_count(now=math.nan)


def test_reserve_uses_actual_client_deadline():
    budget = CooperativeBudget.start(now=0.0)
    budget.before_count(now=0.0, generation_seconds=1000.0)
    with pytest.raises(PreclaimYieldError):
        budget.before_count(now=21.0, generation_seconds=1000.0)
    with pytest.raises(PreclaimYieldError):
        budget.before_claim(now=0.0, generation_seconds=1200.0)
    for invalid in [math.nan, math.inf, 0.0, -1.0, True]:
        with pytest.raises(PreclaimYieldError):
            budget.before_count(now=0.0, generation_seconds=invalid)
