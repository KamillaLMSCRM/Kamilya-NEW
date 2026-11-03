"""Source-bound structural contract; it does not certify semantic correctness."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.models import RuleEntity
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision, reference_context_for_rules
from app.modules.ai.v3.source_units import plan_source_units


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class PracticalSourceBlock:
    block_id: str
    doc_id: str
    source_revision: str
    start: int
    end: int
    text: str
    text_sha256: str


@dataclass(frozen=True, slots=True)
class PracticalSourcePacket:
    tenant_id: str
    blocks: tuple[PracticalSourceBlock, ...]
    reference_context: tuple[str, ...]
    fingerprint: str
    source_documents: tuple[tuple[str, str, str], ...]

    def to_payload(self) -> dict[str, Any]:
        return {'tenant_id': self.tenant_id, 'blocks': [asdict(block) for block in self.blocks],
                'reference_context': list(self.reference_context), 'fingerprint': self.fingerprint,
                'source_documents': [{'doc_id': doc, 'source_revision': rev, 'text_sha256': digest}
                                     for doc, rev, digest in self.source_documents]}


def build_practical_source_packet(corpus: DirectSourceCorpus, reference_decisions: tuple[SourceReferenceDecision, ...] = ()) -> PracticalSourcePacket:
    if not isinstance(corpus, DirectSourceCorpus) or not isinstance(corpus.documents, tuple):
        raise ValueError('practical_source_identity_invalid')
    tenant = corpus.tenant_id
    if not isinstance(tenant, str) or not tenant.strip() or not corpus.documents:
        raise ValueError('practical_source_identity_invalid')
    blocks: list[PracticalSourceBlock] = []
    docs: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    rules = []
    for doc in corpus.documents:
        if (not isinstance(doc, DirectSourceDocument) or not isinstance(doc.doc_id, str) or not doc.doc_id.strip() or doc.doc_id in seen
                or not isinstance(doc.source_revision, str) or not doc.source_revision.strip()
                or not isinstance(doc.source_text, str) or not doc.source_text.strip()):
            raise ValueError('practical_source_identity_invalid')
        seen.add(doc.doc_id)
        source = doc.source_text
        docs.append((doc.doc_id, doc.source_revision, hashlib.sha256(source.encode('utf-8')).hexdigest()))
        position = 0
        for unit in plan_source_units(source):
            if (type(unit.start) is not int or type(unit.end) is not int or unit.start != position
                    or not unit.start < unit.end <= len(source) or unit.text != source[unit.start:unit.end]):
                raise ValueError('practical_source_coverage_invalid')
            digest = hashlib.sha256(unit.text.encode('utf-8')).hexdigest()
            identity = 'src-' + _digest([tenant, doc.doc_id, doc.source_revision, unit.start, unit.end, digest])[:20]
            if any(block.block_id == identity for block in blocks):
                raise ValueError('practical_source_collision')
            blocks.append(PracticalSourceBlock(identity, doc.doc_id, doc.source_revision, unit.start, unit.end, unit.text, digest))
            position = unit.end
        if position != len(source):
            raise ValueError('practical_source_coverage_invalid')
        rules.append(RuleEntity(rule_id=doc.doc_id, section='', title='', statement='', doc_id=doc.doc_id,
                                source_revision=doc.source_revision, source_start=0, source_end=len(source)))
    context = reference_context_for_rules(tenant, tuple(corpus.documents), tuple(reference_decisions), tuple(rules))
    if len(context) != len(reference_decisions):
        raise ValueError('practical_reference_not_scoped')
    fingerprint = _digest([tenant, [asdict(block) for block in blocks], docs, context])
    return PracticalSourcePacket(tenant, tuple(blocks), context, fingerprint, tuple(docs))


def _validate_packet(packet: PracticalSourcePacket) -> None:
    if (not isinstance(packet, PracticalSourcePacket) or not isinstance(packet.tenant_id, str)
            or not packet.tenant_id.strip() or not isinstance(packet.blocks, tuple)
            or not isinstance(packet.source_documents, tuple) or not packet.source_documents
            or not isinstance(packet.reference_context, tuple)
            or not all(isinstance(c, str) and c.strip() for c in packet.reference_context)):
        raise ValueError('practical_source_packet_invalid')
    cursor = 0
    seen: set[str] = set()
    for document in packet.source_documents:
        if (not isinstance(document, tuple) or len(document) != 3
                or not all(isinstance(v, str) and v.strip() for v in document)):
            raise ValueError('practical_source_packet_invalid')
        doc_id, revision, source_hash = document
        if doc_id in seen:
            raise ValueError('practical_source_packet_invalid')
        seen.add(doc_id)
        position = 0
        pieces: list[str] = []
        while cursor < len(packet.blocks):
            block = packet.blocks[cursor]
            if not isinstance(block, PracticalSourceBlock):
                raise ValueError('practical_source_packet_invalid')
            if block.doc_id != doc_id:
                break
            if (not isinstance(block, PracticalSourceBlock) or block.source_revision != revision
                    or type(block.start) is not int or type(block.end) is not int or block.start != position
                    or not isinstance(block.text, str) or block.end != block.start + len(block.text)
                    or block.end <= block.start or block.text_sha256 != hashlib.sha256(block.text.encode('utf-8')).hexdigest()
                    or block.block_id != 'src-' + _digest([packet.tenant_id, doc_id, revision, block.start, block.end, block.text_sha256])[:20]):
                raise ValueError('practical_source_packet_invalid')
            pieces.append(block.text)
            position = block.end
            cursor += 1
        if not pieces or not ''.join(pieces).strip() or hashlib.sha256(''.join(pieces).encode('utf-8')).hexdigest() != source_hash:
            raise ValueError('practical_source_packet_invalid')
    if (cursor != len(packet.blocks) or len({b.block_id for b in packet.blocks}) != len(packet.blocks)
            or packet.fingerprint != _digest([packet.tenant_id, [asdict(b) for b in packet.blocks],
                                               list(packet.source_documents), packet.reference_context])):
        raise ValueError('practical_source_packet_invalid')


def course_response_format(packet: PracticalSourcePacket) -> dict[str, Any]:
    _validate_packet(packet)
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    return _course_format(ids)


def _course_format(ids: list[str]) -> dict[str, Any]:
    if (type(ids) is not list or not ids or not all(type(item) is str and item.strip() for item in ids)
            or len(ids) != len(set(ids))):
        raise ValueError('practical_source_packet_invalid')
    string = {'type': 'string'}
    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
    question = obj({'id': string, 'prompt': string, 'choices': {'type': 'array', 'items': string, 'minItems': 3, 'maxItems': 4},
                    'correct_index': {'type': 'integer'}, 'explanation': string,
                    'source_refs': {'type': 'array', 'items': {'type': 'string', 'enum': ids}, 'minItems': 1}})
    lesson = obj({'id': string, 'title': string, 'content': string,
                  'questions': {'type': 'array', 'items': question, 'minItems': 1}})
    return {'type': 'json_schema', 'json_schema': {'name': 'practical_course', 'strict': True,
            'schema': obj({'title': string, 'lessons': {'type': 'array', 'items': lesson, 'minItems': 1}})}}


def source_model_text(packet: PracticalSourcePacket, *, aliases: Mapping[str, str] | None = None) -> str:
    """One readable view; custody and revisions remain bound in the immutable packet."""
    _validate_packet(packet)
    if aliases is not None:
        expected = {b.block_id: f'SRC{i}' for i, b in enumerate(
            (block for block in packet.blocks if block.text.strip()), 1)}
        if dict(aliases) != expected:
            raise ValueError('practical_source_aliases_invalid')
    parts: list[str] = []
    current_document = None
    for block in packet.blocks:
        if not block.text.strip():
            continue
        if block.doc_id != current_document:
            parts.append('DOCUMENT ' + block.doc_id)
            current_document = block.doc_id
        parts.append('SOURCE_BLOCK ' + (aliases[block.block_id] if aliases is not None else block.block_id) + '\n' + block.text)
    blocks = '\n\n'.join(parts)
    return ('SOURCE_FINGERPRINT ' + packet.fingerprint + '\n\nИСХОДНЫЙ РЕГЛАМЕНТ:\n' + blocks
        + '\n\nПОДТВЕРЖДЁННЫЕ УТОЧНЕНИЯ ОТСЫЛОК:\n' + '\n'.join(packet.reference_context))


def is_practical_course_format(value: Any) -> bool:
    try:
        ids = value['json_schema']['schema']['properties']['lessons']['items']['properties']['questions']['items']['properties']['source_refs']['items']['enum']
        return type(ids) is list and bool(ids) and all(isinstance(i, str) and i for i in ids) and value == _course_format(ids)
    except (KeyError, TypeError, ValueError):
        return False


def matches_practical_course_response(value: Any, response_format: Any) -> bool:
    if not is_practical_course_format(response_format):
        return False
    ids = response_format['json_schema']['schema']['properties']['lessons']['items']['properties']['questions']['items']['properties']['source_refs']['items']['enum']
    try:
        _validate_course(value, set(ids))
        return True
    except (ValueError, TypeError, KeyError):
        return False


def validate_practical_course(value: object, packet: PracticalSourcePacket) -> dict[str, Any]:
    course_response_format(packet)
    return _validate_course(value, {block.block_id for block in packet.blocks if block.text.strip()})


def _validate_course(value: Any, allowed: set[str]) -> dict[str, Any]:
    def fail() -> None:
        raise ValueError('practical_course_invalid')
    def fields(item: object, expected: set[str]) -> bool:
        return type(item) is dict and set(item) == expected
    def nonblank(item: object) -> bool:
        return isinstance(item, str) and bool(item.strip())
    if not fields(value, {'title', 'lessons'}) or not nonblank(value['title']) or type(value['lessons']) is not list or not value['lessons']:
        fail()
    lesson_ids: set[str] = set()
    question_ids: set[str] = set()
    for lesson in value['lessons']:
        if (not fields(lesson, {'id', 'title', 'content', 'questions'}) or not all(nonblank(lesson[k]) for k in ('id', 'title', 'content'))
                or lesson['id'] in lesson_ids or type(lesson['questions']) is not list or not lesson['questions']):
            fail()
        lesson_ids.add(lesson['id'])
        for q in lesson['questions']:
            if (not fields(q, {'id', 'prompt', 'choices', 'correct_index', 'explanation', 'source_refs'})
                    or not all(nonblank(q[k]) for k in ('id', 'prompt', 'explanation')) or q['id'] in question_ids
                    or type(q['choices']) is not list or not 3 <= len(q['choices']) <= 4
                    or not all(nonblank(c) for c in q['choices'])
                    or len({c.strip().casefold() for c in q['choices']}) != len(q['choices'])
                    or type(q['correct_index']) is not int or not 0 <= q['correct_index'] < len(q['choices'])
                    or type(q['source_refs']) is not list or not q['source_refs']
                    or not all(isinstance(ref, str) and ref in allowed for ref in q['source_refs'])
                    or len(set(q['source_refs'])) != len(q['source_refs'])):
                fail()
            question_ids.add(q['id'])
    if lesson_ids & question_ids or (lesson_ids | question_ids) & allowed:
        fail()
    return copy.deepcopy(value)
