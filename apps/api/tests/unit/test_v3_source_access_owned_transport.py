"""Actual V12 producer/decoder/journal/save DTO seam, including cold lookup replay."""

import copy
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.admin.runtime_configuration.catalog import default_snapshot
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V12_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from app.modules.ai.v3.source_access_config import pin_settings
from app.modules.ai.v3.source_access_contract import inner_format
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_literal_source_access import reference_case
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v3 import unit_course
from tests.unit.test_v3_simple_owned_transport_v8 import BetweenStagesError, fresh_journal


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["managed", "cloud"])
@pytest.mark.parametrize("interrupt", [0, 1, 3])
@pytest.mark.parametrize("added_lesson", [False, True])
async def test_v12_real_seam_with_lookup_and_no_duplicate_calls(monkeypatch, transport, interrupt, added_lesson):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V12_POLICY
    corpus, _ = reference_case()
    corpus = replace(corpus, tenant_id=journal.tenant_id)
    packet = build_practical_source_packet(corpus)
    client, calls = client_for(journal), []
    spec = importlib.util.spec_from_file_location(
        "lookup_runner", Path(__file__).resolve().parents[4] / "infra/codex-reserve/runner.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    def produce(fmt, messages):
        assert runner._checked_structured_format(fmt) == fmt["json_schema"]["schema"]
        props = fmt["json_schema"]["schema"]["properties"]
        body = json.loads(messages[1]["content"])
        base = props["base_group"]["enum"][0]
        outer = {k: props[k]["enum"][0] for k in ("source_fingerprint", "context_fingerprint", "base_group")}
        outer.update(lookup_ids=[], results=[])
        calls.append((base, props["context_fingerprint"]["enum"][0]))
        if ":plan:v11:" in base:
            if not body["reference_rows"]:
                outer["lookup_ids"] = [row["id"] for row in body["reference_index"]]
                return outer
            late = body["reference_index"][-1]["id"]
            if late in body["source_access"].get("deferred_lookup_ids", []):
                assert sum(len(row["text"]) for row in body["reference_rows"]) <= 30000
                outer["lookup_ids"] = [late]
                return outer
            assert "PRIVATE_LITERAL_029" in messages[1]["content"]
            assert "PRIVATE_LITERAL_028" not in messages[1]["content"]
            fmt_inner = inner_format(fmt)
            slices = body["source_slices"]
            inner = {
                "source_fingerprint": packet.fingerprint,
                "slices_fingerprint": fmt_inner["json_schema"]["schema"]["properties"]["slices_fingerprint"]["enum"][0],
                "title": "Course",
                "units": [
                    {
                        "id": "work",
                        "title": "Choose a module",
                        "primary_slices": [
                            r["id"] for r in slices if r["source_ref"] == "SRC1" and r.get("text", "").strip()
                        ],
                        "supporting_slices": [r["id"] for r in slices if r.get("reference_row_id")],
                    }
                ],
                "non_teaching": [
                    {
                        "slice_ids": [
                            r["id"]
                            for r in slices
                            if r["source_ref"] == "SRC2" and not r.get("reference_row_id") and r.get("text", "").strip()
                        ],
                        "reason": "Catalogue headings",
                    }
                ],
            }
        elif ":author-unit:" in base:
            inner = unit_course("SRC1", "Consultant checks the exact model. Preserve good body.")
        elif ":editor-joint:" in base:
            lessons = body["original_course"]["lessons"]
            editor_schema = inner_format(fmt)
            assert editor_schema['json_schema']['name'] == 'simple_course_block_editor_v3'
            assert editor_schema['json_schema']['schema']['properties']['added_lessons']['items']['properties']['questions']['minItems'] == 3
            inner = {
                "source_fingerprint": packet.fingerprint,
                "draft_fingerprint": body["draft_fingerprint"],
                "body_edits": [],
                "title_edits": [],
                "question_edits": [],
                "added_lessons": [],
                "lesson_sources": [{"lesson_id": r["id"], "source_refs": ["SRC1"]} for r in lessons],
                "source_questions": [],
            }
            if "finding_dispositions" in inner_format(fmt)["json_schema"]["schema"]["properties"]:
                inner["finding_dispositions"] = []
            if added_lesson:
                added = unit_course('SRC2', 'Read the specific reference row, not a guessed product.')['lessons'][0]
                added['id'] = 'added-reference-use'
                for i, question in enumerate(added['questions']):
                    question['id'] = f'added-question-{i}'
                inner['added_lessons'] = [added]
                inner['lesson_sources'].append({'lesson_id': added['id'], 'source_refs': ['SRC2']})
        elif ":repair-evidence:" in base:
            p = inner_format(fmt)["json_schema"]["schema"]["properties"]
            inner = {
                k: p[k]["enum"][0]
                for k in ("source_fingerprint", "draft_fingerprint", "result_fingerprint", "inventory_fingerprint")
            }
            inner["bindings"] = {k: v["enum"][0] for k, v in p["bindings"]["properties"].items()}
        else:
            p = inner_format(fmt)["json_schema"]["schema"]["properties"]
            inner = {
                "source_fingerprint": packet.fingerprint,
                "course_fingerprint": p["course_fingerprint"]["enum"][0],
                "summary": "Compared teaching and cards",
                "findings": [],
                "source_notes": [],
                "narrative_sources": {
                    k: [v["items"]["enum"][0]] for k, v in p["narrative_sources"]["properties"].items()
                },
            }
        outer["results"] = [inner]
        outer["extra_null"] = None
        return outer

    async def invoke(capability, *, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint()
        request = json.loads(client._prepared[capability])
        fmt = request["response_format"]
        raw = produce(fmt, request["messages"])
        envelope = {
            "model": client.model,
            "structured_output_policy": "typed-json-object-v1",
            "response_format_sha256": response_contract_hash(fmt),
            "choices": [{"message": {"content": json.dumps(raw)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 25},
        }
        result, _ = client._decode_response(json.dumps(envelope).encode(), client._prepared[capability])
        return result

    class Cloud:
        async def ainvoke(self, messages, *, response_format):
            return SimpleNamespace(content=json.dumps(produce(response_format, messages)), finish_reason="stop")

    monkeypatch.setattr(client, "invoke", invoke)
    monkeypatch.setattr("app.modules.ai.v3.service._practical_output_budget", AsyncMock(return_value=32768))
    args = dict(
        corpus=corpus,
        intent=CourseIntent(),
        generation_client=Cloud() if transport == "cloud" else None,
        extraction_journal=journal,
        direct_client=client if transport == "managed" else None,
        revision_policy=POLICY,
        review_policy=SIMPLE_COURSE_REVIEW_V12_POLICY,
        route_fingerprint="d" * 64,
        source_access_settings=pin_settings(default_snapshot()),
    )

    def cold():
        result = fresh_journal(journal, fake)
        result.expected_review_policy = SIMPLE_COURSE_REVIEW_V12_POLICY
        return result

    try:
        if interrupt:

            async def progress(_stage, completed, _total, _provider, _attempt):
                if completed == interrupt:
                    raise BetweenStagesError()

            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert len(calls) == interrupt
            args["extraction_journal"] = cold()
        first = await generate_v3_course_from_corpus(**args)
        previous = copy.deepcopy(calls)
        replay = await generate_v3_course_from_corpus(**{**args, "extraction_journal": cold()})
        assert calls == previous and len(calls) == len(set(calls))
        assert first.content == replay.content and first.assessment == replay.assessment
        access = first.diagnostics["simple_review"]["literal_source_access"]
        assert access["reference_rows"] == 30 and access["stages"][0]["lookup_ids"]
        assert "Preserve good body." in first.content.modules[0].lessons[0].content
        assert len(first.content.modules[0].lessons) == (2 if added_lesson else 1)
    finally:
        client.close()
