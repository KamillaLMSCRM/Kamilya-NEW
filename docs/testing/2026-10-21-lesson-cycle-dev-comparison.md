# Lesson-owned assessment cycle: bounded DEV comparison

Latest result2026-10-21: **V11 bounded pilot ACCEPTED** on the three frozen lessons
after source-based review of all34 retained questions/options/explanations and
fresh-process DEV readback. See the follow-up section below. This is NOT an
acceptance of automatic whole-document target extraction or default rollout.
No shared-default selection, shared-worker deployment or production changes.

The initial V1-V3 comparison below remains historical **NO_GO** evidence; its
failed/false-green results have not been erased or relabeled as successful.

## Scope and reproducibility

- Frozen existing lesson-only baseline: `386478de30ffed5ca2d2c81d062f91e0055807cf`,
  DEV API product0.11.66. Existing `prepare_lesson_assessment` is the baseline;
  this is not a repeat of the whole-document generation pipeline or OCR.
- Permanent synthetic DEV QA: `a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0`.
- Three finished lesson texts frozen from the previously source-checked inputs:
  eligibility/borrower duties, II-category approvals, fire response.
- Same DeepSeek configured model `deepseek-v4-flash`, actual response model
  `deepseek-flash`; temperature0.1, single provider, transport retries0 per
  experiment. Existing baseline low-reasoning audit profiles remain intact.
  This is not an acceptance test or change of the live fallback chain.
- V1 corpus used source-checked lesson excerpts, not full original context.
  V2 human oracle adds governing original page14 context and splits borrower
  duties and after-hours/weekend/holiday targets. Body texts remain unchanged.
  These are manually curated pilot targets, NOT automatic whole-source coverage.
- Baseline was run once; later candidate repetitions explicitly reuse the frozen
  baseline after checking its code, model configuration and lesson hashes. They
  are not new paired randomized replicates or repeatability evidence.
- Actual upstream HTTP POSTs measured by a temporary loopback-only transparent
  forwarder. No credential/header capture. Local candidate consumes ordinary DEV
  APIs for new drafts, never the customer tenant or production.

## Why automatic review missed the defects

V1's author was followed by a blind reviewer deriving the key. The server checked
that quoted evidence existed, each alternative had a classification, exactly one
was supported, and the claimed targets were covered. It did NOT establish that
each source quote logically entailed that classification. A second model verdict
could agree with the same interpretation error.

Manual review found three independent failures in a formally accepted result:

1. A lender's decision to consent for certain categories became a question about
   who has the right to apply. Original page14 supplies the wider right to apply;
   page17 describes the consent conditions. Both context and predicate changed.
2. A >50percent income drop was called false under a broad >30percent eligibility
   condition, although the stronger condition also satisfies that threshold.
3. One collateral-replacement question claimed a compound target containing four
   independent borrower duties. Question counts were not duty coverage.

These failures occurred in the serial lesson cycle too. Parallelism is not needed
to reproduce them. V1's fast result is ROOT_REJECTED, not a speed/quality success.

## Changes implemented locally

- Optional `ai.lesson_cycle.run_lesson_cycles`: finish one lesson's assessment,
  blind review, bounded repair, terminal save, then advance. Complete tenant /
  lesson / source / policy identity prevents incompatible checkpoint reuse.
- V2/V3 add an independent counterexample audit: actively falsify the key,
  preserve actor/action/modality and exceptions, prove individual target coverage
  using exact question and source substrings. Unknown/veto/missing proof fails.
- Deterministic conservative percentage-overlap guard handles numeric literals
  and common RU round-number forms, including comparison boundaries. It does
  NOT prove all natural-language arithmetic or other numeric units. It can reject
  valid exact-boundary questions conservatively; this remains an authoring gap.
- Repair receives the concrete rejected condition, not just a generic quality
  error. Normally3 logical calls, at most6 including one repair; no unbounded
  loop, weakening of admission, or fixed questions-per-lesson quota.
- Checkpoint resume revalidates the key and both evidence/audit snapshots.
- Added a read-only, separate-process resume script. No model call is permitted.

## Measured results

Time is wall time around model work plus new-draft persistence and immediate
readback; queue/OCR/whole-course generation and human review are excluded.

| Case | Frozen current | Latest V3 candidate | Independent disposition |
| --- | --- | --- | --- |
| Eligibility/duties |85.335s;13 HTTP; coverage gate rejected final set |36.918s;5 HTTP;9 questions;9/11 pilot targets; `review_required` |Old modal defect absent from retained set. Income/change still missing; do not claim complete coverage. |
| II-category approval |15.790s;3 HTTP; coverage gate rejected final set |41.953s;6 HTTP;9 questions;9/9 pilot targets; model says ready |ROOT_REJECTED: one question assumes Saturday is a nonworking day without specifying the local schedule. |
| Fire response |127.878s;10 HTTP;10 questions |24.407s;3 HTTP;10 questions;10/10 pilot targets; model says ready |ROOT_REJECTED for strict source fidelity: immediate action became first-priority ordering; one explanation adds simultaneity not stated in its cited action. |

Failed baseline final sets are NOT counted as wrong answer keys. Their gates
rejected coverage; raw intermediate questions were not admitted final output.

Earlier candidates are retained, including negative results:

- V1: eligibility20.585s/2HTTP; approval22.983s/4HTTP;
  fire18.996s/2HTTP. Formal ready is not manual acceptance; eligibility has the
  two substantive errors above and compound-target overclaim.
- V2: eligibility44.956s/6HTTP,8/11 retained; approval40.485s/6HTTP,
  8/9 retained; fire34.239s/6HTTP,10/10 retained. Root did not find a wrong key in
  that fire sample, but the next generation introduced wording defects again.
  A successful sample is not proof of repeatable quality.
- Latest V3 usage, prompt/completion tokens reported by the provider:
  eligibility31927/9066; approval33527/10353; fire9176/5552.
- Frozen current usage: eligibility72860/15421; approval14817/2407;
  fire52667/24945. No verified currency cost or marketing speedup claim follows.

## Exact-defect regression proof

Frozen V1 defective author/reviewer fixtures were replayed through V3, not
regenerated. Numeric overlap was rejected in code. ONE real counterexample-model
HTTP call then rejected the right-to-apply / consent substitution, explicitly
citing the governing page14 context. Both questions remained unaccepted.
This proves rejection of these captured defects, not general semantic soundness.

## Persistence, verification and safety

- Latest owned QA course: `bbd04ebe-d843-4c38-a883-2d8db82de63b`, still draft.
- A separate fresh process reloaded all3 results and read the saved lessons,
  every option/key/explanation through DEV APIs:0 model calls,0 data mutations.
  The3 original lesson texts remained exact matches.
- Persistence is a local identity/result receipt plus DEV lesson/quiz rows,
  NOT a deployed shared-worker checkpoint. Existing manual quiz CRUD defaults
  review status to approved; course drafts isolate this experiment. Native AI
  review-state/publication integration remains a mandatory rollout gate.
-26 public-seam tests;78 focused plus neighboring tests PASS. One existing
  Starlette deprecation warning. Canonical Python quality baseline PASS;
  Ruff owned paths PASS. No local PostgreSQL was used.
- CodeGraph narrowed the current owner before implementation; source was the
  decisive freshness fallback. Post-change sync/exclusion audit passed. Static
  edges do not prove runtime behavior. No token-efficiency claim is measured.
- Private source text, provider captures and exact receipts remain ignored under
  `.release-evidence/lesson-cycle21/` and `.release-evidence/sandyk-audit21/`.
  No source files, existing customer records, roles, assignments or learner
  results were edited; new synthetic drafts are retained as evidence.

## Next required work, not completed

1. Typed question intents: distinguish an exact stated threshold from a
   sufficient condition or concrete scenario; do not fix by stripping operators
   or weakening the overlap gate. Complete both missing financial targets.
2. Explicit temporal applicability and qualifier checks: working schedule is an
   input fact; immediate does not automatically mean first, and sequence or
   simultaneity cannot be invented. Keep negative fixtures from these samples.
3. Repeat source-based acceptance, then native server-owned checkpoint, review
   state and shared-worker integration before selecting this module by default.

No publication/release is authorized by this comparison.

## Follow-up: V4-V11, final bounded acceptance

Owner instruction: repair remaining meaning, conditions and coverage failures,
repeat on problematic lessons through DEV, compare quality/time/calls, no prod.

### Confirmed causes and implemented contracts

1. Deterministic temporal guards reject invented first-priority/simultaneous
   execution and unsupported weekday-to-nonworking-day assumptions. Model
   consensus cannot waive those gates.
2. Explicit numerical intent distinguishes the exact boundary from a sufficient
   example. Percentages, calendar days and months carry an operator/unit; point
   choices are rendered without changing the values or comparison. The blind
   key must match the source's quoted boundary/operator. Minimum-rule duration
   cannot be silently renamed as the overall loan/contract term.
3. AND/OR goals use an explicit full-set question contract. One allowed branch
   is not a false answer to a broad permission question. Duplicate boilerplate
   is removed before the canonical instruction is rendered.
4. Target-owned geographic/category applicability is prepended before both
   reviews. The approval pilot distinguishes inside/outside-settlement rules
   and explicitly states Saturday's nonworking status when that is the scenario.
5. Atomic objectives separate threshold, averaging periods, social-assistance
   alternative, payment decrease, deferral alternatives and minimum duration.
   Several exact evidence fragments may support one objective, but count once.
6. Required correct-answer components prevent a data-only fire-call question
   from claiming the whole immediate-call objective. These are omission guards,
   not substitutes for semantic review; negation/entailment still need review.
7. Server-issued passage references resolve to exact input-owned substrings.
   Models select evidence rather than rewriting long quotes. Invalid/conflicting
   refs and explicit semantic vetoes fail closed. One explicit audit admit/veto
   with a reason/proofs replaces three redundant flags from the same model.
8. The experimental CRUD adapter now respects the existing10-per10-second quiz
   burst with paced writes. No server limiter was changed. Earlier F/G partial
   saves were reconciled by exact matching-prefix readback and writing only
   absent questions, with zero regeneration. G captured HTTP429; F's original
   status was not recorded, so the exact F cause remains unconfirmed.

### Final frozen candidate and results

- Policy: `lesson-cycle-v11`; module SHA256
  `1ed5b68bf7f73e6730ab2148b8cb3b38cefa75b8a59b752b4ea04c80c17c49a3`.
- Final evidence: `.release-evidence/lesson-cycle21/run-n/`.
- Same finished lesson bodies / same configured provider model / same temperature
  as the baseline. Pilot oracle expanded to15/9/10 atomic objectives with manual
  source-checked context, format and answer-component rubrics. This correction is
  explicit; it is not an automatic whole-document extraction result.

| Case | Frozen current wall / actual HTTP | Final V11 wall / actual HTTP | Final model-pipeline time | Source-based final result |
| --- | --- | --- | --- | --- |
| Eligibility/duties |85.335s /13; final set rejected by coverage gate |39.091s /3 |22.19s |15 questions,15/15 planned objectives;0 confirmed key/condition defects |
| II-category approval |15.790s /3; final set rejected by coverage gate |27.653s /3 |17.58s |9 questions,9/9 planned objectives;0 confirmed key/condition defects |
| Fire response |127.878s /10;10 admitted questions |28.718s /3 |17.43s |10 questions,10/10 planned objectives;0 confirmed key/condition defects |

Wall time includes model execution, normal API persistence, paced writes and
immediate readback. Model-pipeline time excludes persistence. The baseline was
frozen once, not paid again for each candidate; provider/cache/latency conditions
were not a randomized controlled performance trial. Two baseline failures are
not usable completed-test times. Do NOT turn this into a whole-course or human
speedup claim. Review/OCR/queue/whole-course planning are outside these timings.

Actual provider request counts26 ->9 for the final three-case comparison. New
prompt/completion tokens: eligibility27743/5583, approval24877/3953,
fire12894/3871. Provider HTTP time sums21.46s /16.85s /16.73s respectively.
No currency cost assertion is made. Fire stem length changed from average287.2 /
max379 characters in the baseline to average74.1 /max125 in the final sample.
This is a measured readability proxy, not a human usability score.

Development effort is separate: F/G/H/J/K/L/M/N used15/18/17/15/15/16/11/9 actual
HTTP attempts, total116 (735503prompt /168176completion tokens). I made no model
call because login preflight failed. The final exact-defect probe adds1call,
so this follow-up used117actual model HTTP attempts overall, NOT9. The9figure
describes only the accepted final generation run; the earlier baseline was reused.
Several intermediate acceptance passes exposed new defects and false rejections;
their cost and failures must not be hidden in a performance or marketing claim.

### Final verification and preservation

- Ordinary synthetic DEV methodologist, same QA tenant. New final course
  `f40c7ae5-082b-479f-97ca-ddc5ddd0acdd` remains draft, containing the three new
  lesson copies. No publication, assignment, email or learner attempt was run.
- All34 questions, alternatives and explanations manually read against the
  previously original-checked frozen lesson/source context. Earlier rights,
  range, temporal and missing-geography errors did not recur in the final sample.
  No confirmed P1/P2 key/condition defect. Some wording repeats the geographic
  context and some distractors remain simplistic; this is not a psychometric
  certification or a claim that every future generation is error-free.
- Fresh separate process reloaded all3 terminal results through DEV APIs,
  checked every key/option/explanation, exact original3lesson-body preservation
  and draft status:0 model calls,0 data mutations. Source module SHA matched
  the final run receipt exactly.
-52 public-seam tests /104 focused-plus-neighbor tests PASS; canonical Python
  quality baseline and owned-file Ruff PASS. Existing Starlette warning remains.
- Exact captured temporal failures: offline public-entry replay rejects all3bad
  questions and retains1good control,0 provider calls. Frozen V1 modal/numeric
  defects replay: numerical rejection in code plus1 real final-policy
  counterexample call;0 admitted bad questions. That probe is separate from
  the9calls in the generation comparison.
- Readiness checks preserved failures: I stopped at login503 before any course
  or model call; N's first launch stopped at a lint gate before experiment
  creation, then the same output directory was first created only after checks
  passed. Earlier candidate failures, static corrections and source/oracle
  revisions are retained, not claimed as final-policy replicates.
  Intermediate L was inadvertently started after a mypy failure because an ad
  hoc PowerShell sequence did not stop. It is NOT accepted as final code proof.
  Explicit failed-gate exits were used for the accepted final launch.
- CodeGraph post-final-source sync/exclusion audit PASS. Decisive public-entry
  links checked in source. Combined Graphify readiness was not asserted; no
  unresolved cross-language edge required it. No tool token-saving claim.

### What this acceptance does NOT include

This implementation still runs as an opt-in local candidate using real provider
calls and existing shared DEV APIs. It has NOT replaced the shared DEV worker's
default generator. Native server-owned transactional checkpoints, AI review state
instead of manual CRUD's approved default, automatic grounded objective/context/
component extraction, full source-to-course OCR acceptance, browser/learner
delivery and option-order/assessment-hardness acceptance remain rollout gates.
Do not silently promote the manually curated pilot oracle into a general product
guarantee. Production, model routing, provider tiers/limits, voice and reserve
configuration were not changed. No push/deployment/release was performed.

## V12 automatic planning / native DEV worker follow-up

Owner instruction2026-10-21 explicitly adds automatic source planning and shared
DEV worker integration. V11 acceptance above remains the MANUAL-oracle pilot,
not proof for V12. Production remains forbidden.

Implemented source-owned target/applicability/component extraction, independent
source-inventory completeness audit, exact substring/reference admission and one
bounded repair. Repair receives the rejected plan, not just unbound criticism.
The server derives source coverage from target source_refs; redundant model
disposition claims cannot create coverage. Rejected plans are durable terminal
review states. Models do not select provider routes or publication status.

The optional application assessor now runs immediately after each realized lesson,
persists via existing tenant/job-bound checkpoint tables, then advances. Existing
transactional course/quiz creation keeps needs_review. Exact DEV runtime IDs and
an explicit QA tenant allowlist protect production and other DEV tenants. Flag
defaults OFF. Changed contract: IMPACT_ADDENDUM_V12.md.

Pre-rollout real-model probes are NOT worker acceptance. B/C/D/E/F/G/H/I/J/L
contain source-plan rejection cases (format, real omissions and reviewer false
positives); all preserved, no question quota padding. K admitted10of11targets,
but root found a P2: stopping all work except firefighting and stopping only
non-fire work were incorrectly marked mutually exclusive. Exact replay went RED
then GREEN; V12 rejects the observed exception-equivalence class independently of
both reviewers and gives explicit repair feedback. No universal entailment claim.
K and L predate this final guard and are NOT exact-candidate acceptance.

Technical evidence:4083unit/neighbor/schema-contract tests PASS, canonical Python
quality PASS; small later guard/validation deltas have focused regressions.
Actual isolated Supabase DEV checkpoint gate PASS15checks, restricted lms_app,
FORCE RLS/cross-tenant/concurrent-claim/cancel tests, temporary schema removed and
public0183 unchanged. Ordinary QA preflight confirms all3retained source IDs,
successful indexing and no active own generation jobs. API/worker existing SHA
386478de30ffed5ca2d2c81d062f91e0055807cf, Free resources unchanged.

Native worker rollout and fresh whole-source quality acceptance remain OPEN until
exact runtime and actual job evidence are appended. Source completeness, semantic
quality and successful task execution remain separate gates. Restart reuses a
cycle only for an identical finished lesson/source/policy; caching realization
before the existing course pipeline reruns is not claimed implemented here.

## V13 partial target admission: native failure and repair

DEV3f89306f exact release passed CI39555514778 (all7checks). Existing API
dep-dbc5pcei0phs73ag8et0, worker dep-dbc5qbeq1p3s73cdctt0 and frontend
dpl_D3BAHwG1Vec7Z6PGVZHyhdg9qejv were read back. Only the two opt-in flags on
API/worker changed; all other environment values and Free/Hobby plans unchanged.
The retained three source binaries were downloaded through ordinary QA API and
matched their original SHA256. No original/course/history cleanup was performed.

First native fire job8ec31785-cd89-4d7f-96eb-ff1dffa26d1a ended interrupted,
saved draft ecec4df7-433f-4fdf-b868-93296c8a7d31:8lessons,0questions. Worker
elapsed207.01s (started-to-terminal). All8plans were rejected; exact plan/audit
checkpoints retained. Therefore V12 native quality FAILED, despite healthy
infrastructure. No production change. Contract IMPACT_ADDENDUM_V13.md records
the corrective interface and its DEV-only boundary.

V13 independent per-target review keeps trusted goals while preserving vetoes
and actual source gaps. Canonical primary inventory is derived from target refs,
not echoed model coverage. Headings can ground applicability only when source-
owned; simultaneous component/context bound failures are fed back together.
The bounded drafting-bibliography classifier keeps legal citations in context.
Only explicitly admitted targets enter the existing author/blind-key review/
counterexample loop; there is no positive admission from silence. Restart
revalidates partial proof without calls. Fresh jobs get separate checkpoint keys.
Full owned lesson/fact inputs are retained for later exact replay.

Local real-model probe M (not shared-worker acceptance): fire-response saved4
reviewed questions/12automatic objectives;8missing targets remain explicit,
review_required.7logical calls and the transport trace are retained separately.
This demonstrates non-blocking partial progress, NOT satisfactory full coverage.
Whole-source shared DEV results must follow below; no human-baseline speed claim.
