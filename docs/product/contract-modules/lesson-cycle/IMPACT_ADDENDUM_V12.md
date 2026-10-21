# Automatic source plan and shared DEV worker V12

Status: Accepted for DEV implementation and acceptance,2026-10-21.
Approved by: product owner, current chat instruction; production prohibited.
Supersedes: V1/V4 rollout exclusions only for explicitly selected DEV execution.
Root/module owner/reviewer: root Codex. Product owner: workspace owner.
Change control: root can refine internals; production/schema/billing/routes remain
outside this approval. Historical pilot contracts and results remain immutable.

## Outcome, module map and ownership

Existing source ingestion -> evidence-owned facts and finished lesson -> automatic
source assessment plan -> lesson cycle blind review/counterexample -> existing
generation checkpoint repository -> existing draft course/quiz persistence.

`source_assessment_plan.build_source_assessment_plan` owns objectives, applicability,
answer components, source references and explicit source-unit dispositions. Input
is the source-owned fact inventory and finished lesson, never the manual pilot
oracle. Exact reference/substring checks are necessary but not entailment proof;
a separate completeness/meaning review must admit the plan. One bounded repair.
Unknown, missing or conflicting source dispositions fail closed. No fixed question
quota; bounded batches do not authorize dropping objectives. Input and source
versions participate in checkpoint identity. Source content is untrusted data.

Worker adapter owns integration, not truth: it consumes the existing repository
under exact tenant/job ownership, persists immutable plan and terminal assessment,
then maps reviewed questions to the existing draft artifacts. No direct quiz writes
or approved-review default. Existing persistence owns needs_review, publication
and transactional course creation. Reusing a saved result requires full cycle
validation; storage failure prevents progression. Cancellation is propagated.

## Impact and negative space

- ai/evidence_engine/application.py: compatible optional per-lesson assessor;
  selected path assesses/saves each realized lesson before next realization.
- ai/pipeline.py: select only explicit DEV environment plus dedicated flag;
  inject exact tenant/job and cancellation, ordinary worker task unchanged.
- core/config.py: DEV-only switch default false. Production cannot select it.
  Exact runtime identities are render-development/render-development-worker;
  APP_ENV is production even in DEV. A separate explicit tenant allowlist keeps
  the experiment restricted to the permanent synthetic QA tenant.
- ai/generation_checkpoint.py: consumer only; no schema/ACL/retention change.
- ai/lesson_cycle.py: unchanged review semantics, optional cancellation boundary.
- New planner/worker modules and public-seam tests, comparison/evidence scripts.
- Legacy disabled path, provider chain/model/budget, OCR, UI, roles/RLS,
  assignments/results, production and customer originals remain unchanged.

## Verification and rollout

Red/green seams: automatic plan, full worker adapter, existing course application.
Mock only external model/storage. Reject invented context/components, skipped
primary units, unknown refs, wrong tenant and altered checkpoints. Cover ordinary
source, conditions/OR, numbers, administrative exclusions and repair cap. Run
neighbor tests, canonical quality and AI-COURSE-01 gates. Actual shared DEV worker
jobs use QA copies of Lombard originals; compare to independent original-based
oracle, not only planner counts. Record exact runtime SHA, quality, time and calls.
Retain failures, no destructive automatic cleanup. No publication or assignments.
Target source_refs are the sole source-target mapping authority. The server
derives the redundant disposition target list before the independent audit;
model claims cannot add coverage. Missing unreferenced operational units still
fail. Repair receives the exact rejected plan and concrete feedback, not a blind
request to reconstruct everything. Structural checks happen outside provider
fallback so a local contract failure cannot masquerade as provider downtime.
Roll back by flag off/existing DEV revision; no migration. Plan completeness and
semantic quality remain separate acceptance gates from successful task execution.
