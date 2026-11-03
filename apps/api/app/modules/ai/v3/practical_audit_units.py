"""Structural source-audit groups; never a claim of semantic completeness."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _validate_packet
from app.modules.ai.v3.source_units import (
    SourceUnit,
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
            # Coalescing a cover with its first section must not absorb the next
            # numbered major section. Keep coalescers inside exact source windows.
            majors = list(re.finditer(r'(?m)^[ \t]*#{1,6}[ \t]+\d+\.[ \t]+[^\r\n]+', source))
            boundaries = [0, *(m.start() for m in majors[1:]), len(source)]
            windows: list[SourceUnit] = []
            for start, end in zip(boundaries, boundaries[1:], strict=False):
                window = tuple(unit for unit in planned if start <= unit.start and unit.end <= end)
                if not window or window[0].start != start or window[-1].end != end:
                    raise ValueError('practical_audit_units_source_boundary_invalid')
                window = coalesce_table_headers(window, source)
                window = coalesce_structural_prose(window, source, allow_single_section=True)
                windows.extend(coalesce_leading_context(window, source))
            units = tuple(windows)
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
    encoded = json.dumps(['practical-audit-units-v2', packet.fingerprint, mapping],
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return PracticalAuditUnits(mapping, hashlib.sha256(encoded).hexdigest())
