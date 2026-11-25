"""Bound a joint editor call to its owned lessons while retaining global findings."""
from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_joint_related_source import related_source_blocks

LESSONS_PER_BATCH = 2
JOINT_LESSON_LIMIT = 4
_ARRAYS = ('body_edits', 'title_edits', 'question_edits', 'added_lessons',
           'lesson_sources', 'source_questions', 'finding_dispositions')

_BATCH_TASK = (
    ' The course outline describes peer lessons for orientation only. The original_course '
    'in this request contains the complete owned lessons for this edit. Edit only their supplied '
    'BODY IDs, lesson IDs and question IDs. Use material_findings as the exact disposition inventory '
    'for this batch. Return lesson_sources for these owned lessons and any lessons you add. '
    'A source rule already taught by a peer is not a new coverage requirement. Add a lesson only '
    'if an assigned course-level finding or missing primary illustration requires one. '
    'Apply no edits to the course title, outline or peer lessons. The server combines disjoint '
    'proposals against the same original draft.'
)


def _refs(row: dict[str, Any]) -> set[str]:
    return set(row.get('source_refs', ()))


def batch_joint_editor(
    messages: list[dict[str, str]], *, related_evidence: bool = False
) -> list[tuple[list[dict[str, str]], dict[str, Any]]]:
    payload = json.loads(messages[1]['content'])
    lessons = payload['original_course']['lessons']
    if len(lessons) <= JOINT_LESSON_LIMIT:
        return []

    quizzed_in = {question['id']: lesson['id'] for lesson in lessons for question in lesson['questions']}
    lesson_index = {lesson['id']: index // LESSONS_PER_BATCH for index, lesson in enumerate(lessons)}
    global_review = payload['independent_content_review']
    narrative = global_review['narrative_sources']
    records = {record['lesson_id']: record for record in payload['unit_reviews']}
    course_outline = [{'id': lesson['id'], 'title': lesson['title']} for lesson in lessons]
    context_refs: list[set[str]] = []
    for start in range(0, len(lessons), LESSONS_PER_BATCH):
        refs = set()
        for lesson in lessons[start:start + LESSONS_PER_BATCH]:
            record = records[lesson['id']]
            refs.update(record['primary_refs'])
            refs.update(record['supporting_refs'])
            refs.update(narrative[lesson['id']])
            for question in lesson['questions']:
                refs.update(_refs(question))
        context_refs.append(refs)

    def closest(refs: set[str]) -> int:
        return max(range(len(context_refs)), key=lambda index: len(context_refs[index] & refs))

    findings: list[list[dict[str, Any]]] = [[] for _ in context_refs]
    for item in payload.get('material_findings', []):
        finding = item['finding']
        target = finding['target']
        owner = quizzed_in.get(target['id'], target['id'])
        index = lesson_index[owner] if owner in lesson_index else closest(_refs(finding))
        findings[index].append(item)

    visuals: list[list[dict[str, Any]]] = [[] for _ in context_refs]
    for row in payload['unrepresented_primary_illustrations']:
        visuals[closest(_refs(row))].append(row)

    batches = []
    for index, refs in enumerate(context_refs):
        start = index * LESSONS_PER_BATCH
        scoped_lessons = lessons[start:start + LESSONS_PER_BATCH]
        owners = {lesson['id'] for lesson in scoped_lessons}
        scoped_findings = findings[index]
        ids = {item['id'] for item in scoped_findings}
        allowed_refs = refs | {ref for item in scoped_findings for ref in _refs(item['finding'])}
        allowed_refs.update(ref for row in visuals[index] for ref in _refs(row))
        related = related_source_blocks(payload['source_blocks'], allowed_refs) if related_evidence else []
        scoped = {
            **payload,
            'original_course': {**payload['original_course'], 'lessons': scoped_lessons},
            'course_outline': course_outline,
            'material_findings': scoped_findings,
            'source_blocks': [block for block in payload['source_blocks'] if block['id'] in allowed_refs],
            'unit_reviews': [
                {key: records[lesson['id']][key] for key in ('lesson_id', 'primary_refs', 'supporting_refs')}
                for lesson in scoped_lessons
            ],
            'independent_content_review': {
                'narrative_sources': {lesson['id']: narrative[lesson['id']] for lesson in scoped_lessons},
            },
            'unrepresented_primary_illustrations': visuals[index],
        }
        instruction = messages[0]['content'] + _BATCH_TASK
        if related:
            scoped['source_blocks'].extend(related)
            scoped['companion_source_refs'] = [row['id'] for row in related]
            instruction += (
                ' Companion source passages repeat parts of the same wording elsewhere in the approved source. '
                'Compare them with the rule as taught in your owned lessons. Include any stated alternative, '
                'exception or condition that changes the correct action. Ignore similar wording about a different '
                'case. Preserve the unchanged rule and cite the passages that govern each branch.'
            )
        custody = {
            'batch': index + 1,
            'draft_fingerprint': payload['draft_fingerprint'],
            'owners': owners,
            'all_owners': set(lesson_index),
            'blocks': {block['id']: lesson['id'] for lesson in scoped_lessons for block in lesson['body_blocks']},
            'questions': {question['id'] for lesson in scoped_lessons for question in lesson['questions']},
            'findings': ids,
            'allow_additions': bool(visuals[index]) or any(
                item['finding']['target']['kind'] == 'course' for item in scoped_findings),
            'narrative_sources': scoped['independent_content_review']['narrative_sources'],
        }
        batches.append(([{'role': 'system', 'content': instruction},
                         {'role': 'user', 'content': json.dumps(scoped, sort_keys=True, ensure_ascii=False)}],
                        custody))
    return batches


def owned_joint_proposal(value: dict[str, Any], custody: dict[str, Any]) -> dict[str, Any]:
    """Check addresses against the actual payload. Reuse original refs for unchanged lessons."""
    proposal = copy.deepcopy(value)
    for key, address, inventory in (
        ('body_edits', 'block_id', 'blocks'), ('title_edits', 'lesson_id', 'owners'),
        ('question_edits', 'id', 'questions'), ('finding_dispositions', 'finding_id', 'findings'),
    ):
        if any(row[address] not in custody[inventory] for row in proposal.get(key, ())):
            raise ValueError('simple_v12_joint_batch_scope_invalid')

    added = proposal['added_lessons']
    originals = {row['id'] for row in added}
    if (len(originals) != len(added) or originals & custody['all_owners']
            or added and not custody['allow_additions']):
        raise ValueError('simple_v12_joint_batch_addition_invalid')
    replacements = {identity: 'lesson-' + _digest(
        [custody['draft_fingerprint'], custody['batch'], identity])[:24] for identity in originals}
    for lesson in added:
        lesson['id'] = replacements[lesson['id']]
        for question in lesson['questions']:
            question['id'] = 'question-' + _digest([lesson['id'], question['id']])[:24]

    allowed = custody['owners'] | originals
    source_rows = {row['lesson_id']: row for row in proposal['lesson_sources']}
    if not set(source_rows) <= allowed or len(source_rows) != len(proposal['lesson_sources']):
        raise ValueError('simple_v12_joint_batch_scope_invalid')
    for identity, refs in custody['narrative_sources'].items():
        source_rows.setdefault(identity, {'lesson_id': identity, 'source_refs': refs})
    if set(source_rows) != allowed:
        raise ValueError('simple_v12_joint_batch_sources_missing')
    for row in source_rows.values():
        row['lesson_id'] = replacements.get(row['lesson_id'], row['lesson_id'])
    proposal['lesson_sources'] = list(source_rows.values())
    for row in proposal.get('finding_dispositions', ()):
        target = row['target']
        if target['kind'] == 'lesson_content':
            target['id'] = custody['blocks'].get(target['id'], target['id'])
        inventory = allowed if target['kind'].startswith('lesson_') else custody['questions']
        if target['id'] not in inventory and row['status'] != 'UNRESOLVED':
            raise ValueError('simple_v12_joint_batch_scope_invalid')
        target['id'] = replacements.get(target['id'], target['id'])
    return proposal


def combine_joint_proposals(proposals: list[dict[str, Any]]) -> dict[str, Any]:
    combined = {key: value for key, value in proposals[0].items() if key not in _ARRAYS}
    for key in _ARRAYS:
        if key in proposals[0]:
            combined[key] = [row for proposal in proposals for row in proposal[key]]
    if combined['source_questions']:
        combined['source_questions'] = list({
            _digest([row['question'], sorted(row['source_refs'])]): row
            for row in combined['source_questions']
        }.values())
    return combined
