"""Offline checks for exact cross-lesson learner-visible duplicate detection."""
import socket

import httpx
import pytest

from app.modules.ai.v3.exact_duplicate_review import has_cross_lesson_duplicate
from app.modules.ai.v3.models import V3Lesson, V3Question


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(httpx.Client, 'send', deny)
    monkeypatch.setattr(httpx.AsyncClient, 'send', deny)


def lesson(identifier, scenario, prompt):
    question = V3Question(question_id=identifier, scenario_premise=scenario, prompt=prompt,
        options=(), explanation='', rule_id='r', source_quote='')
    return V3Lesson(lesson_id=identifier, title='synthetic', module_title='synthetic', content='',
                    covered_rule_ids=('r',), questions=(question,))


def test_exact_cross_lesson_stem_is_reported_once_without_content():
    items = [lesson('1', 'Same scenario', 'What now?'), lesson('2', 'Same  scenario', 'What now?')]
    assert has_cross_lesson_duplicate(items) is True


def test_same_question_with_different_scenario_is_not_merged():
    assert has_cross_lesson_duplicate([lesson('1', 'Scenario A', 'What now?'),
                                   lesson('2', 'Scenario B', 'What now?')]) is False


def test_distinct_case_and_numeric_conditions_are_not_merged():
    assert has_cross_lesson_duplicate([lesson('1', 'At 100', 'Proceed?'),
                                   lesson('2', 'At 101', 'Proceed?'),
                                   lesson('3', 'At 100', 'proceed?')]) is False


def test_many_lessons_produce_one_bounded_boolean():
    lessons = [lesson(str(i), 'same scenario', 'same question') for i in range(10000)]
    assert has_cross_lesson_duplicate(lessons) is True


def test_many_distinct_lessons_and_last_duplicate_require_full_traversal():
    lessons = [lesson(str(i), f'scenario {i}', 'same question') for i in range(10000)]
    assert has_cross_lesson_duplicate(lessons) is False
    lessons[-1] = lesson('last', 'scenario 0', 'same question')
    assert has_cross_lesson_duplicate(lessons) is True
