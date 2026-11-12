"""Address-only reconciliation of a block-editor proposal."""
from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_block_editor import apply_simple_block_editor, block_editor_format, body_blocks
from app.modules.ai.v3.simple_course_editor import _fingerprint_valid, _format, _object


def address_repair_format(source_fp: str, draft_fp: str, proposal_fp: str, edit_count: int,
                          block_ids: list[str]) -> dict[str, Any]:
    return _format('simple_course_block_addresses_v1', _object({
        'source_fingerprint': {'type': 'string', 'enum': [source_fp]},
        'draft_fingerprint': {'type': 'string', 'enum': [draft_fp]},
        'proposal_fingerprint': {'type': 'string', 'enum': [proposal_fp]},
        'assignments': {'type': 'array', 'items': _object({
            'edit_id': {'type': 'string', 'enum': [f'EDIT{i}' for i in range(1, edit_count + 1)]},
            'block_id': {'type': 'string', 'enum': [*block_ids, 'UNRESOLVED']},
        })},
    }))


def is_address_repair_format(fmt: Any) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        source, draft, proposal = (props[key]['enum'][0] for key in
                                   ('source_fingerprint', 'draft_fingerprint', 'proposal_fingerprint'))
        item = props['assignments']['items']['properties']
        edits, blocks = item['edit_id']['enum'], item['block_id']['enum']
        return (all(_fingerprint_valid(fp) for fp in (source, draft, proposal))
                and type(edits) is list and bool(edits)
                and edits == [f'EDIT{i}' for i in range(1, len(edits) + 1)]
                and type(blocks) is list and len(blocks) > 1 and blocks[-1] == 'UNRESOLVED'
                and blocks[:-1] == [f'BODY{i}' for i in range(1, len(blocks))]
                and fmt == address_repair_format(source, draft, proposal, len(edits), blocks[:-1]))
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def matches_address_repair_shape(value: Any, fmt: Any) -> bool:
    return bool(is_address_repair_format(fmt) and _matches(value, fmt['json_schema']['schema']))


def apply_address_repair(value: Any, proposal: Any, original: dict[str, Any], ids: list[str],
                         source_fp: str, draft_fp: str, finding_ids: list[str] | None = None
                         ) -> tuple[dict[str, Any], dict[str, Any]]:
    if _digest(original) != draft_fp:
        raise ValueError('simple_address_repair_draft_stale')
    blocks = [row['id'] for row in body_blocks(original)]
    proposal_format = block_editor_format(ids, source_fp, draft_fp, blocks, finding_ids)
    if not _matches(proposal, proposal_format['json_schema']['schema']):
        raise ValueError('simple_address_repair_proposal_invalid')
    proposal_fp = _digest(proposal)
    fmt = address_repair_format(source_fp, draft_fp, proposal_fp, len(proposal['body_edits']), blocks)
    if not matches_address_repair_shape(value, fmt):
        raise ValueError('simple_address_repair_response_invalid')
    assignments = value['assignments']
    edit_ids = [row['edit_id'] for row in assignments]
    expected = [f'EDIT{i}' for i in range(1, len(proposal['body_edits']) + 1)]
    if len(edit_ids) != len(expected) or set(edit_ids) != set(expected):
        raise ValueError('simple_address_repair_assignments_invalid')
    if any(row['block_id'] == 'UNRESOLVED' for row in assignments):
        raise ValueError('simple_address_repair_unresolved')
    resolved = {row['edit_id']: row['block_id'] for row in assignments}
    if len(set(resolved.values())) != len(resolved):
        raise ValueError('simple_address_repair_duplicate_target')
    repaired = copy.deepcopy(proposal)
    trace = []
    for index, edit in enumerate(repaired['body_edits'], 1):
        edit_id = f'EDIT{index}'
        trace.append({'edit_id': edit_id, 'proposed_block_id': edit['block_id'],
                      'resolved_block_id': resolved[edit_id]})
        edit['block_id'] = resolved[edit_id]
    apply_simple_block_editor(repaired, original, ids, source_fp, draft_fp, finding_ids)
    return repaired, {'source_fingerprint': source_fp, 'draft_fingerprint': draft_fp,
                      'proposal_fingerprint': proposal_fp, 'repaired_fingerprint': _digest(repaired),
                      'assignments': trace, 'semantic_text_preserved': True}
