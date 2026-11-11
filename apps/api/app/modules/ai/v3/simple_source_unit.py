"""A selected literal source unit for a single lesson; no semantic approval."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, cast

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.practical_contract import (
    PracticalSourcePacket,
    _course_format,
    _digest,
    _validate_packet,
    build_practical_source_packet,
    normalize_author_question_ids,
    validate_practical_course,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_course_editor import _COMMON
from app.modules.ai.v3.simple_course_editor_v2 import _current_context
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision
from app.modules.ai.v3.source_units import plan_source_units
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument


@dataclass(frozen=True, slots=True)
class LiteralTeachingUnit:
    source_fingerprint: str
    selection_fingerprint: str
    primary_refs: tuple[str, ...]
    supporting_refs: tuple[str, ...]


def _selection(packet: PracticalSourcePacket, primary_refs: Any, supporting_refs: Any) -> LiteralTeachingUnit:
    _validate_packet(packet)
    if type(primary_refs) not in (list, tuple) or type(supporting_refs) not in (list, tuple):
        raise ValueError('simple_unit_selection_invalid')
    primary, supporting = tuple(primary_refs), tuple(supporting_refs)
    owned = {block.block_id for block in packet.blocks if block.text.strip()}
    all_refs = primary + supporting
    if (not primary or any(type(ref) is not str or ref not in owned for ref in all_refs)
            or len(set(all_refs)) != len(all_refs)):
        raise ValueError('simple_unit_selection_invalid')
    fingerprint = _digest([packet.fingerprint, list(primary), list(supporting)])
    return LiteralTeachingUnit(packet.fingerprint, fingerprint, primary, supporting)


def source_unit_request(packet: PracticalSourcePacket, corpus: DirectSourceCorpus, intent: Any,
                        primary_refs: Any, supporting_refs: Any, *,
                        reference_decisions: tuple[SourceReferenceDecision, ...] = ()
                        ) -> tuple[list[dict[str, str]], dict[str, Any], LiteralTeachingUnit]:
    view, context = _current_context(packet, corpus, intent)
    unit = _selection(packet, primary_refs, supporting_refs)
    if type(reference_decisions) is not tuple:
        raise ValueError('simple_unit_reference_decisions_invalid')
    if packet.reference_context and not reference_decisions:
        raise ValueError('simple_unit_reference_context_unscoped')
    if build_practical_source_packet(corpus, reference_decisions) != packet:
        raise ValueError('simple_unit_source_packet_mismatch')

    # Unit metadata is not carried in PracticalSourceBlock. Reconstruct it from
    # the exact approved text and bind by document and source coordinates.
    by_span = {(b.doc_id, b.start, b.end): b for b in packet.blocks}
    table_dependencies: dict[str, set[str]] = {}
    for doc in corpus.documents:
        units = plan_source_units(doc.source_text or '')
        headers: dict[str, list[Any]] = {}
        for source_unit in units:
            if source_unit.kind == 'table_header':
                headers[source_unit.container_id] = [source_unit]
            elif source_unit.kind == 'table_row':
                header = headers.get(source_unit.container_id, [])
                # A bold first row may form a second, literal table header.
                if header and source_unit.context == ''.join(item.text for item in header) + source_unit.text:
                    headers[source_unit.container_id].append(source_unit)
                dependencies = headers.get(source_unit.container_id, [])
                table_dependencies[by_span[(doc.doc_id, source_unit.start, source_unit.end)].block_id] = {
                    by_span[(doc.doc_id, item.start, item.end)].block_id for item in dependencies
                    if (item.start, item.end) != (source_unit.start, source_unit.end)
                }

    def overlapping(doc_id: str, start: int, end: int) -> set[str]:
        return {b.block_id for b in packet.blocks if b.doc_id == doc_id and b.text.strip()
                and b.start < end and start < b.end}

    selected = set(unit.primary_refs + unit.supporting_refs)
    applicable_decisions: set[int] = set()
    while True:
        expanded = set(selected)
        for ref in selected:
            expanded.update(table_dependencies.get(ref, ()))
        for index, decision in enumerate(reference_decisions):
            anchors = overlapping(decision.document_id, decision.reference_start, decision.reference_end)
            if anchors & expanded:
                applicable_decisions.add(index)
                expanded.update(anchors)
                expanded.update(overlapping(decision.document_id, decision.target_start, decision.target_end))
        if expanded == selected:
            break
        selected = expanded
    additions = [b.block_id for b in packet.blocks if b.block_id in selected
                 and b.block_id not in unit.primary_refs and b.block_id not in unit.supporting_refs]
    unit = _selection(packet, unit.primary_refs, (*unit.supporting_refs, *additions))
    reference_context = [build_practical_source_packet(corpus, (decision,)).reference_context[0]
                         for index, decision in enumerate(reference_decisions) if index in applicable_decisions]
    selected = set(unit.primary_refs + unit.supporting_refs)
    blocks = [block for block in packet.blocks if block.block_id in selected]
    documents = []
    for doc, metadata in zip(corpus.documents, context['documents'], strict=True):
        ranges = [(block.start, block.end) for block in blocks if block.doc_id == doc.doc_id]
        if not ranges:
            continue
        approval = cast(ApprovedEditorialDocument, doc.editorial_document)
        decisions = []
        for row in approval.decision_context:
            spans = [span for span in approval.spans if row['start'] is not None
                     and span['raw_start'] < row['end'] and row['start'] < span['raw_end']]
            working_ranges = []
            for span in spans:
                if span['item_id'] is None:
                    start = span['working_start'] + max(row['start'], span['raw_start']) - span['raw_start']
                    end = span['working_start'] + min(row['end'], span['raw_end']) - span['raw_start']
                    working_ranges.append((start, end))
                else:
                    working_ranges.append((span['working_start'], span['working_end']))
            applicable = row['start'] is None or any(
                left < end and start < right for left, right in working_ranges for start, end in ranges)
            if applicable:
                decisions.append({'item_id': row['item_id'], 'decision': row['decision'], 'reason': row['reason']})
        documents.append({**{key: metadata[key] for key in ('document_id', 'source_revision', 'approval_id', 'working_sha256')},
                          'approved_decisions': decisions})
    source = [{'id': view.canonical_to_alias[block.block_id], 'document_id': block.doc_id,
               'role': 'primary' if block.block_id in unit.primary_refs else 'supporting', 'text': block.text}
              for block in blocks]
    payload = {'source_fingerprint': packet.fingerprint, 'selection_fingerprint': unit.selection_fingerprint,
               'documents': documents, 'source_blocks': source, 'intent': context['intent'],
               'reference_context': reference_context}
    instruction = ('Create one connected, practical lesson and 3–4 questions from the primary literal source blocks. '
        'Supporting blocks supply parent scope and explicit dependencies, not new unrelated topics. '
        'Keep applicable source conditions visible in the lesson and quiz title or the specific question stem. '
        'Each question should have one wholly source-supported best answer and clearly incorrect alternatives within its stated context. '
        'Use plausible work mistakes as alternatives with comparable specificity; avoid unrelated absurd options and length giveaways. '
        'Vary correct-answer positions and never refer to an option by its position. '
        'Preserve meaningful original source-asset markers where relevant. Do not invent facts or require unrelated content.')
    messages = [{'role': 'system', 'content': _COMMON + '\n' + instruction},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
    fmt = view.schema(_course_format([block.block_id for block in blocks]))
    return messages, fmt, unit


def compile_source_unit(value_canonical: Any, packet: PracticalSourcePacket,
                        primary_refs: Any, supporting_refs: Any) -> dict[str, Any]:
    unit = _selection(packet, primary_refs, supporting_refs)
    view = PracticalModelView(packet)
    view.assert_course_ids_disjoint(value_canonical)
    normalized = normalize_author_question_ids(value_canonical, set(view.canonical_to_alias))
    course = validate_practical_course(normalized, packet)
    selected = set(unit.primary_refs + unit.supporting_refs)
    if (len(course['lessons']) != 1 or not 3 <= len(course['lessons'][0]['questions']) <= 4
            or any(not set(question['source_refs']) <= selected for question in course['lessons'][0]['questions'])):
        raise ValueError('simple_unit_course_invalid')
    return copy.deepcopy(course)
