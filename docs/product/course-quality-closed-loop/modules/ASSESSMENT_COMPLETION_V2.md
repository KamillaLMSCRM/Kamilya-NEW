# Assessment completion and coverage

Status: Accepted
Version: V2
Supersedes: `ASSESSMENT_COMPLETION_V1.md`
Reason: the accepted policy is implemented inside the sole Evidence V2 semantic
assessment module; the separate legacy assessment/audit/completion generator and
its tests were retired.
Approved by: Product owner (`делай` and instruction to replace stale rules),
2026-09-25; integrated and reviewed by root.

## Responsibility

`evidence_engine.semantic_assessment.generate_block_assessment(...)` turns
source-owned assessment axes plus model-authored distractors into a bounded
`BlockAssessmentResult`. It owns deterministic validation, blind all-option
review, constraint review, bounded deterministic/model repair, course-level
deduplication, omission classification and coverage diagnostics.

## Non-responsibilities

It does not select providers, persist courses, publish content, change source
facts, use generated lesson prose as evidence, call TypeSafe at runtime or fill
a desired question quota.

## External interface

```python
generate_block_assessment(
    lessons: list[LessonDraft],
    facts_by_id: dict[str, SourceFact],
    client: GenerationClient,
    *,
    on_progress=None,
    checkpoint=None,
) -> BlockAssessmentResult
```

The result contains retained `QuestionDraft` values, sanitized `audit`
diagnostics and provider-attempt count. Callers and tests use this same seam.

## Invariants

- The server owns the axis, correct answer, evidence IDs and source locator.
- Every retained option answers the same question and exactly one is correct.
- Generated lesson prose is not evidence.
- Deterministic repair precedes a bounded model repair where possible.
- Irreparable candidates are omitted without quota padding.
- At most three assessable axes are selected per lesson; this is a ceiling, not
  a target.
- Every derived axis is classified as retained, omitted, unassessable or
  uncovered with a reason when applicable.
- `review_required` is emitted for incomplete contract/source-topic coverage;
  warnings do not become silent success.
- Provider/contract failure remains distinguishable from semantic rejection.

## Data and side effects

The module is stateless. It reads immutable lesson/fact values and invokes only
the injected generation-client interface. It owns no database row, tenant state,
provider routing, credentials or billing. The application seam owns persistence.

## Observability

The audit includes block and axis outcomes, attempt counters, retained/omitted/
unassessable/uncovered counts, per-lesson question counts, topic coverage,
contract coverage and terminal status. `analyze_evidence_v2_replay.py` aggregates
these fields from local artifacts without external calls or writes.

## Verification

| Level | Current evidence |
|---|---|
| Axis/materialization policy | `test_assessment_axes.py` |
| Authorship/review/repair/coverage seam | `test_semantic_block_assessment.py` |
| V2 generation/application | `test_evidence_course_engine_v2.py`, `test_evidence_course_application.py` |
| Replay diagnostics | `test_evidence_v2_replay_diagnostics.py` |
| Sole-engine/legacy retirement | `test_evidence_v2_retirement_contract.py` |
| End-to-end release boundary | `docs/critical-journeys/ai-course-generation.json` |

## Negative space and rollback

No schema, API, queue, provider, frontend, RLS or tenant-data behavior changes.
Rollback is the exact source revision; no data transformation is required.
