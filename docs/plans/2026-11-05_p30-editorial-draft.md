# P30: editable draft and explicit human review

Owner-approved scope: selected six-step audit-reconciliation plan, 2026-11-05.
ASUS/model-run pause remains active. No new critics, provider changes, migrations,
customer mutations or promotion of P30 outside its existing DEV QA admission.

Observable outcome: a complete source-bound draft survives review findings;
the methodologist sees all material issues, edits in the existing course editor,
and resolves the exact current version before ordinary approval/publication.

Ownership/impact:
- AI/source-core owns unit custody, generated questions and self-review output.
- A pure editorial manifest binds material findings and observations to the draft.
- courses/source_uncertainty owns human resolution, history, content/revision fence.
- Existing course and quiz review/publication remain authoritative, separate states.
- Existing course editor hosts one panel consuming existing inspection/resolution API.
- Legacy P29/older wire formats, tenants, provider/profile/save guards are preserved.

Frozen implementation decisions:
1. P30 machine success means draft prepared, not human approval. Always preserve
   human review on generated P30; expose self-review result separately.
2. One typed material-issue list from structured findings, unresolved goals/cases,
   plan/source uncertainties and discovered links. Prose summaries/notes are visible
   observations, never string-matched as normative decisions. No extra model call.
3. Valid non-teaching units remain byte-custodied as auxiliary context adjacent to
   an owned lesson, never silently discarded or declared a verified exemption.
4. Reuse snapshot/source revision and per-defect resolution API. Preserve historical
   raw findings. Human resolution does not automatically approve or publish.
5. For P30 only, a stable learning-content snapshot excludes review bookkeeping;
   changed questions/source/content invalidate prior human resolution at approval.
6. Panel rejects unsaved/stale work, duplicate submits, wrong course/session responses;
   409 requires fresh inspection. No automatic mutation retry after unknown outcomes.

Acceptance: pure positive/negative contract tests; P30 cycle/service seams; existing
resolution API/cross-tenant/concurrency regressions; panel and real-page integration
tests; web types/lint/build and appropriate API suite. Refresh static navigation once
after source changes; graphs are navigation only. Saved cases first, zero new model calls.
After owner lifts pause: three original-document DEV runs and measured editor effort,
then existing DeepSeek/release/live gates. Local tests do not close those gates.

Local implementation completed 2026-11-05:
- P30 retains a complete editable draft and versioned findings/observations, even
  when automated semantic review leaves issues. No new critic or repair loop.
- Auxiliary source blocks remain in exact source custody. Initial and final
  findings keep the actual reviewed case/options; retained IDs keep first context.
- Existing resolution API is integrated into the real course editor. Explicit
  per-issue decisions, source revisions, content hash and history remain separate
  from course/test approval and publication.
- Approval/publication check the current snapshot under course/source locks;
  content edits invalidate previous P30 review. Legacy policy behavior is retained.
- Final API: 7832 passed, 544 skipped, 57 warnings, 99.97s. Web: 183 files,
  1606 tests passed; typecheck/lint/build passed. Built-app synthetic browser:
  desktop save and mobile stale-version conflict, 2 passed, 3.9s. Independent
  bounded source review GO. Baseline ruff=1005/mypy=2174 passed (existing debt).
- Static navigation refreshed: CodeGraph2346 files; Graphify27733 nodes/82859
  edges/2379 sources, excluded-path audit PASS, zero model calls. Relevant call
  paths confirmed in source, not treated as runtime proof.
- Evidence: .release-evidence/p30-external-review-20261105/DRAFT_STAGE_RESULT_RU.md.
- Still pending: owner lifts ASUS/model pause; fresh native/real DB concurrency,
  three full DEV courses, semantic/time/token acceptance, DeepSeek and release.
  No deployment or production acceptance is claimed by this local stage.

## Follow-on: P31 editorial integration, owner authorized 2026-11-05

- Preserve stored policies through30 and ordinary29 default. Fresh matched native
  DEV QA selects31 with a distinct server-owned marker and worker/final-save fences.
- Coherent teaching author → full keyed editor → one optional addressed revision →
  existing physically blind answer check. No source planner or new critic cascade.
- Review domain is independent of typed target. New source/lesson/question/course
  targets have closed IDs; source and course fingerprints bind every response.
- Material findings remain for human resolution; advisory findings do not authorize
  automatic rewriting. Missing/unrequested siblings are retained and visible.
- Revision returns new lesson-source proposals in the same response. Initial review
  links remain historical; changed prose is explicitly unverified even with links.
- Replay received Standards review/revision using a labelled deterministic legacy
  projection, not fresh-wire or native acceptance. Preserve all source holds.
- Focused tests include full service/checkpoint crash after durable revision,
  cold replay with no repeated calls, unknown outcomes, protected questions,
  source A→B, codec roundtrip, QA-only and native final save. FullAPI7889PASS,
  baseline1004/2174PASS, independent bounded source GO before fresh Luna control.
- Fresh Luna6/HIGH through actual application service + local durable journal now
  running on Standards. This is not PG/nativeDEV acceptance. Then independent
  matrix/reference comparison; extend to Fire/Microcredit on this frozen source
  if the common mechanism holds, before protected deployment/live gates.

P31 implementation checkpoint, 2026-11-05:
- Actual service controls completed on all three documents before shared-source
  guide restoration: Standards5L16Q/4calls, Fire7L21Q/3calls, Microcredit10L29Q/4calls.
  Independent audits found material source omissions; model-clean is not content GO.
- Shared applicability/fidelity/logic/case instructions were restored to the new
  roles without changing historical policies. Guided Fire6L18Q/4calls301.656s;
  guided Standards4L12Q/3calls165.469s. Microcredit guided is the sole active run.
- Fire independently fixes three prior issue classes but retains implementation-duty
  omission and one answer-revealing stem. Usable draft preserved, human review held.
- FullAPI7889PASS544skipped before prompt restoration;58focused and baseline
  Ruff1004/Mypy2174PASS afterward. Crash/cold-replay and unknown-outcome tests PASS.
- Navigation frozen: CodeGraph2351files; Graphify27790nodes/82889edges/2384sources,
  excluded-path auditPASS, AST-only. Source integration reviewed independently.
- Owner's Narrow A design5fb9dcff accepted for integration; full five-commit range
  overlaps P30 editor and generation recovery. Integrate in a clean linked checkout,
  preserve source-review controls and run combined UI tests. No release claim yet.
