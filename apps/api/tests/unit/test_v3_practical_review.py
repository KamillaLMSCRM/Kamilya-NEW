import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_review import (
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)


@pytest.fixture
def example():
    source = "The approver signs the ticket and records the approval in the system."
    revision = "document:" + hashlib.sha256(source.encode()).hexdigest()
    doc = DirectSourceDocument("doc", "Title", "source.md", "general", revision, (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus("tenant", (doc,), len(source), 0))
    ref = packet.blocks[0].block_id
    course = {"title": "Course", "lessons": [{"id": "lesson", "title": "Lesson", "content": source,
        "questions": [{"id": "question", "prompt": "What is the complete procedure?",
            "choices": ["Sign and record", "Sign only", "Do neither"], "correct_index": 0,
            "explanation": "Both actions are required.", "source_refs": [ref]}]}]}
    review = {"source_fingerprint": packet.fingerprint, "source_review": "Sign and record the approval.",
              "findings": [], "source_notes": [], "answer_keys": {"question": 0},
              "question_rules": [{"question_id": "question", "rules": [{"rule": "Sign and record", "source_refs": [ref],
                                                                            "supported_options": [0]}]}],
              "option_checks": [{"question_id": "question", "options": [
                  {"index": 0, "status": "YES", "possible_correct_case": {"exists": "FOUND", "explanation": "Both actions", "source_refs": [ref]}},
                  {"index": 1, "status": "NO", "possible_correct_case": {"exists": "NONE", "explanation": "Missing record", "source_refs": [ref]}},
                  {"index": 2, "status": "NO", "possible_correct_case": {"exists": "NONE", "explanation": "Neither action", "source_refs": []}}]}],
              "narrative_sources": {"lesson": [ref]}}
    return packet, course, review, ref


def finding(scope, target, ref):
    return {"scope": scope, "target_id": target, "problem": "Material issue", "source_refs": [ref],
            "expected_rule": "Sign and record", "correction": "Fix the specified issue"}


def test_independent_key_accepts_incomplete_wrong_answer(example):
    packet, course, review, _ = example
    assert interpret_practical_review(review, packet, course).accepted
    message = practical_review_messages(packet, course)[1]['content']
    candidate = json.loads(message.split('COURSE_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0])
    assert 'correct_index' not in candidate['lessons'][0]['questions'][0]
    assert 'source_refs' not in candidate['lessons'][0]['questions'][0]
    assert 'explanation' not in candidate['lessons'][0]['questions'][0]
    assert packet.blocks[0].text in message


@pytest.mark.parametrize('status', ['YES', 'DEPENDS', 'UNKNOWN'])
def test_alternative_ambiguity_cannot_pass_matching_flat_key(example, status):
    packet, course, review, ref = example
    review['option_checks'][0]['options'][1].update(status=status)
    result = interpret_practical_review(review, packet, course)
    assert not result.accepted and result.question_ids == ('question',)
    assert result.feedback[0]['evidence']['problem'] == 'option_answerability_unresolved'
    assert result.feedback[0]['evidence']['checks'] == review['option_checks'][0]['options']


def test_no_status_cannot_hide_source_supported_counterexample(example):
    packet, course, review, ref = example
    review['option_checks'][0]['options'][1]['possible_correct_case'] = {
        'exists': 'FOUND', 'explanation': 'Another situation satisfies the question', 'source_refs': [ref]}
    result = interpret_practical_review(review, packet, course)
    assert not result.accepted and result.question_ids == ('question',)


@pytest.mark.parametrize('supported', [[0, 1], []])
def test_rule_option_graph_holds_even_when_flat_key_matches(example, supported):
    packet, course, review, _ = example
    review['question_rules'][0]['rules'][0]['supported_options'] = supported
    decision = interpret_practical_review(review, packet, course)
    assert not decision.accepted and decision.question_ids == ('question',)
    assert decision.feedback[0]['evidence']['problem'] == 'rule_option_graph_unresolved'
    assert decision.feedback[0]['evidence']['rules'] == review['question_rules'][0]['rules']


@pytest.mark.parametrize('supported', [[0, 0], [3], [True], ['0']])
def test_rule_option_graph_invalid_indices_rejected(example, supported):
    packet, course, review, _ = example
    review['question_rules'][0]['rules'][0]['supported_options'] = supported
    assert not matches_practical_review(review, practical_review_format(packet, course))


@pytest.mark.parametrize('defect', ['missing_case', 'bad_boolean', 'blank_explanation', 'missing_refs', 'tampered_format'])
def test_possible_case_is_closed_and_bound(example, defect):
    packet, course, review, _ = example
    option = review['option_checks'][0]['options'][0]
    fmt = practical_review_format(packet, course)
    if defect == 'missing_case':
        del option['possible_correct_case']
    elif defect == 'bad_boolean':
        option['possible_correct_case']['exists'] = 1
    elif defect == 'blank_explanation':
        option['possible_correct_case']['explanation'] = ' '
    elif defect == 'missing_refs':
        option['possible_correct_case']['source_refs'] = []
    else:
        fmt['json_schema']['schema']['properties']['option_checks']['items']['properties']['options']['items']['properties']['possible_correct_case']['additionalProperties'] = True
        assert not is_practical_review_format(fmt)
    assert not matches_practical_review(review, fmt)


@pytest.mark.parametrize('defect', ['duplicate_index', 'blank_witness', 'foreign_ref', 'missing_ref', 'missing_option'])
def test_option_check_identity_and_evidence_rejected(example, defect):
    packet, course, review, _ = example
    checks = review['option_checks'][0]['options']
    if defect == 'duplicate_index':
        checks[1]['index'] = 0
    elif defect == 'blank_witness':
        checks[1]['possible_correct_case']['explanation'] = ' '
    elif defect == 'foreign_ref':
        checks[1]['possible_correct_case']['source_refs'] = ['foreign']
    elif defect == 'missing_ref':
        checks[0]['possible_correct_case']['source_refs'] = []
    else:
        checks.pop()
    assert not matches_practical_review(review, practical_review_format(packet, course))


def test_option_question_inventory_and_choice_count_fail_closed(example):
    packet, course, review, _ = example
    second = copy.deepcopy(course['lessons'][0]['questions'][0])
    second['id'] = 'question2'
    course['lessons'][0]['questions'].append(second)
    review['answer_keys']['question2'] = 0
    review['question_rules'].append({'question_id': 'question2',
        'rules': copy.deepcopy(review['question_rules'][0]['rules'])})
    review['option_checks'].append(copy.deepcopy(review['option_checks'][0]))
    review['option_checks'][1]['question_id'] = 'question2'
    fmt = practical_review_format(packet, course)
    assert matches_practical_review(review, fmt)
    duplicate = copy.deepcopy(review)
    duplicate['option_checks'][1]['question_id'] = 'question'
    assert not matches_practical_review(duplicate, fmt)
    extra = copy.deepcopy(review)
    extra['option_checks'][0]['options'].append({'index': 3, 'status': 'NO', 'possible_correct_case': {'exists': 'NONE', 'explanation': 'No', 'source_refs': []}})
    assert not matches_practical_review(extra, fmt)


@pytest.mark.parametrize('defect', ['empty', 'blank', 'foreign', 'duplicate_ref', 'missing_question', 'foreign_question', 'tampered_format'])
def test_question_applicability_inventory_is_closed(example, defect):
    packet, course, review, ref = example
    fmt = practical_review_format(packet, course)
    if defect == 'empty':
        review['question_rules'][0]['rules'] = []
    elif defect == 'blank':
        review['question_rules'][0]['rules'][0]['rule'] = ' '
    elif defect == 'foreign':
        review['question_rules'][0]['rules'][0]['source_refs'] = ['foreign']
    elif defect == 'duplicate_ref':
        review['question_rules'][0]['rules'][0]['source_refs'] = [ref, ref]
    elif defect == 'missing_question':
        review['question_rules'] = []
    elif defect == 'foreign_question':
        review['question_rules'][0]['question_id'] = 'foreign'
    else:
        fmt['json_schema']['schema']['properties']['question_rules']['minItems'] = 0
        assert not is_practical_review_format(fmt)
    assert not matches_practical_review(review, fmt)


def test_source_advisory_does_not_invent_a_course_error_but_material_uncertainty_holds(example):
    packet, course, review, ref = example
    review['source_notes'] = [{'note': 'Source leaves an unclaimed boundary case undefined', 'source_refs': [ref]}]
    assert interpret_practical_review(review, packet, course).accepted
    review['findings'] = [finding('source', ref, ref)]
    assert interpret_practical_review(review, packet, course).source_uncertain


@pytest.mark.parametrize("key", [-1, 1, 2])
def test_wrong_or_uncertain_independent_key_targets_question(example, key):
    packet, course, review, _ = example
    review["answer_keys"]["question"] = key
    result = interpret_practical_review(review, packet, course)
    assert not result.accepted and result.question_ids == ("question",) and result.lesson_ids == ()


@pytest.mark.parametrize("scope", ["lesson", "question", "coverage", "source"])
def test_scoped_findings(example, scope):
    packet, course, review, ref = example
    target = {"lesson": "lesson", "question": "question", "coverage": ref, "source": ref}[scope]
    review["findings"] = [finding(scope, target, ref)]
    result = interpret_practical_review(review, packet, course)
    assert not result.accepted
    assert (result.lesson_ids == ("lesson",)) == (scope in {"lesson", "coverage"})
    assert (result.question_ids == ("question",)) == (scope == "question")
    assert not result.allow_new_lessons
    assert result.source_uncertain == (scope == "source")


def test_missing_fact_in_existing_lesson_allows_prose_fix_not_only_new_lessons(example):
    packet, course, review, ref = example
    review['findings'] = [finding('coverage', 'lesson', ref)]
    result = interpret_practical_review(review, packet, course)
    assert result.lesson_ids == ('lesson',) and not result.allow_new_lessons
    assert not result.question_ids and not result.source_uncertain


def test_owned_coverage_issue_identity_and_explicit_closure_remain_stable(example):
    packet, course, review, ref = example
    review['findings'] = [finding('coverage', ref, ref)]
    first = interpret_practical_review(review, packet, course)
    prior = first.feedback
    review['findings'] = []
    review['issue_checks'] = {prior[0]['issue_id']: {'status': 'OPEN', 'reason': 'Still missing'}}
    again = interpret_practical_review(review, packet, course, prior)
    assert again.feedback == prior and again.lesson_ids == ('lesson',) and not again.allow_new_lessons
    review['issue_checks'][prior[0]['issue_id']]['status'] = 'RESOLVED'
    assert interpret_practical_review(review, packet, course, prior).accepted


def test_unowned_coverage_can_add_and_other_evidence_does_not_claim_ownership(example):
    _packet, course, _review, _ref = example
    source = 'First source.\n\nSecond source.'
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source), 0))
    first, second = (block.block_id for block in packet.blocks)
    course['lessons'][0]['questions'][0]['source_refs'] = [first]
    review = {'source_fingerprint': packet.fingerprint, 'source_review': 'Reviewed', 'source_notes': [],
        'narrative_sources': {'lesson': [first]}, 'findings': [finding('coverage', second, first)],
        'answer_keys': {'question': 0}, 'question_rules': [{'question_id': 'question',
            'rules': [{'rule': 'Rule', 'source_refs': [first], 'supported_options': [0]}]}],
        'option_checks': [{'question_id': 'question', 'options': [
            {'index': i, 'status': 'YES' if i == 0 else 'NO', 'possible_correct_case': {
                'exists': 'FOUND' if i == 0 else 'NONE', 'explanation': 'Reason', 'source_refs': [first]}}
            for i in range(3)]}]}
    result = interpret_practical_review(review, packet, course)
    assert result.allow_new_lessons and not result.lesson_ids


def test_shared_source_coverage_targets_all_exact_owners(example):
    packet, course, review, ref = example
    second = copy.deepcopy(course['lessons'][0])
    second['id'] = 'lesson2'
    second['questions'][0]['id'] = 'question2'
    course['lessons'].append(second)
    review['narrative_sources']['lesson2'] = [ref]
    review['answer_keys']['question2'] = 0
    for field in ('question_rules', 'option_checks'):
        item = copy.deepcopy(review[field][0])
        item['question_id'] = 'question2'
        review[field].append(item)
    review['findings'] = [finding('coverage', ref, ref)]
    result = interpret_practical_review(review, packet, course)
    assert result.lesson_ids == ('lesson', 'lesson2') and not result.allow_new_lessons


@pytest.mark.parametrize("defect", ["missing_key", "foreign_key", "wrong_target", "foreign_ref", "blank_problem", "duplicate_refs"])
def test_invalid_inventories_or_findings_rejected(example, defect):
    packet, course, review, ref = example
    review["findings"] = [finding("question", "question", ref)]
    if defect == "missing_key":
        review["answer_keys"].clear()
    elif defect == "foreign_key":
        review["answer_keys"]["foreign"] = 0
    elif defect == "wrong_target":
        review["findings"][0]["target_id"] = "lesson"
    elif defect == "foreign_ref":
        review["findings"][0]["source_refs"] = ["foreign"]
    elif defect == "blank_problem":
        review["findings"][0]["problem"] = " "
    else:
        review["narrative_sources"]["lesson"] = [ref, ref]
    assert not matches_practical_review(review, practical_review_format(packet, course))


def test_prior_open_retained_resolved_cleared_missing_rejected(example):
    packet, course, review, ref = example
    review["findings"] = [finding("question", "question", ref)]
    prior = interpret_practical_review(review, packet, course).feedback
    review["findings"] = []
    fmt = practical_review_format(packet, course, prior)
    assert not matches_practical_review(review, fmt)
    review["issue_checks"] = {prior[0]["issue_id"]: {"status": "OPEN", "reason": "Still incomplete"}}
    assert interpret_practical_review(review, packet, course, prior).question_ids == ("question",)
    review["issue_checks"][prior[0]["issue_id"]]["status"] = "RESOLVED"
    assert interpret_practical_review(review, packet, course, prior).accepted
    review['issue_checks'][prior[0]['issue_id']] = {
        'status': 'RETRACTED', 'reason': 'The scenario is a valid sufficient subcase, not an exclusive rule.'}
    assert interpret_practical_review(review, packet, course, prior).accepted


def test_format_and_real_runner(example):
    packet, course, review, _ = example
    fmt = practical_review_format(packet, course)
    assert is_practical_review_format(fmt) and matches_practical_review(review, fmt)
    bad = copy.deepcopy(fmt)
    bad["json_schema"]["schema"]["properties"]["source_fingerprint"]["enum"] = ["foreign"]
    assert not matches_practical_review(review, bad)
    runner = Path(__file__).resolve().parents[4] / "infra/codex-reserve/runner.py"
    spec = importlib.util.spec_from_file_location("practical_test_runner", runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(fmt) == fmt["json_schema"]["schema"]


def test_100_questions_and_blocks_schema_bounded():
    source = "".join(f"Operational source item {i}.\n\n" for i in range(100))
    revision = "document:" + hashlib.sha256(source.encode()).hexdigest()
    doc = DirectSourceDocument("doc", "Title", "source.md", "general", revision, (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus("tenant", (doc,), len(source), 0))
    assert len(packet.blocks) == 100
    questions = [{"id": f"q{i}", "prompt": f"Question {i}?", "choices": ["A", "B", "C"],
                  "correct_index": 0, "explanation": "Explanation", "source_refs": [packet.blocks[i].block_id]}
                 for i in range(100)]
    course = {"title": "Course", "lessons": [{"id": "lesson", "title": "Lesson", "content": "Text", "questions": questions}]}
    fmt = practical_review_format(packet, course)
    assert is_practical_review_format(fmt)
    assert len(json.dumps(fmt, ensure_ascii=False, separators=(",", ":")).encode()) < 65536
    from app.modules.ai.v3.practical_model_view import PracticalModelView
    runner = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('large_practical_test_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model_fmt = PracticalModelView(packet).schema(fmt)
    assert module._checked_structured_format(model_fmt) == model_fmt['json_schema']['schema']


def test_synthetic_source_plan_is_not_a_registered_editor_contract(example):
    packet, course, _, _ = example
    fmt = practical_review_format(packet, course)
    assert 'coverage_checks' not in fmt['json_schema']['schema']['properties']
    assert 'SOURCE_REQUIREMENTS_JSON' not in practical_review_messages(packet, course)[1]['content']
