import copy

import pytest

from app.modules.ai.v3.isolated_agreement_graph import _agreement, build_agreement_graph


def _edges_for(graph, modifier, nominal):
    section = graph['spans'][0]
    return [edge for edge in section['edges']
            if section['tokens'][edge['modifier_token']]['text'] == modifier
            and section['tokens'][edge['nominal_token']]['text'] == nominal]


def test_exact_offsets_all_parses_and_raw_input_preserved():
    text = '  нового договора. Новые документы!'
    spans = [(0, 18), (19, len(text))]
    before = copy.deepcopy(spans)
    result = build_agreement_graph(text, spans)
    assert spans == before
    assert result['semantic_acceptance'] is False
    assert result['notice'] == 'GRAMMATICAL_POSSIBILITIES_NOT_SYNTACTIC_OR_SEMANTIC_TRUTH'
    for section in result['spans']:
        for token in section['tokens']:
            assert text[token['start']:token['end']] == token['text']
            assert token['parses'] and all(p['normal_form'] and p['tag'] for p in token['parses'])
        assert all(e['modifier_token'] != e['nominal_token'] for e in section['edges'])
    assert {t['text'] for t in result['spans'][0]['tokens']} == {'нового', 'договора'}
    assert {t['text'] for t in result['spans'][1]['tokens']} == {'Новые', 'документы'}


def test_genitive_modifier_has_agreeing_and_disagreeing_case_possibilities():
    text = 'связанного микрокредита физическому лицу'
    graph = build_agreement_graph(text, [(0, len(text))])
    loan = _edges_for(graph, 'связанного', 'микрокредита')
    person = _edges_for(graph, 'связанного', 'лицу')
    assert any(e['case'] == 'COMPATIBLE' and e['status'] == 'COMPATIBLE' for e in loan)
    assert person and all(e['case'] == 'INCOMPATIBLE' for e in person)


def test_gender_number_and_missing_features_are_explicit():
    def row(case, number, gender):
        return {'case': case, 'number': number, 'gender': gender}
    assert _agreement(row('gent', 'sing', 'masc'), row('gent', 'sing', 'femn'))['status'] == 'INCOMPATIBLE'
    assert _agreement(row('gent', 'sing', 'masc'), row('gent', 'plur', None))['status'] == 'INCOMPATIBLE'
    assert _agreement(row('gent', 'plur', None), row('gent', 'plur', None))['gender'] == 'NOT_APPLICABLE'
    assert _agreement(row(None, 'sing', 'masc'), row('gent', 'sing', 'masc'))['status'] == 'UNKNOWN'
    assert _agreement(row('gent', 'sing', None), row('gent', 'sing', 'masc'))['gender'] == 'UNKNOWN'


def test_every_relevant_parse_pair_is_enumerated_even_if_ambiguous():
    text = 'нового договора'
    section = build_agreement_graph(text, [(0, len(text))])['spans'][0]
    modifier, noun = section['tokens']
    expected = {(mi, ni) for mi, m in enumerate(modifier['parses']) if m['pos'] in {'ADJF', 'PRTF'}
                for ni, n in enumerate(noun['parses']) if n['pos'] in {'NOUN', 'NPRO'}}
    actual = {(e['modifier_parse'], e['nominal_parse']) for e in section['edges']
              if e['modifier_token'] == 0 and e['nominal_token'] == 1}
    assert len(modifier['parses']) > 1 and actual == expected and expected


def test_permutation_does_not_prefer_nearest_and_spans_do_not_cross():
    text = 'новый договор клиента. Новый клиент договора.'
    split = text.index('.') + 1
    graph = build_agreement_graph(text, [(0, split), (split, len(text))])
    for section, expected in zip(graph['spans'], ({'договор', 'клиента'}, {'клиент', 'договора'}), strict=True):
        tokens = section['tokens']
        actual = {tokens[e['nominal_token']]['text'].lower() for e in section['edges']}
        assert expected <= actual


def test_paragraph_span_is_split_before_cross_sentence_pairing():
    text = 'Новый договор. Старая карта!'
    result = build_agreement_graph(text, [(0, len(text))])
    assert len(result['spans']) == 2
    for section in result['spans']:
        for edge in section['edges']:
            tokens = section['tokens']
            assert not ({tokens[edge['modifier_token']]['text'], tokens[edge['nominal_token']]['text']}
                        & {'Новый', 'договор'} and
                        {tokens[edge['modifier_token']]['text'], tokens[edge['nominal_token']]['text']}
                        & {'Старая', 'карта'})


@pytest.mark.parametrize('text,spans', [('', [(0, 1)]), ('a', []), ('a', [(0, 2)]),
    ('word', [(1, 4)]), ('a b', [(0, 2), (1, 3)]), ('abc', [(0, True)]), ('abc', 'bad')])
def test_invalid_inputs(text, spans):
    with pytest.raises(ValueError):
        build_agreement_graph(text, spans)
