import copy
import hashlib

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_question_scope import scoped_course_view as actual_scoped_course_view


def scoped_course_view(packet, course):
    return actual_scoped_course_view(packet, course, legacy_source_rule_scope=True)


def packet_for(*sources):
    docs = []
    for index, text in enumerate(sources):
        revision = 'document:' + hashlib.sha256(text.encode()).hexdigest()
        docs.append(DirectSourceDocument(f'doc-{index}', 'Title', 'source.md', 'general', revision, (), source_text=text))
    return build_practical_source_packet(DirectSourceCorpus('tenant', tuple(docs), sum(map(len, sources)), 0))


def course_for(refs):
    return {'title': 'Course', 'lessons': [{'id': 'lesson', 'title': 'Lesson', 'content': 'Text',
        'questions': [{'id': 'q', 'prompt': 'Which action?', 'choices': ['A', 'B', 'C'],
                       'correct_index': 0, 'explanation': 'Explanation', 'source_refs': refs}]}]}


def test_numbered_rule_scope_is_derived_without_mutation():
    packet = packet_for('4.5. Heater requirements.\n')
    course = course_for([packet.blocks[0].block_id])
    before = copy.deepcopy(course)
    result = scoped_course_view(packet, course)
    assert result['lessons'][0]['questions'][0]['prompt'] == 'По указанным положениям источника (п. 4.5): Which action?'
    assert result['lessons'][0]['questions'][0]['choices'] == ['A', 'B', 'C'] and course == before
    with pytest.raises(ValueError, match='already_projected'):
        scoped_course_view(packet, result)


def test_repeated_inner_numbers_are_disambiguated_by_heading():
    packet = packet_for('# 10. First section\n\n1. First rule.\n\n# 11. Second section\n\n1. Second rule.')
    first = next(b for b in packet.blocks if b.text.strip().startswith('1. First'))
    second = next(b for b in packet.blocks if b.text.strip().startswith('1. Second'))
    prompt = scoped_course_view(packet, course_for([first.block_id, second.block_id]))['lessons'][0]['questions'][0]['prompt']
    assert 'разд. 10, п. 1' in prompt and 'разд. 11, п. 1' in prompt


def test_table_and_unnumbered_locators_are_literal_not_invented():
    packet = packet_for('Opening text.\n\n| Type | Value |\n| --- | --- |\n| A | B |\n')
    table = next(b for b in packet.blocks if '| A | B |' in b.text)
    prose = packet.blocks[0]
    prompt = scoped_course_view(packet, course_for([prose.block_id, table.block_id]))['lessons'][0]['questions'][0]['prompt']
    assert 'фрагмент 1' in prompt and 'таблица 1, строка 1' in prompt and '| A | B |' not in prompt


def test_table_ranges_have_no_holes_or_raw_cell_markup():
    packet = packet_for('| Name | Value |\n| --- | --- |\n| A<br>B | 7**00 |\n| C | 100 |\n| D | 200 |\n| E | 300 |\n')
    course = course_for([packet.blocks[i].block_id for i in (0, 1, 2, 4)])
    result = scoped_course_view(packet, course)
    prompt = result['lessons'][0]['questions'][0]['prompt']
    assert 'таблица 1, строки 1–2, 4' in prompt
    assert '<br>' not in prompt and '7**00' not in prompt and prompt.count('таблица 1') == 1


def test_generated_aliases_render_but_literal_source_alias_is_preserved():
    packet = packet_for(''.join(f'Paragraph {i}.\n\n' for i in range(1, 15)))
    course = course_for([packet.blocks[13].block_id])
    course['lessons'][0]['questions'][0]['explanation'] = 'Правило в SRC14 требует действия.'
    course['lessons'][0]['content'] = 'SRC14 связывает условия.'
    before = copy.deepcopy(course)
    result = scoped_course_view(packet, course)
    assert 'в положении источника (фрагмент 14)' in result['lessons'][0]['questions'][0]['explanation']
    assert 'положение источника (фрагмент 14)' in result['lessons'][0]['content']
    assert course == before
    for foreign in ('SRC999', 'SRC0', 'src-abcdef'):
        course['lessons'][0]['content'] = foreign + ' contains an unknown reference.'
        with pytest.raises(ValueError, match='reference_unknown'):
            scoped_course_view(packet, course)
    course['lessons'][0]['content'] = 'По ' + packet.blocks[13].block_id + ' применяется правило.'
    assert 'По положению источника (фрагмент 14)' in scoped_course_view(packet, course)['lessons'][0]['content']
    literal_packet = packet_for('The literal identifier SRC14 is part of the source.')
    literal_course = course_for([literal_packet.blocks[0].block_id])
    literal_course['lessons'][0]['content'] = 'SRC14 is a genuine identifier.'
    assert scoped_course_view(literal_packet, literal_course)['lessons'][0]['content'] == literal_course['lessons'][0]['content']


def test_rendering_cannot_collapse_distinct_choices():
    packet = packet_for('One source paragraph.')
    course = course_for([packet.blocks[0].block_id])
    course['lessons'][0]['questions'][0]['choices'] = ['SRC1', 'положение источника (фрагмент 1)', 'Other']
    with pytest.raises(ValueError, match='practical_course_invalid'):
        scoped_course_view(packet, course)


def test_multidocument_order_and_alias_rejected():
    packet = packet_for('1. First document.', '1. Second document.')
    refs = [block.block_id for block in packet.blocks]
    prompt = scoped_course_view(packet, course_for(refs))['lessons'][0]['questions'][0]['prompt']
    assert 'документ 1, п. 1' in prompt and 'документ 2, п. 1' in prompt
    for ref in ('foreign', 'SRC1'):
        with pytest.raises(ValueError):
            scoped_course_view(packet, course_for([ref]))


def test_child_items_bind_nearest_dotted_parent():
    packet = packet_for('1.8. Staff should:\n\n1) Detect fire.\n\n2) Notify the service.')
    refs = [next(b.block_id for b in packet.blocks if b.text.strip().startswith(prefix)) for prefix in ('1)', '2)')]
    prompt = scoped_course_view(packet, course_for(refs))['lessons'][0]['questions'][0]['prompt']
    assert 'п. 1.8, подп. 1' in prompt and 'п. 1.8, подп. 2' in prompt


def test_children_do_not_cross_markdown_section_parent():
    packet = packet_for('# 10. Section\n\n1. Parent.\n\n1) First child.\n\n'
                        '# 11. Section\n\n1. Parent again.\n\n1) Second child.')
    first = next(b for b in packet.blocks if b.text.strip().startswith('1) First'))
    second = next(b for b in packet.blocks if b.text.strip().startswith('1) Second'))
    prompt = scoped_course_view(packet, course_for([first.block_id, second.block_id]))['lessons'][0]['questions'][0]['prompt']
    assert 'разд. 10, п. 1, подп. 1' in prompt and 'разд. 11, п. 1, подп. 1' in prompt


def test_missing_parent_uses_list_locator_not_prior_section():
    packet = packet_for('# 10. Prior\n\n1. Previous parent.\n\n# 11. Current\n\n1) Orphan child.')
    orphan = next(b for b in packet.blocks if b.text.strip().startswith('1) Orphan'))
    prompt = scoped_course_view(packet, course_for([orphan.block_id]))['lessons'][0]['questions'][0]['prompt']
    assert 'элемент списка 1, блок ' in prompt and 'п. 1' not in prompt


def test_default_preserves_general_question_and_reviewer_receives_later_exception():
    from app.modules.ai.v3.practical_review import practical_review_messages

    packet = packet_for('# 1. Consent\n\n2. A consent threshold is 1000 МРП.\n\n'
                        '# 2. Exception\n\n4. For unmarried applicants the exception is 250 МРП.')
    early = next(block for block in packet.blocks if '1000 МРП' in block.text)
    course = course_for([early.block_id])
    question = course['lessons'][0]['questions'][0]
    question['prompt'] = 'Какая сумма требует согласия, если заявитель не состоит в браке?'
    before = copy.deepcopy(course)
    result = actual_scoped_course_view(packet, course)
    assert result == before and course == before
    content = practical_review_messages(packet, course)[1]['content']
    assert '1000 МРП' in content and '250 МРП' in content
    assert question['prompt'] in content and 'По указанным положениям источника (' not in content


def test_default_keeps_explicit_authored_scope_and_only_renders_tokens():
    packet = packet_for('1. General rule.\n\n2. Specific exception.')
    course = course_for([packet.blocks[0].block_id])
    question = course['lessons'][0]['questions'][0]
    question['prompt'] = 'По указанным положениям источника в пункте 1, какое действие?'
    original = copy.deepcopy(course)
    assert actual_scoped_course_view(packet, course) == original
    question['prompt'] = 'Согласно SRC1 какое действие?'
    before = copy.deepcopy(course)
    result = actual_scoped_course_view(packet, course)
    assert result['lessons'][0]['questions'][0]['prompt'] == 'Согласно положению источника (п. 1) какое действие?'
    for key in ('choices', 'correct_index', 'source_refs'):
        assert result['lessons'][0]['questions'][0][key] == before['lessons'][0]['questions'][0][key]
    assert course == before
