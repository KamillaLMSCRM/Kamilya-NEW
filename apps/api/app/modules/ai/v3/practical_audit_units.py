"""Structural source-audit groups; never a claim of semantic completeness."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _validate_packet
from app.modules.ai.v3.source_units import (
    coalesce_leading_context,
    coalesce_structural_prose,
    coalesce_table_headers,
    plan_source_units,
)


@dataclass(frozen=True, slots=True)
class PracticalAuditUnits:
    groups: tuple[tuple[str, tuple[str, ...]], ...]
    fingerprint: str


def audit_units(packet: PracticalSourcePacket) -> PracticalAuditUnits:
    _validate_packet(packet)
    groups: list[tuple[str, tuple[str, ...]]] = []
    for doc_id, _, _ in packet.source_documents:
        blocks = [block for block in packet.blocks if block.doc_id == doc_id]
        source = ''.join(block.text for block in blocks)
        planned = plan_source_units(source)
        if [(unit.start, unit.end, unit.text) for unit in planned] != [
                (block.start, block.end, block.text) for block in blocks]:
            raise ValueError('practical_audit_units_source_boundary_invalid')
        has_markdown_structure = (any(unit.kind == 'table_header' for unit in planned)
                                  or re.search(r'(?m)^[ \t]*#{1,6}[ \t]+', source) is not None)
        units = planned
        if has_markdown_structure:
            units = coalesce_table_headers(planned, source)
            units = coalesce_leading_context(coalesce_structural_prose(units, source), source)
        cursor = 0
        for unit in units:
            start = cursor
            while cursor < len(blocks) and blocks[cursor].end <= unit.end:
                cursor += 1
            members = blocks[start:cursor]
            if (not members or members[0].start != unit.start or members[-1].end != unit.end
                    or unit.text != source[unit.start:unit.end]):
                raise ValueError('practical_audit_units_source_boundary_invalid')
            refs = tuple(block.block_id for block in members if block.text.strip())
            if refs:
                groups.append((f'U{len(groups) + 1}', refs))
        if cursor != len(blocks):
            raise ValueError('practical_audit_units_source_boundary_invalid')
    if [ref for _, members in groups for ref in members] != [b.block_id for b in packet.blocks if b.text.strip()]:
        raise ValueError('practical_audit_units_source_boundary_invalid')
    mapping = tuple(groups)
    encoded = json.dumps(['practical-audit-units-v1', packet.fingerprint, mapping],
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return PracticalAuditUnits(mapping, hashlib.sha256(encoded).hexdigest())
