"""Exact source types, not provider guesses, determine the response domain."""
from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes, materialize_assessment
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.quality import _is_complete_binary_modal_opposite, answer_containment_option_indices
from app.modules.ai.evidence_engine.semantic_assessment import _axis_answer_domain


def axis_for(value, key, *, subject='Правила', attribute='положение'):
    fact = SourceFact('f', subject, attribute, value, 'doc_id=synthetic;part=1')
    lesson = LessonDraft('l', 'Правила', 'Обязанности', 'Применять правила', '', ('f',), (), 1)
    return next(a for a in derive_assessment_axes(lesson, [fact], block_id='b') if a.correct_value == key)


def test_complete_nominal_placement_prohibition_has_an_explicit_permission_question():
    key = 'Не допускается размещение стеллажей, шкафов для хранения документов вплотную к источникам тепла и вентиляционным каналам.'
    axis = axis_for('2.4. ' + key, key, attribute='запрет')
    assert axis.required_prompt == 'Допустимо ли размещение стеллажей, шкафов для хранения документов вплотную к источникам тепла и вентиляционным каналам?'
    q = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, 'Как хранить документы?', ()))
    assert q is not None and q.kind == 'true_false'
    assert q.options == (key, key.replace('Не допускается', 'Допускается', 1))
    assert answer_containment_option_indices(q) == ()
    assert answer_containment_option_indices(replace(q, kind='single_choice')) == (1,)
    assert not _is_complete_binary_modal_opposite(q, q.options[1] + ' после проверки')


def test_qualified_placement_does_not_gain_an_unsupported_opposite():
    key = 'Не допускается размещение мебели вплотную к батареям, кроме согласованных случаев.'
    axis = axis_for(key, key, attribute='запрет')
    assert not axis.required_prompt.startswith('Допустимо ли размещение')
    assert materialize_assessment(axis, AuthoredAssessment(axis.axis_id, 'Как хранить мебель?', ())) is None


@pytest.mark.parametrize('tail', [
    '\nРазмещение огнетушителей обозначается знаком',
    ' — размещение огнетушителей обозначается знаком',
    ' – размещение огнетушителей обозначается знаком',
    ', после проверки допускается установка перегородок',
    ', до согласования разрешается хранение коробок',
    ', размещение огнетушителей обозначается знаком',
    ', размещение огнетушителей разрешено',
    ' размещение огнетушителей допустимо',
    ' хранение коробок запрещено',
    ' наличие маркировки обязательно',
    ' хранение коробок возможно',
    ' хранение коробок можно',
])
def test_joined_or_qualified_placement_is_not_a_deterministic_binary(tail):
    from app.modules.ai.evidence_engine.assessment_axes import _server_owned_inverse
    value = 'Не допускается размещение шкафов вплотную к источникам тепла' + tail
    assert _server_owned_inverse(value) is None


def test_single_appointed_control_role_is_not_a_multiple_actor_omission_task():
    actor = 'Должностное лицо, назначенное ответственным за организацию работы по пожарной безопасности в помещениях ломбарда'
    value = actor + ', контролирует соблюдение Правил пожарной безопасности всем персоналом организации.'
    axis = axis_for(value, actor)
    domain = _axis_answer_domain(axis)
    assert domain is not None and domain['kind'] == 'appointed_control_role'
    q = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, ()))
    assert q is not None and q.kind == 'true_false'
    assert q.options == (actor, actor.replace('назначенное', 'не назначенное', 1))
    assert _axis_answer_domain(replace(axis, required_prompt='Кто отвечает за всё?')) != domain
    assert materialize_assessment(replace(axis, correct_value=actor + ' и любой сотрудник'),
                                  AuthoredAssessment(axis.axis_id, axis.required_prompt, ())) is None


def test_appliance_closing_question_exposes_two_independent_error_targets():
    key = 'Необходимо обесточить все электроприборы и осмотреть на наличие признаков возгорания.'
    axis = axis_for('Каждый сотрудник обязан проверить рабочее место. ' + key, key,
                    subject='ТРЕБОВАНИЯ БЕЗОПАСНОСТИ ПО ОКОНЧАНИИ РАБОТЫ', attribute='срок')
    domain = _axis_answer_domain(axis)
    assert domain is not None and domain['kind'] == 'appliance_closing_duties'
    assert domain['required_components'] == ['deenergize_all_appliances', 'inspect_for_fire_signs']
    assert len(domain['misconception_targets']) == 2
    assert _axis_answer_domain(replace(axis, required_prompt='Какие действия предпринимать при пожаре?')) != domain
