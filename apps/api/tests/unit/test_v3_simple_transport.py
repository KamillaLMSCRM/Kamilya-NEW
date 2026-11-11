"""New simple formats traverse the existing strict transport without losing content."""
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_author_transport import (
    author_custody,
    normalize_practical_author,
    validate_author_custody,
    validate_practical_author_artifact,
)
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from app.modules.ai.v3.simple_course_editor import _editor_format, _review_format


@pytest.fixture
def envelope():
    return {
        'source_fingerprint': 'a' * 64, 'draft_fingerprint': 'b' * 64,
        'course': {'title': 'Course', 'lessons': [{'id': 'L1', 'title': 'Lesson',
            'content': 'Check the document before signing.',
            'questions': [{'id': 'Q1', 'prompt': 'When to sign?', 'choices': ['After check', 'Before check', 'Never'],
                'correct_index': 0, 'explanation': 'Check first.', 'source_refs': ['SRC1']}]}]},
        'lesson_sources': [{'lesson_id': 'L1', 'source_refs': ['SRC1']}], 'source_questions': [],
    }


@pytest.mark.parametrize('kind', ['review', 'editor'])
def test_formats_pass_actual_producer_preflight_and_registry(kind):
    formats = {
        'review': _review_format(['SRC1'], ['L1', 'Q1'], 'a' * 64, 'b' * 64),
        'editor': _editor_format(['SRC1'], 'a' * 64, 'b' * 64),
    }
    fmt = formats[kind]
    runner = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('simple_format_producer', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._checked_structured_format(fmt)
    assert response_contract(fmt) == 'simple_course_' + kind


def test_nested_null_extras_keep_original_and_cold_storage_receipt(envelope):
    fmt = _editor_format(['SRC1'], 'a' * 64, 'b' * 64)
    assert matches_response_contract(envelope, fmt)
    expected = json.loads(json.dumps(envelope))
    envelope['extra'] = None
    envelope['course']['lessons'][0]['questions'][0]['extra'] = None
    artifact = normalize_practical_author(json.dumps(envelope), fmt)
    assert artifact.normalized_value == expected
    assert artifact.receipt.removed_paths == ('/course/lessons/0/questions/0/extra', '/extra')
    assert validate_practical_author_artifact(artifact, fmt)
    receipt = json.loads(json.dumps(author_custody(artifact, fmt)))
    assert validate_author_custody(receipt, expected, fmt)
    receipt['removed_paths'] = ['/course/title']
    assert not validate_author_custody(receipt, expected, fmt)


@pytest.mark.parametrize('fault', ['declared_null', 'nonnull_extra', 'foreign_ref', 'invalid_key'])
def test_editor_does_not_normalize_semantic_or_declared_data(envelope, fault):
    fmt = _editor_format(['SRC1'], 'a' * 64, 'b' * 64)
    question = envelope['course']['lessons'][0]['questions'][0]
    if fault == 'declared_null':
        question['explanation'] = None
    elif fault == 'nonnull_extra':
        envelope['extra'] = 'unsupported'
    elif fault == 'foreign_ref':
        envelope['lesson_sources'][0]['source_refs'] = ['SRC9']
    else:
        question['correct_index'] = 9
    with pytest.raises(ValueError):
        normalize_practical_author(json.dumps(envelope), fmt)
