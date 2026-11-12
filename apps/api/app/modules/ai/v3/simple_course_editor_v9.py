"""Source-to-body diagnosis followed by one coordinated addressed edit."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.normalized_editorial_review import normalized_editorial_review_format, normalized_review_format
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.simple_course_address_repair import address_repair_format, apply_address_repair
from app.modules.ai.v3.simple_course_block_editor import apply_simple_block_editor, block_editor_format, body_blocks
from app.modules.ai.v3.simple_course_editor import _COMMON, _course_valid
from app.modules.ai.v3.simple_course_editor_v2 import PROSE_REVIEW_INSTRUCTION, _current_context
from app.modules.ai.v3.simple_course_editor_v3 import course_media_safe
from app.modules.ai.v3.simple_course_editor_v6 import run_simple_course_editor_v6, unrepresented_source_images
from app.modules.ai.v3.simple_course_editor_v8 import _COMPARE, _GRAMMAR
from app.modules.ai.v3.simple_editor_findings import compile_finding_dispositions, inventory
from app.modules.ai.v3.simple_plan_formatting import complete_formatting_plan
from app.modules.ai.v3.simple_semantic_source_plan import compile_semantic_plan, semantic_unit_request
from app.modules.ai.v3.simple_source_origin import source_origin_blocks

_SCOPED_COMMON = _COMMON.replace(
    'A keep decision preserves original text while its reason governs interpretation.',
    'A keep decision preserves original text and binds only the specific issue and interpretation stated in its reason. '
    'It does not approve other interpretations of the quoted passage or claims in the draft.').replace(
    'Do not reopen deliberately kept or already registered source matters.',
    'Do not reopen the specific source issue already settled or registered. Evaluate all other draft claims against '
    'the source; draft text and earlier model analysis are not human decisions.')
_JOINT = ('You are the practical course editor. Compare the complete original approved source with the original '
    'course and the independent source-to-lesson review. Cross-check findings against the source; do not blindly '
    'apply proposals or assume the current draft is approved. Correct substantive source-to-teaching and question '
    'errors together, preserving good material. Return body edits using the supplied BODY block ID and the complete '
    'replacement for that block; preserve unchanged blocks. Return necessary title edits and complete same-ID question '
    'objects; the server owns question placement. For every changed teaching rule, retain its '
    'source-defined actors, objects, conditions, relations, exceptions and limits; reconcile affected stems, choices, '
    'keys and explanations with that teaching. A quiz card shows its lesson title, not other cards or the lesson '
    'body. Questions must stand on that visible context. Do not count test explanations as teaching coverage. '
    'Add a complete new lesson only for a genuinely missing practical topic. Preserve original illustrations beside '
    'their actual operations and provide lesson_sources for every final lesson. Only genuinely incompatible '
    'unresolved source meanings are source_questions. If no substantive change is needed, return empty edit arrays. '
    'All changes address the single original course fingerprint; no rewritten full-course snapshot.')
_UNIT_SCOPE = (' This is a source-unit review, not a whole-document coverage review. The authored lesson must teach the '
    'selected primary source slices and their operative conditions. Supporting slices and full surrounding '
    'blocks provide context and resolve dependencies; do not require every supporting rule as separate teaching. '
    'Use only the provided original source and actual lesson; no other model interpretations are supplied.')


def _review_within(value: dict[str, Any], allowed: set[str]) -> bool:
    refs = [ref for row in value['findings'] for ref in row['source_refs']]
    refs += [ref for row in value['source_notes'] for ref in row['source_refs']]
    refs += [ref for items in value['narrative_sources'].values() for ref in items]
    targets = [row['target']['id'] for row in value['findings'] if row['target']['kind'] == 'source']
    return set(refs + targets) <= allowed


async def review_source_unit_v9(packet: Any, corpus: Any, intent: Any, plan: dict[str, Any], unit: dict[str, Any],
                                course: dict[str, Any], stage: Any, *, reference_decisions: tuple[Any, ...] = ()) -> dict[str, Any]:
    plan = compile_semantic_plan(plan, packet, corpus)
    if unit not in plan['units']:
        raise ValueError('simple_v9_unit_invalid')
    view, _ = _current_context(packet, corpus, intent)
    course = _course_valid(course, packet, view)
    plan_fp = _digest(plan)
    lesson_id = 'lesson-' + _digest([plan_fp, unit['id']])[:24]
    if course['title'] != plan['title'] or len(course['lessons']) != 1 or course['lessons'][0]['id'] != lesson_id:
        raise ValueError('simple_v9_unit_course_invalid')
    messages, _, selection = semantic_unit_request(packet, corpus, intent, plan, unit['id'],
                                                    reference_decisions=reference_decisions)
    payload = json.loads(messages[1]['content'])
    payload['lessons'] = [{key: lesson[key] for key in ('id', 'title', 'content')} for lesson in course['lessons']]
    payload['draft_fingerprint'] = _digest(course)
    allowed = selection['primary_refs'] + selection['supporting_refs']
    fmt = view.schema(normalized_review_format(list(allowed), [lesson_id],
        [q['id'] for q in course['lessons'][0]['questions']], packet.fingerprint, _digest(course)))
    messages = [{'role': 'system', 'content': _SCOPED_COMMON + '\n' + PROSE_REVIEW_INSTRUCTION + _GRAMMAR + _COMPARE + _UNIT_SCOPE},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, sort_keys=True)}]

    def validate(value: Any) -> dict[str, Any]:
        canonical: dict[str, Any] = view.decode(value)
        compile_editorial_review(canonical, packet, course)
        if not _review_within(canonical, set(allowed)):
            raise ValueError('simple_v9_unit_review_scope_invalid')
        return canonical

    group = ('practical:simple:review-unit:v9:' + packet.fingerprint + ':plan=' + plan_fp +
             ':unit=' + selection['selection_fingerprint'])
    review = validate(await stage('review', group, messages, fmt, validate))
    return {'source_fingerprint': packet.fingerprint, 'plan_fingerprint': plan_fp,
            'selection_fingerprint': selection['selection_fingerprint'], 'unit_id': unit['id'],
            'lesson_id': lesson_id, 'reviewed_unit_fingerprint': _digest(course),
            'primary_refs': list(selection['primary_refs']), 'supporting_refs': list(selection['supporting_refs']),
            'review': review}


def _validate_unit_reviews(packet: Any, corpus: Any, intent: Any, original: dict[str, Any], plan: dict[str, Any],
                           unit_reviews: list[dict[str, Any]], reference_decisions: tuple[Any, ...], *,
                           require_complete: bool) -> None:
    plan_fp = _digest(plan)
    if type(unit_reviews) is not list or require_complete and len(unit_reviews) != len(plan['units']):
        raise ValueError('simple_v9_unit_reviews_invalid')
    by_lesson = {lesson['id']: lesson for lesson in original['lessons']}
    expected_lessons = {'lesson-' + _digest([plan_fp, unit['id']])[:24] for unit in plan['units']}
    if require_complete and set(by_lesson) != expected_lessons:
        raise ValueError('simple_v9_unit_reviews_invalid')
    try:
        records = {row['unit_id']: row for row in unit_reviews}
    except (KeyError, TypeError):
        raise ValueError('simple_v9_unit_reviews_invalid') from None
    if (len(records) != len(unit_reviews) or not set(records) <= {unit['id'] for unit in plan['units']}
            or require_complete and set(records) != {unit['id'] for unit in plan['units']}):
        raise ValueError('simple_v9_unit_reviews_invalid')
    for unit in plan['units']:
        if unit['id'] not in records:
            continue
        row = records[unit['id']]
        _, _, selection = semantic_unit_request(packet, corpus, intent, plan, unit['id'],
                                                reference_decisions=reference_decisions)
        lesson_id = 'lesson-' + _digest([plan_fp, unit['id']])[:24]
        if lesson_id not in by_lesson:
            raise ValueError('simple_v9_unit_reviews_invalid')
        partial = {'title': plan['title'], 'lessons': [copy.deepcopy(by_lesson[lesson_id])]}
        if (row['source_fingerprint'] != packet.fingerprint or row['plan_fingerprint'] != plan_fp
                or row['selection_fingerprint'] != selection['selection_fingerprint'] or row['lesson_id'] != lesson_id
                or row['reviewed_unit_fingerprint'] != _digest(partial)
                or row['primary_refs'] != list(selection['primary_refs'])
                or row['supporting_refs'] != list(selection['supporting_refs'])
                or not _review_within(row['review'], set(row['primary_refs'] + row['supporting_refs']))):
            raise ValueError('simple_v9_unit_reviews_invalid')
        compile_editorial_review(row['review'], packet, partial)


async def edit_reviewed_course_v9(packet: Any, corpus: Any, intent: Any, original: dict[str, Any],
                                  plan: dict[str, Any], selections: list[dict[str, Any]], stage: Any, *,
                                  unit_reviews: list[dict[str, Any]], reference_decisions: tuple[Any, ...] = (),
                                  additional_stage_callback: Any = None
                                  ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    view, context = _current_context(packet, corpus, intent)
    original = _course_valid(original, packet, view)
    plan = compile_semantic_plan(plan, packet, corpus)
    fingerprint, plan_fp = _digest(original), _digest(plan)
    _validate_unit_reviews(packet, corpus, intent, original, plan, unit_reviews, reference_decisions, require_complete=True)
    context['source_blocks'] = [{**row, 'id': view.canonical_to_alias[row['id']]}
        for row in source_origin_blocks(packet, corpus) if row['id'] in view.canonical_to_alias]
    review_fmt = view.schema(normalized_editorial_review_format(packet, original))
    review_payload = {**context, 'lessons': [{key: lesson[key] for key in ('id', 'title', 'content')}
                                           for lesson in original['lessons']], 'draft_fingerprint': fingerprint}
    review_messages = [{'role': 'system', 'content': _SCOPED_COMMON + '\n' + PROSE_REVIEW_INSTRUCTION + _GRAMMAR + _COMPARE},
                       {'role': 'user', 'content': json.dumps(review_payload, ensure_ascii=False, sort_keys=True)}]

    def validate_review(value: Any) -> dict[str, Any]:
        canonical: dict[str, Any] = view.decode(value)
        compile_editorial_review(canonical, packet, original)
        return canonical

    review_wire = await stage('review', 'practical:simple:review-content:v9:' + packet.fingerprint + ':unit=' + plan_fp,
                              review_messages, review_fmt, validate_review)
    review = validate_review(review_wire)
    return await apply_reviewed_course_v9(packet, corpus, intent, original, plan, stage,
        content_review=review, unit_reviews=unit_reviews, reference_decisions=reference_decisions,
        additional_stage_callback=additional_stage_callback)


async def apply_reviewed_course_v9(packet: Any, corpus: Any, intent: Any, original: dict[str, Any],
                                   plan: dict[str, Any], stage: Any, *, content_review: dict[str, Any],
                                   unit_reviews: list[dict[str, Any]], reference_decisions: tuple[Any, ...] = (),
                                   additional_stage_callback: Any = None
                                   ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    view, context = _current_context(packet, corpus, intent)
    original = _course_valid(original, packet, view)
    plan = compile_semantic_plan(plan, packet, corpus)
    fingerprint, plan_fp = _digest(original), _digest(plan)
    compile_editorial_review(content_review, packet, original)
    _validate_unit_reviews(packet, corpus, intent, original, plan, unit_reviews, reference_decisions, require_complete=False)
    review = copy.deepcopy(content_review)
    context['source_blocks'] = [{**row, 'id': view.canonical_to_alias[row['id']]}
        for row in source_origin_blocks(packet, corpus) if row['id'] in view.canonical_to_alias]
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    blocks = body_blocks(original)
    findings = inventory(packet.fingerprint, fingerprint, [('global', review)] +
                         [(row['unit_id'], row['review']) for row in unit_reviews])
    finding_ids = [row['id'] for row in findings] or None
    edit_fmt = view.schema(block_editor_format(ids, packet.fingerprint, fingerprint,
                                              [row['id'] for row in blocks], finding_ids))
    block_course = {'title': original['title'], 'lessons': [
        {'id': lesson['id'], 'title': lesson['title'],
         'body_blocks': [{'id': block['id'], 'text': block['text']} for block in blocks if block['lesson_id'] == lesson['id']],
         'questions': copy.deepcopy(lesson['questions'])} for lesson in original['lessons']]}
    review_records = [{**row, 'primary_refs': [view.canonical_to_alias[ref] for ref in row['primary_refs']],
                       'supporting_refs': [view.canonical_to_alias[ref] for ref in row['supporting_refs']]}
                      for row in unit_reviews]
    edit_payload = {**context, 'original_course': view.encode(block_course),
                    'unit_reviews': view.encode(review_records),
                    'independent_content_review': view.encode(review), 'draft_fingerprint': fingerprint,
                    'unrepresented_primary_illustrations': view.encode(unrepresented_source_images(packet, corpus, plan, original))}
    edit_messages = [{'role': 'system', 'content': _SCOPED_COMMON + '\n' + _JOINT + _GRAMMAR + _COMPARE},
                     {'role': 'user', 'content': json.dumps(edit_payload, ensure_ascii=False, sort_keys=True)}]
    if findings:
        edit_payload['material_findings'] = view.encode(findings)
        edit_messages[0]['content'] += (' For EACH material_findings ID give a finding_disposition: CORRECTED, '
            'ALREADY_SATISFIED, NOT_MATERIAL or UNRESOLVED. Cross-check the finding; do not change good text to satisfy '
            'a false criticism. Give a reason, a short exact original source_quote with source_refs, and a short '
            'exact final_quote in the final field identified by target.kind/id/choice_index (0 unless a choice). '
            'A lesson-content finding needs evidence in that lesson body, not a test explanation. CORRECTED means '
            'that field actually changes; ALREADY_SATISFIED means the evidence already existed. NOT_MATERIAL needs '
            'source and final-text evidence explaining why no substantive change is warranted. Silence or unsupported '
            'claims remain unresolved; this is your editorial judgment, not independent approval.')
        edit_messages[1]['content'] = json.dumps(edit_payload, ensure_ascii=False, sort_keys=True)

    def validate_edit(value: Any) -> dict[str, Any]:
        if not _matches(value, edit_fmt['json_schema']['schema']):
            raise ValueError('simple_v9_editor_shape_invalid')
        canonical: dict[str, Any] = view.decode(value)
        return canonical

    def apply_edit(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        envelope, receipt = apply_simple_block_editor(value, original, ids, packet.fingerprint, fingerprint, finding_ids)
        envelope['course'] = _course_valid(envelope['course'], packet, view)
        if any(len(lesson['questions']) < 3 for lesson in envelope['course']['lessons']):
            raise ValueError('simple_v9_question_count_invalid')
        if not course_media_safe(original, envelope['course'], packet):
            raise ValueError('simple_v9_editor_media_changed')
        return envelope, receipt

    edit_wire = await stage('repair', 'practical:simple:editor-joint:v9:' + packet.fingerprint + ':unit=' + plan_fp,
                            edit_messages, edit_fmt, validate_edit)
    proposal = validate_edit(edit_wire)
    proposal_fp = _digest(proposal)
    address_value = None
    address_receipt = None
    edits = proposal['body_edits']
    targets = [row['block_id'] for row in edits]
    if len(targets) != len(set(targets)):
        if additional_stage_callback:
            await additional_stage_callback()
        address_fmt = address_repair_format(packet.fingerprint, fingerprint, proposal_fp, len(edits),
                                            [row['id'] for row in blocks])
        titles = {lesson['id']: lesson['title'] for lesson in original['lessons']}
        address_payload = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
            'proposal_fingerprint': proposal_fp,
            'body_blocks': [{'id': row['id'], 'lesson_title': titles[row['lesson_id']], 'text': row['text']}
                            for row in blocks],
            'edits': [{'edit_id': f'EDIT{i}', 'proposed_block_id': row['block_id'], 'after': row['after']}
                      for i, row in enumerate(edits, 1)]}
        address_messages = [{'role': 'system', 'content': 'Match each prepared edit to its physical original BODY block. '
            'Return each EDIT exactly once. Do not change text or make semantic edits. Use UNRESOLVED if it cannot '
            'be placed without merging text; do not choose arbitrary distinct blocks to satisfy uniqueness.'},
            {'role': 'user', 'content': json.dumps(address_payload, ensure_ascii=False, sort_keys=True)}]

        def validate_address(value: Any) -> dict[str, Any]:
            if not _matches(value, address_fmt['json_schema']['schema']):
                raise ValueError('simple_v9_address_shape_invalid')
            result: dict[str, Any] = value
            return result

        address_value = await stage('repair', 'practical:simple:repair-address:v9:' + packet.fingerprint +
            ':unit=' + plan_fp + ':proposal=' + proposal_fp, address_messages, address_fmt, validate_address)
        address_value = validate_address(address_value)
    body_receipt: dict[str, Any] = {'content_review': review, 'unit_reviews': copy.deepcopy(unit_reviews),
                    'proposal_fingerprint': proposal_fp}
    try:
        applied = proposal
        if address_value is not None:
            applied, address_receipt = apply_address_repair(address_value, proposal, original, ids,
                                                            packet.fingerprint, fingerprint, finding_ids)
        envelope, delta_receipt = apply_edit(applied)
        body_receipt.update({'application_status': 'applied', 'joint_delta_receipt': delta_receipt})
        if address_receipt is not None:
            body_receipt['address_receipt'] = address_receipt
    except ValueError as exc:
        envelope = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
                    'course': copy.deepcopy(original),
                    'lesson_sources': [{'lesson_id': lesson['id'],
                        'source_refs': copy.deepcopy(review['narrative_sources'][lesson['id']])}
                        for lesson in original['lessons']],
                    'source_questions': copy.deepcopy(proposal['source_questions'])}
        body_receipt.update({'application_status': 'unapplied', 'error_code': 'simple_v9_correction_unapplied',
                             'address_result': copy.deepcopy(address_value)})
        if address_value is not None:
            address_error = str(exc)
            body_receipt['address_error'] = (address_error if address_error.startswith('simple_address_repair_')
                                             else 'simple_v9_correction_unapplied')
    card_receipt = {'method': 'passthrough', 'no_extra_model_call': True}
    body_receipt['finding_dispositions'] = compile_finding_dispositions(
        findings, proposal.get('finding_dispositions', []), packet, original, envelope['course'])
    return envelope, copy.deepcopy(envelope), body_receipt, card_receipt


async def run_simple_course_editor_v9(packet: Any, corpus: Any, intent: Any, stage: Any, *,
                                      reference_decisions: tuple[Any, ...] = (), planned_callback: Any = None,
                                      retain_unit_title_context: bool = False,
                                      repair_plan_accounting: bool = False) -> Any:
    plan: dict[str, Any] | None = None
    plan_normalization: dict[str, Any] | None = None
    accounting_receipt: dict[str, Any] | None = None
    role_normalization: dict[str, Any] | None = None
    selections_by_fp: dict[str, tuple[dict[str, Any], Any]] = {}
    records: list[dict[str, Any]] = []

    async def versioned(name: str, group: str, messages: Any, fmt: Any, validator: Any) -> Any:
        nonlocal plan, plan_normalization, accounting_receipt, role_normalization
        if ':plan:v6:' in group:
            plan_messages = copy.deepcopy(messages)
            system = plan_messages[0]['content']
            if not system.startswith(_COMMON):
                raise ValueError('simple_v9_plan_instruction_invalid')
            plan_messages[0]['content'] = _SCOPED_COMMON + system[len(_COMMON):]
            def validated_plan(value: Any) -> dict[str, Any]:
                nonlocal plan_normalization
                completed, receipt = complete_formatting_plan(value, packet, corpus)
                if receipt['auto_excluded'] or plan_normalization is None:
                    plan_normalization = receipt
                canonical: dict[str, Any] = validator(completed)
                return canonical

            def structural_plan(value: Any) -> dict[str, Any]:
                from app.modules.ai.v3.simple_semantic_source_plan import matches_semantic_plan_structure

                if not matches_semantic_plan_structure(value, fmt):
                    raise ValueError('semantic_plan_invalid')
                return copy.deepcopy(value)

            wire = await stage(name, group.replace(':v6:', ':v9:', 1), plan_messages, fmt,
                               structural_plan if repair_plan_accounting else validated_plan)
            if repair_plan_accounting:
                from app.modules.ai.v3.simple_plan_formatting import canonicalize_plan_support

                wire, role_normalization = canonicalize_plan_support(wire, packet, corpus)
            try:
                plan = validated_plan(wire)
            except ValueError as exc:
                if not repair_plan_accounting or str(exc) != 'semantic_plan_invalid':
                    raise
                from app.modules.ai.v3.simple_plan_accounting import accounting_request, apply_accounting

                repair_messages, repair_fmt = accounting_request(wire, packet, corpus)

                def validate_accounting(value: Any) -> dict[str, Any]:
                    return apply_accounting(value, wire, packet, corpus)[0]

                proposal = await stage('repair', 'practical:simple:plan-accounting:v11:' + packet.fingerprint
                    + ':unit=' + _digest(wire), repair_messages, repair_fmt, validate_accounting)
                plan, accounting_receipt = apply_accounting(proposal, wire, packet, corpus)
            for unit in plan['units']:
                _, _, selected = semantic_unit_request(packet, corpus, intent, plan, unit['id'],
                                                       reference_decisions=reference_decisions)
                identity = selected['selection_fingerprint']
                if identity in selections_by_fp:
                    raise ValueError('simple_v9_unit_selection_invalid')
                selections_by_fp[identity] = (unit, selected)
            if planned_callback:
                await planned_callback(2 * len(plan['units']) + 3 + int(accounting_receipt is not None))
            return plan
        if plan is None or ':author-unit:v6:' not in group:
            raise ValueError('simple_v9_stage_invalid')
        selection_fp = group.rsplit(':unit=', 1)[-1]
        if selection_fp not in selections_by_fp:
            raise ValueError('simple_v9_unit_selection_invalid')
        unit, _ = selections_by_fp[selection_fp]
        author_group = ('practical:simple:author-unit:v9:' + packet.fingerprint + ':plan=' + _digest(plan) +
                        ':unit=' + selection_fp)
        authored_messages = copy.deepcopy(messages)
        system = authored_messages[0]['content']
        if not system.startswith(_COMMON):
            raise ValueError('simple_v9_author_instruction_invalid')
        authored_messages[0]['content'] = _SCOPED_COMMON + system[len(_COMMON):] + _GRAMMAR
        wire = await stage(name, author_group, authored_messages, fmt, validator)
        authored = validator(wire)
        lesson = copy.deepcopy(authored['lessons'][0])
        if retain_unit_title_context:
            from app.modules.ai.v3.simple_course_editor_v6 import unit_lesson_title

            lesson['title'] = unit_lesson_title(unit['title'], lesson['title'])
        lesson['id'] = 'lesson-' + _digest([_digest(plan), unit['id']])[:24]
        for question in lesson['questions']:
            question['id'] = 'question-' + _digest([lesson['id'], question['id']])[:24]
        partial = {'title': plan['title'], 'lessons': [lesson]}
        records.append(await review_source_unit_v9(packet, corpus, intent, plan, unit, partial, stage,
                                                   reference_decisions=reference_decisions))
        return wire

    async def editor(source_packet: Any, source_corpus: Any, source_intent: Any, original: Any,
                     source_plan: Any, selections: Any, _stage: Any) -> Any:
        async def extra_stage() -> None:
            if planned_callback:
                await planned_callback(2 * len(source_plan['units']) + 4 + int(accounting_receipt is not None))
        return await edit_reviewed_course_v9(source_packet, source_corpus, source_intent, original, source_plan,
            selections, stage, unit_reviews=records, reference_decisions=reference_decisions,
            additional_stage_callback=extra_stage)

    result = await run_simple_course_editor_v6(packet, corpus, intent, versioned,
        reference_decisions=reference_decisions, course_editor=editor,
        retain_unit_title_context=retain_unit_title_context)
    fingerprint = _digest(result.draft)
    body_receipt = result.review['editor_delta_receipts']['body']
    reviews = [('global', body_receipt['content_review'])] + [
        (row['unit_id'], row['review']) for row in body_receipt['unit_reviews']]
    observations = []
    pending: dict[str, dict[str, Any]] = {}
    for provenance, content_review in reviews:
        for finding in content_review['findings']:
            if finding['domain'] != 'source':
                continue
            question, refs = finding['problem'], finding['source_refs']
            already_reported = any(row['question'] == question and row['source_refs'] == refs
                                   for row in result.source_questions)
            identity = 'simple-v9-source-' + _digest([packet.fingerprint, fingerprint, question, refs])[:24]
            observations.append({'id': identity, 'status': 'UNVERIFIED', 'question': question, 'problem': question,
                                 'basis': finding['basis'], 'source_refs': copy.deepcopy(refs),
                                 'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
                                 'finding': copy.deepcopy(finding), 'review_origin': provenance,
                                 'already_joint_source_question': already_reported})
            if finding['severity'] == 'material' and not already_reported:
                pending.setdefault(identity, {'id': identity, 'status': 'UNVERIFIED', 'question': question,
                    'problem': question, 'basis': finding['basis'], 'source_refs': copy.deepcopy(refs),
                    'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint})
    receipt = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
               'source_findings': observations, 'unverified_source_questions': list(pending.values())}
    dispositions = body_receipt.get('finding_dispositions', [])
    receipt['review_finding_dispositions'] = copy.deepcopy(dispositions)
    unresolved = [{**copy.deepcopy(row), 'id': 'simple-v9-unapplied-' + row['id']}
                  for row in dispositions if not row['model_resolved']]
    if unresolved:
        receipt['unapplied_review_findings'] = unresolved
    if body_receipt.get('application_status') == 'unapplied':
        unapplied: dict[str, dict[str, Any]] = {row['id']: row for row in unresolved}
        for _, content_review in reviews:
            for finding in content_review['findings']:
                if finding['domain'] == 'source' or finding['severity'] != 'material':
                    continue
                identity = 'simple-v9-unapplied-' + _digest([packet.fingerprint, fingerprint, finding])[:24]
                unapplied[identity] = {'id': identity, 'status': 'UNVERIFIED', 'finding': copy.deepcopy(finding),
                    'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint}
        if not unapplied:
            finding = {'domain': 'content', 'severity': 'material', 'target': {'kind': 'course', 'id': ''},
                'problem': 'The proposed course correction could not be applied.',
                'correction': 'Review the original course and apply the needed correction.', 'basis': '',
                'source_refs': [next(block.block_id for block in packet.blocks if block.text.strip())]}
            identity = 'simple-v9-unapplied-' + _digest([packet.fingerprint, fingerprint, finding])[:24]
            unapplied[identity] = {'id': identity, 'status': 'UNVERIFIED', 'finding': finding,
                'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint}
        receipt['unapplied_review_findings'] = list(unapplied.values())
    extra = {'source_plan_accounting': accounting_receipt} if accounting_receipt is not None else {}
    if role_normalization is not None:
        extra['source_plan_role_normalization'] = role_normalization
    return replace(result, review={**result.review, 'method': 'semantic-unit-source-reviews-joint-block-editor-v1',
                                   'source_plan_normalization': plan_normalization, 'revision_receipt': receipt, **extra})
