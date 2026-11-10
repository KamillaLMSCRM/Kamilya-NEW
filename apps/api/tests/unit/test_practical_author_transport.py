import copy
import dataclasses
import json

import pytest

from app.modules.ai.v3.practical_author_transport import normalize_practical_author, validate_practical_author_artifact
from app.modules.ai.v3.practical_contract import _course_format


@pytest.fixture
def fmt():
    return _course_format(["SRC1", "SRC2"])


@pytest.fixture
def course():
    return {
        "title": "Course",
        "lessons": [
            {
                "id": "lesson",
                "title": "Lesson",
                "content": "Content",
                "questions": [
                    {
                        "id": "q",
                        "prompt": "Question?",
                        "choices": ["A", "B", "C"],
                        "correct_index": 0,
                        "explanation": "Reason",
                        "source_refs": ["SRC1"],
                    }
                ],
            }
        ],
    }


def test_null_extras_are_removed_only_at_declared_object_levels(fmt, course):
    course["unknown/root~"] = None
    course["lessons"][0]["extra"] = None
    course["lessons"][0]["questions"][0]["other"] = None
    raw = json.dumps(course, ensure_ascii=False)
    original = copy.deepcopy(course)
    original_format = copy.deepcopy(fmt)
    artifact = normalize_practical_author(raw, fmt)
    assert course == original
    assert fmt == original_format
    assert artifact.receipt.removed_paths == ("/lessons/0/extra", "/lessons/0/questions/0/other", "/unknown~1root~0")
    assert "unknown/root~" not in artifact.normalized_value
    assert len(artifact.normalized_value["lessons"][0]["questions"][0]["choices"]) == 3
    assert validate_practical_author_artifact(artifact, fmt)
    assert raw not in repr(artifact)


@pytest.mark.parametrize(
    "fault",
    ["nonnull_extra", "declared_null", "missing", "invalid_choices", "invalid_key", "invalid_refs", "array_null"],
)
def test_invalid_declared_or_nonnull_content_is_never_repaired(fmt, course, fault):
    question = course["lessons"][0]["questions"][0]
    if fault == "nonnull_extra":
        question["extra"] = {"nested": None}
    elif fault == "declared_null":
        question["explanation"] = None
    elif fault == "missing":
        del question["prompt"]
    elif fault == "invalid_choices":
        question["choices"] = ["A", "a", "C"]
    elif fault == "invalid_key":
        question["correct_index"] = 3
    elif fault == "invalid_refs":
        question["source_refs"] = ["SRC3"]
    else:
        question["choices"][0] = None
    with pytest.raises(ValueError):
        normalize_practical_author(json.dumps(course), fmt)


@pytest.mark.parametrize(
    "raw",
    [
        '{"title":"x","title":"y"}',
        '{"x":{"a":1,"a":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":1e999}',
        "[]",
        "null",
        "{",
    ],
)
def test_strict_parse_rejects_invalid_json_duplicate_and_nonfinite(fmt, raw):
    with pytest.raises(ValueError):
        normalize_practical_author(raw, fmt)


def test_unchanged_has_explicit_empty_receipt_and_is_immutable(fmt, course):
    artifact = normalize_practical_author(json.dumps(course), fmt)
    assert artifact.receipt.removed_paths == ()
    value = artifact.normalized_value
    value["lessons"].clear()
    assert artifact.normalized_value == course
    with pytest.raises(dataclasses.FrozenInstanceError):
        artifact.normalized_text = "changed"
    assert validate_practical_author_artifact(artifact, fmt)


def test_tampering_or_unknown_format_is_rejected(fmt, course):
    course["drop"] = None
    artifact = normalize_practical_author(json.dumps(course), fmt)
    for candidate in [
        dataclasses.replace(artifact, raw_text="{}"),
        dataclasses.replace(artifact, normalized_text="{}"),
        dataclasses.replace(artifact, receipt=dataclasses.replace(artifact.receipt, raw_sha256="0" * 64)),
        dataclasses.replace(artifact, receipt=dataclasses.replace(artifact.receipt, normalized_sha256="0" * 64)),
        dataclasses.replace(artifact, receipt=dataclasses.replace(artifact.receipt, format_sha256="0" * 64)),
        dataclasses.replace(artifact, receipt=dataclasses.replace(artifact.receipt, removed_paths=("/bad",))),
    ]:
        assert not validate_practical_author_artifact(candidate, fmt)
    other = copy.deepcopy(fmt)
    other["json_schema"]["name"] = "other"
    with pytest.raises(ValueError):
        normalize_practical_author(json.dumps(course), other)
    assert not validate_practical_author_artifact(artifact, other)


def test_receipt_binds_exact_schema_even_when_references_remain_valid(fmt, course):
    artifact = normalize_practical_author(json.dumps(course), fmt)
    for alternative in (_course_format(["SRC1", "SRC2", "SRC3"]), _course_format(["SRC2", "SRC1"])):
        assert normalize_practical_author(artifact.raw_text, alternative).normalized_value == course
        assert not validate_practical_author_artifact(artifact, alternative)
    assert validate_practical_author_artifact(artifact, fmt)


@pytest.mark.parametrize('field,value', [('strict', 1), ('minItems', 3.0)])
def test_format_types_are_exact(fmt, course, field, value):
    if field == 'strict':
        fmt['json_schema']['strict'] = value
    else:
        fmt['json_schema']['schema']['properties']['lessons']['items']['properties']['questions']['items']['properties']['choices']['minItems'] = value
    with pytest.raises(ValueError):
        normalize_practical_author(json.dumps(course), fmt)


@pytest.mark.asyncio
async def test_author_checkpoint_retains_raw_and_checks_custody_on_replay(fmt, course):
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_v3_partitioned_extraction import Journal

    journal = Journal()
    course['lessons'][0]['questions_note'] = None
    raw = json.dumps(course)
    artifact = normalize_practical_author(raw, fmt)
    calls = []
    async def invoke():
        calls.append(1)
        return artifact
    args = dict(journal=journal, stage='lesson', group_id='practical:author:v1',
                source_sha256='a' * 64, route_fingerprint='b' * 64,
                messages=[{'role': 'user', 'content': 'synthetic'}], response_format=fmt, invoke=invoke)
    assert await stage_once(**args) == artifact.normalized_value
    assert await stage_once(**args) == artifact.normalized_value
    assert calls == [1]
    saved = journal.values[next(key for key in journal.values if key.startswith('v3-stage-result:'))]
    assert saved['author_custody']['raw_text'] == raw
    saved['author_custody']['raw_text'] = '{}'
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        await stage_once(**args)
    assert calls == [1]


@pytest.mark.asyncio
async def test_typed_author_artifact_rejected_outside_author_stage(fmt, course):
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_v3_partitioned_extraction import Journal

    async def invoke():
        return normalize_practical_author(json.dumps(course), fmt)
    with pytest.raises(ValueError, match='stage_invalid'):
        await stage_once(journal=Journal(), stage='review', group_id='practical:review:v1',
                         source_sha256='a' * 64, route_fingerprint='b' * 64,
                         messages=[{'role': 'user', 'content': 'synthetic'}], response_format=fmt, invoke=invoke)


@pytest.mark.parametrize('stage,group,allowed', [
    ('lesson', 'practical:author:v1', True),
    ('lesson', 'practical:author:editorial:v31:output=32768', True),
    ('lesson', 'practical:author:editorial:v33', True),
    ('lesson', 'practical:focused:author:v36:' + 'a' * 64 + ':output=32768', True),
    ('review', 'practical:author:v1', False),
    ('lesson', 'practical:author:v1extra', False),
    ('lesson', 'practical:author:v1:output=0', False),
    ('lesson', 'practical:editorial:revision:v31', False),
    ('lesson', None, False),
])
def test_author_stage_scope_is_exact_for_journal_and_journal_free_paths(stage, group, allowed):
    from app.modules.ai.v3.practical_author_transport import is_practical_author_stage
    assert is_practical_author_stage(stage, group) is allowed


@pytest.mark.asyncio
async def test_journal_free_typed_artifact_rejects_non_author_group(course, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import course_response_format
    from app.modules.ai.v3.practical_service import generate_practical_course
    from app.modules.ai.v3.revision_policy import FOCUSED_EDITORIAL_REVIEW_POLICY

    async def fake_cycle(packet, corpus, intent, references, stage, **kwargs):
        fmt = course_response_format(packet)
        course['lessons'][0]['questions'][0]['source_refs'] = [packet.blocks[0].block_id]
        artifact = normalize_practical_author(json.dumps(course), fmt)
        invoke.return_value = artifact
        return await stage('lesson', 'not-an-author-group', [], fmt, lambda _: None)
    monkeypatch.setattr('app.modules.ai.v3.practical_focused_cycle.run_focused_cycle', fake_cycle)
    monkeypatch.setattr('app.modules.admin.runtime_configuration.runtime.resolve_runtime_settings',
        AsyncMock(return_value=SimpleNamespace(integer=lambda _: 1)))
    doc = DirectSourceDocument('doc', 'Source', 'source.txt', 'general', 'r1', (), source_text='A source rule.')
    corpus = DirectSourceCorpus('tenant', (doc,), len(doc.source_text), 0)
    invoke = AsyncMock()
    with pytest.raises(ValueError, match='transport_scope_invalid'):
        await generate_practical_course(corpus, intent=SimpleNamespace(), invoke=invoke,
            source_sha256='a' * 64, journal=None, route_fingerprint='b' * 64,
            review_policy=FOCUSED_EDITORIAL_REVIEW_POLICY)


@pytest.mark.asyncio
async def test_pending_author_checkpoint_replays_without_another_call(fmt, course):
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_pending_stage_journal import journal

    active, fake = journal()
    course['lessons'][0]['questions_note'] = None
    artifact = normalize_practical_author(json.dumps(course), fmt)
    calls = []
    async def invoke():
        calls.append(1)
        return artifact
    args = dict(journal=active, stage='lesson', group_id='practical:author:v1',
                source_sha256='a' * 64, route_fingerprint='b' * 64,
                messages=[{'role': 'user', 'content': 'synthetic'}], response_format=fmt, invoke=invoke)
    assert await stage_once(**args) == artifact.normalized_value
    assert await stage_once(**args) == artifact.normalized_value
    assert calls == [1]


@pytest.mark.asyncio
async def test_pending_author_finalize_unknown_never_reissues(fmt, course, monkeypatch):
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_pending_stage_journal import journal

    active, _ = journal()
    artifact = normalize_practical_author(json.dumps(course), fmt)
    calls = []
    async def invoke():
        calls.append(1)
        return artifact
    async def fail_finalize(**kwargs):
        assert kwargs['value']['author_custody']['raw_text'] == artifact.raw_text
        raise TimeoutError('synthetic unknown')
    monkeypatch.setattr('app.modules.ai.v3.pending_stage_journal.finalize_pending', fail_finalize)
    args = dict(journal=active, stage='lesson', group_id='practical:author:v1',
                source_sha256='a' * 64, route_fingerprint='b' * 64,
                messages=[{'role': 'user', 'content': 'synthetic'}], response_format=fmt, invoke=invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    assert calls == [1]
