"""One explicit model stage for missing decisions; retained decisions are immutable."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_verification import (
    matches_editorial_verification,
    matches_editorial_verification_shape,
)


def is_joint_verification_group(group: object) -> bool:
    return isinstance(group, str) and re.fullmatch(r'practical:editorial:verify:v34:joint:[a-f0-9]{64}', group) is not None


async def complete_editorial_resolutions(value: dict[str, Any], fmt: dict[str, Any],
                                         messages: list[dict[str, str]], complete: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not matches_editorial_verification_shape(value, fmt):
        raise ValueError('editorial_resolution_completion_shape_invalid')
    expected = fmt['json_schema']['schema']['properties']['resolutions']['items']['properties']['issue_id']['enum']
    retained = [row['issue_id'] for row in value['resolutions']]
    missing = [key for key in expected if key not in retained]
    if not missing:
        raise ValueError('editorial_resolution_completion_not_needed')
    subset = copy.deepcopy(fmt)
    subset['json_schema']['schema']['properties']['resolutions']['items']['properties']['issue_id']['enum'] = missing
    request = copy.deepcopy(messages)
    request.append({'role': 'user', 'content': (
        'The complete HTTP reply omitted decisions for the issue IDs below. '
        'Complete ONLY these missing decisions using the current source, course and observations above. '
        'All existing decisions and findings are retained unchanged outside this call. '
        'Do not return decisions for another ID, rewrite a lesson, or invent a source question. '
        'Use literal owned evidence and distinguish a model/course error from a genuinely unresolved source choice. '
        'Keep any actual remaining current defect as a precise finding. '
        '\nMISSING_RESOLUTION_IDS_JSON\n' + json.dumps(missing, ensure_ascii=False)
        + '\nRETAINED_CURRENT_FINDINGS_JSON\n' + json.dumps(value['findings'], ensure_ascii=False, sort_keys=True))})

    def validate(result: Any) -> None:
        if not matches_editorial_verification(result, subset):
            raise ValueError('editorial_resolution_completion_incomplete')

    group = 'practical:editorial:verify:v34:complete-resolutions:' + _digest([value, fmt])
    extra = await complete(group, request, subset, validate)
    validate(extra)
    merged = copy.deepcopy(value)
    merged['resolutions'].extend(copy.deepcopy(extra['resolutions']))
    for key in ('findings', 'source_notes'):
        seen = {_digest(row) for row in merged[key]}
        for row in extra[key]:
            identity = _digest(row)
            if identity not in seen:
                merged[key].append(copy.deepcopy(row))
                seen.add(identity)
    for target, refs in extra['narrative_sources'].items():
        merged['narrative_sources'][target] = list(dict.fromkeys([*merged['narrative_sources'][target], *refs]))
    if not matches_editorial_verification(merged, fmt):
        raise ValueError('editorial_resolution_completion_merge_invalid')
    return merged, {'group_id': group, 'requested_issue_ids': missing, 'retained_issue_ids': retained,
                    'original_response_sha256': _digest(value), 'completion_response_sha256': _digest(extra),
                    'merged_response_sha256': _digest(merged)}
