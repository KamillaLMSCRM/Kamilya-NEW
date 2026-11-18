"""Source-unit navigation plan; coverage validation is not semantic approval."""
from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _validate_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_course_editor import _COMMON, _fingerprint_valid, _format, _object
from app.modules.ai.v3.simple_source_origin import source_origin_blocks
from app.modules.ai.v3.source_units import plan_source_units, source_section_label, source_table_topic


def _canonical_format(ids: list[str], fingerprint: str) -> dict[str, Any]:
    refs = {'type': 'array', 'items': {'type': 'string', 'enum': ids}}
    text = {'type': 'string'}
    unit = _object({'id': text, 'title': text, 'primary_refs': {**refs, 'minItems': 1}, 'supporting_refs': refs})
    excluded = _object({'source_refs': {**refs, 'minItems': 1}, 'reason': text})
    return _format('simple_source_unit_plan_v1', _object({
        'source_fingerprint': {'type': 'string', 'enum': [fingerprint]}, 'title': text,
        'units': {'type': 'array', 'minItems': 1, 'items': unit},
        'non_teaching': {'type': 'array', 'items': excluded}}))


def _plan_format(ids: list[str], fingerprint: str) -> dict[str, Any]:
    text = {'type': 'string'}
    refs = {'type': 'array', 'items': {'type': 'string', 'enum': ids}}
    unit = _object({'id': text, 'title': text, 'supporting_refs': refs})
    # A fixed-position vector accounts for every source without a schema node
    # per block, keeping large inputs within the producer's schema limits.
    return _format('simple_source_unit_plan_v2', _object({
        'source_fingerprint': {'type': 'string', 'enum': [fingerprint]}, 'title': text,
        'units': {'type': 'array', 'minItems': 1, 'items': unit},
        'assignments': {'type': 'array', 'minItems': len(ids), 'maxItems': len(ids), 'items': text}}))


def is_source_unit_plan_format(fmt: Any) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        ids = props['units']['items']['properties']['supporting_refs']['items']['enum']
        fingerprint = props['source_fingerprint']['enum'][0]
        return (type(ids) is list and bool(ids) and all(type(x) is str and x.strip() for x in ids)
                and len(set(ids)) == len(ids) and _fingerprint_valid(fingerprint)
                and fmt == _plan_format(ids, fingerprint))
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def matches_source_unit_plan(value: Any, fmt: Any) -> bool:
    if not is_source_unit_plan_format(fmt) or not _matches(value, fmt['json_schema']['schema']):
        return False
    props = fmt['json_schema']['schema']['properties']
    ids = props['units']['items']['properties']['supporting_refs']['items']['enum']
    if not value['title'].strip() or value['source_fingerprint'] != props['source_fingerprint']['enum'][0]:
        return False
    units = value['units']
    unit_ids = [unit['id'] for unit in units]
    if (any(not item.strip() or item in ids or item.startswith('CONTEXT:') for item in unit_ids) or len(set(unit_ids)) != len(unit_ids)
            or any(not unit['title'].strip() for unit in units)):
        return False
    assignments = value['assignments']
    primaries: dict[str, set[str]] = {unit_id: set() for unit_id in unit_ids}
    for ref, assignment in zip(ids, assignments, strict=True):
        if assignment in primaries:
            primaries[assignment].add(ref)
        elif not (assignment.startswith('CONTEXT: ') and assignment[len('CONTEXT: '):].strip()):
            return False
    return all(primaries[unit['id']] for unit in units)


def _matches_canonical(value: Any, fmt: Any) -> bool:
    if not _matches(value, fmt['json_schema']['schema']):
        return False
    props = fmt['json_schema']['schema']['properties']
    ids = props['units']['items']['properties']['primary_refs']['items']['enum']
    if not value['title'].strip() or value['source_fingerprint'] != props['source_fingerprint']['enum'][0]:
        return False
    units = value['units']
    unit_ids = [unit['id'] for unit in units]
    if (any(not item.strip() or item in ids or item.startswith('CONTEXT:') for item in unit_ids) or len(set(unit_ids)) != len(unit_ids)
            or any(not unit['title'].strip() for unit in units)):
        return False
    primary = [ref for unit in units for ref in unit['primary_refs']]
    non_teaching = [ref for row in value['non_teaching'] for ref in row['source_refs']]
    if (any(not row['reason'].strip() for row in value['non_teaching'])
            or len(primary) != len(set(primary)) or len(non_teaching) != len(set(non_teaching))
            or set(primary) & set(non_teaching) or set(primary + non_teaching) != set(ids)):
        return False
    return all(len(unit['supporting_refs']) == len(set(unit['supporting_refs']))
               and not set(unit['primary_refs']) & set(unit['supporting_refs']) for unit in units)


def source_unit_plan_request(packet: PracticalSourcePacket, corpus: DirectSourceCorpus,
                             intent: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    from app.modules.ai.v3.simple_course_editor_v2 import _current_context

    view, context = _current_context(packet, corpus, intent)
    context['source_blocks'] = [{**row, 'id': view.canonical_to_alias[row['id']]}
        for row in source_origin_blocks(packet, corpus) if row['id'] in view.canonical_to_alias]
    by_span = {(block.doc_id, block.start, block.end): block for block in packet.blocks}
    structure = []
    for doc in corpus.documents:
        source = doc.source_text or ''
        headers: dict[str, list[Any]] = {}
        for unit in plan_source_units(source):
            block = by_span[(doc.doc_id, unit.start, unit.end)]
            if unit.kind == 'table_header':
                headers[unit.container_id] = [unit]
            elif unit.kind == 'table_row':
                current = headers.get(unit.container_id, [])
                if current and unit.context == ''.join(item.text for item in current) + unit.text:
                    headers[unit.container_id].append(unit)
            if not block.text.strip():
                continue
            header_refs = [view.canonical_to_alias[header.block_id] for item in headers.get(unit.container_id, [])
                           if (item.start, item.end) != (unit.start, unit.end)
                           for header in [by_span[(doc.doc_id, item.start, item.end)]] if header.text.strip()]
            structure.append({'source_ref': view.canonical_to_alias[block.block_id], 'document_id': doc.doc_id,
                'kind': unit.kind, 'section_label': source_section_label(source, unit),
                'table_topic': source_table_topic(unit), 'table_header_refs': header_refs})
    context['source_structure'] = structure
    context['assignment_source_order'] = list(view.alias_to_canonical)
    assignment_index = {alias: index for index, alias in enumerate(context['assignment_source_order'])}
    for block in context['source_blocks']:
        if block['id'] is not None:
            block['assignment_index'] = assignment_index[block['id']]
    instruction = ('Plan meaningful teachable units from the complete current approved literal source. '
        'Fill the fixed-length assignments array in assignment_source_order, one value for each source ID at its assignment_index: '
        'use exactly the owning unit ID, or use '
        '"CONTEXT: " followed by a nonempty reason for non-teaching context. Unit IDs must not start with "CONTEXT:". '
        'Every unit needs at least one primary assignment. '
        'Group related operative material into coherent topics; never classify an operative instruction as auxiliary or non-teaching merely because it is brief. '
        'Prefer meaningful original section boundaries, combining short related subsections into one coherent practical lesson '
        'with 3–4 nonredundant questions; split only for distinct practical tasks, without an arbitrary count or size limit. '
        'Follow unambiguous textual references to the actual target procedures and conditions as supporting references, '
        'not merely their heading. Human-confirmed decisions govern ambiguous references. Include literal parent headings, '
        'table headers and definitions where needed; support can be shared across units. Structural metadata is navigation only, '
        'not a substitute for the literal source. Non-teaching is only for administrative or contextual material '
        'and requires a reason. Source segments retain their origin: visual_ocr and visual_description '
        'come from embedded illustrations; their field labels and sample values do not alone assign employee duties. '
        'Use surrounding document instructions and approved interpretations to understand an illustration’s role. '
        'Origin itself does not establish normative authority. Titles and groupings are navigation, '
        'never replacement source or normative summaries.')
    messages = [{'role': 'system', 'content': _COMMON + '\n' + instruction},
                {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, sort_keys=True)}]
    return messages, _plan_format(list(view.alias_to_canonical), packet.fingerprint)


def decode_source_unit_plan(value_wire: Any, view: PracticalModelView) -> Any:
    """Compile the fixed source-ordered wire assignments into canonical references."""
    if (type(value_wire) is not dict or type(value_wire.get('source_fingerprint')) is not str
            or not matches_source_unit_plan(value_wire, _plan_format(list(view.alias_to_canonical), value_wire['source_fingerprint']))):
        raise ValueError('simple_unit_plan_invalid')
    units = [{'id': unit['id'], 'title': unit['title'], 'primary_refs': [],
              'supporting_refs': [view.alias_to_canonical[ref] for ref in unit['supporting_refs']]}
             for unit in value_wire['units']]
    by_id = {unit['id']: unit for unit in units}
    non_teaching = []
    for alias, assignment in zip(view.alias_to_canonical, value_wire['assignments'], strict=True):
        ref = view.alias_to_canonical[alias]
        if assignment.startswith('CONTEXT: '):
            non_teaching.append({'source_refs': [ref], 'reason': assignment[len('CONTEXT: '):]})
        else:
            by_id[assignment]['primary_refs'].append(ref)
    for unit in units:
        primary = set(unit['primary_refs'])
        unit['supporting_refs'] = list(dict.fromkeys(ref for ref in unit['supporting_refs'] if ref not in primary))
    return {'source_fingerprint': value_wire['source_fingerprint'], 'title': value_wire['title'],
            'units': units, 'non_teaching': non_teaching}


def encode_source_unit_plan(value_canonical: Any, view: PracticalModelView) -> dict[str, Any]:
    """Encode canonical plans for synthetic transports; not an authority check."""
    if (type(value_canonical) is not dict or type(value_canonical.get('source_fingerprint')) is not str
            or not _fingerprint_valid(value_canonical['source_fingerprint'])
            or not _matches_canonical(value_canonical, _canonical_format(list(view.canonical_to_alias), value_canonical['source_fingerprint']))):
        raise ValueError('simple_unit_plan_invalid')
    assignments = {}
    for unit in value_canonical['units']:
        for ref in unit['primary_refs']:
            assignments[view.canonical_to_alias[ref]] = unit['id']
    for row in value_canonical['non_teaching']:
        for ref in row['source_refs']:
            assignments[view.canonical_to_alias[ref]] = 'CONTEXT: ' + row['reason']
    return {'source_fingerprint': value_canonical['source_fingerprint'], 'title': value_canonical['title'],
            'units': [{'id': unit['id'], 'title': unit['title'],
                       'supporting_refs': [view.canonical_to_alias[ref] for ref in unit['supporting_refs']]}
                      for unit in value_canonical['units']],
            'assignments': [assignments[alias] for alias in view.alias_to_canonical]}


def compile_source_unit_plan(value_canonical: Any, packet: PracticalSourcePacket) -> dict[str, Any]:
    _validate_packet(packet)
    fmt = _canonical_format([block.block_id for block in packet.blocks if block.text.strip()], packet.fingerprint)
    if not _matches_canonical(value_canonical, fmt):
        raise ValueError('simple_unit_plan_invalid')
    return copy.deepcopy(value_canonical)
