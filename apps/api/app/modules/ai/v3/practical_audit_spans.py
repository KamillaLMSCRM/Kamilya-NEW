"""Deterministic structural children, not independent source rules."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _validate_packet


@dataclass(frozen=True, slots=True)
class AuditSpan:
    span_id: str
    source_ref: str
    text: str


def audit_spans(packet: PracticalSourcePacket) -> tuple[AuditSpan, ...]:
    _validate_packet(packet)
    result: list[AuditSpan] = []
    for block in packet.blocks:
        if not block.text.strip():
            continue
        # Split only an explicit, flat list. All other material stays whole.
        markers = list(re.finditer(r'(?m)^(?P<indent>[ \t]*)[-*•][ \t]*(?=\S)', block.text))
        prefix = block.text[:markers[0].start()] if markers else ''
        if (len(markers) >= 2 and prefix.strip() and prefix.rstrip().endswith(':')
                and len({m.group('indent') for m in markers}) == 1):
            parts = [block.text[0 if i == 0 else m.start():
                     markers[i + 1].start() if i + 1 < len(markers) else len(block.text)]
                     for i, m in enumerate(markers)]
        elif not markers and not block.text.lstrip().startswith('|'):
            boundaries = [0, *(m.end() for m in re.finditer(r'\r?\n[ \t]*\r?\n', block.text)), len(block.text)]
            parts = []
            for left, right in zip(boundaries, boundaries[1:], strict=False):
                part = block.text[left:right]
                if not part.strip() and parts:
                    parts[-1] += part
                elif part:
                    parts.append(part)
            if len(parts) > 1 and parts[0].rstrip().endswith(':'):
                parts = [parts[0] + parts[1], *parts[2:]]
        else:
            parts = [block.text]
        for part in parts:
            result.append(AuditSpan(f'SPAN{len(result) + 1}', block.block_id, part))
    return tuple(result)
