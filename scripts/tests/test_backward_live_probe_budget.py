"""The live quality probe must stop before an unauthorized paid request."""

import json
import sys
from pathlib import Path

import pytest

from scripts.tests.probe_backward_course_live import BudgetLedger, BudgetStop, BoundedDeepSeek, LocalGLM


def test_budget_reserves_worst_case_before_request_and_survives_restart(tmp_path):
    path = tmp_path / "budget.json"
    first = BudgetLedger(path, cap_micro_usd=2_000_000, prior_micro_usd=70_000)
    estimate = first.reserve(input_bytes=20_000, max_output_tokens=8_192)
    assert estimate >= 15_000
    second = BudgetLedger(path, cap_micro_usd=2_000_000, prior_micro_usd=70_000)
    assert second.reserved_micro_usd == 70_000 + estimate
    assert second.requests == 1


def test_budget_rejects_request_without_modifying_existing_ledger(tmp_path):
    path = tmp_path / "budget.json"
    ledger = BudgetLedger(path, cap_micro_usd=80_000, prior_micro_usd=70_000)
    before = path.read_bytes()
    with pytest.raises(BudgetStop):
        ledger.reserve(input_bytes=20_000, max_output_tokens=8_192)
    assert path.read_bytes() == before


def test_budget_rejects_changed_approval_or_unreadable_ledger(tmp_path):
    path = tmp_path / "budget.json"
    BudgetLedger(path, cap_micro_usd=2_000_000, prior_micro_usd=70_000)
    with pytest.raises(BudgetStop):
        BudgetLedger(path, cap_micro_usd=3_000_000, prior_micro_usd=70_000)
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(BudgetStop):
        BudgetLedger(path, cap_micro_usd=2_000_000, prior_micro_usd=70_000)


def test_budget_fails_closed_when_another_probe_holds_lock(tmp_path):
    path = tmp_path / "budget.json"
    ledger = BudgetLedger(path, cap_micro_usd=2_000_000, prior_micro_usd=70_000)
    path.with_suffix(".lock").write_text("held", encoding="utf-8")
    with pytest.raises(BudgetStop, match="locked"):
        ledger.reserve(input_bytes=100, max_output_tokens=100)
    assert ledger.requests == 0


@pytest.mark.asyncio
async def test_probe_mirrors_one_production_json_syntax_correction(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "apps" / "api"))
    class Response:
        status_code = 200

        def __init__(self, content):
            self.content = content

        def json(self):
            return {"choices": [{"message": {"content": self.content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10}}

    class FakeClient:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            type(self).calls += 1
            return Response("{invalid" if type(self).calls == 1 else '{"ok":true}')

    from scripts.tests import probe_backward_course_live as probe

    monkeypatch.setattr(probe.httpx, "AsyncClient", FakeClient)
    ledger = BudgetLedger(tmp_path / "budget.json", cap_micro_usd=2_000_000,
                          prior_micro_usd=70_000)
    client = BoundedDeepSeek("synthetic-key", max_calls=2, ledger=ledger)
    result = await client.ainvoke_validated(
        [{"role": "user", "content": '{"task":"assessment_repair"}'}],
        parser=json.loads, repair_json_syntax=True,
    )
    assert result.value == {"ok": True}
    assert result.attempt_count == 2
    assert client.calls == ledger.requests == 2


@pytest.mark.asyncio
async def test_closed_probe_rejects_a_new_paid_run_before_loading_credentials(monkeypatch):
    from scripts.tests import probe_backward_course_live as probe

    monkeypatch.setattr(sys, "argv", [
        "probe", "--allow-paid", "--approval-id", "2026-09-23-reapproved-2usd",
    ])
    with pytest.raises(SystemExit, match="2"):
        await probe.main()


@pytest.mark.asyncio
async def test_local_glm_uses_exact_model_and_long_timeout_without_paid_ledger(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "apps" / "api"))
    from scripts.tests import probe_backward_course_live as probe

    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen["timeout"] = kwargs["timeout"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            seen["url"] = url
            seen["payload"] = kwargs["json"]

            class Response:
                status_code = 200

                def json(self):
                    return {"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 10, "completion_tokens": 10}}

            return Response()

    monkeypatch.setattr(probe.httpx, "AsyncClient", FakeClient)
    client = LocalGLM(max_calls=2)
    result = await client.ainvoke_validated(
        [{"role": "user", "content": '{"task":"lesson"}'}], parser=json.loads,
    )
    assert result.value == {"ok": True}
    assert result.model_id == "GLM-5.3-Flash-EXL3"
    assert seen["url"] == "http://10.66.66.28:8888/v1/chat/completions"
    assert seen["payload"]["model"] == "GLM-5.3-Flash-EXL3"
    assert seen["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["timeout"] >= 600
    assert client.calls == 1


@pytest.mark.asyncio
async def test_local_glm_low_reasoning_is_explicit_and_bounded(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "apps" / "api"))
    from scripts.tests import probe_backward_course_live as probe

    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            seen.update(kwargs["json"])

            class Response:
                status_code = 200

                def json(self):
                    return {"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}]}

            return Response()

    monkeypatch.setattr(probe.httpx, "AsyncClient", FakeClient)
    client = LocalGLM(max_calls=1, reasoning="low")
    await client.ainvoke_validated([{"role": "user", "content": "{}"}], parser=json.loads)
    assert seen["chat_template_kwargs"] == {"reasoning_effort": "low"}
    with pytest.raises(BudgetStop):
        await client.ainvoke_validated([{"role": "user", "content": "{}"}], parser=json.loads)
