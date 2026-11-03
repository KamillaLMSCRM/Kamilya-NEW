"""Project explicit source-rule comprehension scope without changing source custody."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, validate_practical_course
from app.modules.ai.v3.source_units import plan_source_units

_PREFIX = 'По указанным положениям источника ('
_HEADING = re.compile(r'(?m)^\s{0,3}#{1,6}\s+([^\r\n]+)')
_CLAUSE = re.compile(r'^\s*(\d+(?:\.\d+)*)([.)])(?:\s|$)')
_PARENT = re.compile(r'(?m)^[ \t]*(\d+(?:\.\d+)*)\.(?:[ \t]|$)')
_INTERNAL = re.compile(r'(?<![\w-])(?:(в|из|по|согласно)\s+)?(SRC\d+|src-[0-9a-f]{1,64})(?![\w-])', re.IGNORECASE)


def _literal(line: str) -> str:
    return ' '.join(line.strip().replace('(', '[').replace(')', ']').split())[:100]


def scoped_course_view(packet: PracticalSourcePacket, course: dict[str, Any], *,
                       legacy_source_rule_scope: bool = False) -> dict[str, Any]:
    """Render explicit source tokens; legacy mode also projects selected source scope."""
    if type(legacy_source_rule_scope) is not bool:
        raise ValueError('practical_question_scope_policy_invalid')
    result = validate_practical_course(course, packet)
    docs = [doc_id for doc_id, _revision, _digest in packet.source_documents]
    sources = {doc: ''.join(block.text for block in packet.blocks if block.doc_id == doc) for doc in docs}
    blocks = {block.block_id: block for block in packet.blocks if block.text.strip()}
    ordinals: dict[str, int] = {}
    counts = {doc: 0 for doc in docs}
    for block in packet.blocks:
        if block.text.strip():
            counts[block.doc_id] += 1
            ordinals[block.block_id] = counts[block.doc_id]
    table_units: dict[tuple[str, int, int], tuple[int, int | None]] = {}
    for doc in docs:
        table_numbers: dict[str, int] = {}
        row_counts: dict[str, int] = {}
        for unit in plan_source_units(sources[doc]):
            if unit.kind not in {'table_header', 'table_row'}:
                continue
            if unit.container_id not in table_numbers:
                table_numbers[unit.container_id] = len(table_numbers) + 1
                row_counts[unit.container_id] = 0
            row = None
            if unit.kind == 'table_row':
                row_counts[unit.container_id] += 1
                row = row_counts[unit.container_id]
            table_units[(doc, unit.start, unit.end)] = (table_numbers[unit.container_id], row)

    def label(ref: str) -> str:
        block = blocks[ref]
        source = sources[block.doc_id]
        table = table_units.get((block.doc_id, block.start, block.end))
        if table is not None:
            table_number, row = table
            value = f'таблица {table_number}' + (f', строка {row}' if row is not None else '')
            return f'документ {docs.index(block.doc_id) + 1}, {value}' if len(docs) > 1 else value
        headings = list(_HEADING.finditer(source, 0, block.start))
        initial_heading = _HEADING.match(block.text)
        section_start = headings[-1].end() if headings else 0
        if initial_heading is not None:
            headings.append(initial_heading)
            section_start = block.start + initial_heading.end()
        heading = headings[-1].group(1).strip() if headings else ''
        lines = [line.strip() for line in block.text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        first = lines[0] if lines else ''
        clause = _CLAUSE.match(first)
        if clause:
            number = clause.group(1)
            section = re.match(r'(\d+)[.)](?:\s|$)', heading)
            if clause.group(2) == ')' and '.' not in number:
                position = source.find(first, block.start, block.end)
                parents = list(_PARENT.finditer(source, section_start, position)) if position >= section_start else []
                if parents:
                    parent = parents[-1].group(1)
                    if '.' not in parent and section:
                        value = f'разд. {section.group(1)}, п. {parent}, подп. {number}'
                    else:
                        value = f'п. {parent}, подп. {number}'
                else:
                    value = f'элемент списка {number}, блок {ordinals[ref]}'
            elif '.' not in number and section:
                value = f'разд. {section.group(1)}, п. {number}'
            else:
                value = f'п. {number}'
        elif heading:
            value = f'заголовок «{_literal(heading)}», фрагмент {ordinals[ref]}'
        else:
            value = f'фрагмент {ordinals[ref]}'
        if len(docs) > 1:
            value = f'документ {docs.index(block.doc_id) + 1}, {value}'
        return value

    labels = {ref: label(ref) for ref in blocks}
    repeated = {value for value, count in Counter(labels.values()).items() if count > 1}
    for ref, value in list(labels.items()):
        if value in repeated and (value.startswith('п. ') or ', п. ' in value):
            labels[ref] = f'{value}, фрагмент {ordinals[ref]}'
    aliases = {f'SRC{index}': block.block_id for index, block in enumerate(blocks.values(), 1)}
    all_source = '\n'.join(sources.values())

    def render(text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            preposition, token = match.group(1), match.group(2)
            if re.search(r'(?<![\w-])' + re.escape(token) + r'(?![\w-])', all_source):
                return match.group(0)
            ref = aliases.get(token) if token.startswith('SRC') else token if token in blocks else None
            if ref is None:
                raise ValueError('practical_display_source_reference_unknown')
            forms = {'в': 'в положении', 'из': 'из положения', 'по': 'по положению',
                     'согласно': 'согласно положению'}
            phrase = forms.get(preposition.lower(), 'положение') if preposition else 'положение'
            if preposition and preposition[0].isupper():
                phrase = phrase[0].upper() + phrase[1:]
            return f'{phrase} источника ({labels[ref]})'
        return _INTERNAL.sub(replace, text)

    for lesson in result['lessons']:
        lesson['content'] = render(lesson['content'])
        for question in lesson['questions']:
            if not legacy_source_rule_scope:
                question['prompt'] = render(question['prompt'])
                question['explanation'] = render(question['explanation'])
                question['choices'] = [render(choice) for choice in question['choices']]
                continue
            if question['prompt'].startswith(_PREFIX):
                raise ValueError('practical_question_scope_already_projected')
            selected = list(dict.fromkeys(question['source_refs']))
            selected_tables = {(blocks[ref].doc_id, table_units[(blocks[ref].doc_id, blocks[ref].start, blocks[ref].end)][0])
                               for ref in selected if (blocks[ref].doc_id, blocks[ref].start, blocks[ref].end) in table_units
                               and table_units[(blocks[ref].doc_id, blocks[ref].start, blocks[ref].end)][1] is not None}
            chosen = [ref for ref in selected if not ((blocks[ref].doc_id, blocks[ref].start, blocks[ref].end) in table_units
                and table_units[(blocks[ref].doc_id, blocks[ref].start, blocks[ref].end)][1] is None
                and (blocks[ref].doc_id, table_units[(blocks[ref].doc_id, blocks[ref].start, blocks[ref].end)][0]) in selected_tables)]
            output_labels = []
            emitted_tables: set[tuple[str, int]] = set()
            for ref in chosen:
                block = blocks[ref]
                table = table_units.get((block.doc_id, block.start, block.end))
                if table is None or table[1] is None:
                    output_labels.append(labels[ref])
                    continue
                key = (block.doc_id, table[0])
                if key in emitted_tables:
                    continue
                emitted_tables.add(key)
                selected_rows: set[int] = set()
                for item in chosen:
                    candidate = blocks[item]
                    entry = table_units.get((candidate.doc_id, candidate.start, candidate.end))
                    if candidate.doc_id == block.doc_id and entry is not None and entry[0] == table[0] and entry[1] is not None:
                        selected_rows.add(entry[1])
                rows = sorted(selected_rows)
                ranges: list[tuple[int, int]] = []
                for row in rows:
                    if ranges and row == ranges[-1][1] + 1:
                        ranges[-1] = (ranges[-1][0], row)
                    else:
                        ranges.append((row, row))
                numbers = ', '.join(str(a) if a == b else f'{a}–{b}' for a, b in ranges)
                prefix = f'документ {docs.index(block.doc_id) + 1}, ' if len(docs) > 1 else ''
                output_labels.append(f'{prefix}таблица {table[0]}, ' + ('строка ' if len(rows) == 1 else 'строки ') + numbers)
            question['prompt'] = _PREFIX + '; '.join(dict.fromkeys(output_labels)) + '): ' + render(question['prompt'])
            question['explanation'] = render(question['explanation'])
            question['choices'] = [render(choice) for choice in question['choices']]
    return validate_practical_course(result, packet)
