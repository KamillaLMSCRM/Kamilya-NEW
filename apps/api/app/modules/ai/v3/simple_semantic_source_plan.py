"""Addressable literal slices and source-only planning, without semantic certification."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_editor import _COMMON, _fingerprint_valid, _format, _object
from app.modules.ai.v3.simple_course_editor_v2 import _current_context
from app.modules.ai.v3.simple_source_origin import source_origin_blocks
from app.modules.ai.v3.simple_source_unit import source_unit_request
from app.modules.ai.v3.source_units import plan_source_units, source_table_topic


def build_semantic_slices(packet: Any, corpus: Any) -> list[dict[str, Any]]:
    origins = source_origin_blocks(packet, corpus)
    structures = {(doc.doc_id, unit.start, unit.end): unit for doc in corpus.documents
                  for unit in plan_source_units(doc.source_text or '')}
    result: list[dict[str, Any]] = []
    for block, origin in zip(packet.blocks, origins, strict=True):
        structural = structures[(block.doc_id, block.start, block.end)]
        parent = {'kind': structural.kind, 'row_label': source_table_topic(structural),
                  'table_header': structural.context}
        segments = origin['segments']
        pos = block.start
        index = 0
        while index < len(segments):
            segment = segments[index]
            # Keep an image's OCR and description together as one observation.
            if segment.get('asset_id') and segment['origin'] in ('visual_ocr', 'visual_description'):
                group = [segment]
                while (index + 1 < len(segments) and segments[index + 1].get('asset_id') == segment['asset_id']
                       and segments[index + 1]['origin'] in ('visual_ocr', 'visual_description')):
                    index += 1
                    group.append(segments[index])
                pieces = [group]
            elif segment['origin'] == 'unclassified_text' and 'source-asset:' in segment['text']:
                # Unknown visual boundaries cannot safely be divided into observations.
                pieces = [[segment]]
            else:
                text = segment['text']
                parts = re.split(r'(?<=\n)|(?<=<br>)|(?<=<br/>)|(?<=<br />)', text, flags=re.IGNORECASE)
                pieces = [[{**segment, 'text': part}] for part in parts if part]
            for group in pieces:
                literal = ''.join(part['text'] for part in group)
                result.append({'id': f'S{len(result) + 1}', 'source_ref': block.block_id,
                               'document_id': block.doc_id, 'start': pos, 'end': pos + len(literal),
                               'text': literal, 'structure': parent, 'origins': copy.deepcopy(group)})
                pos += len(literal)
            index += 1
        if pos != block.end:
            raise ValueError('semantic_slice_origin_invalid')
    return result


def _plan_format(ids: list[str], source_fp: str, catalog_fp: str) -> dict[str, Any]:
    text = {'type': 'string'}
    refs = {'type': 'array', 'items': {'type': 'string', 'enum': ids}}
    unit = _object({'id': text, 'title': text, 'primary_slices': {**refs, 'minItems': 1},
                    'supporting_slices': refs})
    excluded = _object({'slice_ids': {**refs, 'minItems': 1}, 'reason': text})
    return _format('simple_semantic_source_plan_v1', _object({
        'source_fingerprint': {'type': 'string', 'enum': [source_fp]},
        'slices_fingerprint': {'type': 'string', 'enum': [catalog_fp]}, 'title': text,
        'units': {'type': 'array', 'minItems': 1, 'items': unit},
        'non_teaching': {'type': 'array', 'items': excluded}}))


def semantic_plan_format(packet: Any, corpus: Any) -> dict[str, Any]:
    catalog = build_semantic_slices(packet, corpus)
    ids = [item['id'] for item in catalog if item['text'].strip()]
    if not ids:
        raise ValueError('semantic_slice_empty')
    return _plan_format(ids, packet.fingerprint, _digest(catalog))


def is_semantic_plan_format(fmt: Any) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        ids = props['units']['items']['properties']['primary_slices']['items']['enum']
        source = props['source_fingerprint']['enum'][0]
        catalog = props['slices_fingerprint']['enum'][0]
        return (type(ids) is list and bool(ids) and all(type(x) is str and x.strip() for x in ids)
                and len(ids) == len(set(ids)) and _fingerprint_valid(source) and _fingerprint_valid(catalog)
                and fmt == _plan_format(ids, source, catalog))
    except (TypeError, KeyError, IndexError, ValueError):
        return False


def _matches_semantic_plan(value: Any, fmt: Any, *, complete: bool) -> bool:
    if not is_semantic_plan_format(fmt) or not _matches(value, fmt['json_schema']['schema']):
        return False
    ids = set(fmt['json_schema']['schema']['properties']['units']['items']['properties']['primary_slices']['items']['enum'])
    if not value['title'].strip():
        return False
    unit_ids = [unit['id'] for unit in value['units']]
    if len(unit_ids) != len(set(unit_ids)) or any(not item.strip() or item in ids for item in unit_ids):
        return False
    primary: set[str] = set()
    accounted: set[str] = set()
    for unit in value['units']:
        p, s = unit['primary_slices'], unit['supporting_slices']
        if not unit['title'].strip() or len(set(p + s)) != len(p) + len(s):
            return False
        primary.update(p)
        accounted.update(p + s)
    excluded: set[str] = set()
    for item in value['non_teaching']:
        refs = item['slice_ids']
        if not item['reason'].strip() or len(set(refs)) != len(refs) or excluded.intersection(refs):
            return False
        excluded.update(refs)
    # Referenced parent/definition context is accounted input, not missing
    # primary teaching. This check establishes ownership, never semantic coverage.
    return not primary.intersection(excluded) and (not complete or accounted | excluded == ids)


def matches_semantic_plan(value: Any, fmt: Any) -> bool:
    return _matches_semantic_plan(value, fmt, complete=True)


def matches_semantic_plan_structure(value: Any, fmt: Any) -> bool:
    """Typed, owned plan structure; complete source accounting belongs to the consumer."""
    return _matches_semantic_plan(value, fmt, complete=False)


def semantic_plan_request(packet: Any, corpus: Any, intent: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    view, context = _current_context(packet, corpus, intent)
    catalog = build_semantic_slices(packet, corpus)
    context['source_slices'] = [{**row, 'source_ref': view.canonical_to_alias.get(row['source_ref']),
        'origins': [{k: v for k, v in origin.items() if k != 'text'} for origin in row['origins']]}
        for row in catalog]
    context.pop('source_blocks', None)
    fmt = semantic_plan_format(packet, corpus)
    context['slices_fingerprint'] = fmt['json_schema']['schema']['properties']['slices_fingerprint']['enum'][0]
    instruction = ('Group literal source slices into coherent practical teaching units. Identify actual actors, actions, '
        'conditions, dependencies and branches; preserve parent scope and outcomes. Select primary slices and supporting '
        'context. A slice may support multiple units. Account for every nonblank slice as primary or give a reason it is '
        'non-teaching. Use introductory roles, purpose and definitions as context for practical units unless they '
        'support useful independent practice; do not create padded lessons or questions about what a fragment mentions. '
        'Exact table row labels and headers identify the scope of excerpts. Example labels alone do not establish '
        'duties. This plan is navigation, not verified source truth.')
    return ([{'role': 'system', 'content': _COMMON + '\n' + instruction},
             {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, sort_keys=True)}], fmt)


def compile_semantic_plan(value: Any, packet: Any, corpus: Any) -> dict[str, Any]:
    if not matches_semantic_plan(value, semantic_plan_format(packet, corpus)):
        raise ValueError('semantic_plan_invalid')
    return copy.deepcopy(value)


def semantic_unit_request(packet: Any, corpus: Any, intent: Any, plan: Any, unit_id: str,
                          reference_decisions: tuple[Any, ...] = ()) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    plan = compile_semantic_plan(plan, packet, corpus)
    found = [unit for unit in plan['units'] if unit['id'] == unit_id]
    if len(found) != 1:
        raise ValueError('semantic_unit_id_invalid')
    unit = found[0]
    catalog = {row['id']: row for row in build_semantic_slices(packet, corpus)}
    primary = list(dict.fromkeys(catalog[s]['source_ref'] for s in unit['primary_slices']))
    supporting = list(dict.fromkeys(catalog[s]['source_ref'] for s in unit['supporting_slices']
                                    if catalog[s]['source_ref'] not in primary))
    messages, fmt, selection = source_unit_request(packet, corpus, intent, primary, supporting,
                                                     reference_decisions=reference_decisions)
    payload = json.loads(messages[1]['content'])
    from app.modules.ai.v3.practical_model_view import PracticalModelView
    view = PracticalModelView(packet)
    def visible(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, 'source_ref': view.canonical_to_alias[row['source_ref']],
                'origins': [{k: v for k, v in origin.items() if k != 'text'} for origin in row['origins']]}
    payload['primary_slices'] = [visible(catalog[s]) for s in unit['primary_slices']]
    payload['supporting_slices'] = [visible(catalog[s]) for s in unit['supporting_slices']]
    origin_by_ref = {view.canonical_to_alias[row['id']]: row for row in source_origin_blocks(packet, corpus)
                     if row['id'] in view.canonical_to_alias}
    payload['source_blocks'] = [{'id': block['id'], 'document_id': block['document_id'],
        'role': 'literal_parent_context', 'segments': origin_by_ref[block['id']]['segments']}
        for block in payload['source_blocks']]
    payload['unit_title'] = unit['title']
    payload['course_outline'] = [{'id': row['id'], 'title': row['title']} for row in plan['units']]
    messages[0]['content'] += (' The exact primary_slices define the teaching topic; source_blocks are literal parent and '
                               'dependency context, not a demand to teach all neighboring material. Use supporting slices '
                               'for conditions and preserve source-asset illustrations where relevant. Literal '
                               'structure labels bind excerpts to their parent scope; make that scope explicit when '
                               'it limits an instruction. Write practical employee learning material, not commentary '
                               'about an available fragment. Assess the primary practical topic rather than '
                               're-quizzing supporting definitions from neighboring units. Do not expose internal '
                               'source aliases in learner text.')
    messages[1]['content'] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    slices = [copy.deepcopy(catalog[s]) for s in unit['primary_slices'] + unit['supporting_slices']]
    metadata = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': plan['slices_fingerprint'],
                'selection_fingerprint': _digest([packet.fingerprint, plan['slices_fingerprint'], unit,
                                                  list(selection.primary_refs), list(selection.supporting_refs)]),
                'primary_refs': list(selection.primary_refs), 'supporting_refs': list(selection.supporting_refs),
                'slices': slices}
    return messages, fmt, metadata
