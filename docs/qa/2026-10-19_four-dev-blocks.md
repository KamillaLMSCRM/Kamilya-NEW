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
- Full API final:4424 passed,60 skipped,55 warnings; integration directory excluded.
  Do not present skipped database tests as passed. Changed schema/RLS/races were
  checked separately against real Supabase DEV isolated owned schemas.
- Runtime isolated gate:17 PASS, owned schema removed, public catalog neutral.
- Staff isolated final gate:29 PASS, owned schema removed, public catalog neutral.
  Includes SERIALIZABLE competing confirms, no partial writes, old learning
  preservation, cancelled/superseded/completed cases and25,001 unrelated history.
- Operational/deployment-contract tests:211 PASS with one existing Windows skip.
  Python quality baseline PASS Ruff1005 /
  Mypy2170, unchanged debt baseline. Release contract PASS326 error entries,
  single migration head0183. Web build with all four existing DEV flags ON passed.
- Frontend full final:1339/1339 PASS, no skipped tests (exact R2 source, unchanged
  in R3). R1 predecessor1333/1333. Typecheck/lint passed
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
At this interpretation checkpoint no assignment had been executed; the later
explicit-confirm acceptance is recorded below. The candidate carries queries,
not authority IDs; only preview resolves exact tenant-owned objects.

Settings save31 and reload revision8 PASS. Fresh tab12 controlled Modal Cancel
performed no write; explicit target7 revert then reloaded at revision9. Independent
readback confirms all31 original values, history suffix and routing unchanged. No
old history deleted and no native confirm remains in the current tab set.

Harness corrections (not product defects): team-user search does not include
personnel number; use workspace roster query to read back the created employee,
without repeating creation. Preview endpoint is singular assignment-preview.
Interpretation response was preserved/reused rather than repaying for another call.

Additional live/browser acceptance: assignment plan ccc5ba46-04df-42fb-8616-7abfb2cc2a1e
was explicitly confirmed with one created enrollment and no notification; the same
receipt reloaded. Employee transfer plan6402f3e2 affected one employee, added0 and
preserved1; empty-unit plan67bd2a8c affected0; roster/path reloads passed. The
employee transfer's retained learning and placement were re-read independently.
Existing QA16 users/16 units/10 journal rows independently read back unchanged.
Methodologist runtime-settings read returns403; no privilege expansion used.

Synthetic XLSX built/inspected/rendered with Artifact Tool, one source sheet/one
employee/no contacts. Ordinary DEV import analyze -> branch+department correction
-> GET reloaded proposal -> approve -> commit PASS. Generic and legacy names agree;
one new employee/position and2 units, corrected linked placement, rules recompute
success, deleted0. Existing QA state preserved; fixtures remain active for
authorized reconciliation/soft-cleanup, with no old tenant-history purge.

R2 controlled confirmation received independent review. Initial review found
incomplete envelope capture, stale auth-generation handling and stale conflict
display; repaired. Root strengthened the asynchronous negative assertion and found
the same stale save-failure bug RED, then extended the existing generation guard.
Focused12 PASS, typecheck/scoped lint PASS. Earlier broad R2 web1335 PASS loaded
the8-case intermediate runtime test; do not present it as final12-case verification.
Frozen final broad web run and exact R2 deployment are recorded below; live UI
remains pending and is not inferred from API/static artifact checks.
Final independent review approved the captured revert envelope and auth-generation
guards. Review additionally caught save409 pending-state lock after the guard
extension; fixed and proved explicit retry with refreshed revision3/no auto replay.
Final focused12/typecheck/lint PASS, no source-review blocker. API source and DB
contracts remain byte-identical to accepted R1; only two web files and docs changed.

R2 exact web source fa6cd4ea broad final1339/1339 PASS; CI39196262631 SUCCESS.
Source inspection of the live import summary uncovered a separate reporting
defect: generic branch created correctly but branch counter0 (aggregate2).
IMPORT_COUNTS_ADDENDUM_V1 accepted; narrow source fix preserves old receipts and
all domain/placement behavior. Created/updated async-loop tests RED2 then focused
GREEN12, independent review approved. Final full API4423 PASS/60 SKIP/55 warnings,
unchanged Ruff1005/Mypy2170 baseline PASS. Fresh DEV counter receipts are recorded
below; the old inaccurate import summary was not repaired retroactively.

R2 controller RELEASE_OK: API dep-dbap7nmi0phs73a2cp60, worker
dep-dbap8qmq1p3s73ciein0, frontend dpl_76c6XLk9gNazK1F1mq9HsrbToNQB,
all exact fa6cd4ea. Public frontend bundle independently includes the controlled
confirmation and frozen envelope; static artifact proof only, not UI acceptance.
New counts XLSX inspected/rendered/re-imported with Artifact Tool; root visual
review PASS, SHA256637d186551d38ee8a37c99910ea3df7f49d7321310173c9da8b5cf0a62dcf534.

Independent final source/artifact audit approved ce95010ac4a24c9815bd57856a9c4908581cb720
against production baseline1bce48e9, no unresolved P1/P2 in the bounded scope.
All15 staff gate source hashes still match. Fresh-tab settings readback revision9:
all31 original values and routing hash unchanged. Read-only production health
04:03UTC remains0.11.62/1df26939, remote master1bce48e9 unchanged.
R3 CI39197219609 SUCCESS; controller REL-FOUR-BLOCKS-DEV-R3-20261019 RELEASE_OK.
API dep-dbapdg61egvs73bk41o0, worker dep-dbapeirbc2fs73c9kh20, frontend
dpl_86ppFMEc1qLxgYrmsufwpBAaRvxr all exact ce95010a with health PASS.
Separate final provider inventory `provider-final.json` at04:06UTC confirms
Free/Free/Hobby and all12 preexisting flags (not inferred from execute.json);
no resource or model-route activation changed. No public schema migration was run.

Fresh real DEV counts acceptance PASS: sessionA459f2b1f-8035-4522-90f8-79664fad4736
created branch1/department1/aggregate2/position1/staff1, rules recompute success;
sessionB39232c2a-d3e9-4276-9d8c-5a2effe341e8 updated only branch1/aggregate1,
created0/staff_updated0/departments_updated0/deleted0. Stable exact unit/position/
employee IDs, employee placement and department fields independently read back;
A receipt unchanged. Existing inaccurate R1 receipt also independently unchanged.
Final old QA16users/16units/10journal rows unchanged. No unresolved pending write
in either counts session or the saved counts harness state.
The stateful harness itself received root repair and independent review before
execution: no nonexistent workspace external-key lookup or hardcoded proposal IDs.

The selected browser acceptance is closed for DEV; old agent-created IAB11 tabs
are absent and no current native dialog is open. Fresh controlled-Modal
save/reload/cancel/revert/reload, browser assignment, staff schema/transfer, and
corrected-import journeys are accepted for DEV. The
completed import wizard clears on reload after commit as intended; no claim is made
that the UI restores a completed receipt view.
New owned fixtures (three synthetic loginless employees and their units/positions,
plans/import sessions/legitimate learning) remain for authorized reconciliation;
one owned empty unit was soft-archived. No test account privilege or old history
was changed.

## Explicit limits

No production release/master push, plan/resource changes, voice, iSpring, new
ASUS/1C connector activation, model routing activation/order or old-history purge.
Impact relevant rows and tenant placement/reporting metadata remain bounded at
25,000 with explicit fail-closed response; no unlimited-scale claim.
