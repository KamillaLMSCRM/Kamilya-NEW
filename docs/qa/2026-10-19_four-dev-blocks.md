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

PENDING. Existing DEV API/worker Free, frontend Hobby; all12 relevant existing
flags already enabled, public DEV schema already0183 (read-only gate PASS).
The existing provider start commands require the accepted DEV private launcher;
its exact dependency is retained, no new relay/model/ASUS activation added.

Planned: exact SHA CI/API/worker/frontend parity; ordinary superadmin settings
edit/readback/revert; ordinary QA methodologist real-model date-only assignment
dialogue/preview/explicit-confirm/reload; schema/roster/transfer/archive and corrected
import/qualification restore. New synthetic fixtures only; preserve prior QA data.

## Explicit limits

No production release/master push, plan/resource changes, voice, iSpring, new
ASUS/1C connector activation, model routing activation/order or old-history purge.
Impact relevant rows and tenant placement/reporting metadata remain bounded at
25,000 with explicit fail-closed response; no unlimited-scale claim.
