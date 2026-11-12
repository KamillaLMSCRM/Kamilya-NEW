"""Complete only unassigned literal formatting slices, without semantic approval."""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_semantic_source_plan import (
    build_semantic_slices,
    compile_semantic_plan,
    matches_semantic_plan_structure,
    semantic_plan_format,
)

_BREAK = re.compile(r'\s*<br\s*/?\s*>\s*', re.IGNORECASE)


def canonicalize_plan_support(value: Any, packet: Any, corpus: Any
                              ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """A model-selected primary slice needs no second supporting membership."""
    if not matches_semantic_plan_structure(value, semantic_plan_format(packet, corpus)):
        raise ValueError('semantic_plan_invalid')
    original = copy.deepcopy(value)
    canonical = copy.deepcopy(value)
    removed = []
    for unit in canonical['units']:
        primary = set(unit['primary_slices'])
        redundant = [ref for ref in unit['supporting_slices'] if ref in primary]
        if redundant:
            unit['supporting_slices'] = [ref for ref in unit['supporting_slices'] if ref not in primary]
            removed.append({'unit_id': unit['id'], 'slice_ids': redundant})
    if not removed:
        return canonical, None
    return canonical, {'source_fingerprint': packet.fingerprint, 'original_plan': original,
        'model_plan_fingerprint': _digest(original), 'normalized_plan_fingerprint': _digest(canonical),
        'removed_redundant_support': removed, 'semantic_approval': False}


def complete_formatting_plan(value: Any, packet: Any, corpus: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    fmt = semantic_plan_format(packet, corpus)
    # Shape, catalog ownership and fingerprints are checked before inspecting the proposal.
    # The original compiler retains responsibility for all other strict invariants.
    if not _matches(value, fmt['json_schema']['schema']):
        compile_semantic_plan(value, packet, corpus)
        raise ValueError('semantic_plan_invalid')
    original = copy.deepcopy(value)
    plan = copy.deepcopy(value)
    assigned = {ref for unit in plan['units'] for key in ('primary_slices', 'supporting_slices')
                for ref in unit[key]}
    assigned.update(ref for row in plan['non_teaching'] for ref in row['slice_ids'])
    excluded = []
    for row in build_semantic_slices(packet, corpus):
        literal = row['text']
        # Blank slices are not included in the V1 plan schema's required inventory.
        origins = row.get('origins')
        ordinary_text = (type(origins) is list and bool(origins) and all(
            type(origin) is dict and origin.get('origin') == 'document_body' and 'asset_id' not in origin
            for origin in origins))
        if row['id'] not in assigned and ordinary_text and literal.strip() and _BREAK.fullmatch(literal):
            excluded.append({'id': row['id'], 'text': literal, 'start': row['start'], 'end': row['end'],
                             'text_sha256': hashlib.sha256(literal.encode('utf-8')).hexdigest()})
    if excluded:
        plan['non_teaching'].append({'slice_ids': [row['id'] for row in excluded],
                                     'reason': 'Literal formatting only'})
    compiled = compile_semantic_plan(plan, packet, corpus)
    return compiled, {'source_fingerprint': packet.fingerprint, 'original_plan': original,
                      'model_plan_fingerprint': _digest(original), 'normalized_plan_fingerprint': _digest(compiled),
                      'auto_excluded': excluded, 'semantic_approval': False}
