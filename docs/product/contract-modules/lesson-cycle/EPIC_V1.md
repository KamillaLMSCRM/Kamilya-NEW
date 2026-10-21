# Lesson-owned assessment cycle V1

Status: Accepted for bounded DEV comparison, not default rollout
Approved by: product owner, explicit chat instruction2026-10-21
Root/module owner/reviewer: root Codex; product owner: workspace owner.
Change control: root may refine internals within this contract; shared-default,
schema, provider/billing or production changes need separate owner authority.

## Outcome and exclusions

Prepare a lesson-owned question set, independently review options against the
finished lesson and supplied source context, save its terminal result before
starting the next lesson, and resume without paying again for saved results.
Compare with the existing lesson regeneration interface on identical owned QA
lesson snapshots. Production and the default generator remain unchanged.

## Module mini-spec

- Identity/version: `ai.lesson_cycle`, V1, experimental callable module.
- Responsibility: lesson -> question set -> blind review -> bounded repair ->
  checkpoint, including coverage and telemetry at the caller-visible interface.
- Non-responsibilities: OCR, original-source recovery, authentication, provider
  routing, publication, learner grading, or replacing current generation defaults.
- Interface: `run_lesson_cycles(packets, client, store)`; dependencies supplied.
- Inputs: exact tenant/lesson/source identity, finished text, original contextual
  excerpts, required operational learning targets and model-policy revision.
- Outputs: immutable reviewed questions or explicit review-required result,
  missing targets, bounded failure codes, logical invocation count and timing.
- Data owner: cycle owns its result; caller-owned checkpoint adapter owns durable
  writes under the same tenant. Existing course/quiz APIs remain their owners.
- States: absent -> authoring -> reviewing -> optional one repair/re-review ->
  ready_for_methodologist or review_required -> saved; next lesson only after save.
- Invariants: model-authored keys are not trusted. Blind option classification
  must yield exactly one supported answer, all other answers contradicted under
  the question's conditions, evidence quotes present in supplied source, and the
  answer taught in the finished lesson. Unknown/ambiguous alternatives fail closed.
  All required targets must be covered by admitted questions for ready status.
  Administrative trivia is excluded by operational targets, not question quotas.
- Checkpoint identity: complete packet, source/lesson content and policy version;
  reject tenant/identity mismatch. Resume validates the saved terminal snapshot.
- Errors: provider/parse failure yields review_required, no silent empty success;
  checkpoint failure propagates and prevents advancement. Cancellation propagates.
- Security/privacy: sources are untrusted data; no credentials in prompts/logs;
  only exact DEV QA fixtures; original customer records never mutated.
- Performance: one author and one blind-review pass normally; at most one targeted
  repair plus re-review. Provider transport retries measured separately, not hidden
  by logical call counters. No new resource/model/tier or rate-limit changes.
- Read scope: AI evidence engine/client, captured source-owned QA lesson snapshots,
  existing lesson/course/quiz interfaces and generation checkpoint repository.
- Write scope: new cycle module/tests, bounded DEV comparison adapter, sanitized
  result ledger and this contract. QA copies/checkpoints only, never publication.
- Impact map: current assessment/pipeline unchanged; LLM client consumed without
  modifying global configuration; existing checkpoint/API interfaces consumed.
- Verification: deterministic public-interface tests for blind key ownership,
  invalid/unknown options, source/lesson evidence, missing targets, repair cap,
  durable ordering and restart; real paired DEV benchmark with exact inputs,
  transport/model counters and manual original-based quality review.
- Stop conditions: unknown ownership, source/policy mismatch, repeated auth errors,
  unapproved provider spend/resource change, need to weaken evidence/RLS controls.
- Ready: exact problematic owned lessons and independent expected facts recorded.
- Done: module/tests pass; paired real-model results and durable DEV readback;
  quality/time/calls reported with failures and remaining rollout gates explicit.
- Rollback: do not select the experimental module. No default/production changes
  or migration; retain authorized QA drafts as evidence, no automatic deletion.

## Critical journeys

1. Two lessons: save first fully reviewed terminal result before authoring second.
2. Restart after second fails: reuse first, do not regenerate or alter its key.
3. Eligible sibling category cannot be admitted as a false option.
4. Unknown option, omitted exception or unsupported explanation is review_required.
5. Same frozen lessons/model policy, current then experimental (reverse next case),
   measure time, provider HTTP attempts, logical calls, tokens when available,
   accepted questions/targets and independently found semantic defects.

## Graph disposition

CodeGraph search/callers narrowed current owner to application.py -> pipeline.py
and semantic_assessment.py. Readiness reports source snapshot changed; decisive
relations confirmed in source. SOURCE_FALLBACK for freshness, not runtime proof.
No unresolved cross-language edge; Graphify duplicate traversal unnecessary.
