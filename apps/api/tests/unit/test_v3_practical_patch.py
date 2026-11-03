import copy
import importlib.util
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_patch import (
    _fingerprint,
    is_practical_patch_format,
    matches_practical_patch,
    merge_practical_patch,
    practical_patch_course_view,
    practical_patch_format,
)
from app.modules.ai.v3.practical_review import PracticalReviewDecision


@pytest.fixture
def case():
    text = "First source.\n\nSecond source."
    doc = DirectSourceDocument("doc", "Title", "file", "category", "r1", (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus("tenant", (doc,), len(text), 0))

    def q(qid):
        return {
            "id": qid,
            "prompt": f"prompt {qid}",
            "choices": ["a", "b", "c"],
            "correct_index": 0,
            "explanation": "reason",
            "source_refs": [packet.blocks[0].block_id],
        }

    course = {
        "title": "Course",
        "lessons": [
            {"id": "l1", "title": "Title 1", "content": "First rule.\n\nFalse qualifier.\n\nSecond rule.", "questions": [q("q1"), q("q2")]},
            {"id": "l2", "title": "Title 2", "content": "Content 2", "questions": [q("q3")]},
        ],
    }
    return packet, course


def bound(course, patch):
    return {"course_fingerprint": _fingerprint(course), **patch}


def decision(lessons=(), questions=(), additions=False):
    return PracticalReviewDecision(False, False, lessons, questions, additions, ())


def test_targeted_changes_preserve_siblings_and_input(case):
    packet, course = case
    before = copy.deepcopy(course)
    scope = decision(("l1",), ("q1",))
    replacement = copy.deepcopy(course["lessons"][0]["questions"][0])
    replacement.update(
        prompt="new prompt",
        choices=["red", "blue", "green", "black"],
        correct_index=2,
        explanation="new reason",
        source_refs=[packet.blocks[1].block_id],
    )
    patch = {
        "new_lessons": [],
        "new_questions": [],
        "lesson_updates": {"l1": {"title": "Revised", "replacements": [
            {"fragment_id": "F2", "new_text": ""}]}},
        "question_updates": {"q1": replacement},
    }
    fmt = practical_patch_format(packet, course, scope)
    assert is_practical_patch_format(fmt) and matches_practical_patch(bound(course, patch), fmt)
    result = merge_practical_patch(course, packet, scope, bound(course, patch))
    assert result["lessons"][0]["title"] == "Revised"
    assert result["lessons"][0]["content"] == "First rule.\n\n\n\nSecond rule."
    assert result["lessons"][0]["questions"][0] == replacement
    assert result["lessons"][0]["questions"][1] == before["lessons"][0]["questions"][1]
    assert result["lessons"][1] == before["lessons"][1] and course == before
    result["lessons"][0]["questions"][0]["choices"][0] = "changed"
    assert patch["question_updates"]["q1"]["choices"][0] == "red"


def test_multiple_replacements_use_original_coordinates_and_preserve_siblings(case):
    packet, course = case
    patch = {"new_lessons": [], "new_questions": [], "lesson_updates": {"l1": {
        "title": "Title 1", "replacements": [
            {"fragment_id": "F1", "new_text": "A substantially longer first rule."},
            {"fragment_id": "F2", "new_text": ""},
        ]}}}
    result = merge_practical_patch(course, packet, decision(("l1",)), bound(course, patch))
    assert result["lessons"][0]["content"] == "A substantially longer first rule.\n\n\n\nSecond rule."
    assert result["lessons"][1] == course["lessons"][1]


@pytest.mark.parametrize('kind', ['foreign', 'duplicate', 'empty_result'])
def test_invalid_fragment_edits_rejected(case, kind):
    packet, course = case
    edits = [{'fragment_id': 'F9', 'new_text': 'Changed'}]
    if kind == 'duplicate':
        edits = [{'fragment_id': 'F1', 'new_text': 'Changed'}, {'fragment_id': 'F1', 'new_text': 'Again'}]
    elif kind == 'empty_result':
        course['lessons'][0]['content'] = 'Single paragraph'
        edits = [{'fragment_id': 'F1', 'new_text': ''}]
    patch = {'new_lessons': [], 'new_questions': [], 'lesson_updates': {
        'l1': {'title': 'Title 1', 'replacements': edits}}}
    with pytest.raises(ValueError):
        merge_practical_patch(course, packet, decision(('l1',)), bound(course, patch))


def test_repeated_paragraphs_are_distinct_and_stale_fingerprint_rejected(case):
    packet, course = case
    course['lessons'][0]['content'] = 'Repeat.\n\nRepeat.\n\nKeep.'
    scope = decision(('l1',))
    view = practical_patch_course_view(course, scope)
    assert [row['fragment_id'] for row in view['lessons'][0]['content_fragments']] == ['F1', 'F2', 'F3']
    assert view['lessons'][1] == course['lessons'][1]
    patch = bound(course, {'new_lessons': [], 'new_questions': [], 'lesson_updates': {'l1': {
        'title': 'Title 1', 'replacements': [{'fragment_id': 'F2', 'new_text': 'Changed.'}]}}})
    result = merge_practical_patch(course, packet, scope, bound(course, patch))
    assert result['lessons'][0]['content'] == 'Repeat.\n\nChanged.\n\nKeep.'
    stale = copy.deepcopy(course)
    stale['lessons'][0]['content'] = 'Other.\n\nRepeat.\n\nKeep.'
    with pytest.raises(ValueError):
        merge_practical_patch(stale, packet, scope, patch)


def test_coverage_additions(case):
    packet, course = case
    added_q = copy.deepcopy(course["lessons"][0]["questions"][0])
    added_q["id"] = "q4"
    added_q["source_refs"] = [packet.blocks[1].block_id]
    added_lesson = {"id": "l3", "title": "More", "content": "New material", "questions": [dict(added_q, id="q5")]}
    patch = {"new_lessons": [added_lesson], "new_questions": [{"lesson_id": "l2", "question": added_q}]}
    result = merge_practical_patch(course, packet, decision(additions=True), bound(course, patch))
    assert result["lessons"][:1] == course["lessons"][:1]
    assert result["lessons"][1]["questions"][-1] == added_q
    assert result["lessons"][2] == added_lesson


@pytest.mark.parametrize(
    "kind", ["lesson", "question", "new_question_collision", "duplicate_new_lesson", "duplicate_question"]
)
def test_identity_collisions_rejected(case, kind):
    packet, course = case
    q = copy.deepcopy(course["lessons"][0]["questions"][0])
    new = {"id": "l3", "title": "New", "content": "New", "questions": [dict(q, id="q4")]}
    patch = {"new_lessons": [], "new_questions": []}
    if kind == "lesson":
        patch["new_lessons"] = [dict(new, id="l1")]
    if kind == "question":
        patch["new_lessons"] = [dict(new, questions=[q])]
    if kind == "new_question_collision":
        patch["new_questions"] = [{"lesson_id": "l1", "question": q}]
    if kind == "duplicate_new_lesson":
        patch["new_lessons"] = [new, dict(new, questions=[dict(q, id="q5")])]
    if kind == "duplicate_question":
        patch["new_questions"] = [
            {"lesson_id": "l1", "question": dict(q, id="q4")},
            {"lesson_id": "l2", "question": dict(q, id="q4")},
        ]
    with pytest.raises(ValueError):
        merge_practical_patch(course, packet, decision(additions=True), bound(course, patch))


def test_forbidden_changes_and_foreign_refs_rejected(case):
    packet, course = case
    scope = decision(questions=("q1",))
    question = copy.deepcopy(course["lessons"][0]["questions"][0])
    fmt = practical_patch_format(packet, course, scope)
    patch = {"new_lessons": [], "new_questions": [], "question_updates": {"q1": question}}
    question["source_refs"] = ["foreign"]
    assert not matches_practical_patch(bound(course, patch), fmt)
    with pytest.raises(ValueError):
        merge_practical_patch(course, packet, scope, bound(course, patch))
    question["source_refs"] = [packet.blocks[0].block_id]
    question["id"] = "q2"
    assert not matches_practical_patch(bound(course, patch), fmt)
    forged = copy.deepcopy(fmt)
    forged["json_schema"]["schema"]["properties"]["question_updates"]["properties"]["q1"]["properties"]["id"][
        "enum"
    ] = ["q2"]
    assert not is_practical_patch_format(forged)
    with pytest.raises(ValueError):
        practical_patch_format(packet, course, decision(lessons=("unknown",)))


def test_real_runner_accepts_patch_schema(case):
    packet, course = case
    path = Path(__file__).resolve().parents[4] / "infra" / "codex-reserve" / "runner.py"
    spec = importlib.util.spec_from_file_location("practical_test_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for scope in (decision(("l1",), ("q1",)), decision(additions=True)):
        form = practical_patch_format(packet, course, scope)
        assert module._checked_structured_format(form) == form["json_schema"]["schema"]


@pytest.mark.parametrize("bad_id", [42, " "])
def test_registry_rejects_consistently_forged_source_id(case, bad_id):
    packet, course = case
    form = practical_patch_format(packet, course, decision(additions=True))
    old = packet.blocks[0].block_id

    def replace_id(node):
        if isinstance(node, dict):
            return {key: replace_id(value) for key, value in node.items()}
        if isinstance(node, list):
            return [replace_id(value) for value in node]
        return bad_id if node == old else node

    assert not is_practical_patch_format(replace_id(form))


def test_new_lesson_may_use_old_synthetic_placeholder(case):
    packet, course = case
    question = dict(course["lessons"][0]["questions"][0], id="new-question")
    lesson = {"id": "__patch_questions__", "title": "New", "content": "New", "questions": [question]}
    other_question = dict(question, id="another-question")
    patch = {"new_lessons": [lesson], "new_questions": [{"lesson_id": "l1", "question": other_question}]}
    result = merge_practical_patch(course, packet, decision(additions=True), bound(course, patch))
    assert result["lessons"][-1] == lesson
