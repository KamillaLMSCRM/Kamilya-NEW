# Four bounded DEV improvements — acceptance record

Owner: root. User request: implement first four rows of the remaining DEV table.
Production is excluded. This record separates source/isolated checks from live
shared DEV acceptance. Baseline production62 fixes/instructions are preserved.

## Source review and checks

- Runtime/assignment independent source review: no blocking finding.
- Staff independent review found historical cancellation eligibility, overly
  broad import UPDATE rejection, quadratic overview, unrelated-history overflow
  and archive discoverability gaps. Fixed under accepted repair addendum.
- UI writer's work independently reviewed by a separate leaf/root. Backend writer
  and independent reviewer are different. Final changed test oracles independently
  reviewed; native-confirm and overly broad UPDATE expectations were obsolete,
  not product regressions or waived security checks.
- Full API final:4421 passed,60 skipped,55 warnings; integration directory excluded.
  Do not present skipped database tests as passed. Changed schema/RLS/races were
  checked separately against real Supabase DEV isolated owned schemas.
- Runtime isolated gate:17 PASS, owned schema removed, public catalog neutral.
- Staff isolated final gate:29 PASS, owned schema removed, public catalog neutral.
  Includes SERIALIZABLE competing confirms, no partial writes, old learning
  preservation, cancelled/superseded/completed cases and25,001 unrelated history.
- Operational/controller tests:79 PASS. Python quality baseline PASS Ruff1005 /
  Mypy2170, unchanged debt baseline. Release contract PASS324 error entries,
  single migration head0183. Web build with all four existing DEV flags ON passed.
- Frontend full final:1333/1333 PASS, no skipped tests. Typecheck/lint passed
  separately; optimized build PASS67 routes with all four existing DEV flags ON.
- Navigation: CodeGraph runtime unavailable in this checkout; Graphify output
  absent. Bounded source fallback used; no graph-backed verification claim.

Evidence: `.release-evidence/four-dev-blocks/` (sanitized local output).
Initial full-suite failures are preserved, not overwritten or relabeled success.

## DEV deployment and live journeys

R1 deployed SHA0dad851d98ef2fc34f2447b94c331f51d316597a. CI39193975371 success;
API dep-dbaoq8mi0phs73a0spjg, worker dep-dbaorbgm7kps739mmte0 live;
frontend dpl_FxPfWS3yfmi8Rokr5TBK7bw9BFAo READY, exact SHA parity/health PASS.
This is deployment evidence, not complete product acceptance.

Existing DEV API/worker Free, frontend Hobby; all12 relevant existing
flags already enabled, public DEV schema already0183 (read-only gate PASS).
The existing provider start commands require the accepted DEV private launcher;
its exact dependency is retained, no new relay/model/ASUS activation added.

Planned: exact SHA CI/API/worker/frontend parity; ordinary superadmin settings
edit/readback/revert; ordinary QA methodologist real-model date-only assignment
dialogue/preview/explicit-confirm/reload; schema/roster/transfer/archive and corrected
import/qualification restore. New synthetic fixtures only; preserve prior QA data.

Live R1: qualification profile restore PASS through ordinary API, current linked
department and current label preserved, normal synthetic fixture label restored.
Real model missing-date clarification1.171s then date-only follow-up1.282s retained
course/department and resolved one exact synthetic recipient in owned preview.
No assignment executed yet. Interpretation candidate intentionally carries queries,
not authority IDs; only preview resolves exact tenant-owned objects.

Settings save30->31 and reload PASS(revision6). Native revert confirm interrupted
IAB; UI revert NOT ACCEPTED. Read-only reconciliation proved no revert had run;
canonical API restored original catalog values/routing at revision7. Controlled
Modal repair/redeploy/fresh live acceptance pending. No old history deleted.

Harness corrections (not product defects): team-user search does not include
personnel number; use workspace roster query to read back the created employee,
without repeating creation. Preview endpoint is singular assignment-preview.
Interpretation response was preserved/reused rather than repaying for another call.

Additional live API acceptance: assignment explicitly confirmed, no notification,
same receipt after GET reload; employee transfer added1 course and replayed the
same receipt; unit-subtree transfer affected1 employee, added0 and preserved2.
Both learning rows were compared across the unit move; the employee transfer's
preservation count was1. Byte-identical employee-transfer history is separately
proved by the owned SQL gate, not claimed from a missing harness pre-write capture.
Existing QA16 users/16 units/10 journal rows independently read back unchanged.
Methodologist runtime-settings read returns403; no privilege expansion used.

Synthetic XLSX built/inspected/rendered with Artifact Tool, one source sheet/one
employee/no contacts. Ordinary DEV import analyze -> branch+department correction
-> GET reloaded proposal -> approve -> commit PASS. Generic and legacy names agree;
one new employee/position and2 units, corrected linked placement, rules recompute
success, deleted0. Existing QA state preserved; fixtures still active pending final
browser acceptance/soft-cleanup, no old tenant-history purge.

R2 controlled confirmation received independent review. Initial review found
incomplete envelope capture, stale auth-generation handling and stale conflict
display; repaired. Root strengthened the asynchronous negative assertion and found
the same stale save-failure bug RED, then extended the existing generation guard.
Focused12 PASS, typecheck/scoped lint PASS. Earlier broad R2 web1335 PASS loaded
the8-case intermediate runtime test; do not present it as final12-case verification.
Frozen final broad web run and exact R2 DEV deployment/live UI remain pending.
Final independent review approved the captured revert envelope and auth-generation
guards. Review additionally caught save409 pending-state lock after the guard
extension; fixed and proved explicit retry with refreshed revision3/no auto replay.
Final focused12/typecheck/lint PASS, no source-review blocker. API source and DB
contracts remain byte-identical to accepted R1; only two web files and docs changed.

## Explicit limits

No production release/master push, plan/resource changes, voice, iSpring, new
ASUS/1C connector activation, model routing activation/order or old-history purge.
Impact relevant rows and tenant placement/reporting metadata remain bounded at
25,000 with explicit fail-closed response; no unlimited-scale claim.
