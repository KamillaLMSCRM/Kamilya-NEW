# Completion forms V2 — separate test and DEV acceptance

Status: Accepted for implementation and existing free DEV deployment by owner request on 2026-10-18. Production forbidden.
Supersedes the standalone-test exclusion of `2026-10-18_completion-form-builder.md`; other V1 protections remain.
Root/module owner: root. Product owner/Approved by: workspace owner (current request). UI leaf owns only its assigned files; root reviews combined diff and owns external operations.

## Interface extension and chain

Admin settings -> quiz-specific title/intro/confirmation + selected fields -> successful persisted quiz submission -> immutable evidence snapshot -> learner result/history download -> same PDF after reload/template change.

- Add `quiz_title`, `quiz_intro_text`, `quiz_confirmation_text` to tenant form settings, with safe defaults explicitly describing a separate test, not whole-course completion. `to_print_form(for_quiz=True)` maps these texts into a normal immutable PrintFormEvidence snapshot. Explicit field selection enables the configured quiz form; legacy null settings keep old behavior.
- Snapshot that form in new quiz-submission events only after existing identity/hash checks. Include failed outcomes honestly as a result record, not proof of successful passing. No new certificate or course completion is issued.
- Configured knowledge-check export is bound to the event's exact quiz/attempt ID and verified evidence digest. It must not pick a later/better attempt, include another quiz, or change after a retry. Missing/inconsistent evidence returns409. Legacy complete audit behavior remains unchanged.
- Add student-only GET `/v1/training-evidence/quiz-attempts/mine/{attempt_id}/export`; resolve only own tenant/user/source-key evidence and enforce assignment-scoped bearer restrictions through the existing learner export. Unknown/foreign IDs404. Historical attempts without configured snapshot409; never retroactively attach a current template.
- Existing event download also renders a configured quiz-only form. It always identifies the individual test and attempt and states it does not confirm whole-course completion, even if optional fields omit test title. Existing course and public audit rendering are unchanged.
- Student quiz result exposes a download immediately; attempt history exposes it again after reload. Buttons produce actual PDF downloads, validate PDF bytes, show bounded errors, and revoke Blob URLs. No OTP bypass/automatic signature; returned signed-copy workflow stays course-only.

## Data ownership / negatives / rollout

Existing tenant JSON settings owner and append-only event owner remain unchanged; no table, migration, new permission or retention policy. Readers/writers stay tenant admin/config, student/own result, methodologist/audit. Repeated GET is side-effect-free; event idempotency remains source-key based. No production, billing, model routing, reserve, voice or ASUS mutations. Keep unrelated DEV branch changes with a preserving merge, not a reset or whole-DEV promotion to master.

## Ready, done and failures

Read scope: named evidence, quiz submit/player, settings, export and existing DEV controller/test infrastructure. Write scope: these modules/tests, plan/guide/changelog/ledger and a bounded DEV acceptance harness. Stop for unexpected data mutation, ambiguous ownership, provider cost/plan change, or unsafe deployment conflict. Root handles integration; no live success inferred from local tests.

Verification: focused policy/workflow/render/HTTP/component tests; full applicable local risk suite and exact CI; canonical isolated Supabase DEV tests for persistence/RBAC/RLS/cross-tenant/cleanup; preserving DEV release on existing Free/Free/Hobby, exact API/worker/frontend readback; ordinary browser admin save/reload/sample -> ordinary learner test before course completion -> download/reload/history -> change template -> unchanged old PDF; negative failed/foreign attempt. Preserve existing QA history and restore only owned settings. Retain new synthetic event/course/attempt evidence unless exact cleanup is supported without deleting unrelated state.
