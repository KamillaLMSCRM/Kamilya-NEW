import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_prose_revision import (
    compile_prose_revision,
    is_prose_revision_format,
    matches_prose_revision,
    prose_revision_format,
)
from app.modules.ai.v3.response_contracts import matches_transport_contract, response_contract


@pytest.fixture
def revision_case():
    packet = SimpleNamespace(fingerprint='a' * 64)
    course = {'title': 'Course', 'lessons': [
        {'id': 'first', 'title': 'One', 'content': 'One text', 'questions': [{'id': 'Q1', 'key': 2}]},
        {'id': 'second', 'title': 'Two', 'content': 'Two text', 'questions': [{'id': 'Q2', 'key': 1}]}]}
    fmt = prose_revision_format(packet.fingerprint, _digest(course), ['second'])
    value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course), 'updates': []}
    return packet, course, fmt, value


def test_registered_native_format_and_empty_update(revision_case, monkeypatch):
    packet, course, fmt, value = revision_case
    assert response_contract(fmt) == 'practical_prose_revision'
    assert matches_transport_contract(value, fmt)
    result = compile_prose_revision(value, packet, course, ['second'])
    assert result['course'] == course and result['course'] is not course and not result['semantic_acceptance']
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('prose_revision_native_runner', path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runner)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


def test_only_owned_content_changes_and_input_is_unmodified(revision_case):
    packet, course, _, value = revision_case
    original = copy.deepcopy(course)
    value['updates'] = [{'lesson_id': 'second', 'content': 'Revised prose'}]
    result = compile_prose_revision(value, packet, course, ['second'])
    expected = copy.deepcopy(course)
    expected['lessons'][1]['content'] = 'Revised prose'
    assert result['course'] == expected and course == original
    assert result['updated_lesson_ids'] == ['second'] and not result['semantic_acceptance']
    result['course']['lessons'][0]['questions'][0]['key'] = 0
    assert course == original


@pytest.mark.parametrize('mutation', ['foreign', 'duplicate', 'blank', 'source_fp', 'course_fp', 'extra', 'badtype'])
def test_invalid_proposal_fails_closed(revision_case, mutation):
    packet, course, fmt, value = revision_case
    value['updates'] = [{'lesson_id': 'second', 'content': 'Edited'}]
    if mutation == 'foreign':
        value['updates'][0]['lesson_id'] = 'first'
    elif mutation == 'duplicate':
        value['updates'].append(copy.deepcopy(value['updates'][0]))
    elif mutation == 'blank':
        value['updates'][0]['content'] = '  '
    elif mutation == 'source_fp':
        value['source_fingerprint'] = 'c' * 64
    elif mutation == 'course_fp':
        value['course_fingerprint'] = 'c' * 64
    elif mutation == 'extra':
        value['updates'][0]['title'] = 'Changed'
    else:
        value['updates'] = False
    assert not matches_prose_revision(value, fmt)
    with pytest.raises(ValueError):
        compile_prose_revision(value, packet, course, ['second'])


def test_stale_course_scope_and_tampered_schema_fail(revision_case):
    packet, course, fmt, value = revision_case
    changed = copy.deepcopy(course)
    changed['lessons'][0]['questions'][0]['key'] = 0
    with pytest.raises(ValueError):
        compile_prose_revision(value, packet, changed, ['second'])
    with pytest.raises(ValueError):
        compile_prose_revision(value, packet, course, ['foreign'])
    altered = copy.deepcopy(fmt)
    altered['json_schema']['schema']['additionalProperties'] = True
    assert not is_prose_revision_format(altered) and not matches_prose_revision(value, altered)
    for invalid in (None, True, [], {'json_schema': {}}):
        assert not is_prose_revision_format(invalid)


@pytest.mark.asyncio
async def test_managed_prepare_accepts_exact_new_kind_without_network(revision_case):
    _, _, fmt, _ = revision_case
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic', tenant_id=uuid4(),
        user_id=uuid4(), job_id=str(uuid4()), credential_revision='synthetic', model='gpt-6-luna',
        deadline_seconds=300, reasoning_effort='high')
    try:
        cap = await client.prepare([{'role': 'user', 'content': 'Synthetic review.'}], max_output_tokens=1000,
                                   ownership_checkpoint=AsyncMock(return_value=True), response_format=fmt)
        sent = json.loads(client._prepared.pop(cap))
        assert sent['response_format'] == fmt and sent['structured_output_policy'] == 'typed-json-object-v1'
    finally:
        client.close()
