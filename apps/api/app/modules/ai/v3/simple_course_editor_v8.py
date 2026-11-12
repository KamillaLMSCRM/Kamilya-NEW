"""One fallible source-only reading per planned unit, then addressed editing."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_semantics import (
    _read_format,
    compile_source_semantics,
    matches_source_semantics,
)
from app.modules.ai.v3.simple_course_editor import _COMMON
from app.modules.ai.v3.simple_course_editor_v6 import run_simple_course_editor_v6
from app.modules.ai.v3.simple_course_editor_v7 import _BODY, _CARDS, _READ
from app.modules.ai.v3.simple_semantic_source_plan import semantic_unit_request
from app.modules.ai.v3.simple_source_origin import source_origin_blocks

_REFERENTS = (' For every qualifier, identify the exact source entity it qualifies in conditions.applies_to and '
    'conditions.expression. Do not merely repeat a whole multi-entity sentence or name the overall rule. '
    'Split independently applicable qualifiers into separate conditions. Preserve each supporting literal quote '
    'unchanged. Report an uncertainty only when the referent is genuinely undecidable in the approved source.')
_MINIMAL_SPANS = (' For each explicit relation, quote the minimal exact source span sufficient to support that relation; '
    'do not copy entire multi-rule paragraphs into the reading. The complete approved source remains available.')
_GRAMMAR = (' Resolve which original entity a relative or participial qualifier modifies from the original '
    'grammatical case, gender, number and prepositional relationships before paraphrasing. '
    'Do not silently change grammatical agreement to attach a qualifier to the nearest noun. '
    'Preserve the original referent even when a nearby entity would make a familiar real-world rule.')
_SCOPE = (' This source-only reading sees the complete selected primary and dependency closure; '
    'the full document is available to later editors.')
_COMPARE = (' Independently identify the entity bearing each source qualification and the entity bearing that '
    'qualification in the actual draft. Use the original case, gender, number and prepositional relationships; '
    'compare which cases each formulation includes and excludes. Correct a material scope difference even when '
    'the main action, vocabulary or citation matches. Preserve source-supported content and similar correct cards.')


async def run_simple_course_editor_v8(packet: Any, corpus: Any, intent: Any, stage: Any, *,
                                      reference_decisions: tuple[Any, ...] = (), planned_callback: Any = None,
                                      course_editor: Any = None) -> Any:
    view = PracticalModelView(packet)
    plan: dict[str, Any] | None = None
    plan_fp = ''
    readings: list[dict[str, Any]] = []
    selections: dict[str, tuple[dict[str, Any], Any]] = {}

    def typed_blocks() -> list[dict[str, Any]]:
        return [{**row, 'id': view.canonical_to_alias[row['id']]} for row in source_origin_blocks(packet, corpus)
                if row['id'] in view.canonical_to_alias]

    def aggregate() -> dict[str, Any]:
        return compile_source_semantics({'source_fingerprint': packet.fingerprint,
            'sections': [copy.deepcopy(section) for entry in readings for section in entry['reading']['original']['sections']],
            'uncertainties': [copy.deepcopy(row) for entry in readings for row in entry['reading']['original']['uncertainties']]}, packet)

    async def adapted(name: str, group: str, messages: list[dict[str, str]], fmt: Any, validator: Any) -> Any:
        nonlocal plan, plan_fp
        if not group.startswith('practical:simple:') or ':v6:' not in group:
            raise ValueError('simple_v8_stage_invalid')
        if ':plan:v6:' in group:
            wire = await stage(name, group.replace(':v6:', ':v8:', 1), messages, fmt, validator)
            plan = validator(wire)
            plan_fp = _digest(plan)
            for unit in plan['units']:
                _, _, selected = semantic_unit_request(packet, corpus, intent, plan, unit['id'],
                                                        reference_decisions=reference_decisions)
                identity = selected['selection_fingerprint']
                if identity in selections:
                    raise ValueError('simple_v8_unit_selection_invalid')
                selections[identity] = (unit, selected)
            if planned_callback:
                await planned_callback(2 * len(plan['units']) + 3)
            return wire
        if plan is None:
            raise ValueError('simple_v8_plan_missing')
        messages = copy.deepcopy(messages)
        payload = json.loads(messages[1]['content'])
        if ':author-unit:v6:' in group:
            unit_fp = group.rsplit(':unit=', 1)[-1]
            if unit_fp not in selections or any(item['selection_fingerprint'] == unit_fp for item in readings):
                raise ValueError('simple_v8_unit_selection_invalid')
            unit, selection = selections[unit_fp]
            refs = selection['primary_refs'] + selection['supporting_refs']
            reader_payload = {key: payload[key] for key in ('source_fingerprint', 'selection_fingerprint', 'documents',
                'reference_context', 'source_blocks', 'primary_slices', 'supporting_slices')}
            reader_messages = [{'role': 'system', 'content': _READ + _REFERENTS + _MINIMAL_SPANS + _GRAMMAR + _SCOPE},
                {'role': 'user', 'content': json.dumps(reader_payload, ensure_ascii=False, sort_keys=True)}]
            reader_fmt = view.schema(_read_format(refs, packet.fingerprint))
            def validate_read(value: Any) -> dict[str, Any]:
                if not matches_source_semantics(value, reader_fmt):
                    raise ValueError('simple_v8_reading_scope_invalid')
                return compile_source_semantics(view.decode(value), packet)
            reader_group = ('practical:simple:source-read:v8:' + packet.fingerprint + ':plan=' + plan_fp + ':unit=' + unit_fp)
            reading = validate_read(await stage('review', reader_group, reader_messages, reader_fmt, validate_read))
            readings.append({'unit_id': unit['id'], 'plan_fingerprint': plan_fp, 'selection_fingerprint': unit_fp,
                'primary_refs': list(selection['primary_refs']), 'supporting_refs': list(selection['supporting_refs']),
                'reading': copy.deepcopy(reading)})
            payload['independent_source_reading'] = view.encode({'source_fingerprint': packet.fingerprint,
                'reading_fingerprint': reading['reading_fingerprint'], 'sections': reading['sections']})
            messages[0]['content'] += (' The source-only reading is fallible assistance, not source authority. '
                                       'The original source and approved decisions govern; literal custody is not semantic proof.')
            v8_group = ('practical:simple:author-unit:v8:' + packet.fingerprint + ':plan=' + plan_fp + ':unit=' + unit_fp)
        elif ':editor-body:v6:' in group or ':editor-cards:v6:' in group:
            if len(readings) != len(plan['units']):
                raise ValueError('simple_v8_readings_incomplete')
            reading = aggregate()
            slices = payload.pop('source_slices')
            payload['source_slice_index'] = [{key: value for key, value in row.items() if key not in ('text', 'origins')}
                                             for row in slices]
            payload['source_blocks'] = typed_blocks()
            payload['independent_source_reading'] = view.encode(reading['original'])
            payload['independent_reading_custody'] = {'reading_fingerprint': reading['reading_fingerprint'],
                'rule_flags': [{'rule_id': rule['rule_id'], 'custody_valid': rule['custody_valid']}
                               for section in reading['sections'] for rule in section['rules']],
                'uncertainty_flags': [row['custody_valid'] for row in reading['uncertainties']]}
            messages[0]['content'] = _COMMON + '\n' + (_BODY if ':editor-body:v6:' in group else _CARDS) + _COMPARE
            v8_group = group.replace(':v6:', ':v8:', 1)
        else:
            raise ValueError('simple_v8_stage_invalid')
        messages[1]['content'] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return await stage(name, v8_group, messages, fmt, validator)

    async def reviewed_editor(source_packet: Any, source_corpus: Any, source_intent: Any,
        original: Any, source_plan: Any, source_selections: Any, unused_adapted_stage: Any) -> Any:
        if plan is None or len(readings) != len(plan['units']):
            raise ValueError('simple_v8_readings_incomplete')
        return await course_editor(source_packet, source_corpus, source_intent, original,
            source_plan, source_selections, stage, source_reading=aggregate())

    result = await run_simple_course_editor_v6(packet, corpus, intent, adapted,
        reference_decisions=reference_decisions,
        course_editor=None if course_editor is None else reviewed_editor)
    if plan is None or len(readings) != len(plan['units']):
        raise ValueError('simple_v8_readings_incomplete')
    return replace(result, review={**result.review, 'method': 'semantic-unit-source-readings-addressed-editors-v1',
                                   'unit_source_readings': copy.deepcopy(readings),
                                   'source_only_reading': aggregate()})
