"""Isolated producer protocol tests; no CLI or provider execution."""
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner(tmp_path):
    mod = load("reserve_structured_runner", "infra/codex-reserve/runner.py")
    binary = Path(sys.executable)
    return mod, mod.CodexRunner(binary, tmp_path, hashlib.sha256(binary.read_bytes()).hexdigest())


def fmt():
    return load("author_schema", "apps/api/app/modules/ai/v3/author_response_schema.py").lesson_author_response_format()


def payload(**changes):
    return {"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "example"}],
            "max_tokens": 100, **changes}


def output(text, usage=True, count=5):
    events = [{"type": "item.completed", "item": {"type": "agent_message", "text": text}},
              {"type": "turn.completed", **({"usage": {"input_tokens": 12, "output_tokens": count}} if usage else {})}]
    return b"\n".join(json.dumps(event, ensure_ascii=False).encode() for event in events)


def test_structured_roundtrip_schema_file_and_one_call(runner, monkeypatch):
    mod, worker = runner
    form = fmt()
    item = {"lesson_id": "one", "title": "тест", "module_title": "m",
            "content": ('# Заголовок\n"цитата" \\ path\n' * 100),
            "cases": [{"nested": ["quote \" and newline\n", "кириллица"]}]}
    seen = []
    async def run(args, stdin, *, cwd, timeout):
        seen.append(args)
        assert json.loads((cwd / "response-schema.json").read_text(encoding="utf-8")) == form["json_schema"]["schema"]
        assert "requested JSON object directly" in " ".join(args)
        return 0, output(json.dumps(item, ensure_ascii=False)), b""
    monkeypatch.setattr(worker, "_run", run)
    result = asyncio.run(worker.complete(payload(response_format=form, structured_output_policy=mod.STRUCTURED_POLICY)))
    assert len(seen) == 1 and json.loads(result["choices"][0]["message"]["content"]) == item
    expected = hashlib.sha256(json.dumps(form, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                         allow_nan=False).encode()).hexdigest()
    assert result["structured_output_policy"] == mod.STRUCTURED_POLICY and result["response_format_sha256"] == expected


def test_legacy_format_and_command_unchanged(runner, monkeypatch):
    mod, worker = runner
    async def run(args, stdin, *, cwd, timeout):
        assert json.loads((cwd / "response-schema.json").read_text(encoding="utf-8")) == mod.OUTPUT_SCHEMA
        assert "content field of the required JSON envelope" in " ".join(args)
        return 0, output(json.dumps({"content": '{"hello":"world"}'})), b""
    monkeypatch.setattr(worker, "_run", run)
    result = asyncio.run(worker.complete(payload(response_format={"type": "json_object"})))
    assert result == {"model": mod.MODEL, "choices": [{"message": {"role": "assistant", "content": '{"hello":"world"}'}}],
                      "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}}
    assert worker.command(Path("schema")) == worker.command(Path("schema"), structured=False)


@pytest.mark.parametrize("case", ["missing_policy", "bad_policy", "missing_format", "not_strict", "open_object", "ref", "not_required", "bad_min", "extra_keyword", "oversize", "deep"])
def test_bad_schema_or_mode_rejected_before_call(runner, monkeypatch, case):
    mod, worker = runner
    form = fmt()
    fields = {"response_format": form, "structured_output_policy": mod.STRUCTURED_POLICY}
    schema = form["json_schema"]["schema"]
    if case == "missing_policy":
        del fields["structured_output_policy"]
    elif case == "bad_policy":
        fields["structured_output_policy"] = "unknown"
    elif case == "missing_format":
        del fields["response_format"]
    elif case == "not_strict":
        form["json_schema"]["strict"] = 1
    elif case == "open_object":
        schema["additionalProperties"] = True
    elif case == "ref":
        schema["properties"]["content"] = {"$ref": "https://invalid.example/schema"}
    elif case == "not_required":
        schema["required"].pop()
    elif case == "bad_min":
        schema["properties"]["cases"]["minItems"] = True
    elif case == "extra_keyword":
        schema["properties"]["title"]["pattern"] = ".*"
    elif case == "oversize":
        form["json_schema"]["name"] = "x" * 70000
    else:
        child = {"type": "string"}
        for _ in range(15):
            child = {"type": "array", "items": child}
        schema["properties"]["content"] = child
    run = AsyncMock(side_effect=AssertionError("must not call"))
    monkeypatch.setattr(worker, "_run", run)
    with pytest.raises(mod.RunnerError, match="invalid_input"):
        asyncio.run(worker.complete(payload(**fields)))
    run.assert_not_awaited()


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '[1]', '{bad'])
def test_invalid_structured_result_fails_closed(runner, text):
    mod, _ = runner
    with pytest.raises(mod.RunnerError, match="protocol_mismatch"):
        mod.CodexRunner.parse_result(output(text), structured=True)


@pytest.mark.parametrize("usage,count", [(False, 5), (True, 101)])
def test_usage_limit_does_not_reinvoke(runner, monkeypatch, usage, count):
    mod, worker = runner
    run = AsyncMock(return_value=(0, output('{"x":"ok"}', usage, count), b""))
    monkeypatch.setattr(worker, "_run", run)
    with pytest.raises(mod.RunnerError, match="output_limit"):
        asyncio.run(worker.complete(payload(response_format=fmt(), structured_output_policy=mod.STRUCTURED_POLICY)))
    assert run.await_count == 1
