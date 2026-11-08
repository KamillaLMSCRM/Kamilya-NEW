"""Separate source-to-prose coverage from keyed assessment on the current draft.

No quiz facts can certify teaching coverage; no material finding is lost.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.v3.practical_compact_editorial_contract import (
    compact_editorial_review_format as rule_editorial_review_format,
)
from app.modules.ai.v3.practical_compact_editorial_contract import (
    compact_editorial_verification_format as rule_editorial_verification_format,
)
from app.modules.ai.v3.practical_compact_editorial_contract import (
    compile_compact_editorial_review as compile_rule_editorial_review,
)
from app.modules.ai.v3.practical_compact_editorial_contract import (
    compile_compact_editorial_verification as compile_rule_editorial_verification,
)
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review, editorial_review_format
from app.modules.ai.v3.practical_editorial_proof_correction import correct_resolution_proofs, same_proof_disposition
from app.modules.ai.v3.practical_editorial_verification import (
    compile_editorial_verification,
    editorial_verification_format,
)
from app.modules.ai.v3.practical_source_comparisons import build_source_comparison_groups

CURRENT_TARGET_GUIDE = (
    '\nPrior problem, basis and correction describe historical observations, not the current state. '
    'For each resolution compare them with its adjacent current_target_snapshot and the full current course. '
    'Read the current choices and correct_index explicitly before alleging an old answer-key defect. '
    'Do not repeat an already removed defect. If the old allegation is no longer true, resolve it; '
    'describe any genuinely different defect as a new precise finding. For a question NEEDS_REVISION, '
    'course_quote must be a literal excerpt of that CURRENT question, choices or explanation. '
    'Copy current wording exactly; do not quote a previous revision from prior basis.'
)


def _current_prior_targets(prior: list[dict[str, Any]], course: dict[str, Any], *, prose_only: bool) -> list[dict[str, Any]]:
    lessons = {row['id']: row for row in course['lessons']}
    questions = {q['id']: q for row in course['lessons'] for q in row['questions']}
    result = []
    for row in prior:
        target = row['target']
        snapshot = None
        if target['kind'] == 'question' and not prose_only:
            snapshot = questions.get(target['id'])
        elif target['kind'] == 'lesson' and target['id'] in lessons:
            lesson = lessons[target['id']]
            snapshot = ({key: lesson[key] for key in ('id', 'title', 'content')} if prose_only else lesson)
        result.append({**row, 'current_target_snapshot': copy.deepcopy(snapshot)})
    return result


def _hold_out_of_scope_findings(result: dict[str, Any], lesson_ids: list[str]) -> None:
    """Prose-only observations cannot authorize changes to unseen assessments."""
    for finding in result['review']['findings']:
        if (finding['domain'] == 'assessment' or finding['target']['kind'] == 'question'
                or finding['target']['kind'] == 'lesson' and finding['target']['id'] not in lesson_ids):
            finding['rule_check_unverified'] = True
            finding['out_of_scope_review'] = 'PROSE_ONLY_STAGE'


def _prior_comparison_owner(finding: dict[str, Any], comparisons: list[dict[str, Any]],
                            owners: dict[str, int]) -> int:
    """Route by actual rule/source custody, then lesson attention; never adjudicate."""
    if not comparisons:
        raise ValueError('editorial_comparison_inventory_empty')
    rule_id = finding.get('source_rule_id')
    if rule_id is not None:
        if not isinstance(rule_id, str) or rule_id not in owners:
            raise ValueError('editorial_prior_rule_identity_invalid')
        return owners[rule_id]
    candidates = list(range(len(comparisons)))
    refs = set(finding['source_refs'])
    scores = [len(refs.intersection(ref for goal in group['goals']
                                   for ref in goal['rule']['source_refs'])) for group in comparisons]
    highest = max(scores)
    if highest:
        candidates = [index for index in candidates if scores[index] == highest]
    linked = next((index for index in candidates if comparisons[index]['scope'] == 'linked_lessons'
        and finding['target']['kind'] == 'lesson' and finding['target']['id'] in comparisons[index]['lesson_ids']), None)
    if linked is not None:
        return linked
    return next((index for index in candidates if comparisons[index]['scope'] == 'course_coverage'), candidates[0])


async def review_editorial_candidate(
    packet: Any,
    reading: dict[str, Any],
    course: dict[str, Any],
    context: str,
    view: Any,
    call: Any,
    system: str,
    *,
    max_rules: int,
    assessment_system: str,
    verification_guide: str,
    prior: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    all_prior = prior
    assessment_prior = [row for row in prior or [] if row['domain'] == 'assessment'
                        or row['target']['kind'] == 'question' or row.get('review_origin') == 'COURSE_FIDELITY']
    if prior is not None:
        prior = [row for row in prior if row not in assessment_prior]
    comparisons = build_source_comparison_groups(packet, reading, course, max_rules=max_rules)
    parts = [group['rule_ids'] for group in comparisons]
    owners = {key: index for index, part in enumerate(parts) for key in part}
    assignments: list[list[dict[str, Any]]] = [[] for _ in parts]
    for finding in prior or []:
        owner = _prior_comparison_owner(finding, comparisons, owners)
        assignments[owner].append(finding)
    results = []
    raw_parts = []
    async def request_part(
        comparison: dict[str, Any], ids: list[str], assigned: list[dict[str, Any]],
        correction: list[dict[str, Any]] | None = None
    ) -> tuple[Any, Any]:
        # Put the actual text beside the norms under comparison. The original
        # remains complete for dependencies, but no other quiz/prose can be
        # silently substituted for the lesson the reviewer is evaluating.
        content = "CURRENT_TEACHING_PROSE_JSON\n" + json.dumps(
            {'course_fingerprint': _digest(course), 'title': course['title'],
             'lessons': [{key: lesson[key] for key in ('id', 'title', 'content')}
                         for lesson in course['lessons'] if lesson['id'] in comparison['lesson_ids']]},
            ensure_ascii=False, sort_keys=True)
        content += '\nUNVERIFIED_SOURCE_TO_TEACHING_COMPARISONS_JSON\n' + json.dumps(view.encode(
            [goal for goal in comparison['goals'] if goal['rule_id'] in ids]), ensure_ascii=False, sort_keys=True)
        # Quiz refs are attention anchors, NOT exhaustive prose ownership. Every
        # rule can still be misstated (or already taught) in any peer lesson.
        content += '\nOTHER_CURRENT_TEACHING_PROSE_JSON\n' + json.dumps(
            [{key: lesson[key] for key in ('id', 'title', 'content')}
             for lesson in course['lessons'] if lesson['id'] not in comparison['lesson_ids']],
            ensure_ascii=False, sort_keys=True)
        content += '\nCOMPARISON_SCOPE\n' + comparison['scope']
        content += '\nSOURCE_SECTION_UNVERIFIED\n' + comparison.get('source_section', '')
        content += "\nREQUIRED_SOURCE_RULE_IDS_JSON\n" + json.dumps(ids)
        content += '\nFULL_ORIGINAL_SOURCE_FOR_DEPENDENCIES\n' + context
        if correction:
            content += "\nPRIOR_RULE_CHECKS_UNVERIFIED_JSON\n" + json.dumps(
                view.encode(correction), ensure_ascii=False, sort_keys=True
            )
        if prior is not None:
            content += "\nPRIOR_MATERIAL_FINDINGS_JSON\n" + json.dumps(
                view.encode(_current_prior_targets(assigned, course, prose_only=True)), ensure_ascii=False
            )
            fmt = rule_editorial_verification_format(packet, course, reading, assigned, rule_ids=ids)
        else:
            fmt = rule_editorial_review_format(packet, course, reading, rule_ids=ids)

        def compile_response(value: Any, findings: Any = assigned, subset: Any = ids) -> Any:
            if prior is None:
                return compile_rule_editorial_review(value, packet, course, reading, rule_ids=subset)
            return compile_rule_editorial_verification(value, packet, course, reading, findings, rule_ids=subset)

        instruction = (
            '\nCompare EACH source rule with the actual supplied lesson as a small logical problem. '
            'These are UNVERIFIED comparisons, not established course defects. For EACH required rule ID '
            'try to construct a concrete employee action or state that satisfies everything explicitly taught '
            'by the lesson but violates an independent obligation or condition of that source rule. '
            'If such a counterexample exists, state it and the exact missing action or wrong scope in reason; '
            'return INCOMPLETE or CONTRADICTED with an addressed correction and explicit owned affected '
            'lesson_ids. A missing action needs no invented lesson_quote, but its lesson target must be explicit. '
            'When the source requires several independent actions, list them separately in reason before '
            'testing whether each is taught. Fulfilling one does not logically fulfill another. '
            'Do not mentally complete the lesson using facts from the source, professional expectations '
            'or a neighboring duty. Check peer prose too: source links are navigation, not a guarantee '
            'that a rule is only taught in its primary lesson. An adequate primary lesson cannot hide '
            'a contradictory statement in another lesson. If the same action/condition IS actually taught, return SUPPORTED '
            'and a short exact contiguous lesson_quotes excerpt supporting that SAME action/scope. '
            'Do not invent a quote for a missing action. NOT_APPLICABLE is for irrelevant administration '
            'or source detail not essential to the course; explain why rather than invent coverage. '
            'Optional precision and wording preferences are advisory, not material errors. '
            'A source ID alone does not prove meaning. Source-reading errors are SOURCE_READING_DISPUTED, '
            'not an invented owner question. Questions/keys/explanations are not supplied or assessed here. '
            'Return exactly one source_rule_checks for EACH REQUIRED_SOURCE_RULE_IDS_JSON entry. '
            'For resolutions process exactly PRIOR_MATERIAL_FINDINGS_JSON, retaining strict current quotes. '
            'If PRIOR_RULE_CHECKS_UNVERIFIED_JSON is present, correct those evidence bindings from actual '
            'current prose; do not rewrite the course or assume the earlier verdict was true.'
        )
        if assigned:
            instruction += (
                ' Prior basis describes an earlier observation, not current teaching. '
                'For each resolution use the adjacent current_target_snapshot and current peer prose; '
                'copy literal current text, not a quote from prior basis. Missing-content negatives '
                'need no invented quotation. Questions are not present in these prose-only snapshots.'
            )
        group = (
            "practical:editorial:"
            + ("review" if prior is None else "verify")
            + ":v33:"
            + _digest([course, reading, comparison, ids, assigned, system, instruction, correction])
        )
        raw = await call(
            "review",
            group,
            [{"role": "system", "content": system + instruction}, {"role": "user", "content": content}],
            fmt,
            compile_response,
        )
        return compile_response(raw), raw

    for index, ids in enumerate(parts):
        comparison = comparisons[index]
        assigned = assignments[index]
        result, raw = await request_part(comparison, ids, assigned)
        _hold_out_of_scope_findings(result, [lesson['id'] for lesson in course['lessons']])
        receipt = {'rule_ids': ids, 'lesson_ids': comparison['lesson_ids'], 'scope': comparison['scope'],
                   'source_section': comparison.get('source_section', ''),
                   'response': raw, 'review_kind': 'prose'}
        invalid = [
            row
            for row in result["source_rule_checks"]
            if not row["verified"]
            and not set(row["verification_errors"]) & {"source_reading_unverified", "source_reading_disputed"}
        ]
        if invalid:
            invalid_ids = {row["rule_id"] for row in invalid}
            repair_prior = [row for row in assigned if row.get("source_rule_id") in invalid_ids]
            corrected, corrected_raw = await request_part(comparison, [row["rule_id"] for row in invalid], repair_prior, invalid)
            _hold_out_of_scope_findings(corrected, [lesson['id'] for lesson in course['lessons']])
            previous_cards = {row['rule_id']: row for row in invalid}
            semantic_changes = {row['rule_id'] for row in corrected['source_rule_checks']
                if (row['status'], row['severity']) != (
                    previous_cards[row['rule_id']]['status'], previous_cards[row['rule_id']]['severity'])}
            for card in corrected['source_rule_checks']:
                if card['rule_id'] in semantic_changes:
                    card['verified'] = False
                    card['verification_errors'].append('proof_semantic_change_requires_adjudication')
            replacement = {row["rule_id"]: row for row in corrected["source_rule_checks"]}
            result["source_rule_checks"] = [
                replacement.get(row["rule_id"], row) for row in result["source_rule_checks"]
            ]
            # Supersede only the invalid technical cards, never another finding.
            findings = {
                row["issue_id"]: row
                for row in result["review"]["findings"]
                if not (row.get("source_rule_id") in invalid_ids - semantic_changes and row.get("rule_check_unverified"))
            }
            for finding in corrected['review']['findings']:
                if finding.get('source_rule_id') in semantic_changes:
                    continue  # Keep the original allegation until semantic review.
                if not finding.get('source_rule_id'):
                    finding['rule_check_unverified'] = True
                    finding.setdefault('out_of_scope_review', 'EVIDENCE_ONLY_CORRECTION')
                findings[finding['issue_id']] = finding
            result["review"]["findings"] = list(findings.values())
            resolutions_by_id = {row["issue_id"]: row for row in result["resolutions"]}
            repair_findings = {row['issue_id']: row for row in repair_prior}
            rejected_semantic_changes = []
            for resolution in corrected['resolutions']:
                old = resolutions_by_id[resolution['issue_id']]
                if (not same_proof_disposition(old['disposition'], resolution['disposition'])
                        or old['disposition'] == 'SOURCE_AMBIGUITY'
                        and resolution['source_question'] != old['source_question']
                        or repair_findings[resolution['issue_id']].get('source_rule_id') in semantic_changes):
                    rejected_semantic_changes.append(resolution['issue_id'])
                    continue  # Literal repair cannot add a semantic confirmation or closure.
                resolutions_by_id[resolution['issue_id']] = {**resolution, 'disposition': old['disposition']}
            result["resolutions"] = list(resolutions_by_id.values())
            receipt['unverified_resolution_changes'] = rejected_semantic_changes
            result["review"]["source_notes"].extend(corrected["review"]["source_notes"])
            for lesson, refs in corrected["review"]["narrative_sources"].items():
                result["review"]["narrative_sources"][lesson] = list(
                    dict.fromkeys([*result["review"]["narrative_sources"].get(lesson, []), *refs])
                )
            receipt["evidence_correction"] = corrected_raw
            # One addressed correction of a completed bad proof. No blind retry.
        results.append(result)
        raw_parts.append(receipt)
    checks = [row for result in results for row in result["source_rule_checks"]]
    expected = [key for part in parts for key in part]
    if len(checks) != len(expected) or {c["rule_id"] for c in checks} != set(expected):
        raise ValueError("editorial_rule_review_incomplete")
    resolutions = [row for result in results for row in result["resolutions"]]
    prior_ids = {row["issue_id"] for row in prior or []}
    if len(resolutions) != len(prior_ids) or {row["issue_id"] for row in resolutions} != prior_ids:
        raise ValueError("editorial_rule_resolutions_incomplete")
    findings = {row["issue_id"]: row for result in results for row in result["review"]["findings"]}
    notes = {_digest(row): row for result in results for row in result["review"]["source_notes"]}
    narrative: dict[str, list[str]] = {}
    for result in results:
        for lesson, refs in result["review"]["narrative_sources"].items():
            narrative[lesson] = list(dict.fromkeys([*narrative.get(lesson, []), *refs]))
    qa_content = context + '\nFULL_COURSE_WITH_KEYS_AND_EXPLANATIONS_JSON\n' + json.dumps(
        view.encode(course), ensure_ascii=False, sort_keys=True)
    if assessment_prior:
        qa_content += '\nPRIOR_MATERIAL_FINDINGS_JSON\n' + json.dumps(
            view.encode(_current_prior_targets(assessment_prior, course, prose_only=False)), ensure_ascii=False)
        qa_format = editorial_verification_format(packet, course, assessment_prior)
    else:
        qa_format = editorial_review_format(packet, course)

    def compile_assessment(value: Any) -> Any:
        if assessment_prior:
            return compile_editorial_verification(value, packet, course, assessment_prior)
        return {'review': compile_editorial_review(value, packet, course), 'resolutions': []}

    qa_group = ('practical:editorial:verify:v33:assessment:' if assessment_prior
        else 'practical:editorial:review:v33:assessment:') + _digest([course, assessment_prior, assessment_system])
    qa_raw = await call('review', qa_group,
        [{'role': 'system', 'content': assessment_system + (verification_guide + CURRENT_TARGET_GUIDE if assessment_prior else '')},
         {'role': 'user', 'content': qa_content}], qa_format, compile_assessment)
    qa_result = compile_assessment(qa_raw)
    for finding in qa_result['review']['findings']:
        if finding['domain'] == 'content':
            finding['review_origin'] = 'COURSE_FIDELITY'
    findings.update({row['issue_id']: row for row in qa_result['review']['findings']})
    notes.update({_digest(row): row for row in qa_result['review']['source_notes']})
    resolutions.extend(qa_result['resolutions'])
    expected_prior = {row['issue_id'] for row in all_prior or []}
    if len(resolutions) != len(expected_prior) or {row['issue_id'] for row in resolutions} != expected_prior:
        raise ValueError('editorial_candidate_resolutions_incomplete')
    raw_parts.append({'review_kind': 'assessment', 'response': qa_raw})
    # Assessment source proposals never certify teaching coverage.
    compiled = {
        'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
            'summary': '\n'.join([*(result['review']['summary'] for result in results), qa_result['review']['summary']]),
            'findings': list(findings.values()), 'source_notes': list(notes.values()), 'narrative_sources': narrative},
        'source_rule_checks': checks, 'resolutions': resolutions, 'raw_parts': raw_parts,
    }
    if all_prior is not None:
        return await correct_resolution_proofs(packet, course, all_prior, compiled, context, view, call)
    return compiled
