"""Regression cases for source ambiguity and addressed proof custody."""

import copy
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_rule_editorial_cycle import review_source_rules
from tests.unit.test_v3_autonomous_editorial_cycle import predicate_value, rule_wire, source_wire
from tests.unit.test_v3_editorial_contract import review_value, revision_value
from tests.unit.test_v3_rule_editorial_contract import case as rule_case
from tests.unit.test_v3_rule_editorial_contract import response

pytest_plugins = ("tests.unit.test_v3_practical_cycle",)


@pytest.mark.asyncio
async def test_nonmaterial_source_rule_ambiguity_does_not_block_clean_course(case):
    corpus, packet, course = case
    view = PracticalModelView(packet)

    async def stage(name, group, messages, fmt, validate):
        wire = source_wire(packet, view, fmt, messages)
        if wire is not None:
            value = view.decode(wire)
            if ":source-semantics:verify:" in group:
                value["rule_checks"][0].update(
                    status="SOURCE_AMBIGUITY", source_question="Which interpretation applies?"
                )
        elif name == "lesson":
            value = course
        elif "option-predicates" in group:
            value = predicate_value(packet, course, fmt=fmt)
        elif ":revision:" in group:
            raise AssertionError("Source uncertainty is not a lesson edit")
        else:
            value = review_value(packet, course)
            value["findings"] = []
            value = rule_wire(value, fmt, course)
            if "source_rule_checks" in value:
                value["source_rule_checks"][0].update(status="NOT_APPLICABLE", lesson_quotes=[])
            if ":verify:" in group:
                pending = json.loads(messages[1]["content"].split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1])
                value["resolutions"] = [
                    {
                        "issue_id": row["issue_id"],
                        "disposition": "NOT_MATERIAL",
                        "reason": "Teaching does not require resolving this detail.",
                        "source_refs": [packet.blocks[0].block_id],
                        "source_quote": packet.blocks[0].text,
                        "course_quote": "",
                        "source_question": "",
                    }
                    for row in pending
                ]
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert result.decision.accepted
    assert not result.decision.source_uncertain
    assert result.history[0]["confirmed_source_questions"] == []


@pytest.mark.asyncio
async def test_proof_repair_does_not_replace_unrelated_unresolved_resolution():
    packet, course, reading = rule_case()
    view = PracticalModelView(packet)
    prior_review = compile_editorial_review(review_value(packet, course), packet, course)
    generic = prior_review["findings"][0]
    calls = []

    async def call(name, group, messages, fmt, validate):
        text = messages[1]["content"]
        is_repair = "PRIOR_RULE_CHECKS_UNVERIFIED_JSON" in text
        assigned = view.decode(json.loads(text.split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1]))
        calls.append((is_repair, [x["issue_id"] for x in assigned]))
        value = response(packet, course, reading)
        ids = fmt["json_schema"]["schema"]["properties"]["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
        value["source_rule_checks"] = [row for row in value["source_rule_checks"] if row["rule_id"] in ids]
        if not is_repair:
            value["source_rule_checks"][0]["lesson_quotes"][0]["quote"] = "not present in teaching"
        value["resolutions"] = [
            {
                "issue_id": row["issue_id"],
                "disposition": "FIXED" if is_repair else "UNRESOLVED",
                "reason": "Current question evidence.",
                "source_refs": [packet.blocks[0].block_id],
                "source_quote": "credit for personal use",
                "course_quote": course["lessons"][0]["questions"][0]["prompt"] if is_repair else "",
                "source_question": "",
            }
            for row in assigned
        ]
        validate(value)
        return value

    result = await review_source_rules(
        packet, reading, course, "Full source", view, call, "Review", max_rules=40, prior=[generic]
    )
    assert len(calls) == 2
    assert generic["issue_id"] not in calls[1][1]
    row = next(row for row in result["resolutions"] if row["issue_id"] == generic["issue_id"])
    assert row["disposition"] == "UNRESOLVED" and not row["verified"]


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["SOURCE_AMBIGUITY", "NOT_MATERIAL"])
async def test_invalid_source_quote_requires_confirmation_to_promote_but_not_to_dismiss(case, disposition):
    corpus, packet, course = case
    view = PracticalModelView(packet)
    verify_calls = 0

    async def stage(name, group, messages, fmt, validate):
        nonlocal verify_calls
        wire = source_wire(packet, view, fmt, messages)
        if wire is not None:
            value = view.decode(wire)
            if ":source-semantics:read:" in group:
                value["uncertainties"] = [
                    {
                        "source_refs": [packet.blocks[0].block_id],
                        "source_quote": "not in source",
                        "question": "Which source condition applies?",
                    }
                ]
        elif name == "lesson":
            value = course
        elif "option-predicates" in group:
            value = predicate_value(packet, course, fmt=fmt)
        elif ":revision:" in group:
            raise AssertionError("Invalid source evidence is not a lesson edit")
        else:
            value = review_value(packet, course)
            value["findings"] = []
            value = rule_wire(value, fmt, course)
            if ":verify:" in group:
                verify_calls += 1
                pending = json.loads(messages[1]["content"].split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1])
                value["resolutions"] = [
                    {
                        "issue_id": row["issue_id"],
                        "disposition": disposition if verify_calls == 1 else "UNRESOLVED",
                        "reason": "Recheck this source assertion.",
                        "source_refs": [packet.blocks[0].block_id],
                        "source_quote": packet.blocks[0].text,
                        "course_quote": "",
                        "source_question": "Which source condition applies?"
                        if verify_calls == 1 and disposition == "SOURCE_AMBIGUITY"
                        else "",
                    }
                    for row in pending
                ]
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert verify_calls == (2 if disposition == "SOURCE_AMBIGUITY" else 1)
    assert result.decision.accepted is (disposition == "NOT_MATERIAL")
    assert not result.decision.source_uncertain
    assert result.history[0]["confirmed_source_questions"] == []
    assert result.history[0]["initial_source_proposals"][0]["basis"] == "not in source"


@pytest.mark.asyncio
async def test_new_noneditable_findings_do_not_cause_unbounded_unchanged_course_loop(case, monkeypatch):
    """A new hold is retained, but it is not editable progress on unchanged content."""
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle

    corpus, packet, course = case
    view = PracticalModelView(packet)
    verification_calls = 0

    def source_issue(index):
        return {
            "issue_id": f"source-hold-{index}",
            "domain": "source",
            "severity": "material",
            "target": {"kind": "source", "id": packet.blocks[0].block_id},
            "problem": f"Unresolved source observation {index}",
            "basis": "Source details remain uncertain.",
            "correction": "Review source.",
            "source_refs": [packet.blocks[0].block_id],
        }

    async def review(_packet, _reading, current, _context, _view, _call, _system, **kwargs):
        nonlocal verification_calls
        previous = kwargs.get("prior")
        if previous is None:
            findings = [source_issue(0)]
            resolutions = []
        else:
            verification_calls += 1
            if verification_calls >= 3:
                raise AssertionError("bounded stub detected repeated unchanged-course verification")
            findings = [source_issue(verification_calls)]
            resolutions = [
                {
                    "issue_id": row["issue_id"],
                    "disposition": "UNRESOLVED",
                    "reason": "Still unresolved",
                    "source_refs": [packet.blocks[0].block_id],
                    "source_quote": packet.blocks[0].text,
                    "course_quote": "",
                    "source_question": "",
                    "verified": False,
                    "verification_errors": ["unresolved"],
                }
                for row in previous
            ]
        return {
            "review": {
                "source_fingerprint": packet.fingerprint,
                "course_fingerprint": cycle._digest(current),
                "summary": "Review",
                "findings": findings,
                "source_notes": [],
                "narrative_sources": {lesson["id"]: [packet.blocks[0].block_id] for lesson in current["lessons"]},
            },
            "source_rule_checks": [],
            "resolutions": resolutions,
            "raw_parts": [],
        }

    monkeypatch.setattr(cycle, "review_editorial_candidate", review)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == "lesson":
            value = course
        elif "option-predicates" in group:
            value = predicate_value(packet, course, fmt=fmt)
        else:
            raise AssertionError("Noneditable source holds must not invoke a course writer")
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert verification_calls == 1
    assert result.stop_reason == "autonomous_edit_no_progress"
    assert {row["issue_id"] for row in result.decision.feedback} == {"source-hold-0", "source-hold-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize('confirmed', [True, False])
async def test_confirmed_evidence_only_finding_becomes_editable_only_after_full_review(case, monkeypatch, confirmed):
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle

    corpus, packet, original = case
    view = PracticalModelView(packet)
    candidate = copy.deepcopy(original)
    finding = compile_editorial_review(review_value(packet, original, kind='lesson', target='l1', domain='content'), packet, original)['findings'][0]
    finding.update(rule_check_unverified=True, out_of_scope_review='EVIDENCE_ONLY_CORRECTION')
    sibling = {**copy.deepcopy(finding), 'issue_id': 'source-sibling', 'domain': 'source',
               'target': {'kind': 'source', 'id': packet.blocks[0].block_id}}
    seen = []

    async def review(_packet, _reading, current, _context, _view, _call, _system, **kwargs):
        prior = kwargs.get('prior')
        seen.append(('review', None if prior is None else [row['issue_id'] for row in prior]))
        resolutions = [] if prior is None else [
            {'issue_id': row['issue_id'], 'disposition': ('NOT_MATERIAL' if row['issue_id'] == sibling['issue_id']
                else 'NEEDS_REVISION' if current == original else 'FIXED'),
             'verified': row['issue_id'] == sibling['issue_id'] or confirmed,
             'verification_errors': [] if row['issue_id'] == sibling['issue_id'] or confirmed else ['source_quote_invalid'],
             'reason': 'Full independent review',
             'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
             'course_quote': current['lessons'][0]['content'] if current != original and row['issue_id'] != sibling['issue_id'] else '',
             'source_question': ''} for row in prior]
        return {'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': cycle._digest(current),
            'summary': 'Review', 'findings': [finding, sibling] if prior is None else [], 'source_notes': [],
            'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in current['lessons']}},
            'source_rule_checks': [], 'resolutions': resolutions, 'raw_parts': []}

    monkeypatch.setattr(cycle, 'review_editorial_candidate', review)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == 'lesson':
            value = original
        elif 'option-predicates' in group:
            value = predicate_value(packet, candidate, fmt=fmt)
        elif ':revision:' in group:
            assert seen[-1][0] == 'review' and seen[-1][1] is not None
            assert finding['issue_id'] in messages[1]['content']
            assert sibling['issue_id'] not in messages[1]['content']
            seen.append(('writer', finding['issue_id']))
            candidate['lessons'][0]['content'] += '\nThe required action is recorded.'
            value = revision_value(packet, original, candidate)
        else:
            raise AssertionError(group)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    if not confirmed:
        assert [event[0] for event in seen] == ['review', 'review']
        assert not result.decision.accepted and not result.decision.source_uncertain
        assert any(row['issue_id'] == finding['issue_id'] for row in result.decision.feedback)
        return
    assert [event[0] for event in seen] == ['review', 'review', 'writer', 'review']
    assert result.decision.accepted and not result.decision.source_uncertain
    assert result.course['lessons'][0]['questions'] == original['lessons'][0]['questions']
    assert {row['issue_id'] for row in result.history[0]['all_material_findings']} == {finding['issue_id'], sibling['issue_id']}

@pytest.mark.asyncio
async def test_option_uncertainty_alone_remains_noneditable(case, monkeypatch):
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle

    corpus, packet, course = case
    view = PracticalModelView(packet)
    verifications = []

    async def review(packet, reading, current, context, view, call, system, *, prior=None, **kwargs):
        verifications.append(prior)
        return {'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': cycle._digest(current),
            'summary': 'Review', 'findings': [], 'source_notes': [],
            'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in current['lessons']}},
            'source_rule_checks': [], 'raw_parts': [], 'resolutions': [
                {'issue_id': row['issue_id'], 'disposition': 'UNRESOLVED', 'reason': 'Still uncertain',
                 'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                 'course_quote': '', 'source_question': '', 'verified': False,
                 'verification_errors': ['unresolved']} for row in (prior or [])]}

    monkeypatch.setattr(cycle, 'review_editorial_candidate', review)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == 'lesson':
            value = course
        elif 'option-predicates' in group:
            value = predicate_value(packet, course, fmt=fmt)
            question = course['lessons'][0]['questions'][0]
            undecided = (question['correct_index'] + 1) % len(question['choices'])
            value['judgments'][undecided].update(status='UNDECIDABLE', compatible_case='')
        else:
            raise AssertionError('Uncertainty alone must not invoke a writer')
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert not result.decision.accepted
    assert result.course == course
    assert result.history[0]['revisions_used'] == 0
    assert result.decision.feedback
    assert any(row.get('rule_check_unverified') for row in verifications[-1])

@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['NEEDS_REVISION', 'NOT_MATERIAL'])
async def test_blind_predicate_needs_independent_verification_before_edit(case, monkeypatch, outcome):
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle

    corpus, packet, original = case
    candidate = copy.deepcopy(original)
    view = PracticalModelView(packet)
    events = []
    issue_ids = []

    async def review(packet, reading, current, context, view, call, system, *, prior=None, **kwargs):
        if prior is not None:
            events.append('verify')
            assert len(prior) == 1
            issue_ids.append(prior[0]['issue_id'])
            disposition = outcome if current == original else 'FIXED'
        else:
            disposition = ''
        return {'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': cycle._digest(current),
            'summary': 'Independent review', 'findings': [], 'source_notes': [],
            'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in current['lessons']}},
            'source_rule_checks': [], 'raw_parts': [], 'resolutions': [
                {'issue_id': row['issue_id'], 'disposition': disposition, 'reason': 'Independent assessment',
                 'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                 'course_quote': current['lessons'][0]['questions'][0]['prompt'] if disposition == 'FIXED' else '',
                 'source_question': '', 'verified': True, 'verification_errors': []} for row in (prior or [])]}

    monkeypatch.setattr(cycle, 'review_editorial_candidate', review)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == 'lesson':
            value = original
        elif 'option-predicates' in group:
            value = predicate_value(packet, candidate, fmt=fmt, wrong_question='q1' if candidate == original else None)
        elif ':revision:' in group:
            assert outcome == 'NEEDS_REVISION' and events == ['verify']
            assert issue_ids[0] in messages[1]['content']
            events.append('writer')
            candidate['lessons'][0]['questions'][0]['prompt'] = 'Which two actions complete approval?'
            value = revision_value(packet, original, candidate)
        else:
            raise AssertionError(group)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert result.decision.accepted
    if outcome == 'NEEDS_REVISION':
        assert events == ['verify', 'writer', 'verify'] and issue_ids[0] == issue_ids[1]
        assert result.course == candidate and candidate != original
    else:
        assert events == ['verify'] and result.course == original
        assert result.history[0]['revisions_used'] == 0

@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['prose', 'question', 'key'])
async def test_two_lesson_predicate_cache_rechecks_only_changed_bank(case, monkeypatch, change):
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle
    from app.modules.ai.v3.practical_option_predicates import _inventory

    corpus, packet, original = case
    original = copy.deepcopy(original)
    second = copy.deepcopy(original['lessons'][0])
    second['id'] = 'l2'
    for index, q in enumerate(second['questions']):
        q['id'] = f'other-{index}'
    original['lessons'].append(second)
    candidate = copy.deepcopy(original)
    view = PracticalModelView(packet)
    finding = compile_editorial_review(
        review_value(packet, original, kind='lesson', target='l1', domain='content'), packet, original
    )['findings'][0]
    bank_calls = []
    edits = []

    async def review(packet, reading, current, context, view, call, system, *, prior=None, **kwargs):
        resolutions = []
        for row in prior or []:
            wrong_key = row['target']['kind'] == 'question' and current['lessons'][0]['questions'][0]['correct_index'] != 0
            resolutions.append({'issue_id': row['issue_id'], 'disposition': 'NEEDS_REVISION' if wrong_key else 'FIXED',
                'reason': 'Independent current review', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text, 'course_quote': current['lessons'][0]['content'] if row['target']['kind'] == 'lesson'
                    else current['lessons'][0]['questions'][0]['prompt'],
                'source_question': '', 'verified': True, 'verification_errors': []})
        return {'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': cycle._digest(current),
            'summary': 'Review', 'findings': [finding] if prior is None else [], 'source_notes': [],
            'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in current['lessons']}},
            'source_rule_checks': [], 'raw_parts': [], 'resolutions': resolutions}

    monkeypatch.setattr(cycle, 'review_editorial_candidate', review)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == 'lesson':
            value = original
        elif 'option-predicates' in group:
            expected = fmt['json_schema']['schema']['properties']['bank_fingerprint']['enum'][0]
            owner = next(lesson['id'] for lesson in candidate['lessons']
                if _inventory(packet, {**candidate, 'lessons': [lesson]})[0] == expected)
            bank_calls.append(owner)
            # The independent answer remains option zero even after a key-only edit.
            answer_course = copy.deepcopy(candidate)
            answer_course['lessons'][0]['questions'][0]['correct_index'] = 0
            value = predicate_value(packet, answer_course, fmt=fmt)
        elif ':revision:' in group:
            before = copy.deepcopy(candidate)
            edits.append(group)
            if len(edits) == 1:
                candidate['lessons'][0]['content'] += '\nThe required procedure is complete.'
                if change == 'question':
                    candidate['lessons'][0]['questions'][0]['prompt'] += ' Please identify it.'
                elif change == 'key':
                    candidate['lessons'][0]['questions'][0]['correct_index'] = 1
            else:
                assert change == 'key'
                candidate['lessons'][0]['questions'][0]['correct_index'] = 0
            value = revision_value(packet, before, candidate)
        else:
            raise AssertionError(group)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert result.decision.accepted
    assert bank_calls == (['l1', 'l2', 'l1'] if change == 'question' else ['l1', 'l2'])
    assert len(edits) == (2 if change == 'key' else 1)
    assert result.course['lessons'][1] == original['lessons'][1]

@pytest.mark.asyncio
async def test_unverified_current_resolution_revokes_prior_edit_authority(case, monkeypatch):
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle

    corpus, packet, original = case
    candidate = copy.deepcopy(original)
    view = PracticalModelView(packet)
    events = []
    issue_ids = []

    async def review(packet, reading, current, context, view, call, system, *, prior=None, **kwargs):
        if prior is not None:
            events.append('verify')
            assert len(prior) == 1
            issue_ids.append(prior[0]['issue_id'])
        after_edit = current != original
        return {'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': cycle._digest(current),
            'summary': 'Review', 'findings': [], 'source_notes': [],
            'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in current['lessons']}},
            'source_rule_checks': [], 'raw_parts': [], 'resolutions': [
                {'issue_id': row['issue_id'], 'disposition': 'UNRESOLVED' if after_edit else 'NEEDS_REVISION',
                 'reason': 'Current evidence needs review' if after_edit else 'Confirmed before edit',
                 'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                 'course_quote': '', 'source_question': '', 'verified': not after_edit,
                 'verification_errors': ['course_quote_invalid'] if after_edit else []} for row in (prior or [])]}

    monkeypatch.setattr(cycle, 'review_editorial_candidate', review)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == 'lesson':
            value = original
        elif 'option-predicates' in group:
            value = predicate_value(packet, candidate, fmt=fmt, wrong_question='q1' if candidate == original else None)
        elif ':revision:' in group:
            assert events == ['verify'], 'Unverified latest resolution must not authorize another writer'
            events.append('writer')
            before = copy.deepcopy(candidate)
            candidate['lessons'][0]['questions'][0]['prompt'] = 'Revised question requiring current verification?'
            value = revision_value(packet, before, candidate)
        else:
            raise AssertionError(group)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert events[:3] == ['verify', 'writer', 'verify']
    assert events.count('writer') == 1 and all(event == 'verify' for event in events[3:])
    assert issue_ids[0] == issue_ids[1]
    assert not result.decision.accepted and not result.decision.source_uncertain
    assert result.decision.feedback
    assert result.course == candidate and result.course != original
