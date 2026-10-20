"""A converter attribute is not a source-proved normative category."""
from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.provider_engine import coalesce_grounded_blocks
from app.modules.ai.evidence_engine.provider_models import GroundedBlock


def test_generic_right_label_does_not_turn_assigned_responsibility_into_permission():
    text = ('1.4. Обеспечение пожарной безопасности и пожаротушение возлагается на руководителя организации. '
            'Руководитель организации назначает лиц, ответственных за пожарную безопасность.')
    fact = SourceFact('f', '1. ОБЩИЕ ПОЛОЖЕНИЯ', 'право', text, 'doc_id=synthetic;part=1')
    blocks = coalesce_grounded_blocks([GroundedBlock('l', 'право', text, ('f',))], {'f': fact})
    assert blocks[0].heading == 'Правило 1.4'
    assert blocks[0].text == text


def test_meaningful_authored_heading_and_table_attribute_are_preserved():
    prose = SourceFact('f', 'Общие положения', 'право', 'Руководитель назначает ответственное лицо.', 'doc_id=synthetic;part=1')
    block = GroundedBlock('l', 'Ответственность руководителя', prose.value, ('f',))
    assert coalesce_grounded_blocks([block], {'f': prose})[0].heading == block.heading
    cell = SourceFact('c', 'Модель', 'Право', 'Использование', 'doc_id=synthetic;sheet=1;row=1;column=2')
    assert coalesce_grounded_blocks([GroundedBlock('l', 'Право', cell.value, ('c',))], {'c': cell})[0].heading == 'Право'


def test_multi_fact_generic_label_cannot_assign_a_permission_category():
    facts = {key: SourceFact(key, '1. ОБЩИЕ ПОЛОЖЕНИЯ', 'право', text, 'doc_id=synthetic;part=1')
             for key, text in [('a', '1.4. Руководитель назначает ответственное лицо.'),
                               ('b', '1.5. Сотрудники проходят инструктаж.') ]}
    body = '\n\n'.join(f.value for f in facts.values())
    blocks = coalesce_grounded_blocks([GroundedBlock('l', 'право', body, tuple(facts))], facts)
    assert blocks[0].heading == 'Подтверждённые сведения'
    assert blocks[0].text == body and blocks[0].fact_ids == tuple(facts)
