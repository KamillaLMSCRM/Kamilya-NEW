"""Versioned assessment guidance distinguishes taught material from tests."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_arbitration import (
    ASSESSMENT_COVERAGE_GUIDE,
    arbitration_messages,
)
from tests.unit.test_v3_practical_arbitration import allegation
from tests.unit.test_v3_practical_review_purpose import typed_allegation

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def course_with_unexamined_inspection(course):
    course = copy.deepcopy(course)
    lesson = course['lessons'][0]
    lesson['content'] = 'При осмотре проверьте исправность, маркировку и доступность оборудования.'
    questions = lesson['questions']
    for index, prompt in enumerate(('Когда проводится осмотр?', 'Кто оформляет журнал?', 'Где хранится акт?')):
        question = copy.deepcopy(questions[0])
        question.update(id=f'q{index + 1}', prompt=prompt,
                        choices=['Первый вариант', 'Второй вариант', 'Третий вариант'])
        if index < len(questions):
            questions[index] = question
        else:
            questions.append(question)
    return course


@pytest.mark.parametrize('scope', ['assessment', 'comparison'])
def test_coverage_guidance_distinguishes_examined_decision_from_taught_content(case, scope):
    _, packet, original = case
    course = course_with_unexamined_inspection(original)
    decision = (allegation(packet, scope='assessment', target='l1') if scope == 'assessment'
                else typed_allegation(packet, 'COURSE_ASSESSMENT'))
    decision.feedback[0]['evidence']['problem'] = 'Не проверяются критерии осмотра оборудования.'
    options = {'selectors': True, 'typed_findings': True}
    default = arbitration_messages(packet, course, decision, **options)
    assert default == arbitration_messages(packet, course, decision, assessment_coverage=False, **options)
    fresh = arbitration_messages(packet, course, decision, assessment_coverage=True, **options)
    assert fresh[1] == default[1]
    system = fresh[0]['content']
    assert ASSESSMENT_COVERAGE_GUIDE in system
    assert 'формулировки вопросов и варианты ответов' in system
    assert 'Текст урока, авторское объяснение, число вопросов' in system
    assert 'не требуй отдельного вопроса на каждый пункт' in system
    assert 'семейства рабочих решений является MATERIAL_ERROR' in system
    assert 'SOURCE_AMBIGUITY' in system
    assert 'если урок объясняет её' not in system
    assert 'Обычно 3–4 вопроса' not in system
    assert 'нужное знание уже раскрыто или представительно проверяется' not in system
    body = json.loads(fresh[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1])
    lesson = body['whole_course']['lessons'][0]
    assert 'исправность' in json.dumps(lesson['content'], ensure_ascii=False)
    assert [q['prompt']['text'] for q in lesson['questions']] == [
        'Когда проводится осмотр?', 'Кто оформляет журнал?', 'Где хранится акт?']
    assert all('исправность' not in q['prompt']['text'] for q in lesson['questions'])


def test_blind_answer_view_keeps_its_scope_with_new_policy(case):
    _, packet, course = case
    decision = typed_allegation(packet, 'ANSWER_VALIDITY')
    options = {'selectors': True, 'question_only': True, 'typed_findings': True}
    before = arbitration_messages(packet, course, decision, **options)
    after = arbitration_messages(packet, course, decision, assessment_coverage=True, **options)
    assert before[1] == after[1] and 'whole_course' not in after[1]['content']
    assert ASSESSMENT_COVERAGE_GUIDE in after[0]['content']


@pytest.mark.parametrize('options', [
    {'selectors': False, 'typed_findings': True},
    {'selectors': True, 'typed_findings': False},
    {'selectors': False, 'typed_findings': False},
    {'selectors': True, 'typed_findings': True, 'assessment_coverage': 'yes'},
])
def test_assessment_coverage_requires_typed_selectors(case, options):
    _, packet, course = case
    decision = allegation(packet)
    flags = {'assessment_coverage': True, **options}
    with pytest.raises(ValueError, match='practical_arbitration_policy_invalid'):
        arbitration_messages(packet, course, decision, **flags)
