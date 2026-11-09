"""Untrusted source/learner attachment navigation over exact owned records."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any

from app.modules.ai.v3.isolated_agreement_graph import _analyzer, build_agreement_graph
from app.modules.ai.v3.isolated_attachment_choice_contract import (
    attachment_choice_format,
    matches_attachment_choice_response,
)
from app.modules.ai.v3.practical_contract import _digest

GUIDE = 'Для каждого task выбери действительную грамматическую вершину определения\nв точном тексте его record. Это выбор связи между существующими словами, не\nпересказ правила и не проверка курса. Кандидаты получены перебором ВСЕХ словарных\nразборов и согласований; список допускает лишние варианты и не доказывает связь.\nГолова может находиться не рядом с определением. Проверь весь исходный контекст\nзаписи и роль слов; не выбирай случайный омоним или служебное слово только потому,\nчто словарь допускает номинальную интерпретацию. Не меняй формы слов и не\nподменяй их предполагаемым обычным смыслом. При недостатке основания выбирай\nUNKNOWN. Если список пуст, возможен только UNKNOWN. Не придумывай последствий,\nне решай существенность и не формулируй вопросов человеку. selected_head_id —\nодин из переданных координатных ID или UNKNOWN; краткое основание — rationale.\nВсе выборы остаются непроверенными гипотезами. Сохрани роль и отпечатки.'


def _inventory(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    if type(records) is not list or any(type(r) is not dict or set(r) != {'id', 'text', 'sha256'} for r in records):
        raise ValueError('attachment_records_invalid')
    ids = [r['id'] for r in records]
    if (any(type(r['id']) is not str or not r['id'] or type(r['text']) is not str
            or not r['text'] or r['sha256'] != hashlib.sha256(r['text'].encode('utf8')).hexdigest() for r in records)
            or len(ids) != len(set(ids))):
        raise ValueError('attachment_records_invalid')
    result = []
    for record in records:
        graph = build_agreement_graph(record['text'], [(0, len(record['text']))])
        tasks: list[dict[str, Any]] = []
        spans = []
        for span in graph['spans']:
            edges: Any = defaultdict(Counter)
            for edge in span['edges']:
                edges[(edge['modifier_token'], edge['nominal_token'])][edge['status']] += 1
            tokens = []
            for index, token in enumerate(span['tokens']):
                parses = token['parses']
                tokens.append({'text': token['text'], 'start': token['start'], 'end': token['end'],
                    'lemmas': frozenset(row['normal_form'] for row in parses),
                    'modifier': any(row['pos'] in ('ADJF', 'PRTF') for row in parses),
                    'all_readings': copy.deepcopy(parses)})
                if not tokens[-1]['modifier']:
                    continue
                mid = f"W{token['start']}_{token['end']}"
                heads = []
                for (source, target), counts in sorted(edges.items()):
                    if source != index or not (counts['COMPATIBLE'] or counts['UNKNOWN']):
                        continue
                    head = span['tokens'][target]
                    heads.append({'token_id': f"W{head['start']}_{head['end']}", 'text': head['text'],
                                  'start': head['start'], 'end': head['end']})
                tasks.append({'task_id': record['id'] + ':' + mid, 'record_id': record['id'],
                    'modifier_token_id': mid, 'modifier_text': token['text'],
                    'modifier_start': token['start'], 'modifier_end': token['end'], 'head_candidates': heads})
            for match in re.finditer(r'\d+', record['text'][span['start']:span['end']]):
                start, end = span['start'] + match.start(), span['start'] + match.end()
                parses = _analyzer().parse(match.group())
                tokens.append({'text': match.group(), 'start': start, 'end': end,
                    'lemmas': frozenset(p.normal_form for p in parses), 'modifier': False,
                    'all_readings': [{'normal_form': p.normal_form, 'tag': str(p.tag), 'pos': p.tag.POS,
                                      'case': p.tag.case, 'number': p.tag.number, 'gender': p.tag.gender} for p in parses]})
            tokens.sort(key=lambda token: (token['start'], token['end']))
            spans.append({'start': span['start'], 'end': span['end'], 'tokens': tokens})
        result.append({'record': copy.deepcopy(record), 'tasks': tasks, 'segments': spans})
    return result


def _matches_token(source: dict[str, Any], learner: dict[str, Any]) -> bool:
    if source['text'].isdigit() or learner['text'].isdigit():
        return bool(source['text'] == learner['text'])
    return bool(source['lemmas'] & learner['lemmas'])


def _nominal_only(text: str) -> bool:
    parses = _analyzer().parse(text)
    return bool(parses) and all(p.tag.POS in ('NOUN', 'NPRO') for p in parses)


def _origin(source_tokens: list[dict[str, Any]], learner_tokens: list[dict[str, Any]],
            source_task: dict[str, Any], learner_task: dict[str, Any]) -> dict[str, Any]:
    sh = {(h['start'], h['end']) for h in source_task['head_candidates']}
    lh = {(h['start'], h['end']) for h in learner_task['head_candidates']}
    source_positions, learner_positions, uncertain = [], [], []
    for index, (s, learner_row) in enumerate(zip(source_tokens, learner_tokens, strict=True)):
        if s['text'].casefold() != learner_row['text'].casefold():
            continue
        if not _nominal_only(s['text']) or not _nominal_only(learner_row['text']):
            uncertain.append(index)
            continue
        if (s['start'], s['end']) in sh:
            source_positions.append(index)
        if (learner_row['start'], learner_row['end']) in lh:
            learner_positions.append(index)
    flagged = bool(source_positions and learner_positions and any(s != learner_row for s in source_positions for learner_row in learner_positions))
    return {'status': 'DIFFERENT_POSSIBLE_ANCHORS_UNVERIFIED' if flagged else 'UNKNOWN',
            'source_positions': source_positions, 'learner_positions': learner_positions,
            'uncertain_positions': uncertain,
            'aligned_coordinates': [{'source_start': s['start'], 'source_end': s['end'],
                'learner_start': learner_row['start'], 'learner_end': learner_row['end']} for s, learner_row in zip(source_tokens, learner_tokens, strict=True)]}


def _role_plan(role: str, rows: list[dict[str, Any]], selected: set[str], source_fp: str, course_fp: str) -> list[dict[str, Any]]:
    records, tasks, bindings = [], [], {}
    for row in rows:
        chosen = [t for t in row['tasks'] if t['task_id'] in selected]
        if not chosen:
            continue
        records.append(row['record'])
        for task in chosen:
            heads = [{'token_id': h['token_id'], 'text': h['text']} for h in task['head_candidates']]
            tasks.append({'task_id': task['task_id'], 'record_id': task['record_id'],
                          'modifier_token_id': task['modifier_token_id'], 'modifier_text': task['modifier_text'],
                          'head_candidates': heads})
            bindings[task['task_id']] = {'record_id': task['record_id'], 'modifier_token_id': task['modifier_token_id'],
                                         'allowed_head_token_ids': [h['token_id'] for h in heads]}
    if not tasks:
        return []
    def build(chunk: list[dict[str, Any]]) -> dict[str, Any]:
        used = {task['record_id'] for task in chunk}
        local_bindings = {task['task_id']: bindings[task['task_id']] for task in chunk}
        data = {'role': role, 'records': [record for record in records if record['id'] in used], 'tasks': chunk,
                'candidate_status': 'DICTIONARY_POSSIBILITIES_NOT_ATTACHMENT_TRUTH'}
        fp = _digest(data)
        fmt = attachment_choice_format(fp, source_fp, course_fp, role, local_bindings)
        messages = [{'role': 'system', 'content': GUIDE}, {'role': 'user', 'content': json.dumps({
            'input_fingerprint': fp, 'source_fingerprint': source_fp, 'course_fingerprint': course_fp, **data},
            ensure_ascii=False, separators=(',', ':'))}]
        return {'messages': messages, 'response_format': fmt, 'bindings': local_bindings}
    plans: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for task in tasks:
        try:
            build([*current, task])
        except ValueError as error:
            if str(error) != 'attachment_choice_format_too_large' or not current:
                raise
            plans.append(build(current))
            current = [task]
            build(current)
        else:
            current.append(task)
    if current:
        plans.append(build(current))
    return plans


def plan(source_records: list[dict[str, str]], learner_records: list[dict[str, str]],
         source_fp: str, course_fp: str) -> dict[str, Any]:
    if any(type(fp) is not str or not re.fullmatch(r'[0-9a-f]{64}', fp) for fp in (source_fp, course_fp)):
        raise ValueError('attachment_fingerprint_invalid')
    source, learner = _inventory(source_records), _inventory(learner_records)
    source_tasks = {t['task_id']: t for row in source for t in row['tasks']}
    learner_tasks = {t['task_id']: t for row in learner for t in row['tasks']}
    source_segments: list[tuple[dict[str, Any], dict[str, Any]]] = []
    positions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in source:
        for span in row['segments']:
            si = len(source_segments)
            source_segments.append((row, span))
            for ti, token in enumerate(span['tokens']):
                for lemma in token['lemmas']:
                    positions[lemma].append((si, ti))
    pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in learner:
        for span in row['segments']:
            ltokens = span['tokens']
            for li, token in enumerate(ltokens):
                candidates: set[tuple[int, int]] = set()
                for lemma in token['lemmas']:
                    candidates.update(positions.get(lemma, ()))
                for si, sj in sorted(candidates):
                    sr, ss = source_segments[si]
                    stokens = ss['tokens']
                    if not _matches_token(stokens[sj], token):
                        continue
                    if sj and li and _matches_token(stokens[sj - 1], ltokens[li - 1]):
                        continue
                    length = 0
                    while sj + length < len(stokens) and li + length < len(ltokens) and _matches_token(stokens[sj + length], ltokens[li + length]):
                        length += 1
                    if length < 2:
                        continue
                    sc, lc = stokens[sj:sj + length], ltokens[li:li + length]
                    for st, lt in zip(sc, lc, strict=True):
                        if not (st['modifier'] and lt['modifier']) or st['text'].casefold() == lt['text'].casefold():
                            continue
                        sid = sr['record']['id'] + f":W{st['start']}_{st['end']}"
                        lid = row['record']['id'] + f":W{lt['start']}_{lt['end']}"
                        if sid not in source_tasks or lid not in learner_tasks:
                            raise ValueError('attachment_task_invalid')
                        origin = _origin(sc, lc, source_tasks[sid], learner_tasks[lid])
                        origin.update({'source_record_id': sr['record']['id'], 'learner_record_id': row['record']['id'],
                                       'source_segment': [ss['start'], ss['end']], 'learner_segment': [span['start'], span['end']]})
                        pairs.setdefault((sid, lid), []).append(origin)
    flagged = {key for key, origins in pairs.items() if any(o['status'] != 'UNKNOWN' for o in origins)}
    paired_source = {s for s, _ in pairs}
    paired_learner = {learner_row for _, learner_row in pairs}
    def provenance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{'record_id': row['record']['id'], 'segments': [
            {'start': span['start'], 'end': span['end'], 'tokens': [
                {'text': token['text'], 'start': token['start'], 'end': token['end'],
                 'all_readings': copy.deepcopy(token['all_readings'])} for token in span['tokens']]}
            for span in row['segments']]} for row in rows]
    return {'source_fingerprint': source_fp, 'course_fingerprint': course_fp,
        'source_records_fingerprint': _digest(source_records), 'learner_records_fingerprint': _digest(learner_records),
        'source_token_provenance': provenance(source), 'learner_token_provenance': provenance(learner),
        'pairs': [{'source_task_id': s, 'learner_task_id': learner_row, 'status': 'FLAGGED_UNVERIFIED' if (s,learner_row) in flagged else 'UNKNOWN',
                   'origins': origins} for (s,learner_row), origins in pairs.items()],
        'unmatched_source_tasks': [key for key in source_tasks if key not in paired_source],
        'unmatched_learner_tasks': [key for key in learner_tasks if key not in paired_learner],
        'coverage': 'UNMATCHED_AND_UNFLAGGED_UNKNOWN',
        'source_plans': _role_plan('source', source, {s for s,_ in flagged}, source_fp, course_fp),
        'learner_plans': _role_plan('learner', learner, {learner_row for _,learner_row in flagged}, source_fp, course_fp),
        'semantic_acceptance': False}


def compile_choices(prepared: dict[str, Any], source_records: list[dict[str, str]],
                    learner_records: list[dict[str, str]], source_fp: str, course_fp: str,
                    source_values: list[dict[str, Any]], learner_values: list[dict[str, Any]]) -> dict[str, Any]:
    if (prepared['source_fingerprint'] != source_fp or prepared['course_fingerprint'] != course_fp
            or prepared['source_records_fingerprint'] != _digest(source_records)
            or prepared['learner_records_fingerprint'] != _digest(learner_records)):
        raise ValueError('attachment_input_changed')
    if prepared != plan(source_records, learner_records, source_fp, course_fp):
        raise ValueError('attachment_plan_changed')
    choices: dict[str, dict[str, Any]] = {}
    for role, values in (('source', source_values), ('learner', learner_values)):
        plans = prepared[role + '_plans']
        if len(values) != len(plans):
            raise ValueError('attachment_response_count_invalid')
        choices[role] = {}
        for item, value in zip(plans, values, strict=True):
            if not matches_attachment_choice_response(value, item['response_format']):
                raise ValueError('attachment_response_invalid')
            choices[role].update(value['decisions'])
    output = []
    for pair in prepared['pairs']:
        row = copy.deepcopy(pair)
        if row['status'] == 'FLAGGED_UNVERIFIED':
            s = choices['source'][row['source_task_id']]['selected_head_id']
            learner_row = choices['learner'][row['learner_task_id']]['selected_head_id']
            for origin in row['origins']:
                aligned = origin['aligned_coordinates']
                sp = [i for i,x in enumerate(aligned) if s == f"W{x['source_start']}_{x['source_end']}"]
                lp = [i for i,x in enumerate(aligned) if learner_row == f"W{x['learner_start']}_{x['learner_end']}"]
                origin['selected_instance_relation'] = ('UNKNOWN' if not sp or not lp else
                    'SAME_ALIGNED_POSITION_UNVERIFIED' if sp[0] == lp[0] else 'DIFFERENT_ALIGNED_POSITION_UNVERIFIED')
            row['source_selected_head_id'], row['learner_selected_head_id'] = s, learner_row
        output.append(row)
    return {'pairs': output, 'semantic_acceptance': False}
