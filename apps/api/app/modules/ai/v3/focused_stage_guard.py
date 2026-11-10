"""Exact v36 native stage/format fences; journal owns source and actor custody."""
from __future__ import annotations

import re
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.response_contracts import response_contract
from app.modules.ai.v3.revision_policy import FOCUSED_EDITORIAL_REVIEW_POLICY


def focused_stage_allowed(stage: object, group: object, fmt: Any, *, policy: Any, validator: Any) -> bool:
    if (type(stage) is not str or type(group) is not str or policy != FOCUSED_EDITORIAL_REVIEW_POLICY
            or not callable(validator) or not isinstance(fmt, dict)):
        return False
    match = re.fullmatch(r'practical:focused:(author|graph:source|graph:learner|attachment:source|attachment:learner|action|noun|questions|question-repair|blind|editorial-review|editorial-revision):v36:([0-9a-f]{64}):output=([1-9][0-9]*)', group)
    if not match:
        return False
    name = match[1]
    kind = response_contract(fmt)
    allowed = {'author': ('lesson', 'practical_course'),
        'graph:source': ('review', 'practical_action_object_graph'),
        'graph:learner': ('review', 'practical_action_object_graph'),
        'attachment:source': ('review', 'practical_isolated_attachment_choice'),
        'attachment:learner': ('review', 'practical_isolated_attachment_choice'),
        'action': ('repair', 'practical_prose_revision'), 'noun': ('repair', 'practical_prose_revision'),
        'questions': ('repair', 'practical_question_editor'), 'question-repair': ('repair', 'practical_question_editor'),
        'editorial-review': ('review', 'practical_editorial_review'),
        'editorial-revision': ('repair', 'practical_editorial_revision'),
        'blind': ('review', 'practical_option_predicates')}
    if (stage, kind) != allowed[name]:
        return False
    if ':' in name:
        role = name.rsplit(':', 1)[1]
        try:
            if fmt['json_schema']['schema']['properties']['role']['enum'] != [role]:
                return False
        except (KeyError, TypeError):
            return False
    return True


def focused_source_review_required(artifacts: Any) -> bool:
    """Keep source holds distinct from explicitly tracked editorial-only provenance gaps."""
    diagnostics = artifacts.diagnostics
    lessons = [lesson for module in artifacts.content.modules for lesson in module.lessons]
    legacy = bool(diagnostics.get('requires_source_review', True) or any(x.requires_source_review() for x in lessons))
    pending = diagnostics.get('focused_editorial_only_provenance_pending')
    display = diagnostics.get('practical_display_course')
    draft = diagnostics.get('draft_review')
    if (diagnostics.get('requires_source_review') is not False or diagnostics.get('requires_editorial_review') is not True
            or diagnostics.get('automated_review_passed') is not False or diagnostics.get('quality_verdict') != 'needs_review'
            or type(pending) is not list or any(type(item) is not str for item in pending)
            or len(pending) != len(set(pending)) or not isinstance(display, dict)
            or not isinstance(display.get('lessons'), list) or not isinstance(draft, dict)
            or draft.get('human_review_required') is not True or draft.get('source_clarification_required') is not False
            or not isinstance(diagnostics.get('practical_course'), dict)
            or draft.get('draft_fingerprint') != _digest(diagnostics['practical_course'])
            or draft.get('source_fingerprint') != diagnostics.get('source_packet_fingerprint')):
        return legacy
    originals = display['lessons']
    if len(originals) != len(lessons) or any(not isinstance(row, dict) or type(row.get('id')) is not str for row in originals):
        return True
    ids = [row['id'] for row in originals]
    if len(ids) != len(set(ids)) or not set(pending) <= set(ids):
        return True
    for raw, lesson in zip(originals, lessons, strict=True):
        if (raw.get('title') != lesson.title or raw.get('content') != lesson.content
                or any('[UNREADABLE_PERCENTAGE_VALUE]' in value for value in (lesson.content, *lesson.source_chunks))
                or lesson.requires_source_review() and raw['id'] not in pending):
            return True
    return False
