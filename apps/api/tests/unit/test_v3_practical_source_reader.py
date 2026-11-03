import copy
import json

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_reader import (
    is_source_read_format,
    matches_source_read,
    source_read_format,
    source_read_messages,
    source_reader_parts,
    validate_source_read,
)


def packet(*texts):
    docs = tuple(DirectSourceDocument(f'doc{i}', 'Title', 'f', 'general', 'r1', (), source_text=text)
                 for i, text in enumerate(texts))
    return build_practical_source_packet(DirectSourceCorpus('tenant', docs, sum(map(len, texts)), 0))


def response(p, part):
    return {'source_fingerprint': p.fingerprint, 'part_fingerprint': part.fingerprint,
            'source_checks': [{'unit_id': key, 'status': 'NORM',
                               'rules': [{'actor': 'worker', 'action': 'check', 'object': 'device',
                                          'conditions': ['a', 'b'], 'condition_relation': 'ALL',
                                          'alternatives': [], 'source_refs': list(refs)}]}
                              for key, refs in part.groups], 'source_notes': [], 'unresolved_refs': []}


def source_text(payload, scope):
    return ''.join(block['text'] for block in payload['source_blocks'] if block['scope'] == scope)


def test_partition_custody_and_context():
    text = 'Cover\n\n# 1. Definitions\nFirst.\n\n## Extra\nContinuation.\n\n# 2. Work\nSecond.\n\n## 2.1. Detail\nThird.\n\n# 3. End\nLast.\n'
    p = packet(text, 'Whole document without headings.\n')
    parts = source_reader_parts(p)
    assert len(parts) == 4
    assert [g for part in parts for g in part.groups] == list(audit_units(p).groups)
    payloads = [json.loads(source_read_messages(p, part)[1]['content']) for part in parts]
    assert ''.join(source_text(x, 'primary') for x in payloads[:3]) == text
    assert 'Continuation' in source_text(payloads[0], 'primary')
    assert '2.1. Detail' in source_text(payloads[1], 'primary')
    assert '# 3. End' not in source_text(payloads[1], 'primary')
    assert source_text(payloads[1], 'definition_context') == source_text(payloads[0], 'primary')
    assert source_text(payloads[3], 'definition_context') == ''
    for part in parts:
        assert validate_source_read(response(p, part), p, part)


def test_closed_format_membership_and_alias():
    p = packet('# 1. Definitions\nTerms.\n\n# 2. Work\nRule.\n')
    first, part = source_reader_parts(p)
    fmt = source_read_format(p, part)
    value = response(p, part)
    assert is_source_read_format(fmt) and matches_source_read(value, fmt)
    view = PracticalModelView(p)
    assert matches_source_read(view.encode(value), view.schema(fmt))
    assert validate_source_read(view.decode(view.encode(value)), p, part) == value
    supplemented = copy.deepcopy(value)
    supplemented['source_checks'][0]['rules'][0]['source_refs'].extend(first.groups[0][1])
    assert validate_source_read(supplemented, p, part)
    assert 'SRC' in source_read_messages(p, part, view)[1]['content']
    for mutate in ('duplicate', 'foreign', 'context', 'index', 'fingerprint', 'empty_norm'):
        bad = copy.deepcopy(value)
        if mutate == 'duplicate':
            bad['source_checks'].append(copy.deepcopy(bad['source_checks'][0]))
        elif mutate == 'foreign':
            bad['source_checks'][0]['rules'][0]['source_refs'] = ['foreign']
        elif mutate == 'context':
            bad['source_checks'][0]['rules'][0]['source_refs'] = list(first.groups[0][1])
        elif mutate == 'index':
            bad['source_checks'][0]['rule_indices'] = [999]
        elif mutate == 'fingerprint':
            bad['part_fingerprint'] = '0' * 64
        else:
            bad['source_checks'][0]['rules'] = []
        with pytest.raises(ValueError):
            validate_source_read(bad, p, part)
    badfmt = copy.deepcopy(fmt)
    badfmt['json_schema']['schema']['additionalProperties'] = True
    assert not is_source_read_format(badfmt)


def test_uncertainty_and_condition_relation_require_structural_support():
    p = packet('# 1. Terms\nA.\n\n# 2. Rules\nB.\n')
    part = source_reader_parts(p)[1]
    value = response(p, part)
    for relation, conditions in [('ANY', []), ('SINGLE', ['a', 'b'])]:
        bad = copy.deepcopy(value)
        bad['source_checks'][0]['rules'][0].update(condition_relation=relation, conditions=conditions)
        assert not matches_source_read(bad, source_read_format(p, part))
    for relation, conditions in [('ALL', ['one']), ('ANY', ['one or another']), ('ALL', [])]:
        valid = copy.deepcopy(value)
        valid['source_checks'][0]['rules'][0].update(condition_relation=relation, conditions=conditions)
        # A one-element logical operator retains the whole opaque predicate;
        # no source text is split, guessed, or rewritten by the validator.
        assert validate_source_read(valid, p, part) == valid
    uncertain = copy.deepcopy(value)
    uncertain['source_checks'][0]['status'] = 'UNCERTAIN'
    assert not matches_source_read(uncertain, source_read_format(p, part))
    uncertain['source_notes'] = [{'note': 'Ambiguous.', 'source_refs': list(part.groups[0][1])}]
    assert validate_source_read(uncertain, p, part)
    uncertain['source_notes'][0]['source_refs'] = list(source_reader_parts(p)[0].groups[0][1])
    with pytest.raises(ValueError):
        validate_source_read(uncertain, p, part)
    context = copy.deepcopy(value)
    context['source_checks'][0]['status'] = 'CONTEXT'
    assert not matches_source_read(context, source_read_format(p, part))


def test_twenty_five_nested_rules_and_legacy_pointers_rejected():
    p = packet('# 1. Terms\nA.\n\n# 2. Rules\nB.\n')
    part = source_reader_parts(p)[1]
    value = response(p, part)
    example = value['source_checks'][0]['rules'][0]
    value['source_checks'][0]['rules'] = [dict(example, object=f'device {i}') for i in range(25)]
    assert validate_source_read(value, p, part) == value
    old = copy.deepcopy(value)
    old['rules'] = old['source_checks'][0].pop('rules')
    old['source_checks'][0]['rule_indices'] = list(range(26))
    assert not matches_source_read(old, source_read_format(p, part))
    with pytest.raises(ValueError):
        validate_source_read(old, p, part)


def test_schema_budget():
    p = packet('# 1. Terms\nText.\n\n# 2. Rules\nDo it.\n')
    fmt = source_read_format(p, source_reader_parts(p)[1])
    def count(node):
        if isinstance(node, dict):
            return 1 + sum(count(v) for v in node.values())
        if isinstance(node, list):
            return 1 + sum(count(v) for v in node)
        return 1
    assert count(fmt) < 512
    assert len(json.dumps(fmt).encode()) < 65536


def test_cover_groups_stay_inside_major_sections():
    p = packet('Cover\n\n# 1. First\nText.\n\n# 2. Second\nText.\n')
    parts = source_reader_parts(p)
    assert len(parts) == 2
    assert 'Cover' in source_text(json.loads(source_read_messages(p, parts[0])[1]['content']), 'primary')
    assert all(validate_source_read(response(p, part), p, part) for part in parts)
