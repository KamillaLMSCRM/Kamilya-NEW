# ASSESSMENT-CONTRACT-V1

Status: Accepted for implementation 2026-09-19

## Producer

`AXIS-CONTRACT-V1` produces an ordered set of immutable contracts. Each contract has:

- stable `contract_id` and `lesson_id`;
- coherent source-block identity;
- exact evidence fact IDs/quote references;
- assessed axis/kind;
- one server-owned correct answer preserving conditions and negation;
- question intent/prompt constraints;
- eligible misconception/distractor constraints;
- bounded unassessable reason instead of a fabricated contract.

## Consumer

`ASSESSMENT-COMPLETION-V1` may ask an injected model adapter only for candidate
distractors or an identity-preserving repair. It must reject any response that changes
the contract identity, evidence, axis or keyed answer.

## Result

The consumer returns one `AssessmentOutcome`:

```text
retained_questions
omitted_contracts(reason)
coverage(covered, uncovered, unassessable)
attempt_counts(authored, deterministic_repair, model_repair, replacement)
status(completed | completed_with_warnings | review_required)
safe_diagnostics
```

Malformed/provider failures do not masquerade as omissions or successful outcomes.

## Compatibility

V1 permits additive diagnostic/reason fields. Contract identity, evidence, axis, keyed
answer, attempt ceilings and status meanings are invariant. A change to those fields
requires V2 or an accepted impact addendum and executable producer-consumer tests.
