"""A conditional handover signature is one decision, not unrelated workflow steps."""
from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes, materialize_assessment
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.quality import answer_containment_option_indices
from app.modules.ai.evidence_engine.semantic_assessment import (
    _axis_answer_domain,
    _axis_author_payload,
    _constraint_request,
    _review_request,
)

VALUE = (
    "Сменный специалист во время приема-передачи участка (если операция не согласована руководителем) "
    "обязан визуально проверить соответствие объекта выданной сумме. "
    "В случае своего согласия поставить свою подпись в карточке. "
    "Если объект вызывает подозрения в отношении качественных характеристик, "
    "то сменный специалист обязан сразу уведомить руководителя."
)
KEY = 'поставить свою подпись в карточке'


def fixture(value=VALUE):
    fact = SourceFact('f', 'Категория Б', 'Порядок', value, 'doc_id=synthetic;table=1;row=2;column=2')
    lesson = LessonDraft('l', '', '', '', '', ('f',), (), 1)
    axis = next(a for a in derive_assessment_axes(lesson, [fact], block_id='b') if a.correct_value == KEY)
    return axis, fact


def test_complete_conditional_signature_uses_a_source_bound_binary_without_fake_steps():
    axis, fact = fixture()
    # These are the actual failure pattern: other acts and invented prerequisites.
    authored = AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        'Составить акт несоответствия',
        'Направить карточку в Стоп-лист',
        'Отказаться подписывать карточку до повторного согласования',
    ))
    q = materialize_assessment(axis, authored)
    assert q is not None and q.kind == 'true_false'
    assert q.options == (KEY, 'не требуется ' + KEY)
    assert q.correct_answer == q.source_quote == KEY
    assert 'если операция не согласована руководителем' in q.prompt
    assert 'В случае своего согласия' in q.prompt
    assert 'во время приема-передачи участка' in q.prompt
    assert answer_containment_option_indices(q) == ()
    domain = _axis_answer_domain(axis)
    assert domain is not None and domain['kind'] == 'conditioned_signing_action'
    first = _review_request('b', [q], [fact], answer_domains={q.question_id: domain})
    second = _constraint_request({'block_id': 'b', 'facts': first['governing_facts'],
                                  'axes': [_axis_author_payload(axis)]}, [q])
    assert first['questions'][0]['answer_domain'] == second['questions'][0]['answer_domain'] == domain


def test_signature_domain_does_not_invent_nonapproval_for_an_explicit_positive_condition():
    axis, _fact = fixture(VALUE.replace('не согласована', 'согласована'))
    q = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, ()))
    assert q is not None and 'если операция согласована руководителем' in q.prompt
    assert 'non-approval' not in _axis_answer_domain(axis)['scope']


@pytest.mark.parametrize('mutation', ['drop_nonapproval', 'drop_agreement', 'different_key', 'no_source'])
def test_unproved_or_broadened_signature_does_not_gain_a_binary(mutation):
    axis, _fact = fixture()
    if mutation == 'drop_nonapproval':
        axis = replace(axis, required_prompt=axis.required_prompt.replace('если операция не согласована руководителем', 'любая операция'))
    elif mutation == 'drop_agreement':
        axis = replace(axis, required_prompt=axis.required_prompt.replace('В случае своего согласия', 'в любом случае'))
    elif mutation == 'different_key':
        axis = replace(axis, correct_value=KEY + ' и закрыть участок')
    else:
        axis = replace(axis, distractor_constraints=())
    assert materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, ())) is None
