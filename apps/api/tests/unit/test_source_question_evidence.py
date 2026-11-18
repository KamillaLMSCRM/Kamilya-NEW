"""Literal evidence occurrences do not choose an implicit source edit."""
import pytest

from app.modules.source_editorial_review.question_context import QuestionContextError, contexts

SOURCE = '| Item | Text |\n| --- | --- |\n| A | Two doors. Two doors. |\n| B | Two doors. |\n'


def test_repeated_quote_preserves_every_occurrence_and_product_identity():
    context, = contexts(SOURCE, [(0, SOURCE)])
    first, second = context.references
    evidence = context.evidence('Two doors.', [first, second])
    assert len(evidence) == 3
    assert [e['source_ref'] for e in evidence] == [first, first, second]
    assert [e['source_label'] for e in evidence] == ['A', 'A', 'B']
    assert all(SOURCE[e['start']:e['end']] == e['quote'] == 'Two doors.' for e in evidence)
    assert len({e['start'] for e in evidence}) == 3
    with pytest.raises(QuestionContextError):
        context.bind('Two doors.', [first, second])  # Legacy edit API stays unique.


@pytest.mark.parametrize('quote,refs', [('Invented value.', ['S2']), ('Two doors.', ['foreign']),
                                        ('Two doors.', ['S2', 'S2'])])
def test_invalid_or_foreign_evidence_is_not_an_owner_question(quote, refs):
    context, = contexts(SOURCE, [(0, SOURCE)])
    with pytest.raises(QuestionContextError):
        context.evidence(quote, refs)


def scoped_state():
    from app.modules.source_editorial_review.domain import ReviewState
    context, = contexts(SOURCE, [(0, SOURCE)])
    ref = next(iter(context.references))
    unit = context.references[ref]
    question = {'id': 'q', 'start': None, 'end': None, 'quote': 'Two doors.', 'reason': 'Two or three?',
                'source_evidence': context.evidence('Two doors.', [ref]),
                'source_scopes': [{'source_ref': ref, 'start': unit.start, 'end': unit.end, 'text': unit.text}]}
    state = ReviewState()
    state.apply(1, 'analyzed', {'original': SOURCE, 'issues': [question], 'automatic': []})
    return state, ref


def command(ref, **changes):
    from uuid import uuid4

    from app.modules.source_editorial_review.domain import ReviewCommand
    change = {'source_ref': ref, 'quote': 'Two doors.', 'replacement': 'Three doors.', **changes}
    return ReviewCommand(expected_revision=1, request_id=uuid4(), action='resolve', item_id='q',
                         decision='replace', reason='Confirmed synthetic product.', source_changes=[change])


def test_explicit_all_occurrences_edits_only_the_owned_row_and_undoes_as_one_decision():
    from uuid import uuid4

    from app.modules.source_editorial_review.domain import ReviewCommand
    state, ref = scoped_state()
    kind, payload = state.plan(command(ref, all_occurrences=True))
    assert len(payload['source_changes']) == 2
    state.apply(2, kind, payload)
    assert state.working()[0] == SOURCE.replace('| A | Two doors. Two doors. |', '| A | Three doors. Three doors. |')
    from app.modules.source_editorial_review.domain import ApprovedEditorialDocument
    working, spans = state.working()
    approved = ApprovedEditorialDocument(document_id='synthetic', source_revision='original', approval_id='approval',
        recognized_text=SOURCE, working_text=working, working_sha256=__import__('hashlib').sha256(working.encode()).hexdigest(),
        spans=tuple(spans), fidelity={}, decision_context=state.decision_context())
    assert approved.valid(document_id='synthetic', source_revision='original')
    assert len(approved.decision_context) == 2
    assert len({entry['item_id'] for entry in approved.decision_context}) == 2
    kind, payload = state.plan(ReviewCommand(expected_revision=2, request_id=uuid4(), action='reopen_issue',
                                            item_id='q', reason='Undo the synthetic decision.'))
    state.apply(3, kind, payload)
    assert state.working()[0] == SOURCE and not state.decisions


def test_legacy_request_digest_remains_identical_when_scoped_changes_are_absent():
    from uuid import uuid4

    from app.modules.source_editorial_review.domain import ReviewCommand, text_hash
    from app.modules.source_editorial_review.service import _command_digest
    command = ReviewCommand(expected_revision=1, request_id=uuid4(), action='resolve', item_id='legacy',
                            decision='keep', reason='Original owner decision.')
    old_digest = text_hash(command.model_dump_json(exclude={'pages', 'selected_part_ids', 'preparation_sha256',
        'acknowledge_outcome_and_cost_unknown', 'source_changes'}))
    assert _command_digest(command) == old_digest


def test_overlapping_batch_is_atomic_and_stale_scope_is_rejected():
    from uuid import uuid4

    from app.modules.source_editorial_review.domain import ReviewCommand, ReviewConflictError
    state, ref = scoped_state()
    change = {'source_ref': ref, 'quote': 'Two doors.', 'replacement': 'Three doors.', 'all_occurrences': True}
    duplicate = ReviewCommand(expected_revision=1, request_id=uuid4(), action='resolve', item_id='q', decision='replace',
        reason='Synthetic confirmation.', source_changes=[change, change])
    with pytest.raises(ReviewConflictError):
        state.plan(duplicate)
    assert state.working()[0] == SOURCE and state.revision == 1
    state.issues['q']['source_scopes'][0]['text'] += 'stale'
    with pytest.raises(ReviewConflictError):
        state.plan(command(ref, all_occurrences=True))


@pytest.mark.parametrize('foreign', [False, True])
def test_scoped_edit_never_selects_first_occurrence_or_borrows_another_product(foreign):
    from app.modules.source_editorial_review.domain import ReviewConflictError
    state, ref = scoped_state()
    with pytest.raises(ReviewConflictError):
        state.plan(command('S3' if foreign else ref))
    assert state.working()[0] == SOURCE and not state.decisions
