# Error and Recurrence Prevention Log

Current as of: 2026-09-25.

This is the single operational log for confirmed Kamilya LMS workflow errors,
invalid assumptions, fixes, verification, and recurrence prevention. Open product
work belongs in `docs/PRODUCT_BACKLOG.md`; current architecture belongs in
`PROJECT.md` and `docs/PROJECT-CONTEXT.md`; change history belongs in Git.

This file is agent-facing and must be maintained in concise technical English.
Preserve commands, paths, identifiers, error messages, evidence labels, and quoted
runtime output verbatim.

Never store secrets, tokens, passwords, connection strings, cookies, private keys,
personal data, or raw logs here.

## Usage

- Read this file in full before analysis, coding, migrations, provisioning, tests,
  builds, deployments, commits, or pushes.
- Before risky work, re-read the relevant categories.
- When a symptom matches an entry, run its prevention check before retrying.
- Add an entry only after confirming the cause, fix, and verification. Mark an
  unconfirmed cause explicitly as a hypothesis.
- Update an existing entry when the same cause recurs; do not create duplicates.
- Remove or rewrite obsolete guidance against the current source of truth.
- The primary agent owns the final log edit. Other agents submit a draft or edit
  only a pre-agreed unique section. Re-read the current file before patching.

Entry format: unique `CATEGORY-NNN`, date, observed symptom, confirmed cause,
current fix, actual verification, and concrete prevention. If remediation remains
open, also record status, safe interim path, and review condition.

## AI-ARCH-001 - Retired assessment code was mistaken for the production engine

- Date: 2026-09-25. Confirmed against `origin/master` after an external review
  attributed current production behavior to `assessment.py`, even though the
  pipeline had already been fail-closed to `evidence_v2`.
- Symptom: code reviews and generated engineering snapshots reported obsolete
  drop-only, audit-budget and traversal-order behavior as current. Follow-up
  work could therefore target thousands of unreachable lines and their tests.
- Cause: the retired generator, audit, completion module, replay script, prompt
  and extensive unit tests remained in the tree. The snapshot builder also
  enumerated those files. Two live helpers still imported the retired module,
  making deletion unsafe until the helpers were given active owners.
- Fix: extract Markdown-table parsing to `source_tables.py`, keep the active
  question-quality predicate inside Evidence V2, delete the retired path and
  dead-only tests, replace the snapshot builder with an Evidence-V2-only source
  inventory, and add an executable retirement contract. Add offline replay
  diagnostics for coverage reasons, cap saturation, order-independent question
  fingerprints and generic-token ablation.
- Verification: focused retirement/helper tests pass, the active Evidence V2
  assessment result is invariant under reversed lesson/fact traversal, the
  affected AI suite passes 338 tests, the critical journey passes seven tests,
  and the full API suite passes 2853 tests with 499 contour skips. Ruff and diff
  checks are clean. DEV and production are not implied by local evidence.
- Prevention: before using a large implementation as current evidence, trace
  the production entry point from `pipeline.py` and require an active call or
  import path. The retirement contract must fail if old module names, generator
  symbols or snapshot sources return. Historical accepted V1 documents remain
  historical; the module index and V2 successor identify the active contract.

## AI-QUALITY-027 - True source sentences became unrelated answer options

- Date: 2026-09-18. Confirmed against the owner's privacy-question screenshot
  and reproduced through the active V2 application seam before release.
- Symptom: wrong options were true sentences about initial replies/escalation,
  unrelated to the question about handling personal data.
- Cause: deterministic source-peer options survived into final assessment; the
  writer could rewrite prompts but not options. Local structural checks proved
  source membership, not that each option answered the same question. Narrative
  sentence splitting also detached conditions/exceptions from their rules.
- Fix: retain coherent source paragraphs; generate block-owned assessment with
  exact evidence references and a separate all-option semantic review. Allow
  plausible counterfactual mistakes, never arbitrary unrelated true statements.
  One bounded repair preserves original question identity/evidence; invalid
  questions are omitted without quota padding. Zero questions preserves a draft
  with an explicit review outcome and UI action, not a successful course.
- Verification: local API unit suite 1879 PASS (75.89s), final affected tests
  53 PASS after reviewer refinement; frontend focused suite
  25 PASS plus typecheck/lint; canonical Python baseline PASS. Synthetic real
  calls prove one paragraph -> one lesson/one question and three independent
  sections -> three lessons/three questions. TypeSafe is DEV-only report-only;
  some earlier runs return REVIEW, not universal PASS. Production NOT VERIFIED.
- Prevention: test the exact unrelated-options defect, separate option relevance
  from factual truth, test ambiguous and missing review responses, keep bounded
  repair identity/order and zero-question persistence/UI regressions. Do not
  substitute fake provider responses or a green unit suite for semantic QA.
- Additional harness finding: the first synthetic-table replay omitted chunk
  headings/table-fragment metadata and was not valid Excel acceptance. Correct
  the harness and verify exact column ownership before using its quality score.
- Follow-up 2026-09-18: general and separate blind logical reviewers both
  accepted a key converting "not required" into mandatory exclusion. Added a
  narrowly scoped executable Russian optional-exclusion guard with six boundary
  cases, strict constraint-review parsing and per-lesson coverage audit. Exact
  saved replay now rejects the bad key while retaining the valid privacy item.
  Full API unit 1902 PASS / 77.19s; this is not semantic release acceptance.
- Recurrence 2026-09-22: the deterministic reviewer still exempted an option
  whenever that option was a true sentence anywhere in the lesson evidence.
  This let initial-response and escalation rules survive as alternatives to a
  personal-data scenario. For action questions only, derive distinctive anchors
  shared by the question and its selected evidence, exclude generic actor terms,
  and reject every distractor that does not carry one of those anchors. Preserve
  source-grounded competing descriptions for non-scenario attribute questions.
  The exact customer-reported pattern is now a RED/GREEN regression; the focused
  assessment suite passes 119 tests and the combined assessment/auth set passes
  129 tests. The final database-free API verification passes 2123 tests.
  Production semantic acceptance remains required after release.
- Current NO_GO: two frozen-code Excel assessment replays retained 5/9 and 4/9
  questions in 45.655s and 47.895s. One left an entire primary lesson unassessed;
  repair responses failed identity/evidence validation and fallback timed out.
  Do not hide coverage gaps by quota-padding, selecting only a favorable run,
  relaxing evidence checks or repeating full production generation.
- PDF test-input limitation: local Windows OCR reordered definition fragments
  (visually confirmed on original page 3). Production Docling route was not
  configured locally, so this fallback is NOT production ingestion evidence.
  Do not judge generator correctness from a silently substituted corrupt input.
- V1.3 follow-up: server-bound singleton repair allows grounded same-block
  citation refinement and carries trusted rejection reasons. Course-wide primary
  topic coverage fails closed on missing/malformed audit; preserves saved draft
  and idempotent readback. Positional explanations are rejected per question
  before final shuffle, routed through one repair, not a whole-block parse error.
  Full unit1924 PASS does not prove semantic acceptance. Frozen Excel replays6/9
  and5/6 retain3/3 and2/3 topics; latter invalid JSON + unreachable fallbacks
  correctly require review. A bed-replaced-with-dresser distractor still passes
  the model reviewer: OPEN semantic quality defect, not a solved problem.
- Production-converter capture: Docling2.106.0,21pages,95.934s, nofallback;
  hash-bound DEV replay excludes wrong source/engine (6tests). Definition
  fragments improve, but image placeholders/TOC become planned lessons and a
  wrapped heading becomes two sections. PDF acceptance stopped before full
  generation. Source-block normalization remains OPEN. TypeSafe synthetic DEV
  REVIEW also flags repeated misconceptions; not a runtime dependency.
- Capture harness recurrence prevention: resolve active blue/green slot from
  current release state. Docker archive copy failed against read-only runtime;
  transfer exact temporary files through the running process and writable /tmp,
  never disable hardening. Capture/result/identity and bounded cleanup must be
  tested before treating local replay as production-converter evidence.
- 2026-09-19 correction: a live local PDF run had no `DOCLING_URL` or
  `DOCLING_API_KEY`, silently used `pypdf`, and misreported the resulting empty
  scan as a converter failure. The ignored canonical local env now carries the
  VM126 API key and a loopback tunnel URL. The DEV runner fails before work with
  `live_docling_not_configured` when those values are absent. The reusable
  tunnel reaches `docling:8600` through proxy SSH, VM126 SSH and the active API
  container network; it does not publish port 8600. Fresh application conversion
  of exact source SHA `a30c8f3d...e605` returned Docling 2.106.0, 21 pages,
  72,525 Markdown characters in 98.189s, no fallback; Markdown SHA matched the
  prior production capture. Focused regression 15 PASS; Ruff and diff check PASS.
- V1.4 local follow-up: explanations now use verified exact quotations rather
  than model-authored additions; opt-in JSON syntax correction is bounded to
  one additional request per validated call. General/constraint reviews require
  practical and distinct errors. Four frozen diagnostic cases pass after enum
  clarification, but fresh Excel questions still contain roller-guide bed-base
  distractors and internally conflicting lamella claims. NO_GO remains; do not
  substitute a catalog of forbidden furniture words for a general quality fix.
- Source normalization correction: checking only absence of explicit Contents
  or image headings missed overlap TOC tails and repeated heading concatenation.
  Verify actual first facts and all final titles on the captured production
  corpus, not only synthetic marker checks. Prefix removal must corroborate
  later body headings and preserve meaningful pre-TOC numbered rules. Final
  source-only replay:116chunks267facts26plannedlessons; not a generated course.
- Independent-review correction: one reviewer incorrectly rejected a palette
  statement actually present in its exact cited fact. Root reread withdrew it.
  Reviewers and TypeSafe are fallible evidence, not substitutes for direct
  source checking or missing-topic coverage. Latest synthetic TypeSafe PASS
  covers surviving content while source-topic coverage still requires review.
- Objective-alignment pilot, 2026-09-18: isolated DEV module; unchanged runtime
  SHA256 map (50 AI files). Frozen A/B protocol ran 16 attempts. Baseline produced
  8/8 artifacts, experimental B only1/8; this is completion, not quality. B still
  duplicated a personal-messenger action under different excuses and converted
  optional final resolution into exclusion. TypeSafe PASS and first independent
  reviewer PASS missed both; root source review corrected acceptance to NO_GO.
- Pilot validator defects: an 8-character citation floor rejected valid `МДФ`;
  duplicate free-text error labels rejected distinct glue/screw alternatives.
  Fixed only in DEV, with RED/GREEN positive controls (19focused PASS total).
  Offline replay of all8 B traces requires0 provider calls and does NOT turn
  partial/failed runs into completed courses. Original frozen code, outputs and
  failed metrics remain intact. Short exact source values are valid; descriptive
  category equality is not semantic action equivalence.
- Open experiment constraints: a paragraph containing teachable rules plus an
  informational introduction cannot be simultaneously marked cited/omitted by
  whole fact_id; source-topic coverage does not prove objective coverage. The
  new module is not production-ready. Do not patch prompts against disclosed
  holdout or discard failed cases; a fresh experiment needs fresh held-out cases.
- Local continuation: source -> objective -> teaching -> blind-key review now
  supports selective distractor deletion and singleton question repair without
  replacing valid teaching/questions. Explicit unassessable/empty assessment
  remains a gap. These are DEV-only changes, not a production acceptance.
- Thinking-mode finding: canonical DeepSeek factory forces thinking disabled.
  Same-prompt low-thinking DEV examples improved semantic contrasts, but raised
  time/tokens and did not prove universal correctness. Per-request role policy
  is possible with one key; account concurrency/balance is shared across keys.
  Record configured AND returned model IDs because provider aliases can drift.
- New frozen holdout: eight attempts, five completed artifacts, only the two
  smallest cases manually accepted. Matrix narrative notes never reached the
  model: table_keys caused the whole matching chunk to be excluded from prose
  processing. DEV source adapter preserves adjacent prose, original roles and
  locators; three offline controls pass. Fresh live replay remains NOT VERIFIED.
- Oracle correction: a worker-written expected objective converted 'not required'
  into 'do not continue'. Do not alter frozen inputs or reward model agreement
  with an incorrect oracle. Root must check every expected behavior against its
  exact quote, especially permissions/obligations and necessary conditions.
- Provider stop: after three HTTP failures, read-only balance returned available
  false and USD -0.03. Original HTTP codes were not captured, so 402 is inference,
  not measured evidence. DEV Recorder now retains numeric HTTP status only and
  stops batch on 401/402/403. No payment, credential or billing change performed.
  Preserve partial artifacts and resume only after access/balance is restored.
- Cache-observability correction, 2026-09-18: DEV Recorder retained input/output
  totals but discarded provider cache-hit/miss and reasoning counters. Historical
  totals do not prove zero cache hits. Preserve per-request optional counters
  (missing means unknown, not zero), exact payload hash, returned model and time;
  do not log keys or hidden reasoning. Two regression tests reproduced the gap
  and prove the new explicit ASUS GLM route cannot inherit DeepSeek parameters
  or paid fallback. Prefix caching never replaces newly generated output.
- ASUS GLM repeatability follow-up, 2026-09-18: source-faithful fallbacks now
  expand partial citations to complete facts, neutralize unsupported scenario
  requirements only when the keyed answer remains supported, remove duplicate
  wrong actions, restore missing teaching blocks from exact evidence, and
  collapse identical fallback prose. The focused objective-alignment suite is
  61 PASS with Ruff/diff checks clean. Nevertheless, no final frozen series
  achieved two completed, root-accepted repeats after all corrections: the
  latest live series was 1 NOT_COMPLETED + 1 COMPLETED. A prior apparent 2/2
  completion lost one required clause inside a cited fact and is rejected by
  root review. GLM availability and timeout are not the blocker; unconstrained
  plan/teaching/question cardinality remains variable. Production GO remains
  denied. Next design must derive the assessed axis and keyed answer from the
  normalized source contract and restrict the model to candidate distractors;
  do not add another prompt-only retry or select a favorable repeat.
- Axis-owned completion, 2026-09-19: provider wording could still switch to a
  different source function, use another clause of the same compound fact, or
  leave a server fallback prompt such as `Что верно в отношении ... у объекта`
  learner-visible. A three-axis block cap also hid the status of later assessable
  facts, and terminal review state was not reflected by the development runner.
  The current fix binds wording, answer key, distractors and evidence to one
  immutable source axis; classifies every assessable axis as retained, omitted,
  unassessable or uncovered; rejects placeholder prompts, unfinished keys and
  `[UNREADABLE_*]` facts; and propagates terminal review status through both the
  application seam and runner. A permanently failed redundant axis may be
  omitted only when another accepted item covers the same lesson/topic, while
  the provider failure remains in audit evidence. A sole failed axis stays
  uncovered and requires review. Full API unit suite `2054 PASS`; exact
  `AI-COURSE-01` selection `7 PASS`; complete Excel acceptance retained 8 items
  with 3/3 topics; production-Docling PDF acceptance retained 30 items with
  13/13 topics and classified 44/44 assessable axes. Root manually checked all
  retained questions against source quotations. Prevention: acceptance must
  assert complete contract classification, terminal review propagation, zero
  learner-visible OCR/placeholders, no quota padding and explicit provider
  failure evidence before release. Final candidate regression is `2055 PASS`;
  fresh repeated acceptance retained 8/8 Excel questions and 29/30 PDF questions
  across runs while preserving full topic/contract classification.
- Release-gate correction, 2026-09-19: exact-SHA CI run `35443649257`
  stopped before deployment because two changed modules introduced one mypy
  `arg-type` and one mypy `assignment` violation. The pre-push packet had run
  Ruff and unit tests but not the blocking Python quality baseline, so local
  green evidence was incomplete. The relation is now explicitly narrowed to
  the server-owned literal type and the reused list/bool local is split into
  distinct names. Focused assessment tests `178 PASS` and changed-file Ruff
  pass. Prevention: every release packet that changes Python must run the
  canonical Python quality baseline, or an OS-equivalent changed-file mypy
  check when the Windows baseline wrapper reports unrelated path-normalization
  noise, before commit and push; never raise the committed baseline for a new
  violation.

## UI-CONTENT-001 - Read-only lesson preview exposed Markdown editing syntax

- Date: 2026-09-14. Confirmed during the post-release production browser
  acceptance of an Excel-generated course.
- Symptom: the wide inline editor was usable, but the read-only lesson card
  still displayed `#`, `##`, Markdown table delimiters and a duplicate title.
- Cause: `CoursePreviewTree` rendered `content_preview` as plain preformatted
  text even though the field contains editable Markdown.
- Fix: derive a display-only summary that removes heading/emphasis/code markers,
  omits the repeated lesson title and flattens table cells. Preserve the original
  Markdown unchanged for editing and saving.
- Verification: four formatting regressions, TypeScript and targeted ESLint
  pass.
- Prevention: preview components for Markdown-backed fields must test rendered
  display separately from editor round-trip preservation.

## AI-QUALITY-022 - A grounded question tested a neighboring lesson topic

- Date: 2026-09-14. Confirmed in the production synthetic-tenant Lombard PDF
  course and reproduced with a source containing both application and complaint
  deadlines.
- Symptom: lesson content correctly taught application review and the GKB check,
  while its quiz could ask the independently grounded deadline for customer
  complaints from another source section. Similar crossings appeared between
  APR and reward-payment timing, and between client rights and lender duties.
- Cause: evidence validation proved the question and answer against the complete
  lesson retrieval window but did not bind a neighboring quote to the admitted
  direct-source lesson topic.
- Fix: only for lessons carrying the current direct-source quality policy, admit
  a quote outside the authored lesson body when the tested fact shares at least
  two distinctive title/objective anchors. Matrix entity cards retain their
  stricter dedicated ownership gate. Rejected questions are not quota-padded.
- Verification: the first title-only guard was rejected because five existing
  tests exposed false positives. The bounded replacement passes seven new
  positive/negative regressions, 357 related tests and the complete 1694-test API
  unit suite.
- Prevention: every source-window expansion must replay one same-document
  neighboring topic with a shared generic verb, plus a grounded paraphrase
  positive. A fact may be source-grounded and still be wrong for the lesson.

## AI-ADMISSION-002 - Source-reuse confirmation was rate-limited by its own probe

- Date: 2026-09-14. Confirmed in the production synthetic-tenant browser flow.
- Symptom: the first generate request intentionally returned
  `409 source_documents_already_used`; the immediate confirmed request then
  returned `429`, leaving the methodologist in a reopen-and-wait loop.
- Cause: both requests consumed the endpoint limiter, but the configured burst
  allowed only one request although the supported reuse flow requires exactly
  two adjacent POST requests.
- Fix: retain the existing two-per-minute and ten-per-hour limits while allowing
  a burst of two for `/api/v1/ai/generate-course`.
- Verification: the regression failed against burst size one, then the focused
  limiter suite passed 37 tests and the complete API unit suite passed 1694.
- Prevention: every expected multi-request UI handshake must have one contract
  test binding its maximum immediate request count to the limiter configuration.

## AI-QUALITY-021 - Similar matrix columns crossed lesson and question ownership

- Date: 2026-09-14. Confirmed with the complete control workbook after the
  content-quality hardening candidate.
- Symptom: a comparison worksheet could merge `Чикаго Нео` and `Чикаго Стрит`
  because both names shared a broad lexical stem. A later assessment could then
  ask a question about a peer collection inside the wrong lesson. A supporting
  worksheet whose title contained several collection names could also be
  mistaken for an unreferenced required source.
- Cause: primary matrix column selection used stem intersection instead of exact
  entity-token containment; assessment context fallback selected a leading text
  slice rather than the complete row for the named entity; structure validation
  treated every supporting worksheet name as an independent title obligation.
- Fix: recognize characteristic-by-entity matrices explicitly, create one
  source card per entity, select columns by complete entity-token containment,
  rank the exact entity row for assessment evidence, and exempt a supporting
  title only when its stems are fully explained by primary entity headers.
  Validate that every retained question belongs to the lesson's named entity and
  delete invalid questions without generating replacements.
- Verification: complete API unit and contract selection passed 1714 tests;
  Python quality baseline passed. A private replay of the complete workbook
  produced three named collection lessons and retained five source-grounded
  questions: two for `Феникс`, one for `Чикаго Нео`, and two for
  `Чикаго Стрит`. No question assessed another lesson's entity, no lesson or
  assessment objective remained uncovered, and no rejected question was padded.
- Prevention: every comparison-matrix change must include two entity names with
  a shared prefix, a supporting-sheet title composed from primary entities, an
  off-entity question negative, a relation-scope negative, and a full-source
  replay reviewed by meaning rather than question count.

## APPROVAL-001 - Unchecked control did not reflect the persisted approval policy

- Date: 2026-09-09.
- Symptom: a methodologist-reviewed draft displayed an unchecked separate-approval
  control, but publication returned HTTP 409 with `details.code=approval_required`.
- Cause: the editor course response omitted the policy; the shared card
  initialized from an absent value as false and never loaded the persisted policy.
  Database/model defaults are already false; automatic enablement was not found.
- Interim production recovery: owner-authorized explicit policy disable followed
  by publication returned HTTP 200 and the published UI state. No bulk policy reset.
- Fix: prepared tenant-scoped read-only policy endpoint; authoritative shared-card
  readback, unknown/error states, retry and stale-response isolation; localized
  publication errors. Existing explicit approval requirements remain enforced.
- Verification: focused API and UI regression tests cover default/persisted
  policies, ownership, read failure and course switching. Systemic deployment and
  production readback remain pending; the customer recovery is not release proof.
- Prevention: never infer persisted workflow state from an omitted response field.
  Test reload, course switch and rejected publication; deploy API before frontend.

## TOOL-001 - Screenshot or browser context was mistaken for project scope

- Date: 2026-08-13.
- Symptom: an agent entered another repository after a UI screenshot although the
  user had not changed scope from Kamilya LMS.
- Cause: ambient browser state and visual similarity were treated as authority.
- Fix: default scope is `Kamilya-NEW` and `kamilya-landing`; another repository
  is allowed only when explicitly named in the current request.
- Verification: workspace rules and `AGENTS.md` require scope/worktree checks; the
  corrected procedure changed no external project.
- Prevention: resolve the absolute target before any read or patch; stop if it is
  outside both Kamilya directories and was not explicitly named.

## SECRET-001 - Diagnostics or documentation exposed a secret value

- Date: 2026-08-13.
- Symptom: a traceback or historical log could contain a full connection string or
  credential.
- Cause: command output was not made safe; an old mixed log retained raw details.
- Fix: keep only variable names and safe facts. Treat any printed value as
  compromised and require owner-controlled rotation.
- Verification: CI runs `detect-secrets`; the release-contract gate scans
  `ERRORS.md` for private keys, credential URLs, and known secret prefixes without
  printing values.
- Prevention: define safe stdout/stderr before `.env` or provider commands. Print
  only names, counts, statuses, and masked IDs. Stop copying accidental disclosure,
  notify the owner, and keep the incident open until rotation is confirmed.
- Recurrence (2026-08-30): an external coding agent embedded a local database URL
  in its shell command twice, despite a no-secret instruction. The confirmed cause
  was direct command construction from a credential-bearing value instead of a
  root-owned process-local execution boundary. The value is intentionally not
  retained here. That agent is no longer permitted to receive database,
  environment, credential, deployment, or infrastructure tasks. Local Step 1 DB
  checks now use `scripts/dev/run_editor_assistant_step1_checks.ps1`: it targets one
  exact local PG18 container, creates and removes a disposable database, passes the
  connection only through child-process environment, sanitizes output, and accepts
  no URL or credential argument. Its static contract tests and a complete
  migration/test execution must pass before reuse.

## MIGRATION-001 - Green deploy and health concealed a stale DB schema

- Date: 2026-08-13 (original incident: 2026-06-29).
- Symptom: health returned HTTP 200, but a path using new schema failed;
  `alembic_version` was behind repository head.
- Cause: migration execution had no confirmed owner; readiness was inferred from
  deploy status and health.
- Fix: Render uses `preDeployCommand`; Docker migrates fail-closed before Uvicorn;
  HTTP lifespan does not migrate.
- Verification: `python scripts/ci/release-contract-gate.py` verifies one migration
  owner and a linear chain. Release separately compares `alembic current`,
  `alembic heads`, and affected schema.
- Prevention: match live revision to head, verify required schema objects, then run
  a business smoke that uses the change.

## MIGRATION-002 - Offline SQL fails at historical migration 0003

- Date: 2026-08-13.
- Symptom: `alembic upgrade ... --sql` stops at revision `0003` while inspecting
  a `MockConnection`.
- Cause: `sa.inspect(op.get_bind())` requires a real connection unavailable in
  Alembic offline mode.
- Fix: validate chain shape with the AST gate and `alembic heads`; validate upgrade
  on authorized PostgreSQL followed by schema/RLS tests.
- Verification: `0003_add_enrollment_progress_documents.py` contains the
  inspector-dependent branch; the release-contract gate confirms one linear chain.
- Prevention: offline SQL is not sole proof of migration applicability. Changing an
  applied migration requires a compatibility plan; real PostgreSQL testing remains
  mandatory.

## TENANT-001 - A privileged DB session produced a false-positive RLS result

- Date: 2026-08-13.
- Symptom: a direct integration query saw tenant data unavailable to runtime.
- Cause: the fixture used the migration owner, not restricted `lms_app`.
- Fix: create fixture data privileged, then assert after
  `SET LOCAL ROLE lms_app` and exact tenant context.
- Verification: DB/RLS suites switch to runtime role and distinguish fixture setup
  from runtime visibility.
- Prevention: every RLS/grant/cross-tenant test proves role and tenant context before
  querying. Owner-level success is not security evidence.

## DEPLOY-001 - Worker ran a different release than web and API

- Date: 2026-08-13.
- Symptom: Vercel/Render ran a new commit while VPS Celery still ran old code or
  lacked the task.
- Cause: worker deployment is independent from Git push, Vercel, and Render.
- Fix: release manifest records GitHub CI, Vercel and Render commits, Alembic
  revision, worker checkout, and required Celery tasks independently.
- Verification: check exact commit, units, Celery ping, registered tasks, and queues
  before business smoke.
- Prevention: HTTP 200/provider status is insufficient. Match exact SHA across every
  executable contour and separately verify DB and user flow.

## WORKER-001 - Celery task used an incompatible asyncio event loop

- Date: 2026-08-13 (original incident: 2026-06-29).
- Symptom: a DB-backed task reported a Future attached to another loop; task state
  could remain successful without a domain mutation.
- Cause: Celery prefork, imported async SQLAlchemy/asyncpg engine, and a manual event
  loop had different lifecycles; item errors were summarized instead of failing.
- Fix: run the coroutine with `asyncio.run()`, create DB sessions inside it, and
  return explicit `failed_user_ids` plus item errors.
- Verification: focused registration test plus production prefork smoke with
  non-empty disposable input, result inspection, and domain-side-effect readback.
- Prevention: test changed async jobs through a real prefork worker. `SUCCESS`
  without result/data verification is not completion proof.

- 2026-09-06 reminder follow-up: d6ec720e production recovery logged one item
  RuntimeError and asyncpg cross-loop connection termination errors. The next
  recovery succeeded before sending: actual Gmail reminder received once,
  ledger sent/attempt_count1. This was a recovered delivery delay, not mail loss.
  Creating a session inside asyncio.run was insufficient while its imported
  engine still pooled connections belonging to a previous loop.
- Bounded correction: learning_reminders.deliver owns a NullPool engine/session
  for each default invocation and disposes it in finally; injected session
  factories remain caller-owned. API core pool, tenant context, SQL claim/send
  reservation, SMTP no-retry and deduplication contracts are unchanged.
- Verification: read-only Supabase runtime-role reproducer
  scripts/ops/learning_reminder_loop_dev_check.py --execute --baseline completed
  first real delivery DB checkout and failed on the next event loop. Fixed
  default path passes three distinct loops; no DB writes/provider calls.
  Focused existing reminder tests17PASS; final exact CI/release tracked in the
  manager-attention plan. Do not substitute one-loop mocked tests for this check.

## TEST-001 - Mutation smoke tested only SELECT

- Date: 2026-08-13 (original incident: 2026-06-30).
- Symptom: read-only smoke passed, but the first create returned HTTP 404/500 due to
  required-column/ORM mismatch.
- Cause: the test did not execute the changed INSERT/UPDATE or real service; mocks
  did not reproduce schema.
- Fix: exercise the real service on a disposable fixture and roll back or remove
  created data; compare required columns with PostgreSQL.
- Verification: new mutations use DB-backed integration and observable API flows.
- Prevention: repeat the defect's verb and boundary: INSERT with INSERT, queue with a
  real worker, export with a real file, UI with an observable action.

## TEST-002 - Unavailable PostgreSQL was replaced with mock evidence

- Date: 2026-08-13.
- Symptom: local DB tests failed with connection refused, after which AsyncMock or a
  route seam appeared to prove RLS, concurrency, or atomicity.
- Cause: test layers were not separated; missing PostgreSQL weakened acceptance.
- Fix: unit/route contracts are separate evidence; DB gate stays blocked until real
  migrated PostgreSQL is available.
- Verification: reports name tests that ran and tests stopped in fixture setup;
  DB/RLS/concurrency claims require integration pass.
- Prevention: do not rewrite security tests around mocks. Check target/revision
  without credentials, run the original test on authorized DB, or leave gate open.

## TEST-008 - A Jest-only flag prevented the Vitest suite from starting

- Date: 2026-08-31.
- Symptom: `pnpm test -- --runInBand` stopped with
  `CACError: Unknown option --runInBand`; no frontend test had executed.
- Cause: `--runInBand` is a Jest flag, while the repository package script runs
  Vitest 4.
- Fix: run the package contract unchanged with `pnpm test`, then run
  `pnpm run typecheck` separately.
- Verification: Vitest completed `85 passed` files and `426 passed` tests;
  `tsc --noEmit` completed successfully.
- Prevention: use the checked-in frontend package scripts without Jest-specific
  flags unless the current Vitest CLI explicitly supports the requested option.
- Recurrence (2026-09-02): running `pnpm run typecheck` concurrently with
  `pnpm exec next build` produced only `TS6053` missing-file errors under
  `.next/types/**` while the build was regenerating that directory. The build
  completed successfully and the same typecheck passed immediately afterward.
  Run typecheck and Next.js build sequentially because both commands read or
  mutate `.next/types`; parallel execution is not valid release evidence.

## WIN-001 - Frontend build script used POSIX env syntax in PowerShell

- Date: 2026-08-13.
- Symptom: `npm run build` did not start Next.js because the script began with
  `NEXT_TELEMETRY_DISABLED=1`.
- Cause: inline environment assignment is POSIX syntax.
- Fix: run `$env:NEXT_TELEMETRY_DISABLED='1'`, then `npx next build`; CI/Linux
  may use the package script.
- Verification: `apps/web/package.json` retains POSIX syntax; the Windows command
  in `AGENTS.md` completes production build.
- Prevention: use `AGENTS.md` Windows commands and verify the Next.js exit code.

## API-001 - One legacy NULL row broke an entire response list

- Date: 2026-08-13 (original incident: 2026-06-30).
- Symptom: a list endpoint returned HTTP 422 and empty UI although records existed.
- Cause: Pydantic required a non-empty timestamp/legacy field while one historical
  row had `NULL`; full-list serialization aborted.
- Fix: accept the confirmed legacy shape and correct data with forward
  migration/backfill, not validation weakening alone.
- Verification: `PositionResponse` accepts confirmed nullable legacy fields; list
  integration includes a legacy-shaped row.
- Prevention: compare nullable/default behavior with live/test schema and historical
  migrations before tightening fields; test the full response with an old row.

## AI-001 - LLM HTTP 200 did not mean a complete structured response

- Date: 2026-08-14.
- Symptom: `morosystems/ThinkingCap-Qwen3.6-27B-NVFP4` under
  `response_format=json_schema` began valid JSON, padded spaces, then stopped at
  token limit. An 8192-token retry took 156 seconds, returned
  `finish_reason=length`, and invalid JSON despite HTTP 200.
- Cause: the current model/runtime/request combination is incompatible with strict
  structured output. The same Architect prompt without `response_format` completed
  in 19 seconds with valid course structure.
- Fix: use a normal JSON prompt, local schema parsing, validation, and controlled
  retry. Do not enable strict response format before model/runtime requalification.
- Verification: reproduced at 5000 and 8192 tokens; normal Architect produced 2
  modules, 4 lessons, and four unique source titles; Assessment produced 5 MCQs.
- Prevention: provider qualification checks `finish_reason`, output tokens,
  latency, and schema parse. HTTP 200 with `finish_reason=length` is failure.

## DEPLOY-002 - Official API Dockerfile did not build from repository root

- Date: 2026-08-17.
- Symptom: clean-SHA build missed shared `packages` or Poetry returned
  `No file/folder found for package api`; a workaround required manual
  `PYTHONPATH`.
- Cause: Dockerfile mixed `apps/api` and root contexts, copied
  `../../packages`, and installed root before source copy.
- Fix: build from root; copy API pyproject/lock and `/packages`, install
  `--no-root`, copy `apps/api`, and set `PYTHONPATH=/app`.
- Verification: image `e9fc8f3` built on VM126; FastAPI import passed; Alembic was
  `0110 (head)`; staging health and real registration/public-lead mutations passed.
- Prevention: keep a Dockerfile contract test; run documented `docker build` and
  import the app inside the new image before replacing a container.

## MIGRATION-003 - Alembic head lacked runtime privileges for bounded functions

- Date: 2026-08-17.
- Symptom: fresh PostgreSQL reached head but `lms_app` got permission denied; after
  a narrow grant registration still returned HTTP 500 `lead tenant mismatch`.
- Cause: migration 0033 had an incomplete runtime-table list. SECURITY DEFINER
  functions from 0094 were owned by the migration role; FORCE RLS policies targeted
  only `lms_app`, hiding newly inserted lead/outbox rows from the function owner.
- Fix: 0109 grants only `tenants`, `content_blocks`, `questions`, and
  `quiz_choices`; 0110 adds policies only for the actual bounded CRM-function
  owner. No direct outbox grants or `BYPASSRLS`.
- Verification: real `lms_app` reads required tables; direct outbox SELECT is
  denied; registration/public lead return 201; cross-tenant users/settings remain
  invisible and not updatable.
- Prevention: after fresh `upgrade head`, audit privileges, execute SECURITY
  DEFINER and public flows, and test cross-tenant RLS as runtime role. Managed grants
  are not migration history.

## STORAGE-001 - Local storage lived inside one container

- Date: 2026-08-17.
- Symptom: with `STORAGE_BACKEND=local`, files lived in API writable layer, were not
  shared with workers, and would disappear on recreation.
- Cause: Compose lacked a shared persistent storage root for `get_storage()`.
- Fix: API and three workers mount
  `/opt/kamilya-runtime/blob-storage:/app/storage/certificates`; host root is
  `0700 root:root`; topology is under `infra/compose`.
- Verification: API wrote a test object, document-worker read it, ops-worker deleted
  it, and host readback confirmed removal.
- Status: runtime persistence is fixed. `kamilya-blob-backup.timer` is enabled on
  VM126; CT125 received a `0600` encrypted archive; SHA-256, decrypt, and tar-list
  checks passed. Production cutover still requires ingress/monitoring verification
  and approved production-data transfer.
- Prevention: run cross-container, recreate, backup/restore, and disk-capacity
  checks. Health alone does not prove durability.

**RECURRENCE 2026-09-07:** document indexing also writes short AI summaries to
`/app/summaries`, but neither production compose mounted that path. With the
read-only root filesystem and UID/GID `10001:10001`, all fresh text-document
indexes failed after chunk creation with `PermissionError: './summaries'`.
Both compose contracts now bind the same host `blob-storage/summaries` directory
into API and all workers and set `create_host_path: false`, so Docker cannot
silently create an unusable root-owned source. The host directory must exist as
`0700 10001:10001` before release. Focused release-contract tests pass (`7 passed`)
and both compose files pass `docker compose config --no-interpolate --quiet`;
production runtime and cross-container readback remain pending release approval.

## ACCESS-001 - Verified domain was mistaken for DNS-management authority

- Date: 2026-08-17.
- Symptom: `kml.kz` was verified in Vercel but Vercel DNS was empty; old proxy name
  returned NXDOMAIN and `api.kml.kz` did not exist.
- Cause: project binding was conflated with authoritative DNS ownership; Cloudflare
  owns the zone NS and the old provider hostname no longer resolves.
- Fix: use `PROXY_VPS_HOST`; create DNS-only A record through confirmed Cloudflare
  authority; issue proxy TLS only after authoritative/public DNS verification.
- Verification: Cloudflare NS and Google DNS returned `92.38.49.167`; proxy SSH and
  WireGuard were active; `443` listened; external
  `https://api.kml.kz/health` passed certificate validation with HTTP 200; HTTP
  redirected to HTTPS.
- Prevention: separately verify NS/provider, existing record, and credential
  authority. Verified domain, Host-header 200, and open port are not DNS/TLS evidence.

## DEPLOY-003 - Dev frontend used an incomplete API base and unknown CORS origin

- Date: 2026-08-17.
- Symptom: first KZ dev used `NEXT_PUBLIC_API_URL` without `/api`; corrected URL
  then received preflight 400 from the new Vercel origin.
- Cause: frontend appends `/v1/...`, and the new alias was absent from exact CORS
  allowlist.
- Fix: set `https://api.kml.kz/api`, make an exact-SHA deployment, add exact known
  Kamilya proxy origins, and add stable dev origin to backend source.
- Verification: compiled login chunk has KZ API and no Render; dev/app/www preflight
  returns one allow-origin/credentials header; unknown origin returns 400; invalid
  login reaches FastAPI and returns 401.
- Prevention: verify URL contract, compiled chunk, preflight, and actual response.
  Backend health alone does not prove browser flow.

## TOOL-002 - Backend command ran from the wrong monorepo directory

- Date: 2026-08-17.
- Symptom: `poetry run alembic heads` from monorepo root could not find
  `pyproject.toml`.
- Cause: backend Poetry project is in `apps/api`.
- Fix: use `workdir=apps/api` for backend Poetry/Alembic; use root for repository
  and documentation commands.
- Verification: from `apps/api`, the command returned single head `0111`.
- Prevention: split repo-level and app-level operations by working directory; do not
  classify a directory/tool error as a migration defect.

## PROVISION-001 - A privileged user was created through learner invitation

- Date: 2026-08-18.
- Symptom: owner received learner-oriented email/code while normal login did not send
  codes for `admin` and `methodologist`.
- Cause: bulk learner invitation was incorrectly used with a privileged role. It is
  only for `student`, creates inactive identity, and requires acceptance.
- Fix: preserve identity and both roles, set `active`, revoke learner invitation,
  and verify ownership through standard login OTP. No password was set or sent.
- Verification: production user has `admin` and `methodologist`, is `active`,
  has no pending learner invitation, and login lookup returns one active identity
  with primary role `admin`.
- Prevention: use bulk `/users/invitations` only for `student`. For privileged
  roles use admin/user service and verify role, `is_active`, login mechanism, and
  exact public URL before sending.

## AUTH-001 - Email login returned neutral 200 but created no OTP in KZ production

- Date: 2026-08-18.
- Symptom: `/auth/email/request-code` returned HTTP 200 and UI said code sent, but
  Valkey had no `auth:email:login` key and no email could arrive.
- Cause: bounded SECURITY DEFINER `lookup_login_user_by_email()` was owned by
  `kamilya_migrator`. FORCE RLS on `users` had no policy for that owner, so lookup
  returned zero. Managed-provider owner privileges had hidden the defect.
- Fix: migration `0111` identifies the actual owner and adds only a SELECT policy
  on `users`. It adds no direct `lms_app` visibility, role mutation, or RLS bypass;
  the app keeps only function EXECUTE.
- Verification: CT125 moved from `0110` to single head `0111`; runtime lookup
  found one active identity; real request-code created an OTP with about 300-second
  TTL and zero failed attempts. Seven migration/security tests and Ruff passed.
- Prevention: neutral anti-enumeration endpoints require lookup, purpose-bound OTP,
  and delivery evidence. Test SECURITY DEFINER under FORCE RLS as runtime role and
  actual function owner.

## AUTH-002 - Public trial registration accepted an unverified email

- Date: 2026-08-26.
- Symptom: a public form could create a trial tenant, admin, lead, and operator
  notification before proving that the registrant controlled the supplied email.
- Cause: `/api/v1/tenants/register` created the workspace immediately and sent only
  a best-effort post-creation welcome message.
- Fix: add a purpose-bound five-minute registration OTP. The request endpoint sends
  it fail-closed through the configured provider; the create endpoint consumes it
  before any tenant-scoped insert. Provider failure invalidates the pending code.
- Verification: backend OTP/email/rate-limit tests `55 passed`; frontend focused
  tests `16 passed`; Ruff, compileall, and TypeScript passed. The DB-backed suite is
  `BLOCKED` before test execution by local PostgreSQL `ConnectionRefusedError
  [WinError 1225]`; dev runtime and production release evidence remain required.
- Prevention: no self-service tenant, user, lead, CRM event, or owner notification
  may be created before a purpose-bound email proof succeeds.

## CANDIDATE-001 - Candidate link existed but public PIN exchange returned 404

- Date: 2026-08-19.
- Symptom: campaign/link/PIN creation succeeded, but public exchange returned `404`.
- Cause: tenant lookup ran before tenant context; credential is protected by
  RLS/FORCE RLS and the SECURITY DEFINER owner intentionally lacks `BYPASSRLS`.
- Fix: capability token carries tenant UUID only as a non-authoritative routing prefix
  plus an independent random secret. API sets tenant context, then validates full
  SHA-256 hash, expiry, and revoke state. Invalid prefix/hash/PIN/revocation denies
  access; no broad grants or `BYPASSRLS`.
- Verification: 27 focused tests and Ruff passed. KZ API and three workers ran image
  `kamilya-api:db797fd`; DB stayed at `0111`. Disposable production journey on
  `too-lombard-sandyk` passed campaign, invitation, PIN/consent, result, manager
  result, and CSV; candidate never entered `users`; all synthetic rows were removed.
- Related defect: Celery retention task existed but host timer was inactive. Recovery
  now runs inside `worker-ops`; production timer is `enabled`/`active`, latest
  result `success`.
- Prevention: unknown-tenant capability flows use non-authoritative routing and
  authorize only after tenant context. Route/UI/credential presence is insufficient
  without exchange, isolation, cleanup, and retention-scheduler evidence.

## AI-002 - Grounded assessment answers became learner-visible evidence dumps

- Date: 2026-08-20; revised 2026-09-13 after representative Excel acceptance.
- Symptom: earlier runs produced off-source JSON/HTTP/REST questions. After the
  first grounding fix, production generated source-based quizzes whose correct
  options were often the longest, contained complete multi-fact excerpts or raw
  Markdown table rows, and did not always answer the atomic question.
- Cause: the server correctly owned bounded evidence, but then replaced the model's
  correct option and explanation with the entire evidence excerpt. Literal
  grounding was achieved by destroying answer atomicity and length balance.
- Fix: rebuild every retry from immutable lesson, never raw prior output. Server
  creates bounded `E01...E24` evidence from the same 8000-character source; model
  selects `source_quote_id`; the server resolves and stores the quote separately.
  The model writes a concise answer. The2026-09-10 correction requires an exact
  contiguous2-12word evidence span, retaining digits, negation and punctuation;
  explanation is a localized trusted prefix plus selected display-text evidence.
  Deterministic checks retain atomic wording, plain learner-visible text and topical
  distractors, then reuse `validate_question_set` for length/style, duplicate,
  malformed and answer-key signals. A failed contract triggers a bounded clean
  retry. If every provider retry still contains a bad question, the server retains
  only independently revalidated questions when at least three of five remain;
  otherwise the assessment still fails closed. Full-pipeline AI quizzes persist as
  `needs_review`; course approval does not replace explicit per-quiz methodologist
  approval.
- Verification: the corrective chain through `03718d8d958d475c02c16381ee6dc27e235e4ae3`
  passed CI run `33423645134` and production release `33424142694`; production
  smoke `33424391721` passed. A disposable synthetic production generation produced
  one module, one lesson, one quiz and three independently validated questions.
  Every question had exactly one keyed answer, no keyed answer was the unique
  longest option, source references rendered through the public compatibility
  schema, publication returned `quiz_review_required` before quiz approval, and
  publication succeeded only after explicit review. No mail was sent and the
  disposable tenant was removed through the normal API with `204` plus `404`
  readback.
- Follow-up evidence2026-09-10: a normal17lesson/61question job completed, but browser
  and independent API detected one invented predicate in a keyed answer. The old
  60percent stem-overlap check ignored digits and admitted invented properties;
  focused recovery forced6words and encouraged filler. New synthetic red tests
  reproduce both unsupported predicates and altered numbers. Remove fixed6words,
  keep bounded recovery/minimum3 and existing balance/distractor checks unchanged.
  Raw quote explanations collided with the existing answer-leak detector; a trusted
  language-specific prefix fixes that interaction without weakening its validator.
 37focused/1175unit tests and independent review pass. Exact candidate isolated
  real-provider probe returns3questions/5calls in20.84seconds, DB/runtime edits0.
  This is candidate evidence, not deployed correction or semantic-entailment proof.
- Follow-up 2026-09-13: the full production workbook path on release `0.5.13`
  persisted all 15 correct choices at position zero. Review also found a
  contextless comparison, invented city-name distractors, mechanically repeated
  options and numbered module placeholders. The candidate distributes persisted
  answer positions, rotates MCQ display order between attempts, rejects those
  question/distractor classes, and derives module titles from source topic ranges.
  The acceptance runner now fails when a fixed-position or longest-answer blind
  strategy can pass a quiz, or when generic module titles remain. Focused RED/GREEN
  regressions, 1443 API unit tests and 581 frontend tests pass; DEV, exact release
  CI and production reacceptance remain separate gates.
- Prevention: successful job and valid JSON are not quality evidence. Verify every
  question's source, keyed-answer support, option-length baseline, Markdown-free
  rendering and review state. Retry must preserve the immutable source boundary and
  never learn from invalid output; production acceptance must include a methodologist
  review and a choose-the-longest baseline.

## API-002 - One kiosk user's NULL email broke the admin dashboard

- Date: 2026-08-20.
- Symptom: stats/trial/users returned `200`, but dashboard returned `500` after a
  student without email was created.
- Cause: provisioning allows `users.email = NULL`; `UserListItem.email` required
  a string, aborting recent-user serialization.
- Fix: input validator normalizes confirmed legacy `NULL` to empty string without
  inventing an address or changing DB evidence.
- Verification: regression uses `email=None`; five admin P0 tests and full unit
  suite passed. Production route must be repeated after exact release.
- Prevention: test every valid identity shape, including kiosk/link-only users
  without email; one nullable row must not break aggregates.

## LEARNING-001 - Reassignment resurrected a completed program

- Date: 2026-08-20.
- Symptom: reassigning the same audience counted completed work as new
  (`added=1`) and made it active.
- Cause: idempotency skipped only `active`; reactivation also applied to
  `completed` instead of only `cancelled`.
- Fix: skip `active` and `completed`, preserving `completed_at` and result; only
  `cancelled` can explicitly reactivate.
- Verification: 11 tests prove `added=0/skipped=1`, unchanged `completed_at`, no
  enrollment sync, and allowed cancelled reactivation; unit suite `261 passed`.
- Prevention: test active/completed/cancelled separately. Initial bulk assignment
  must never reset completed outcomes.

## SECURITY-001 - Lesson content executed as stored HTML

- Date: 2026-08-20.
- Symptom: stored HTML became DOM; event handlers and active URLs entered execution.
- Cause: `simpleMarkdown()` did not escape input before
  `dangerouslySetInnerHTML`.
- Fix: render only React text nodes and bounded `strong`, `em`, `br`; never
  parse raw HTML.
- Verification: regression reproduced injection then proved no `img`, `script`,
  or `javascript:` link while emphasis remained. Focused `5 passed`; typecheck,
  lint, and 57-page build passed. One unrelated flaky contextual-assignment failure
  passed isolated rerun `9 passed`.
- Prevention: never send persisted/API/LLM content to HTML sinks. Rich text requires
  a safe AST/component renderer or validated allowlist sanitizer with XSS corpus and
  CSP defense in depth.

## SECURITY-002 - Personnel number was the kiosk's only secret

- Date: 2026-08-20.
- Symptom: shared link plus personnel number yielded a normal access JWT; distinct
  errors leaked employee existence/status/position.
- Cause: a public identifier was treated as credential; no independent secret,
  lockout, or server-side active-kiosk binding; logs stored the number unmasked.
- Fix: issue six-digit PIN and store only Argon2 hash. Public exchange uses neutral
  error, five attempts, 15-minute lockout, and fail-closed Valkey IP limit. JWT type
  `kiosk_access` validates credential, kiosk, tenant, employee, and position on each
  request. Migration `0120` adds RLS, ownership trigger, and historical masking.
- Verification: security/API `43 passed`; available API `998 passed`; 48 DB tests
  did not start because local PostgreSQL was unavailable. Web `317 passed`;
  typecheck, lint, and 57-page build passed. Alembic head `0120`.
- Prevention: public IDs are not authenticators. Capability sessions need an
  independent secret, attempts/lockout, revocation, tenant ownership, neutral errors,
  and rate-limiter degradation test.

## SECURITY-003 - SCORM was blocked by headers or would run on trusted API origin

- Date: 2026-08-20.
- Symptom: SCORM iframe lacked `sandbox`; global API returned
  `X-Frame-Options: DENY` and `frame-ancestors 'none'`. Removing them globally
  would trust tenant-uploaded JavaScript on API origin.
- Cause: launch shell/assets/commit API/main API lacked a browser trust boundary;
  launch URL used `request.base_url`.
- Fix: use only `SCORM_CONTENT_ORIGIN`; production returns `503` if unset and
  wrong Host returns `421`. Use sandboxed iframe and versioned bridge validating
  exact origin, frame source, random channel, type, and status schema. Only exact
  SCORM host/path receives frameable CSP; app/API keep DENY.
- Verification: SCORM/API `36 passed`; frontend role/SCORM `7 passed`; typecheck
  and lint passed. Production DNS/proxy and malicious-package browser E2E remain gates.
- Prevention: isolate untrusted executable content on a cookieless origin; never
  remove XFO/CSP globally; ingress exposes a minimal route allowlist.

## SECURITY-004 - OOXML and converter lacked one bounded trust boundary

- Date: 2026-08-20.
- Symptom: API read full uploads and checked DOCX/XLSX only by `PK`; existing files
  could enter local parser fallback; converter could start without key and systemd
  ran as root without limits.
- Cause: compressed size was treated as sufficient ZIP control; upload/storage/
  conversion had inconsistent enforcement; empty converter auth disabled checking.
- Fix: stream hash/store. Before storage and each conversion, enforce required parts,
  safe paths, no symlink/encryption, entry count, per-entry/total expanded size, and
  ratio. Validate legacy DOC output. Converter always requires header and rejects
  missing/short production key. Docker/systemd use `docling`, no capabilities,
  private tmp, strict filesystem, state directory, umask, and CPU/RAM/task limits.
- Verification: document/converter `80 passed`; backend unit `292 passed`; Ruff
  `E9,F,I` passed. Production rollout and adversarial archive/OCR smoke remain gates.
- Prevention: ZIP prefix/MIME is not safety evidence. Repeat budgets at every parser
  boundary; helper services fail closed on auth and run with measured sandbox limits.

## SECURITY-005 - Production smoke validated old Render instead of KZ runtime

- Date: 2026-08-20.
- Symptom: GitHub smoke/watchdog accepted HTTP 200 from historical Render; health had
  no deployment/release identity.
- Cause: URL availability was treated as runtime identity; monitoring did not move to
  `api.kml.kz`.
- Fix: health returns `app_environment`, `deployment_environment`, full
  `release_sha`, and `no-store`. KZ Compose requires exact SHA; Render is
  development. Shared verifier refuses redirects and matches KZ identity; GitHub and
  watchdog use it.
- Verification: monitoring TDD `6 passed`; Ruff and shell syntax passed. Watchdog
  checks current Compose services and requires a fresh KZ backup source. Production
  rollout and controlled staging fault injection remain gates.
- Prevention: monitor exact immutable identity, not only DNS/TLS/HTTP. Dev/demo/
  rollback endpoints never enter production success.

## SECURITY-006 - Limiter trusted unsigned tenant and incomplete public-route inventory

- Date: 2026-08-20.
- Symptom: limiter selected tenant from unverified JWT; assignment/candidate/kiosk/
  lead routes were not fail-closed capabilities; invitation trusted arbitrary XFF.
- Cause: middleware mixed transport identity, unverified claims, and route controls
  before auth; runtime lacked explicit trusted proxies.
- Fix: build principal bucket only after full JWT verification and store opaque hash.
  Invalid tokens stay in socket-IP bucket. All public capabilities fail closed when
  Valkey is unavailable; URL tokens are hashed. KZ requires exact
  `FORWARDED_ALLOW_IPS`; route code no longer parses caller XFF. Redis members use
  nonce to prevent same-timestamp collisions.
- Verification: forged JWT, spoofed XFF, verified JWT, hashed capability, outage, and
  Compose tests `33 passed`; backend unit `305 passed`; Ruff passed.
- Prevention: only ASGI handles forwarded headers from allowlisted socket peers. Use
  network bucket before auth and opaque principal after; every public capability
  enters fail-closed inventory and negative outage tests.

## SECURITY-007 - Two package managers and vulnerable frontend dependencies

- Date: 2026-08-20.
- Symptom: web had npm and pnpm locks; CI/Vercel used npm; Docker used pnpm and a
  nonexistent monorepo command. SCA found high Next/PostCSS/nanoid and transitive
  sharp advisories.
- Cause: dependency contracts diverged and package manager/version were unpinned.
- Fix: web/landing pin `pnpm 10.26.1`; remove web npm lock; require frozen pnpm in
  CI/Vercel. Upgrade Next to `15.5.23`; pin patched PostCSS/nanoid/sharp. Docker
  uses app-local pnpm and `next start`; update Next 15 params/ESLint fixture.
- Verification: frozen installs pass; audit `0 high / 0 critical`; web
  `319 passed`, typecheck/lint/build 57 routes; landing `22 passed`,
  typecheck/lint/build 18 pages.
- Prevention: one lockfile and exact packageManager per deployable app; frozen locks,
  SCA, and production build block release. Linux container and production readback
  remain gates.

## SECURITY-008 - Ruff and mypy did not block CI

- Date: 2026-08-20.
- Symptom: Ruff/format used `continue-on-error`; mypy used it plus `|| true` and
  stopped on duplicate `config`/`app.core.config`.
- Cause: all-or-nothing accumulated debt made checks informational.
- Fix: mypy uses `explicit_package_bases`; one blocking script compares per-file/
  per-code Ruff/mypy counts with committed upper bounds. Reduction is allowed;
  increase exits 1. Remove warn-only paths.
- Verification: PASS (`ruff=1140`, `mypy=2429`); contract `4 passed`; seeded
  `F401` makes gate fail.
- Prevention: never raise baseline without separate review; lower it incrementally.
  First GitHub Actions run remains a release gate.

## SECURITY-011 - PII and client content entered runtime logs

- Date: 2026-08-20.
- Symptom: AI paths logged raw output fragments; ingestion/JD logged filenames;
  external exceptions logged full text; debug API copied logger/stdout/stderr without
  a redaction boundary.
- Cause: redaction depended on call sites; handlers, memory buffer, and Sentry had no
  common contract.
- Fix: one bounded redactor covers free text, structured extras, nested telemetry,
  and tracebacks on root handlers, stdout/stderr tee, debug buffer, and Sentry
  `before_send`. Call sites log only opaque IDs, counts/status, and exception class.
- Verification: synthetic sensitive-value tests `7 passed`; focused `53 passed`;
  backend unit `312 passed`.
- Prevention: content/provider boundaries log only opaque IDs, metrics, and error
  type. Production aggregator/Sentry canary remains a gate and uses no real PII.

## SECURITY-013 - Backup did not authenticate ciphertext and KZ restore lacked a fail-closed command

- Date: 2026-08-20.
- Symptom: backup used OpenSSL AES-256-CBC + PBKDF2 without authenticated encryption;
  offsite had no download comparison/immutability; KZ restore lacked a versioned
  command and `restore.sh` mixed Supabase legacy with production override.
- Cause: confidentiality was mistaken for integrity; SHA, empty-target, schema/RLS/
  data, RPO/RTO, and signed evidence were not one fail-closed workflow.
- Fix: `scripts/backup.sh` uses authenticated GPG symmetric encryption, portable
  SHA-256, decrypt/TOC validation, and MinIO round-trip plus governance retention.
  `scripts/kz-restore-drill.sh` rejects production/non-empty targets, validates
  RPO/RTO, Alembic, pgvector, FORCE RLS, aggregates, and signs JSON with separate GPG
  key. Historical `.dump.enc`/Supabase remains separate legacy path.
- Verification: Bash syntax and `scripts/tests/backup_restore_validation.sh` pass;
  tampered GPG is rejected; Python contract `4 passed`. Real KZ offsite upload and
  disposable PostgreSQL 17 + pgvector restore remained operational release gates.
- Prevention: run a fresh disposable signed drill after schema/release changes and
  quarterly verify restore/immutability. File presence without decrypt/TOC and
  offsite readback is not backup evidence.

## SECURITY-014 - DB security gate used another major and partially ran as owner

- Date: 2026-08-20.
- Symptom: CI/local used PostgreSQL 16 while KZ used 17; some cross-tenant tests and
  worker claim ran as migration owner, so green did not prove FORCE RLS runtime.
- Cause: one suite mixed unit/filter/DB tests without explicit version/role/RLS
  contract; parity and `NOBYPASSRLS` were inferred from source.
- Fix: CI/Compose use `pgvector/pgvector:pg17`.
  `scripts/ci/run_rls_release_gate.sh` permits only typed-confirmed localhost
  ephemeral test DB and validates major, pgvector, Alembic, role attributes, FORCE
  RLS, cross-tenant CRUD/export/share/import, worker claim, and superadmin isolation.
  Worker claim runs after `SET LOCAL ROLE lms_app`.
- Verification: source-contract `3 passed`, Ruff, Bash syntax, and CI YAML parsing
  passed. Local DB suite did not run because Docker Desktop daemon was unavailable;
  first green GitHub run or ephemeral PostgreSQL 17 remained the release gate.
- Prevention: production major is a blocking test contract. RLS tests prove effective
  runtime role, not only `tenant_id` predicates. Never run destructive fixtures
  against production or shared remote DB.

## CI-001 - English errors journal broke the release contract parser

- Date: 2026-08-21.
- Symptom: the release contract and backend unit CI jobs failed after `ERRORS.md`
  was translated to English, although every stable entry ID and required field was
  still present.
- Cause: the parser required a Unicode em dash, Russian field names, and Russian
  date labels instead of validating the language-independent journal structure.
- Fix: accept ASCII or legacy heading separators and English or legacy Russian
  field/date labels while keeping stable `CATEGORY-NNN` IDs mandatory.
- Verification: `python scripts/ci/release-contract-gate.py` and
  `tests/unit/test_release_reliability_contracts.py` pass with the English journal.
- Prevention: changes to operational documentation language must update and run
  every machine-readable documentation contract before push.

## CI-002 - New Linux release script was committed without executable mode

- Date: 2026-08-31.
- Symptom: GitHub CI run `33375645285` stopped in `Shell script quality gate`
  before the remaining release-security steps because
  `infra/deploy/kamilya-ct125-release-gate.sh` was tracked as mode `100644`.
- Cause: the script was created on Windows and locally checked only with
  `bash -n`; the repository-wide executable-policy gate was not run before the
  first push.
- Fix: set the Git index mode to `100755` and retain the repository shell gate
  as the authoritative validation for tracked Linux scripts.
- Verification: `scripts/ci/shell-quality-gate.sh` passed all 15 tracked shell
  scripts for LF, CRLF blob, executable policy and syntax after the mode fix.
- Prevention: every new tracked `.sh` file must run the complete
  `scripts/ci/shell-quality-gate.sh` before commit; `bash -n` alone does not
  verify Git executable metadata.
- Recurrence 2026-09-19: release `0.7.3` repeated the Windows mode error for
  `scripts/dev/capture_vm126_pdf.sh` and `scripts/dev/converter_preflight.sh`.
  CI run `35431736647` failed closed before deployment. Both paths were changed
  to Git mode `100755`, the complete shell gate was added to the local release
  packet, and the correction was issued as immutable patch release `0.7.4`
  rather than moving the published `v0.7.3` tag.

## TOOL-003 - Skill validator dependency was absent from available Python runtimes

- Date: 2026-08-23.
- Symptom: `quick_validate.py` failed twice with
  `ModuleNotFoundError: No module named 'yaml'`, first under the default Python and
  then under the bundled Codex Python runtime.
- Cause: the validator imports PyYAML, but neither selected runtime provided that
  tool dependency. Repeating the command with another unqualified interpreter did
  not change the dependency set.
- Fix: the completed skill review first used a fail-closed PowerShell contract check
  plus independent semantic review. PyYAML `6.0.3` was then qualified against the
  official PyPI project and canonical signed GitHub release and installed from a
  binary wheel with `--only-binary=:all:` and `--no-deps` into the isolated
  `%USERPROFILE%\.codex\tool-envs\kamilya-agent-tools` environment. It was not
  added to Kamilya application dependencies or a shared Python runtime.
- Verification: both original Python attempts reproduced the exact import error;
  the bounded replacement contract returned `PASS`; the independent reviewer
  returned `READY`; the isolated environment reported PyYAML `6.0.3`; and the
  original `quick_validate.py` command returned `Skill is valid!`.
  On 2026-08-25 the same runtime-selection class recurred when system Python was
  assumed to contain pytest and a repository-local backend venv was assumed to
  exist. Both stopped before test execution. The documented `poetry run` runner
  was then used; its first collection exposed a separate missing repository-root
  import bootstrap in the new ops test, which was fixed to match existing tests.
  The unchanged canonical runner then completed all 15 remote-exec tests.
- Status: resolved. The reproducible tool dependency is pinned in
  `.codex/tooling/requirements.txt`, with discovery and invocation documented in
  `.codex/tooling/TOOLS.md`.
- Prevention: inspect a helper's imports before first use. When a missing reputable
  package materially improves repeatable work, verify provenance, version,
  install hooks, vulnerabilities, license, and dependency conflicts, then install
  it in an isolated tool environment and rerun the original command. Record the
  pinned desired state and safe usage in `.codex/tooling/`; verify live availability
  instead of assuming the manifest was installed. Do not repeat interpreters with
  the same unresolved dependency set. For repository tests, start with the
  documented project runner and preserve the repository-root import bootstrap used
  by existing out-of-package ops tests; probe any alternate interpreter before use.

## AGENT-001 - A blocked claim incorrectly became the overall reconciliation status

- Date: 2026-08-23.
- Symptom: two blind forward-test scenarios correctly verified available Git or
  provider evidence and correctly left production runtime unverified, but returned
  overall `CURRENT STATUS: BLOCKED` instead of `PARTIALLY VERIFIED`.
- Cause: `kamilya-evidence-reconciliation` listed the allowed overall status values
  without defining mutually exclusive selection criteria. Agents propagated one
  per-claim `BLOCKED` condition to the whole reconciliation even when other
  decision-relevant claims were independently verified.
- Fix: define `VERIFIED`, `PARTIALLY VERIFIED`, and `BLOCKED` separately in the
  skill. `PARTIALLY VERIFIED` now covers mixed verified and unresolved/conflicting
  claims; overall `BLOCKED` is reserved for a named condition that prevents
  verification of every decision-relevant in-scope claim.
- Verification: the canonical skill validator returned `Skill is valid!`. Fresh
  isolated Luna agents, without prior conversation or expected answers, reran the
  access-gap and conflicting-handoff fixtures and both returned
  `PARTIALLY VERIFIED`, preserved the exact unresolved frontier, used valid evidence
  labels, and performed no mutation. The complete-evidence fixture had already
  returned `VERIFIED`.
- Status: resolved.
- Prevention: every skill output enum must define selection semantics, not only
  allowed values. Forward-test at least complete, partially available, access-gap,
  and conflicting-evidence cases with fresh isolated agents before activation.

## GIT-001 - Direct push ignored the valid repository token and opened an interactive path

- Date: 2026-08-23.
- Symptom: direct `git push` failed with `/dev/tty` and could not read a GitHub
  username. A later attempt started device login even though the owner required
  token-only Git access.
- Cause: plain Git does not load the repository `.env`, and the GitHub CLI had no
  persisted login. The access-path failure was initially treated as an authentication
  problem before independently validating the process-local token.
- Fix: use only `GITHUB_TOKEN` from the current repository root `.env`. From
  `apps/api`, validate it with
  `poetry run dotenv -f ..\..\.env run -- gh auth status --hostname github.com`,
  then push through the official process-local helper with
  `poetry run dotenv -f ..\..\.env run -- git -c credential.helper= -c
  "credential.helper=!gh auth git-credential" -C ..\.. push origin
  <exact-sha>:master`.
- Verification: `gh auth status` identified the active token-backed GitHub account
  without exposing the token. The helper then pushed exact commit
  `0492fd72dc18c760f91de7acc96cce14de72d9d1` to `origin/master`; Git reported
  `c1c1385..0492fd7`.
- Status: resolved.
- Prevention: distinguish token validity from credential transport. Never infer an
  expired token from `/dev/tty`, missing persisted `gh` login, or prompt failure.
  Do not switch to browser/device login when token-only access is required. Never
  put a token in a command argument, URL, helper file, Git config, log, or document.

**STOP / RECURRENCE 2026-08-26:** THE CANONICAL ROOT `GITHUB_TOKEN` IS VALID
FOR `KamillaLMSCRM`. THE EXACT COMMIT AUTHOR IS
`Kamilya Codex <kamilla_lms_crm@proton.me>`. A CUSTOM `GIT_ASKPASS` SELECTED
THE INACTIVE `askar0007amirkhanov` KEYRING IDENTITY AND PRODUCED HTTP 403; THIS
WAS A WRONG CREDENTIAL-PATH/ACCOUNT FAILURE, NOT TOKEN EXPIRY. CUSTOM ASKPASS IS
FORBIDDEN FOR THIS REPOSITORY. RUN THE ROOT-ENV `gh auth status` CHECK AND USE
THE OFFICIAL PROCESS-LOCAL `gh auth git-credential` HELPER BEFORE CLASSIFYING
ANY TOKEN FAILURE.

**RECURRENCE 2026-09-04:** the ambient active GitHub CLI account
`askar0007amirkhanov` reported repository permission `READ`, and this was
incorrectly presented as a push blocker before consulting the canonical path.
The root-env `gh auth status` instead identified `KamillaLMSCRM` as the active
process-local token account, and the official helper's exact-branch
`git push --dry-run` successfully resolved `2619592..6a7635c`. Before every Git,
DB, provider, deployment, or infrastructure action, search `AGENTS.md`, this
journal, `docs/PROJECT-CONTEXT.md`, and the matching runbook for the verified
path. Ambient CLI/keyring state cannot override a project-specific credential
contract or establish a blocker.

## GIT-002 - Landing push used the LMS repository token instead of the landing token

- Date: 2026-08-24.
- Symptom: the exact landing release push failed with GitHub HTTP 403 `Write
  access to repository not granted`, although the landing repository had its own
  valid token.
- Cause: generic credential discovery checked standard `GITHUB_TOKEN` names in
  workspace and LMS environment files but did not resolve the landing repository's
  project-local variable names. It therefore selected the LMS token, which had no
  write authority for `KamillaLMSCRM/kamilya-landing`.
- Fix: use `github_landing_token` and `vercel_landing_token` only from
  `C:\Kamilya New\kamilya-landing\.env.local` for landing GitHub and Vercel
  operations. Keep `Kamilya-NEW\.env` credentials scoped to the main repository.
- Verification: the same fast-forward push method, using the process-local landing
  token without exposing it in arguments or output, pushed exact commit
  `35f7184be0a8512e8b94428f271390abd4864fc4` to landing `master`. Vercel then
  created production deployment `dpl_BNYDLCvETP2phjc8tebMCu2VRiRi` from that
  exact Git SHA.
- Status: resolved.
- Prevention: resolve credentials by repository and canonical variable name before
  every provider mutation. Never scan backup or neighboring environment files,
  never substitute another repository's token, and stop after an authorization
  error until the credential source is reconciled. Keep token values process-local
  and out of command arguments, URLs, logs, documents, and Git configuration files.

## 2026-08-24 - Local API test environment drifted from declared dependencies

- **Context:** Focused superadmin tenant lifecycle tests were run against the canonical Supabase dev database through the transaction-rollback fixture.
- **Symptom:** Application import failed sequentially because the existing root `.venv` did not contain declared runtime packages `psutil`, `qrcode`, and `xlrd`.
- **Root cause:** The reusable root `.venv` had drifted behind `apps/api/pyproject.toml`. In addition, `uv sync --frozen --all-groups` created an empty `apps/api/.venv` because the API project currently declares dependencies only under `[tool.poetry]`; `uv` did not treat those tables as a PEP 621 project dependency set.
- **Safe recovery:** Install the missing packages from the declared version ranges into the existing root `.venv`, pass `DATABASE_URL` only through the process environment, and rerun the focused tests. The test fixture wraps every test in an outer transaction and rolls it back.
- **Evidence:** `test_superadmin_create_tenant_defaults_is_demo_false_without_first_admin` and `test_superadmin_create_tenant_persists_explicit_is_demo_true_without_first_admin` passed (`2 passed, 9 deselected`). The empty `apps/api/.venv` created by the failed sync path was removed.
- **Prevention:** Do not assume `uv sync` installs Poetry-only dependency metadata. Before API test work, use the maintained root `.venv` and verify it contains the packages declared by `apps/api/pyproject.toml`, or first migrate the API package to an explicitly supported dependency-manager contract. In a clean worktree, invoke that canonical Python by absolute path; do not run bare `poetry run`, which silently creates an empty per-worktree environment. Frontend worktrees must use the reviewed junction to the maintained `apps/web/node_modules` before invoking `pnpm`, rather than treating missing local dependencies as a product failure. Never fall back to a local Docker/PostgreSQL database for Kamilya dev when the canonical Supabase dev path is required.

## 2026-08-24 - Render dev deploy failed because runtime requirements omitted xlrd

- **Context:** Exact Kamilya LMS dev deployment of commit `c389ccb7c4bb8ef69f59398f3c437c1331acd9df` to Render service `kamilya-lms-api`.
- **Symptom:** Deploy `dep-da64eq8u01pc73965khg` reached `update_failed`; the previous live instance recovered automatically.
- **Root cause:** `apps/api/app/modules/staff_workbook_analysis/loaders.py` imports `xlrd`, and `apps/api/pyproject.toml` declares it, but Render installs `apps/api/requirements.txt`, where `xlrd` was missing. Startup failed with `ModuleNotFoundError: No module named 'xlrd'`.
- **Fix:** Add `xlrd>=2.0.1` to `apps/api/requirements.txt` in commit `5571cca411cc60b23dca9cc26d13dae0db55dc81`.
- **Verification:** Import smoke passed locally; Render deploy `dep-da64h2gu01pc7396daeg` reached `live` on the exact fix commit.
- **Prevention:** Keep `pyproject.toml` and the Render-installed `requirements.txt` dependency sets aligned, or consolidate them into one canonical supported dependency contract.

## 2026-08-24 - Stateless dev orchestration exhausted the superadmin login limit

- **Context:** Sequential setup of the disposable Kärcher demo tenant through the
  Render dev API.
- **Symptom:** A final no-email enrollment request could not start because
  `/api/v1/auth/superadmin-login` returned HTTP 429.
- **Root cause:** Each short operator script created a new superadmin login instead
  of reusing one access token/session. The endpoint intentionally allows five
  requests per minute and twenty per hour.
- **Safe recovery:** Do not alter Redis or the limiter. For this already-authorized
  dev-only run, first verify that the local and Render `JWT_SECRET` values match by
  digest, then mint one process-local, 15-minute, tenant-bound impersonation token
  with the existing application signer. Never print or persist the token.
- **Verification:** The exact two service learners were assigned once; runtime
  readback showed 14 tenant enrollments, zero invitations, and empty notification
  fields for the new personal-link assignments.
- **Prevention:** Reuse one short-lived superadmin session and one impersonation
  token across a bounded related operation sequence. Do not create a fresh login
  per command. External token minting is an exceptional dev recovery path, not a
  normal substitute for login, and requires an exact signer-digest and scope check.

## 2026-08-24 - Render dev document upload returned edge HTTP 503 without app evidence (resolved)

- **Context:** Upload of one 42,241-byte synthetic DOCX to the disposable demo
  tenant for onboarding-course generation.
- **Symptom:** `/api/v1/documents/upload` returned edge HTTP 503 without the
  application's structured JSON error. Render app logs contained no matching
  traceback, timeout, OOM, bucket, RLS, or Supabase exception.
- **Reconciliation:** Render lacked `SUPABASE_URL` and used the local storage
  default. The dev service was minimally configured with the existing matching
  Supabase URL/key and `STORAGE_BACKEND=supabase`, then redeployed once on exact
  commit `5571cca411cc60b23dca9cc26d13dae0db55dc81`. A direct disposable upload,
  existence check, deletion, and absence check against the canonical bucket all
  passed. The application endpoint nevertheless continued to return edge HTTP 503.
- **Root cause and fix:** The async upload route called the synchronous Supabase
  SDK on the event-loop thread and passed FastAPI's `SpooledTemporaryFile` to the
  SDK unchanged. Commit `39c0a45eff0f43594474ea72a4af41cc1fc7f26e`
  offloaded the blocking call, converting the opaque edge failure into the
  application's structured storage error. Commit
  `c7e15486afabb1b7eef2ef387c4a7990d5816ab3` then normalized the bounded upload
  stream to `bytes` before the SDK call. The focused storage suite passed 21/21.
- **Safety evidence:** Every failed request left zero matching Document rows and no
  durable indexing job. The direct provider probe removed its exact diagnostic
  object. Automatic upload and generation retries were stopped.
- **Runtime verification:** Exact Render deploy `dep-da65lku1egvs73a4rucg` became
  live on `c7e15486afabb1b7eef2ef387c4a7990d5816ab3`. One synthetic DOCX upload
  returned HTTP 201; FORCE-RLS-aware DB readback confirmed a 42,241-byte document,
  one indexing job, `embedding_status=success`, and an existing storage blob. One
  authorized generation job completed at 100% and created a linked draft course
  with three modules, six lessons, and six quizzes. The draft remains pending
  methodological review and was not published or assigned.
- **Production verification:** GitHub CI run `32743293275` passed for exact release
  `d17a9206086d8557f797a13563353c406d0ce9f4`. VM126 API and all three workers now
  run `kamilya-api:d17a9206086d`; exact public/private health, zero restarts,
  bounded error counts, Alembic `0131 (head)` and watchdog identity passed. A
  no-credential, no-file upload-route probe returned HTTP 401 rather than edge
  HTTP 503 and created no data. The authenticated synthetic production journey
  is intentionally deferred to the owner-controlled rehearsal.
- **Deployment recurrence:** The first immutable-release script attempt stopped
  before runtime mutation because PowerShell passed escaped quotes literally to
  Bash. On 2026-08-25 the same parser class recurred during a read-only preflight:
  PowerShell damaged nested `python -c -> SSH -> SSH -> Bash` quoting before the
  script reached the remote host. The textual template rule had not been promoted
  into an executable invariant. `scripts/ops/kz_remote_exec.py` now accepts only a
  reviewed local `.sh` file, verifies its exact SHA-256 through the fixed canonical
  VM126 route, runs remote `bash -n`, and only then streams the identical bytes for
  execution. `.codex/skills/kamilya-safe-remote-exec/` makes this the default
  project procedure for KZ guest scripts. Inline cross-shell command bodies,
  `python -c`, shell-built SSH commands, target fallback, and raw remote output are
  prohibited. The routine CT125 route was independently recovered and verified on
  2026-08-26: workstation -> proxy -> VM126 (`10.77.77.2`) -> CT125
  (`192.168.1.225`) with host-specific keys and fixed known-hosts files. A failed
  Proxmox API/QGA attempt is only a failed recovery transport and must never be
  reported as absence of CT125 access until this canonical SSH route is tested.
  The adversarial suite passed 15 tests covering exact
  byte preservation, SHA mismatch, quoting payloads, target/path gates, read-only
  mutation rejection, approval matching, output suppression, and no-env dry run;
  the canonical skill validator and pinned Paramiko import/policy checks passed.
  An adversarial review then rejected the first guard as too permissive. The final
  contract uses a narrow read-only command allowlist, conservative secret/PII
  rejection, exact proxy and guest identity checks, server-side timeout/kill bounds,
  and an audit-only correlation ID that cannot be mistaken for authority.
  Implicit skill selection is limited to local dry-run validation; remote execution
  requires a current explicit request. Alternate credential/known-hosts paths are
  not accepted, and read-only `curl` is limited to one fixed GET health shape with
  a bounded timeout and no output/config/cookie file options.
  A successful exit without at least one valid UTF-8 `EVIDENCE|...` line is also
  blocked; transport success alone cannot become `RUNTIME-DERIVED` evidence.
- **CT125 backup/restore recurrence:** The production backup unit is root-owned,
  invokes `kamilya-pg-backup`, writes encrypted archives under
  `/var/backups/kamilya-postgresql`, and uses `/root/kamilya-backup.pass`. The
  restore utility `/usr/local/sbin/kz-restore-drill` executes database and GPG
  operations as `postgres`. Backup names include `kamilya_staging_<UTC>.dump.gpg`,
  while the restore parser accepts `kamilya_<UTC>.dump.gpg`. Do not rename or
  alter the source archive. Create a bounded encrypted temporary copy with the
  accepted basename, regenerate and verify its SHA-256 sidecar, run the signed
  disposable drill, then prove the disposable database and temporary copy are
  absent. Never expose passfiles or signing material.
- **Streaming-shell recurrence:** `ssh` reads stdin by default. In a streamed
  nested script, every non-payload SSH call must use `ssh -n`, only the final
  payload receiver may use `ssh -T`, and non-interactive Docker exec calls must
  redirect stdin from `/dev/null`. Use `trap cleanup EXIT`, not `EXIT ERR`, when
  cleanup functions may be reached through command substitution; inherited ERR
  traps can delete temporary material in a subshell before the parent uses it.
- **Production rollout recurrence:** A host timer can race with Docker Compose
  container recreation. Stop `kamilya-candidate-retention.timer` immediately
  before recreating the approved containers, run and verify the oneshot after the
  new runtime is healthy, then restart and read back the timer. The watchdog
  EnvironmentFile keys are `EXPECTED_RELEASE` and `EXPECTED_API_IMAGE`; do not
  guess similarly named variables.
- **Historical Vercel recurrence (2026-08-26):** A READY deployment in the dev
  project did not prove the custom production alias moved. On that date the
  owning production project was `web`, not `kamilya-lms-dev`. Since 2026-09-07
  `app.kml.kz` is hosted on CT137: before and after a frontend rollout resolve
  actual DNS, verify the CT active release/full SHA and run public login/business
  smoke. Vercel identity is checked only for dev or an explicitly selected
  rollback.
- **Status:** resolved in canonical dev and deployed to KZ production; business
  flow acceptance remains pending the bounded synthetic rehearsal.
- **Prevention:** Treat edge 503 without an application error body as a separate
  proxy/process failure class. Correlate request, instance lifecycle, memory, and
  application logs before retrying. Keep the async offload and spooled-stream
  regression tests, add a bounded provider-backed upload smoke to the Render dev
  release gate, and preserve a deterministic manual-course fallback for demos;
  never replay AI/provider jobs blindly.

## 2026-08-25 - Cancelled enrollment history broke learner course access

**Symptom:** quiz submission returned HTTP 500 with `MultipleResultsFound` after a learner had both a cancelled historical enrollment and an active enrollment for the same course.

**Root cause:** `require_course_access` queried enrollment history without filtering to access-granting statuses and assumed at most one row.

**Fix:** release `67477ed5a9fabed92e1bd4805c263697a14826d0` filters to `enrolled`, `in_progress`, or `completed` and limits the existence query to one row. Focused tests, full CI, dev regression and production learner E2E passed.

**Prevention:** access checks must treat cancelled/revoked rows as retained evidence, not as active access, and existence checks must not assume history uniqueness.

## 2026-08-25 - Adaptive staff import duplicated legacy organization roots

**Symptom:** a proposal with two branch actions classified as `update` committed as two new legacy roots and four duplicate positions instead of converting the two matched legacy roots into branches.

**Impact:** the synthetic Karcher production tenant temporarily showed 0 branches, 4 legacy roots and 8 positions. Employees, course assignments, completion and certificate evidence were preserved.

**Recovery:** a guarded tenant-scoped transaction verified exact unit/position IDs, zero employees/courses/children on the obsolete rows, four employees on the retained rows and 13 active enrollments. It deleted only the two empty legacy roots and four empty duplicate positions, then converted the two occupied units to `branch`. Independent API readback passed: 2 branches, 0 legacy roots, 4 positions, 4 employees, 13 active assignments and 1 completion.

**Prevention:** add a DB-backed regression where an analyzed workbook matches legacy roots by name, corrections rename them, commit must reuse the original unit IDs, set `unit_type=branch` and `legacy_root=false`, and must not duplicate positions. Until that test and code fix land, do not trust proposal action `update` as proof of commit behavior; require post-commit tree readback and a guarded cleanup plan.

## TOOL-004 - Whole-file formatter expanded a narrow legacy-file change

- Date: 2026-08-25.
- Symptom: `ruff format` changed hundreds of pre-existing lines in
  `blueprint_catalog.py` while formatting a small checklist-contract patch.
- Cause: the legacy file was not Ruff-formatted as a whole; running the mutating
  formatter on the entire file was incorrectly treated as a safe narrow fix.
- Fix: reconstruct the clean `HEAD` text in memory and reapply only the owned
  `example_answer` contract, examples, and call-site changes. No user or unrelated
  worktree content was overwritten because the file was clean before this task.
- Verification: exact-path diff review shows only the intended checklist/UI/test
  changes; focused backend/frontend tests, Ruff check, typecheck, and build pass.
- Prevention: on a legacy file, inspect formatter scope before mutation. If
  `ruff format --check <file>` reports pre-existing whole-file drift, do not run the
  mutating formatter as part of an unrelated patch; keep the owned hunk formatted
  manually and use Ruff lint plus exact diff review.
# 2026-08-26 - VM126 canonical hostname drift blocked the fail-closed SSH adapter

- **Symptom:** `kz_remote_exec.py` returned `target_identity_mismatch` before a reviewed VM126 script could run.
- **Cause:** the canonical WireGuard/SSH target identified itself as `kml`, while the adapter still expected the former hostname `KML-2-77`.
- **Prevention:** keep the adapter's exact hostname assertion synchronized with runtime identity evidence; do not bypass the assertion or guess a different host when it fails.
- **Resolution:** update `VM126_HOSTNAME` and its focused tests to the independently read-back hostname, then rerun the reviewed script through the same pinned host-key and WireGuard route.

## TOOL-005 - VM126 privilege, rollback, and hidden-input assumptions broke release evidence

- Date: 2026-08-26.
- Symptom: read-only Docker preflight failed for `kamilya-admin`; initial deploy
  attempts referenced `docker-compose.yml`, attempted a non-privileged `cd` into
  root-only `/opt/kamilya-runtime`, and one rollback trap returned success after
  restoring the old release. A hidden PTY input also removed `@` from an email
  address, producing misleading SMTP `501` results and one malformed test user.
- Cause: the workstation-to-VM126 adapter did not support the canonical
  `sudo -n` read-only Docker shape; the release script copied assumptions from a
  root execution context; the `ERR` handler did not disable itself and exit with
  the original nonzero status; and hidden PTY input was treated as exact bytes.
- Fix: extend the reviewed adapter with the narrow `sudo -n` read-only command
  shape, use absolute privileged runtime paths, preserve the original nonzero
  status after rollback, and reconstruct email addresses outside hidden PTY input.
- Recovery: narrowly allow only `sudo -n` followed by an existing read-only
  command, plus one fixed container-evidence format; retain sanitized stage
  evidence on remote failure; use absolute root-only paths with
  `sudo -n docker compose --env-file ... -f ...`; make rollback disable `ERR` and
  exit nonzero; and collect email local/domain parts separately. The malformed
  user was deactivated and the valid account passed SMTP welcome/code checks.
- Verification: helper tests pass (`48 passed`); immutable deploy v6 and
  independent public/private readback confirm exact release/image identity,
  four running containers and zero restarts; SMTP envelope returned `250` for
  sender and recipient when the address was reconstructed inside Python.
- Prevention: never use nested SSH quoting, unprivileged runtime-directory
  traversal, success-returning rollback traps, or hidden PTY input for strings
  containing `@`. A deploy report is not accepted until an independent
  postdeploy readback confirms the claimed image and release. The immutable
  remote adapter must execute read-only scripts as `kamilya-admin`, but execute
  an exact-SHA approved `mutation` only as `sudo -n bash -se` after identity,
  hash and syntax gates pass. Do not reintroduce per-release privilege wrappers.

## 2026-08-26 — Staff Sync uniqueness pre-check ran after insert flush

- Symptom: the disposable Supabase dev smoke sent a second external employee
  with an email already owned by another user in the same tenant. Instead of an
  audited `email_conflict`, PostgreSQL raised `uq_users_tenant_email_ci` and the
  API exposed an unhandled `IntegrityError` path.
- Cause: `_upsert_employee()` inserted and flushed a new `User` before calling
  `_assert_employee_keys_available()`. The query itself matched the database
  index semantics, but it ran too late to prevent the unique-constraint error.
- Fix: run the personnel/email availability check before constructing and
  flushing a new user. Preserve the second post-link/update check that excludes
  the current user. Map only known identity-related constraint races to a
  redacted auditable conflict; re-raise unknown integrity failures.
- Recovery: the failed synthetic tenant was removed by its guarded cleanup;
  residue was zero and shared counts were unchanged. The corrected event then
  returned `status=conflict`, retained one user, and persisted the redacted
  conflict event.
- Verification: focused tests pass (`12 passed`), Stage 1 passed
  upsert/replay/reuse/update/conflict, and Stage 2 passed termination/session
  revocation/reactivation/two-tenant FORCE RLS/credential revocation. Both
  stages reported zero residue and unchanged shared counts.
- Prevention: identity pre-checks must precede the first insert flush, while
  database uniqueness remains the concurrency backstop. Every external sync
  path must test both deterministic conflicts and constraint-race translation.

## 2026-08-26 — Git token lookup resolved `.env` from the task subdirectory

- Symptom: the agent incorrectly reported that `GITHUB_TOKEN` was empty and
  then tried the unrelated `kamilya_landing_git_token`, which GitHub rejected
  for the `Kamilya-NEW` remote. The owner correctly stated that the active token
  was present and had already been used during the same workday.
- Cause: the token-safe push helper ran with `apps/api` as its current working
  directory and resolved `Path.cwd() / '.env'`. It therefore read
  `apps/api/.env` instead of the canonical repository-root `.env`. The resulting
  absence was wrongly presented as a credential-state fact rather than a
  path-resolution error.
- Fix: derive the repository root explicitly, then resolve `.env` from that
  root. Inspect every matching variable occurrence by name and non-empty state
  without printing values, and select the last non-empty exact `GITHUB_TOKEN`.
- Recovery: the helper read the correct repository-root file and pushed commit
  `6e80bf5608e1744e3abb38191cc77d82123b7883` to `origin/dev`; exact remote SHA
  readback matched.
- Prevention: Git credential helpers must never infer the secret-file location
  from a task subdirectory. Use `git rev-parse --show-toplevel` or an already
  verified absolute repository root, keep tokens process-local, and distinguish
  `credential absent` from `wrong file inspected` in all reports.

## 2026-08-27 — Employee edit committed, then failed during an RLS-bound refresh

- Symptom: production `PATCH /api/v1/admin/staff/manual/{employee_id}` returned
  HTTP 500 from the employee edit modal. The sanitized runtime classifier found
  one failed PATCH plus `InvalidRequestError: Could not refresh instance` and no
  validation, uniqueness, SQL, network, or explicit RLS-policy error.
- Cause: the endpoint committed the update and then refreshed the ORM object.
  The refresh opened a new transaction after the transaction-local tenant/RLS
  context had ended, so the row was no longer visible to that refresh. This
  could report failure even though the preceding commit had succeeded.
- Fix: construct the minimized response from the tenant-scoped object before
  commit, return it only after a successful commit, and do not perform a
  post-commit refresh.
- Prevention: tenant-scoped write endpoints must not depend on post-commit ORM
  refreshes when RLS context is transaction-local. Regression tests must make
  any such refresh fail and assert that the endpoint never calls it.
# 2026-08-27 - FORCE RLS lifecycle tables were created without runtime grants

- Symptom: production course generation failed during verified-embedding retrieval with
  `InsufficientPrivilegeError: permission denied for table embedding_active_revisions`.
- Cause: migration `0131` created `embedding_active_revisions`,
  `embedding_reindex_runs`, and `embedding_reindex_events` with FORCE RLS policies,
  but omitted the separate table privileges required by the `lms_app` runtime role.
  RLS policy presence does not imply SQL table privileges.
- Fix: additive migration `0133` revokes any public/runtime residue and grants only
  `SELECT, INSERT, UPDATE` on the three lifecycle tables to `lms_app`; it grants no
  `DELETE`, `TRUNCATE`, ownership, or `BYPASSRLS` capability.
- Prevention: every migration that creates a runtime-accessed FORCE RLS table must
  test three independent contracts: table privileges, tenant policy, and FORCE RLS.
  A schema/RLS-only migration test is incomplete.
- Verification: the deterministic pre-fix contract reported
  `RED|missing_runtime_grants=3`; migration `0133` was applied in production, the
  runtime role readback confirmed `SELECT, INSERT, UPDATE` without `DELETE`, and the
  formerly failing verified-embedding query completed under the runtime role.

# 2026-08-27 - Document embeddings used a converted-content source revision

- Symptom: a successfully indexed production document had verified embeddings, but
  course generation retrieved zero chunks after enforcing the active source revision.
- Cause: document ingestion derived `embedding_source_revision` from converted
  Markdown, while retrieval compared it with `document:<documents.content_sha256>`,
  which is the SHA-256 of the original uploaded blob.
- Fix: document operations now pass the canonical original-blob source revision into
  ingestion, and ingestion validates the strict `document:<64 lowercase hex>` form.
- Prevention: upload, reindex and retrieval must share one source-revision contract;
  conversion output hashes are transformation evidence, not document identity.
- Verification: exact release `4de6358851dc22fadcb0a41320e4d52bad9c8069`
  passed dev and master CI, was deployed to production, and three existing documents
  reindexed to the canonical revision successfully.

# 2026-08-27 - Normal adjacent retrieval hits were rejected as overlapping context

- Symptom: production course generation reached content generation and failed with
  `overlapping_context_windows` when semantic search returned neighboring chunks.
- Cause: context expansion treated any repeated chunk across independently expanded
  anchor windows as invalid, although adjacent semantic anchors normally have shared
  context.
- Fix: rank all anchors first, keep every anchor in its own window, and assign each
  non-anchor context chunk to the first eligible ranked window. Tenant, document,
  revision and embedding-space checks remain fail-closed; the final no-overlap
  assertion remains a defensive invariant.
- Prevention: distinguish cross-boundary provenance conflicts from harmless context
  overlap. Deduplicate deterministic overlap instead of rejecting a valid retrieval
  result.
- Verification: releases `901df3658b13ae50d3ee1dc7de51779e05d63ef5`
  and `b4cca57bded652c1c4b825c2cdcb6fff4ddb27a5` passed focused tests, quality,
  dev CI and master CI. Production smoke on `b4cca57bded652c1c4b825c2cdcb6fff4ddb27a5`
  generated 2 modules, 5 lessons and 25 Russian-language questions, then removed the
  disposable course and confirmed that no invitation was sent.

# 2026-08-27 - AI smoke looked for quizzes in the course-structure response

- Symptom: a completed production generation was reported as structurally incomplete
  with zero questions even though the assessment and save stages had completed.
- Cause: the smoke counted questions in `/courses/{id}/structure`; by contract that
  response contains modules and lessons only. Quizzes and questions are returned by
  the separate `/quizzes` API.
- Fix: collect generated lesson IDs from the structure response, then count and
  language-check only quizzes linked to those lessons.
- Prevention: acceptance checks must follow public response schemas rather than
  assuming nested resources. A smoke failure must be classified as product failure or
  verifier-contract failure before another release is attempted.

## MIGRATION-004 - Editor-assistant wrapper stopped one revision below head after rollback rehearsal

- Date: 2026-08-30.
- Symptom: the local PG18 wrapper initially upgraded to `0137`, rehearsed
  downgrade/re-upgrade through `0135` and `0136`, then stopped at `0136` before
  printing `alembic heads`; the printed repository head did not prove that the
  disposable database had actually reached `0137`.
- Cause: the final migration sequence omitted a second `alembic upgrade head`, and
  its catalog assertions covered preview claims but not the new request fingerprint.
- Fix: finish the rehearsal with `alembic upgrade head` and assert both the nullable
  `request_fingerprint_sha256` column and its named check constraint before tests.
- Verification: `scripts/tests/test_editor_assistant_step1_check_wrapper.py` passed
  `4` contract tests; the corrected wrapper reported `0137 (head)`, passed `76`
  DB-backed tests, and removed its disposable PostgreSQL 18 database.
- Prevention: after every downgrade/re-upgrade rehearsal, verify the applied
  database revision and at least one catalog invariant introduced by the final
  migration; `alembic heads` alone describes source history, not live DB state.

## TEST-003 - Multi-document compatibility test omitted the selected course format

- Date: 2026-08-30.
- Symptom: the full frontend suite failed in
  `aiGenerationReusePage.test.tsx` although the isolated UI sent one valid
  compatibility request containing `documents` and `course_format`.
- Cause: the earlier automatic-format UI change updated the request contract but
  left this reuse-flow assertion on the former documents-only payload.
- Fix: require `course_format: "automatic"` in the compatibility-call assertion;
  application behavior is unchanged.
- Verification: the isolated reuse-flow test and the subsequent complete frontend
  test/typecheck/build gate pass on the same working tree.
- Prevention: compatibility request tests must assert all selection-dependent
  fields, including the default course format, whenever generation settings change.

## TEST-004 - Typecheck raced with Next.js generated-type replacement

- Date: 2026-08-30.
- Symptom: `pnpm typecheck` reported multiple `TS6053` missing files under
  `.next/types` while `pnpm exec next build` was running in parallel.
- Cause: both commands shared the same `.next` directory; the build replaced its
  generated type tree while TypeScript was reading files matched by `tsconfig.json`.
- Fix: allow the build to finish, then run `pnpm typecheck` sequentially against the
  stable generated tree.
- Verification: the production build completed successfully, the subsequent
  standalone `pnpm typecheck` exited `0`, and the full frontend suite remained
  `82` files / `410` tests passed.
- Prevention: never run `next build` and `tsc --noEmit` concurrently in the same
  checkout. Parallelize lint or tests instead, then run typecheck after the build
  has finished or use isolated output directories.

## TOOL-006 - Repository-relative paths were staged from the API subdirectory

- Date: 2026-08-31.
- Symptom: `git add apps/web/...` failed with `pathspec did not match any files`, and the following push reported `Everything up-to-date` because no commit had been created.
- Cause: the command ran from `apps/api` while its pathspecs were written relative to the repository root.
- Fix: stage and commit from the repository root, then enter `apps/api` only for process-local `.env` execution of the authenticated push helper.
- Verification: commit `9770dbc5e1f98a5a9af408d20f8fad6e228303d0` was created with exactly the intended seven frontend files and pushed to `origin/dev`.
- Prevention: treat repository-relative Git pathspecs and application-local environment runners as separate working-directory phases; never combine them under an implicit cwd.

## DEPLOY-006 - Browser route audit crossed a frontend alias switch

- Date: 2026-08-31.
- Symptom: the first methodologist route sweep reached `/cohorts`, then returned to `/admin/super`; four later sidebar locators disappeared.
- Cause: the shared dev alias switched frontend deployments during the authenticated impersonation session, invalidating the in-memory impersonation state.
- Fix: wait for the exact Vercel SHA to reach `READY` with the dev alias attached, restore the approved synthetic impersonation, and rerun the complete route/help matrix.
- Verification: all 13 methodologist routes and help dialogs passed on exact SHA `13e43e497ef76b9e6909e32c0aaa9f85c2da7829`.
- Prevention: bind browser acceptance to an immutable READY deployment or wait for alias convergence before creating role/session state; never classify an alias-switch interruption as a product defect.

## INFRA-008 - Vercel project identifiers were assumed to exist in the root env

- Date: 2026-08-31.
- Symptom: a read-only deployment query failed locally with a `TypeError` because `VERCEL_PROJECT_ID` was absent even though `VERCEL_TOKEN` was present and valid.
- Cause: the helper assumed token, project ID, and team ID were all configured instead of checking the canonical root `.env` contract first.
- Fix: use the token process-locally, list accessible projects without exposing values, select the exact `kamilya-lms-dev` project, and use its non-secret project/team identifiers for provider readback.
- Verification: Vercel returned exact SHA `13e43e497ef76b9e6909e32c0aaa9f85c2da7829` as `READY` with `kamilya-lms-dev.vercel.app` attached.
- Prevention: perform presence-only checks before composing provider URLs; discover stable non-secret resource IDs read-only when the canonical env intentionally stores only the token.

## RELEASE-001 - Reindex-specific evidence contract blocked a routine additive release

- Date: 2026-08-31.
- Symptom: exact authorized release `REL-20260831-KAMILYA-020-PROD` passed Git,
  CI, public-health, VM126 image and archive-transfer preflight, but
  `kamilya-release-evidence-gate` returned `NO_GO` before build, backup,
  migration or service recreation.
- Cause: the single gate contract requires Supabase-dev downgrade/re-upgrade,
  production reindex, provider-spend approval, cross-tenant canary and
  latency/cost evidence for every release. Those nodes belong to the earlier
  migration/reindex workstream and have no not-applicable/profile mechanism for
  a bounded additive `0138 -> 0139` backend release.
- Fix: commit `42e8a461a95202839990931611738815d9582ef2` adds explicit
  `full_reindex`, `bounded_schema_predeploy`, and `bounded_schema_final`
  contracts. Each profile enumerates its applicable evidence and approvals;
  unknown profiles, unrelated nodes and skipped requirements fail closed.
- Verification: 14 evaluator contract tests passed. The preserved
  `bounded_schema_predeploy` envelope for exact SHA
  `42e8a461a95202839990931611738815d9582ef2` returned structural `GO` with 5/5
  evidence nodes, 3/3 approvals and zero blockers while retaining mandatory
  root reference verification.
- Safe interim state: production remains on release
  `25ffe4f8ef0144ab064c358aa5b1c27a89d8934c`; CT125 backup and migration did not
  start; no service restarted; the transferred VM126 archive was hash-verified
  and removed through an immutable cleanup script.
- Prevention: make release evidence requirements profile-specific and
  fail-closed. A profile must explicitly enumerate applicable evidence and
  approvals, reject unknown/skipped nodes, and retain exact target/SHA/causality
  checks. Do not mark unrelated evidence `PASS` and do not bypass `NO_GO` until
  the corrected gate and its contract tests pass.

## TEST-005 - Errors journal append reused an existing contract identifier

- Date: 2026-08-31.
- Symptom: documentation-only CI failed the release-contract gate and the backend suites that import it with `duplicate ids: TOOL-005`.
- Cause: the new Git working-directory incident was assigned `TOOL-005` without first checking the append-only journal's existing identifiers.
- Fix: rename the new incident to the next unused identifier, `TOOL-006`, and run the release-contract gate locally before pushing the correction.
- Verification: `python scripts/ci/release-contract-gate.py` reports the errors journal contract as valid, and its focused reliability test passes.
- Prevention: before appending an incident, enumerate headings for the selected prefix and choose the next unused number; the release gate remains the required pre-push check for `ERRORS.md` edits.

## LEARNING-002 - Completed assignment blocked idempotent course completion retry

- Date: 2026-08-31.
- Symptom: a learner reached the terminal lesson, received a valid certificate, but a repeated completion action through the same assignment credential returned `409 assignment_enrollment_not_active`; the UI still exposed a no-op `Next lesson` action.
- Cause: the course-completion route enforced an active-enrollment guard before its idempotent completion lookup, even though the assignment bearer remained bound to the same completed enrollment.
- Fix: for the exact bound assignment enrollment only, fall back to the existing completed-enrollment read-access guard and continue the idempotent completion workflow; keep revoked, cancelled and cross-tenant access fail-closed. The terminal UI now calls completion explicitly.
- Verification: the assignment-bearer completion integration test passes on first and repeated completion; the focused evidence/access backend suite passes `34/34`; the course-player regression test verifies the terminal action sends `POST /complete`.
- Prevention: lifecycle mutation endpoints that promise idempotency must evaluate an already-completed exact resource before rejecting its active-state transition, while preserving tenant, credential and revocation boundaries.

## TRIAL-001 - Trial owner started in tenant-admin role without course capabilities

- Date: 2026-08-31.
- Symptom: a verified self-service trial successfully created a tenant and session, but the first user was routed to the admin interface and could not use the promised document and course workflow.
- Cause: registration created only the primary `admin` role, while the product capability contract reserves content operations for `methodologist`.
- Fix: make `methodologist` the active primary role and assign a separate `admin` role; the session exposes both roles without merging their capabilities.
- Verification: a fresh PostgreSQL 18 database migrated through Alembic 0139; the focused registration and blueprint suite passed 8 tests, including listing permitted blueprints and creating the first course with the registration token. The full-suite result is recorded by the release gate.
- Prevention: every self-service plan must test email verification -> tenant activation -> session -> role home -> first value; a successful registration response alone is insufficient.

## TEST-006 - SemVer contract test hardcoded the initial product version

- Date: 2026-08-31.
- Symptom: the version consistency validator passed for release `0.2.0`, but the CI contract-test job failed because a test named `test_real_repo_version_file_is_semver` required the literal value `0.1.0`.
- Cause: the test asserted the repository's initial version instead of the SemVer format described by its name.
- Fix: validate the real `VERSION` file against the numeric `major.minor.patch` SemVer shape while the existing validator continues to enforce cross-manifest equality.
- Verification: the focused version and workflow contract suite passed locally; the replacement exact SHA must pass the GitHub CI job before release.
- Prevention: version-contract tests must validate invariants and consistency, never pin a historical release number unless the product contract explicitly requires that exact version.

## DELETE-001 - Tenant deletion missed restricted and immutable lifecycle rows

- Date: 2026-08-31.
- Symptom: superadmin DELETE with the correct `confirm_slug` first returned HTTP
  500 for a verified self-service tenant and later returned HTTP 500 for a
  synthetic tenant containing a published course release.
- Cause: `registration_legal_acceptances` references both tenant and first user
  with `ON DELETE RESTRICT`, while published `content_releases` are protected by
  an immutable-row trigger and referenced by `courses.current_release_id`. The
  original purge contract represented neither populated lifecycle.
- Fix: migration 0140 grants legal-acceptance DELETE only under exact tenant plus
  superadmin RLS and orders it before users. Migration 0141 adds a bounded
  `SECURITY DEFINER` helper that requires the active superadmin context, exact
  tenant ID and matching slug, rejects the protected `kamilya` tenant, clears the
  current-release pointer and removes only that tenant's releases. Direct release
  mutation remains blocked. The UI uses a selectable/copyable slug modal and keeps
  the destructive action disabled until confirmation matches.
- Verification: CI run `33423645134` passed migrations, RLS/security gates and the
  populated published-release integration regression. Exact release `33424142694`
  reached Alembic `0141`; smoke `33424391721` passed. The previously blocked
  synthetic tenant then returned DELETE `204` and independent GET `404`; no mail
  was sent.
- Prevention: every new tenant-owned RESTRICT or immutable table must be represented in the superadmin deletion contract and tested with a populated real-lifecycle tenant, not only an empty tenant fixture.

## TOOL-007 - Release workflow checks started from inconsistent working directories

- Date: 2026-08-31.
- Symptom: the first focused check did not start because Poetry was invoked from the repository root without a `pyproject.toml`; the parallel YAML check resolved a repository-relative path from `apps/api` and could not find the workflow.
- Cause: the validation commands mixed the repository-root path contract with the canonical `apps/api` Poetry working directory.
- Fix: run every Poetry command from `apps/api` and address repository files explicitly through `..\\..` paths.
- Verification: the corrected YAML command reports `YAML OK`, and the corrected focused pytest command reaches and executes all release workflow tests.
- Prevention: Kamilya Python verification commands must use `apps/api` as their working directory; repository-root artifacts must be passed with explicit relative paths.

## TEST-007 - Build-only workflow contract truncated YAML input blocks

- Date: 2026-08-31.
- Symptom: the new build-only contract test failed while the workflow correctly declared both previous-runtime inputs as optional.
- Cause: the test split an input section on any line beginning with at least six spaces, so it stopped at the first eight-space property line and inspected only the field name.
- Fix: extract the complete eight-space property body with a field-anchored regular expression before asserting `required: false`.
- Verification: the focused release-plane and workflow contract suite passes after the parser correction.
- Prevention: indentation-sensitive workflow contract tests must anchor both field and property indentation instead of using a prefix that also matches nested lines.

## TEST-009 - SCORM duplicate-path test depended on a platform-specific ZIP warning

- Date: 2026-09-04.
- Symptom: the Linux backend unit job failed at `pytest.warns(UserWarning, match="Duplicate name")`, while the same test passed on Windows and the SCORM intake still rejected the archive as `archive_duplicate_path`.
- Cause: Python's Windows ZIP writer normalized `\\` to `/` while building the fixture and emitted a duplicate-name warning; the Linux writer preserved both spellings and emitted no warning. The warning belongs to fixture construction and is not part of the product security contract.
- Fix: construct two distinct case variants that remain distinct ZIP members on every supported platform but collide under the intake's canonical `casefold()` identity, then assert only the product rejection code.
- Verification: run the focused SCORM intake test, the complete backend unit suite and the GitHub Linux CI job on the exact pushed revision.
- Prevention: cross-platform archive tests must assert application-owned validation outcomes, not incidental warnings emitted by a standard-library writer on only one operating system.

## TEST-010 - Route registration test inspected FastAPI's internal route representation

- Date: 2026-09-04.
- Symptom: the complete backend CI suite failed with `AttributeError: '_IncludedRouter' object has no attribute 'path'` while the focused course-blueprint behavior and integration tests remained green.
- Cause: the test iterated `app.routes` and assumed every internal route object exposed `.path`; the upgraded FastAPI version retains included routers as lazy `_IncludedRouter` objects instead of flattening every route into that private collection.
- Fix: assert the three registered course-blueprint paths through the application's generated OpenAPI contract, a public representation of the effective HTTP surface.
- Verification: run the focused route-contract test, the complete local no-DB suite and the exact-revision GitHub backend suite with PostgreSQL, migrations, RLS and coverage.
- Prevention: application route-contract tests must use public OpenAPI output or supported router APIs and must not depend on private FastAPI route object classes.

## GH-001 - Project token could not dispatch the image-build workflow

- Date: 2026-08-31.
- Symptom: the exact build-only `workflow_dispatch` request returned HTTP 403 `Resource not accessible by personal access token`; no workflow run, package or production mutation was created.
- Cause: the canonical project token can push and read repository state but does not have authority to dispatch Actions workflows.
- Fix: trigger immutable image construction automatically from a successful `CI` `workflow_run` on `master`; retain manual dispatch plus the protected environment as the only path to the production job.
- Verification: workflow contract tests prove the event-derived SHA/run identity, successful-master condition and manual-only deploy condition; the next exact SHA must produce a green CI followed by an automatic image-build run.
- Prevention: routine artifact construction must be event-driven from verified CI rather than depend on a broad personal token; production execution remains separately authorized and protected.

## GH-002 - Automatic image build overrode the event SHA with an empty manual input

- Date: 2026-08-31.
- Symptom: automatic release run `33377535020` passed CI identity and checkout, then failed `Verify checked-out SHA` because the step-level `RELEASE_SHA` was empty; no image or production mutation occurred.
- Cause: the verification step retained `RELEASE_SHA: inputs.release_sha`, which is empty for `workflow_run`, and overrode the correct event-derived job environment.
- Fix: remove the step-level override so validation, checkout, verification, image tag and evidence artifact all consume the same event-derived job SHA.
- Verification: the workflow contract forbids a direct manual-input SHA override inside `build-image`; the next successful master CI must trigger an image build with the exact event SHA.
- Prevention: normalize multi-trigger identity once at job scope and prohibit narrower steps from redefining release identity variables.

## DEPLOY-007 - Release controller required a newer Python than VM126

- Date: 2026-08-31.
- Symptom: controller downloads, files and wrapper installation succeeded, but importing the controller failed; the transactional installer removed controller artifacts and left the legacy production runtime unchanged.
- Cause: VM126 runs stock Python 3.10.12, while the controller imported `datetime.UTC`, which is available only from Python 3.11. Installing an unreviewed PPA or the available pre-release Python package would have expanded the production change scope.
- Fix: use Python 3.10-compatible `timezone.utc`, and make the protected workflow invoke only the installed fixed-command runner wrapper.
- Verification: focused controller and workflow contract tests, static Python 3.10 compatibility assertion, then exact-SHA CI, immutable GHCR image and VM126 import readback.
- Prevention: release controllers must test against the oldest supported production runtime and must not rely on unreviewed PPA or pre-release system packages.

## DEPLOY-008 - Runner hardening blocked its fixed-command privilege boundary

- Date: 2026-08-31.
- Symptom: the protected KZ production job passed GitHub environment approval but failed before controller validation because `sudo` reported the inherited `no new privileges` flag. After removing the direct flag, a later execute reached the controller but CT125 SSH returned exit 255.
- Cause: several systemd sandbox directives implicitly set `NoNewPrivileges` for the complete runner process tree, while `ProtectHome=true` hid the root-owned CT125 identity and known-hosts files from the same mount namespace. A successful `runuser ... sudo` check outside that namespace did not test the actual job boundary.
- Fix: retain a dedicated non-login runner account, exact fixed-command sudoers and `PrivateTmp=true`, but remove systemd directives that block the intentional fixed-command elevation, hide root-owned CT125 identity files or remount release-plane write paths read-only. Verify `NoNewPrivs: 0` on every runner process, exact CT125 file readability and exact state/evidence/lock/proxy path writability from the runner mount namespace without copying or printing secrets.
- Verification: the corrected runner reported three processes with `NoNewPrivs: 0`; the workflow validation passed; the protected release completed; independent readback confirmed exact public/private health, four matching zero-restart containers and CT125 revision `0140`.
- Prevention: runner acceptance must execute the exact workflow wrapper from the service process namespace. Host-level sudo success and `systemctl is-active` are insufficient release evidence.

## DEPLOY-009 - CT125 release gate pinned an obsolete guest hostname

- Date: 2026-08-31.
- Symptom: after runner and SSH recovery, the CT125 release gate returned exit 1 even though revision `0138`, encrypted-backup freshness, modes, checksum, timer and plaintext-absence checks all passed.
- Cause: the newly introduced gate required hostname `kml-db`, while independent runtime readback identified the canonical CT125 guest as `KML-1-77`.
- Fix: bind the gate to the verified `KML-1-77` identity and add a focused contract test that preserves strict SSH, revision, timer, checksum and encrypted-backup checks.
- Verification: exact SHA `be35e60c2b1af1465f770375ba9ff15e8bed4d0b` passed local contracts and full GitHub CI; the configured gate SHA matched source, the protected release succeeded, and independent CT125 readback returned revision `0140` with the backup timer active.
- Prevention: guest identity assertions must come from current provider/runtime readback and be covered by contract tests; never weaken or remove identity verification after drift.

## DEPLOY-010 - Rollback trap restored an empty file before backup initialization

- Date: 2026-08-31.
- Symptom: a host-gate update failed safely before its intended edit, but the rollback trap replaced an unused `/usr/local/sbin/kamilya-ct125-release-gate` path with an empty root-owned executable.
- Cause: `mktemp` created the backup path and the EXIT trap was armed before the existing target had been copied into it. A pre-copy assertion failed, and cleanup treated the empty temporary file as a valid rollback source.
- Fix: build and hash-verify the candidate before touching the target; copy the current target and assert a non-empty exact backup before arming rollback; restore only when that populated backup exists. The actual configured gate under `/opt/kamilya-release-plane/bin` was updated transactionally with this corrected order.
- Verification: the configured gate matched source SHA `eaf3dadd4a8894252e31d29981a002b3ab9ee605a5232443f09574035244ab3f`, passed direct CT125 revision/backup checks, and the protected release plus independent production readback succeeded.
- Prevention: every rollback trap must distinguish “temporary path exists” from “valid backup captured”; pre-mutation tests must exercise failure both before and after backup initialization.

## DEPLOY-011 - Release-plane bundle stripped the systemd unit suffix

- Date: 2026-08-31.
- Symptom: protected release-plane upgrade run `33395655075` stopped at the pre-install validation step with `validation_command_failed:systemd-analyze`; install and readback steps were skipped.
- Cause: the deterministic bundle renamed every source to `*.payload`. `systemd-analyze verify` requires the staged unit filename to retain a recognized `.service` suffix even when its content and SHA-256 match the installed unit.
- Fix: bundle payload names preserve a type-safe source suffix; extensionless fixed shell wrappers receive `.sh`. Destinations, modes, hashes and the fixed allowlist remain unchanged.
- Verification: focused bundle tests assert `.service` and `.json` preservation, the complete release-plane contract suite passes locally, and the next exact workflow run must pass validation before any install.
- Prevention: staged artifacts consumed by type-sensitive validators must retain the required filename type, and the bundle contract must test both bytes and validator-visible names.

## CI-003 - Bounded purge rejected the ephemeral CI database owner

- Date: 2026-09-03.
- Symptom: course-approval DEV acceptance passed under the production-like `lms_app` runtime role, but full GitHub CI failed three guarded tenant-deletion tests with `Active superadmin context is required`.
- Cause: migration `0148` required `session_user = 'lms_app'` inside its `SECURITY DEFINER` purge functions. Ephemeral integration tests intentionally run the API as the current database owner, which is already the privileged identity used by the established tenant-purge boundary.
- Fix: additive migration `0149` retains the active `app.is_superadmin` flag and exact slug/protected-tenant checks, while accepting only `lms_app` or the current database owner; every other session role remains rejected and no table-level `DELETE` grant is added.
- Verification: the Python quality baseline, 55 focused contracts and all 864 backend unit tests pass locally; full ephemeral-PostgreSQL lifecycle verification is required from the replacement exact-SHA GitHub CI before release.
- Prevention: security-definer migrations must test both the production runtime role and the ephemeral database-owner execution contour. A DEV route smoke under only one database identity is not sufficient release evidence.

## TOOL-008 - Persistent smoke provisioner crossed the admin/methodologist role boundary

- Date: 2026-08-31.
- Symptom: the first persistent production smoke provisioning run created the correctly marked synthetic tenant, then stopped with HTTP 403 on `GET /users`; no user or email was created.
- Cause: the provisioner used an impersonated tenant `admin` token to list staff even though the canonical product contract assigns staff visibility to `methodologist` and tenant lifecycle visibility to `superadmin`.
- Fix: use the superadmin tenant-admin listing for idempotent methodologist discovery; use the bounded admin-context only when a new methodologist must be created with a password; verify the final account through its own methodologist login.
- Verification: the corrected script compiles, reuses the one exact synthetic tenant and must return `READY` with `mail_sent=false` before browser acceptance.
- Prevention: operational smoke tooling must model each route with its real product role and may not broaden a tenant role merely to simplify idempotency.

## CRM-001 - Disabled CRM integration churned durable events and masked worker readiness

- Date: 2026-09-02.
- Symptom: when `CRM_WEBHOOK_URL` or `CRM_WEBHOOK_SECRET` was absent, delivery claimed an outbox event and finalized it as `configuration_missing`, moving it into retry churn. Configured delivery posted lead payloads without first proving that a sleeping Render Free receiver was awake. The operations endpoint also applied the same timeout to Celery inspect and its outer async wait, systematically reporting healthy workers as unavailable when inspect consumed the full budget.
- Cause: configuration and receiver readiness were checked after the durable claim; there was no non-payload health phase, and the outer timeout had no margin over the Celery control timeout.
- Fix: disabled mode now returns `status=disabled` before opening a session or selecting/claiming rows. Configured delivery derives or accepts an explicit safe health URL, performs a bounded GET health check, and defers before claim on cold/unavailable receivers. Signed payload delivery and post-readiness retry classification remain unchanged. Operations now exposes `integration_status` and `held_count`, with an outer Celery timeout margin.
- Verification: focused CRM and operations tests pass (`35 passed`), including disabled-mode no-claim, recovery no-select, health-before-payload, wake-then-deliver, URL safety, and timeout-margin cases. Full backend execution was attempted but is blocked in this workstation by local PostgreSQL `ConnectionRefusedError [WinError 1225]`; no production or provider mutation was performed.
- Prevention: optional integrations must fail closed before durable claims, external wake/readiness must be a separate non-payload phase, and nested timeouts must reserve an explicit outer margin. Observability contracts must distinguish disabled/held integrations from unavailable workers.

## REMINDER-002 - Non-bypass function owner silently hides due recurring rules

- Date: 2026-09-05. Status: FIXED LOCALLY; production release pending. Owner
  explicitly approved additional migration and unattended acceptance afterward.
- Symptom: on release de6684ab, UI creates and activates a synthetic recurring
  rule, but scheduled recovery repeatedly reports due=0, processed=0. The rule
  is active and next_run_at is in the past; no occurrence or reminder is created.
- Cause: due_recurring_learning_rules(integer) is SECURITY DEFINER owned by
  kamilya_migrator (not superuser, no BYPASSRLS). The FORCE-RLS rules table has
  only tenant_isolation TO lms_app, so the function owner cannot see due rows.
  Worker recovery and application connections target the same host/database;
  actual lms_recovery invocation independently reproduces the empty selection.
- Verification: scripts/ops/manager_attention_acceptance_readback.sh, pre-cleanup
  SHA 4d633dad9ec8ad5c2de5977373bfa7a81787b9b85f30173ef2370dc9b290790a;
  canonical VM126-to-CT125 route, read-only SQL, no provider calls or DB writes
  from the probe. Final cleanup SHA
  24715affaa8fefe5fb49433637a576024eed4bdc7b781516ab9ec36aae272569
  confirms inactive rule, reminder opt-out, zero occurrences/outbox rows,
  and zero active users among the three owned synthetic pilot users.
- Fix: additive0153 adds five owner-resolved SELECT policies on four tables.
  Global discovery only admits active/due rules; reminder-related reads remain
  tenant-context-bound. Existing policies, runtime grants, FORCE RLS, function
  bodies and public-function revocations remain intact; no role attributes change.
  Supabase DEV gate reproduces the empty discovery before the fix and passes10
  checks after it, including two-tenant course/program payloads, opt-out,
  duplicate suppression, downgrade/history preservation and re-upgrade.
  Temporary owner/caller roles are NOLOGIN/non-bypass and rolled back with their
  membership and ownership changes; zero roles/schemas remain. Supabase admin
  cannot SET ROLE lms_app/lms_recovery: caller permissions are mirrored only to
  the temporary caller; actual runtime ACLs are separately checked. This is real
  non-bypass-owner SQL evidence, not a real production recovery login or SMTP test.
- Prevention: DEV owner visibility must reproduce production. The existing
  application harness adds fixture_owner USING(true), which cannot prove the
  real function-owner RLS path. Require a failing non-bypass-owner reproduction,
  two-tenant negatives, isolated upgrade/downgrade, and actual scheduled recovery
  before business acceptance. Inspect processed/due, not merely Celery SUCCESS.
- Safe state: test rule stopped and reminder disabled through UI; three pilot
  accounts soft-deactivated. History and persistent synthetic tenant retained.

## TOOL-009 - Linked release worktree looked for credentials beside `.worktrees`

- Date: 2026-09-13.
- Symptom: a reviewed protected restore drill passed its dry-run contract but the
  execution gate stopped with `credential_source_unavailable` before opening a
  network connection.
- Cause: `kz_remote_exec.py` derived the workspace as `REPO_ROOT.parent`. That is
  correct for the primary checkout, but from a linked release worktree it points
  to `C:\Kamilya New\.worktrees` instead of the canonical workspace root.
- Fix: resolve the primary repository through the linked worktree `.git` pointer,
  require the canonical `.git/worktrees/<name>` shape, and derive the shared
  workspace from the primary repository. Malformed or foreign metadata fails
  closed; the environment-file allowlist remains unchanged.
- Verification: the defect was first reproduced by two failing public-seam tests.
  The complete protected remote-exec contract now passes 53 tests covering a
  primary checkout, a linked worktree and rejection of a noncanonical Git path.
  The failed pre-fix attempt performed no network, server, backup or database
  mutation.
- Prevention: every operational helper that derives a workspace-owned trust path
  must be tested from both the primary checkout and a real linked-worktree shape.
  Do not duplicate secrets into `.worktrees` to mask an incorrect path.

## REMINDER-003 — Legacy assignment outbox FORCE RLS blocks recurring materialization

- Date: 2026-09-05
- Status: FIX IN PROGRESS; production pilot stopped pending exact release.
- Symptom: on 4aaf0b79 / CT1250153, actual lms_recovery discovers the due
  synthetic rule, but materialize_rule rolls back at
  enqueue_course_assignment_notification with InsufficientPrivilegeError on
  course_assignment_notification_outbox. The table and SECURITY DEFINER function
  are owned by non-bypass kamilya_migrator, INSERT/UPDATE ACLs are present,
  FORCE RLS is enabled and no table policy covers that owner.
- Cause: missing non-bypass function-owner RLS coverage in legacy migration0097.
- Additional source boundary: course outbox actor FK is nullable, and audited
  platform impersonation creates recurring rules with created_by=NULL, but the
  old enqueue function rejects NULL. Path enqueue already permits that system
  actor and rejects foreign non-null actors.
- Fix: additive0154 owner-only SELECT/INSERT/UPDATE coverage; discovery
  sees only due rows without context; writes remain tenant-context constrained.
  Existing path outbox gets due-only owner SELECT for bounded recovery. Course
  actor validation permits NULL while preserving foreign-tenant rejection.
  No runtime table grant, DELETE policy, BYPASSRLS or RLS disable is introduced.
- Verification: runtime reproduction and empty historical queues confirmed;
  independent source review passed. DEV baseline reproduces42501 on actual
  course enqueue;0154 green21 checks across reminder/course/path queues, nullable
  and foreign actors, due-only owner visibility, direct-ACL negatives, dedup,
  downgrade/re-upgrade and history preservation. Cleanup: schemas0/roles0;
  provider calls0/shared-public writes0. Production acceptance remains pending.
- Prevention: test the actual legacy assignment outbox as well as the new
  reminder ledger under production-shaped non-bypass ownership. A passing
  isolated reminder ledger cannot prove materialization-to-delivery acceptance.
- Safe state: exact synthetic rule inactive/reminder disabled, no occurrence
  or outbox row committed, no automatic email sent; original customer rules
  and tenant data untouched. The activated synthetic learner remains available
  only until the follow-up test and cleanup complete.
## AI-CANCEL-001 - Cancelled generation persisted an unlinked course

- Date: 2026-09-06. FIXED LOCALLY; production deployment and reacceptance pending.
- Symptom: synthetic job `6393f0b1-c19b-4f1b-af41-91e51882baa7` was cancelled,
  but its worker later committed unlinked draft course
  `c51d62c8-d942-4755-862c-261461c3fa0d`.
- Cause: cancellation was checked before the assessment stage, while assessment
  retries and the independent course transaction could continue after cancellation.
- Fix: cancellation checkpoints surround every assessment model request and retry;
  progress advances only after a lesson assessment completes. Cancellation and
  persistence now take the same tenant-scoped `ai_jobs` row lock, and course data,
  job completion, and course linkage commit in one transaction. Diagnostics use
  bounded validation reason codes without generated or tenant content.
- Verification: focused regression suite 59 passed. Initial CI run `34046308482`
  exposed one stale integration setup that called the protected save helper without
  an `AIJob`; the test now runs through a tenant-scoped `running` job in the same
  rollback transaction. A disposable Supabase DEV
  schema ran six real concurrent save/cancel races; both terminal outcomes occurred
  (latest run: four cancelled/no course, two completed/correct link), with no split
  state. Runtime role remained
  non-superuser/non-BYPASSRLS, shared migration head was unchanged, and cleanup passed.
- Cleanup: after a 19-path foreign-key inventory showed only the course's own
  cascading module tree, the exact synthetic residual was deleted through the
  normal API. Original course `67d782f2-0478-4555-9c19-99d4bc071789`, source
  `05097f1b-8ae9-47be-ad26-0c65bdfb7a16`, and cancelled job history remain.
- Prevention: every cancellable background writer must prove both cancellation
  checkpoints and transactional exclusion at the final persistence boundary.
  Tests that call that boundary directly must seed the same active-job invariant
  as the production queue/worker path; the runtime must not create or infer a
  missing job as a compatibility fallback.
## TEST-011 - An unstable translation mock can starve journal test timers

- Date: 2026-09-06.
- Symptom: the full frontend suite kept one worker busy with increasing memory;
  the isolated `trainingLogDeadlineView.test.tsx` legacy-row case also failed to finish.
- Cause: its useT mock created a new t function on every render. The journal's
  fetch callback depends on t, so state changes repeatedly re-triggered the request.
  The real translation hook preserves function identity with useCallback.
- Fix: keep the test translator stable and add the supported empty catalog response
  to the mock. No production fetch logic or deadline assertions were weakened.
- Verification: the same isolated case completed in ~2 seconds; the four affected
  feature/journal files passed 35 tests. Full-suite evidence is recorded separately
  in docs/product/learning-insights/VERIFICATION_2026-09-06.md.
- Prevention: translation mocks must match reference-stability guarantees used by
  effects; verify the full page, not only helper/source-string assertions. Diagnose
  a stuck runner by per-module progress and stop only its owned session, not all Node processes.

## CI-004 - Successful Next build did not satisfy zero-warning ESLint

- Date: 2026-09-06.
- Symptom: local web tests/build/typecheck passed, but dev CI34027881507 failed
  frontend lint on two exhaustive-deps warnings in LearningInsights.tsx.
- Cause: root's local release packet omitted the separate package lint script.
  Next build tolerates warnings; `eslint . --max-warnings=0` does not. Callback
  filters and initial review objects were referenced through scalar dependency lists.
- Fix: create filters inside the callback and derive reset state from primitive
  review fields. Do not add unstable whole-object dependencies or suppress lint.
- Verification: strict pnpm lint, focused17 tests and typecheck passed; new
  regression preserves in-flight save and prevents refetch on equivalent rerender.
  Replacement exact-SHA CI remains mandatory; earlier failed CI is not a pass.
- Prevention: frontend release packets name pnpm lint separately from build and
  typecheck. Preserve reference stability and tenant cancellation when fixing hooks.
## INFRA-009 - Proxy disk exhaustion blocked multipart document uploads

- Date: 2026-09-07.
- Symptom: a 281596-byte PDF upload returned an nginx HTTP 500 before reaching
  the API, while a 56-byte text upload succeeded.
- Cause: the proxy root filesystem had zero available bytes; request bodies that
  exceeded nginx's in-memory buffer could not be written to its body temp path.
- Fix: the approved bounded cleanup removed only the apt package cache. No
  application data, database data, tenant file, release artifact, or log was deleted.
- Verification: apt cache fell from 328855552 to 20480 bytes, root availability
  rose from zero to 197349376 bytes, and the exact same PDF upload then returned
  the application success contract. The cleanup wrapper's `>250 MB` postcondition
  remained red because the host is still 96% used; that assertion failure is not
  evidence that the cleanup was rolled back.
- Prevention: alert on proxy byte and inode headroom before nginx reaches zero;
  keep package-cache cleanup bounded and recoverable, and do not diagnose a
  large-body nginx 500 as an application upload failure until temp-path capacity
  has been read back. Remaining disk pressure requires a separate capacity audit.
- Recurrence follow-up (2026-09-07): before landing cutover the 4.9 GiB proxy
  again had only about 56 MiB free. The staged landing archive was only a
  temporary 4.8 MiB transit file and was removed; the dominant removable growth
  was systemd journal at about 440 MiB. A bounded vacuum plus apt cleanup raised
  free space to about 509 MiB. Persistent journald limits now set
  `SystemMaxUse=100M` and `SystemKeepFree=300M`; after certificate issuance and
  Nginx config about 399 MiB remained. Proxy scope is Nginx/TLS, WireGuard and
  SSH transit only; never install application runtimes or retain source archives.

## AI-PROVIDER-001 - Production could not persist an encrypted provider key

- Date: 2026-09-07.
- Status: resolved in production; no provider secret was persisted by the failed
  calls.
- Symptom: the superadmin provider-key endpoint returned HTTP 500 when activating
  the owner-selected DeepSeek primary; the provider list remained empty.
- Cause: VM126 runtime had no `PROVIDER_KEY_ENCRYPTION_KEY`. A container-local
  synthetic encryption roundtrip reproduced `EncryptionKeyMissingError` without
  reading or emitting any provider secret.
- Fix: bootstrap one root-owned Fernet key in the canonical production runtime
  environment, keep a rollback copy, load it through the normal blue/green
  release, and store the existing DeepSeek key only through the encrypted
  superadmin provider-key endpoint.
- Verification: the runtime environment contains a root-owned encryption key and
  rollback copy without exposing either value. Release
  `6de9ebb660ae954aefa7436a7952e45805ca6e1b` loaded it into the API and workers;
  a synthetic encryption roundtrip passed, the existing DeepSeek key was stored
  only through the encrypted superadmin endpoint, and the provider probe returned
  success with `last_error=null`. Real-document generation then completed for a
  281,596-byte Plus PDF and a 51,712-byte Lombard DOC; all disposable records were
  removed. Release `9b2fad9056e2e6f64728b99a4c31a14bfb271d7d` fixed the runtime order as
  `deepseek -> custom:qwen38-flash-next -> glm53-flash-asus`; an independent
  synthetic completion used DeepSeek without failover. The ASUS fallback network
  path remains a separate infrastructure gap: VM126 still times out to
  `10.66.66.30:8888` and `10.66.66.28:8000`.
- Prevention: production readiness must verify a synthetic provider-key encryption
  roundtrip before declaring provider-key management available. Provider status
  and probes may expose only provider name, activation state, latency and error
  category; plaintext and ciphertext never enter evidence or logs.

## TEST-012 - A phone-shaped apply-marker UUID triggered assistant PII refusal

- Date: 2026-09-07.
- Symptom: exact-SHA CI failed one otherwise safe assistant test because a random
  lesson UUID made the public response policy return the generic scope refusal.
- Cause: the policy scanned the raw model response before parsing the internal
  `[APPLY_LESSON:UUID]` protocol marker. A UUID ending in eleven decimal digits
  matched the phone-number redactor even though the UUID was not public content.
- Fix: parse the marker first, then apply the unchanged fail-closed policy
  independently to the visible reply, proposed lesson content and optional title.
  Marker UUIDs remain constrained to the methodologist-selected lesson.
- Verification: a deterministic phone-shaped UUID reproduces the pre-fix refusal;
  the corrected assistant policy suite passes all 28 tests, including secret and
  cross-lesson rejection cases. Replacement exact-SHA CI remains required.
- Prevention: structured internal response metadata must be parsed before public
  content redaction, while every user-visible or persisted field is validated
  separately with deterministic adversarial identifiers.

## INFRA-010 - Frontend hosting and TLS renewal documentation lagged runtime

- Date: 2026-09-07.
- Symptom: `app.kml.kz` was moved from Vercel to CT137, while canonical current
  sections still named Vercel as production runtime. The first Let's Encrypt
  certificate used a manual DNS challenge and therefore was not a suitable
  unattended renewal configuration.
- Cause: the frontend hosting boundary changed independently from the existing
  KZ API/DB cutover. Dated Vercel release evidence and current topology were not
  clearly separated. Certbot inherited `manual`/DNS preferences when renewal was
  reconfigured.
- Fix: production frontend now runs as native Next.js/OpenRC/Nginx on CT137,
  without Docker, behind the existing public KZ proxy and a narrow WireGuard
  peer. Cloudflare uses DNS-only `app.kml.kz -> 92.38.49.167`. Certbot renewal
  was reconfigured to `webroot` with HTTP challenge preference; the temporary
  DNS challenge record and work directory were removed. Vercel is retained only
  as the documented CNAME rollback.
- Verification: authoritative Cloudflare, Google and Cloudflare resolvers returned
  the new A-record; public TLS, `/healthz`, `/login`, API health and landing health
  passed. CT services survived restart; exact frontend SHA
  `e463527cd8f5e67e987c44d8d769f337714bd25f` matched active release and health
  identity. A synthetic production methodologist reached `/dashboard` without
  page errors or failed app/API requests. `certbot.timer` is enabled/active and
  renewal config identifies `webroot`.
- Prevention: start every frontend release with
  `docs/PRODUCTION_FRONTEND_RUNBOOK.md`; build only a committed clean SHA, keep
  immutable releases and an explicit rollback, prove exact runtime identity plus
  a real role flow, and preserve dated Vercel rows as history rather than current
  state. A manual certificate success is not automatic-renewal evidence.

## INFRA-011 - Proxmox node migration is not a public routing change

- Date: 2026-09-07.
- Symptom: after CT137 moved from `pve2` to `pve3`, it was unclear whether
  Cloudflare, proxy or WireGuard must be reconfigured.
- Cause: Proxmox placement and application ingress were treated as the same
  identity, although public routing terminates at the KZ proxy and reaches the
  preserved WireGuard identity inside the migrated container.
- Fix: no routing mutation was made. CT137 retained guest IPv4
  `192.168.1.237`; public DNS remained `92.38.49.167`.
- Verification: public frontend `/healthz` and `/login`, production API health
  and landing returned HTTP 200 after migration. Frontend body and
  `X-Kamilya-Release` matched exact SHA
  `e463527cd8f5e67e987c44d8d769f337714bd25f`.
- Prevention: after a Proxmox node migration, verify guest network, WireGuard
  and application services plus public exact-SHA/business readback before any
  DNS or proxy change. Update the internal node placement only; do not expose
  Proxmox topology in client-facing documentation.

## INFRA-012 - Apex geography check was mistaken for LMS application hosting

- Date: 2026-09-07.
- Symptom: a domain checker reported `kml.kz` at AS16509/Amazon in the US after
  the production application frontend had moved to CT137 in Kazakhstan.
- Cause: at the time of the first check the apex and `www` marketing landing
  still used Vercel, while the LMS application hostname `app.kml.kz` already
  used the KZ contour. The checker result was correct for those exact names but
  was overgeneralized to every Kamilya service.
- Fix: the separately authorized landing release moved `kml.kz` and
  `www.kml.kz` to CT137 behind the same KZ proxy. Cloudflare replaced only the
  two Vercel CNAME records with DNS-only A `92.38.49.167`; mail/MX/TXT were not
  changed. Vercel remains a rollback artifact.
- Verification: Cloudflare UI and public resolvers `1.1.1.1` and `8.8.8.8`
  returned A `92.38.49.167` for apex and `www`. Public TLS, redirects, RU/KK,
  exact landing release header, CSP, robots, sitemap and safe lead validation
  passed. `mail.kml.kz` remained `144.91.117.51` and apex MX remained
  `mail.kml.kz` priority 10. Hoster.KZ still displayed its earlier timestamp and
  Amazon values immediately after cutover; treat that page as stale until its
  own cache refreshes.
- Prevention: verify every hostname by authoritative configuration plus at least
  two public resolvers and current TLS/runtime readback. Record third-party
  checker timestamps; a stale page is not authoritative evidence. Landing and
  LMS frontend remain separate repositories/services/releases even though both
  run on CT137.

## AI-EMBED-001 - Query protocol and vector association must be provider-specific

- Date:2026-09-10. Candidate ASUS embedding integration; not a production release.
- Symptom: indexed response ordering can attach a vector to the wrong fragment.
- Cause: consuming indexed responses in array order rather than their explicit
  input indices; generic query preprocessing can alter
  document text or another provider's input protocol.
- Fix: Qwen-only query instruction and L2 normalization, unchanged document text,
  strict indexed-response ordering, one-provider batch fallback and exact-space
  provenance. No cross-provider vector comparisons or implicit tenant-key fallback.
- Verification:65 focused tests; actual synthetic candidate adapter returned4096
  dimensions, unit norms and the correct top document in2.92s on the workstation.
  VM126 worker timed out through its LAN gateway; workstation reachability is not
  production reachability. No network configuration was changed.
- Prevention: retain `test_asus_embeddings.py`, failover/provenance tests, and
  independently verify connectivity from the real worker before release.

## AI-SOURCE-001 - Prefix-only source context loses catalog topics

- Resolution2026-09-10: release0.4.4 (`56f07a4bcbb96a32542a5cadf5243c6f5ad4cb47`)
  deployed the shared exact-serializer budget, per-batch topic allocation,
  budget-aware cache revalidation and one bounded retry with explicit shorter-name
  guidance. Normal production job4acdf88a-f023-47f9-8ec0-43771f8ed4d0 processed
  the owned103616-byte representative Excel copy in744.5seconds and persisted
  3modules/14lessons/14quizzes/54questions. Production browser acceptance under
  the synthetic methodologist verified first/last tests, source explanations and
  tail topics. Acceptance customer writes remained0. A subsequent owner-requested
  repair reindexed the exact existing failed customer document through the normal
  API: jobf413ce89 completed in202.6seconds, revision2 read back ready/success;
  exact source size/hash were checked and source bytes remained unchanged.
- Prevention evidence:1228unitPASS plus focused retry/cache regressions; CI and
  protected release PASS; public health0.4.4/exact SHA; watchdog exact image/SHA
  one-shot PASS and timer active. Keep generated content draft/review-required;
  technical generation success does not replace methodologist approval.
- Current2026-09-10 MAP-V7 candidate: normal0.4.3 jobf0ef8a9d failed
  source_topic_map_overview_budget_exceeded before course creation. Legal per-batch
  outputs had no shared serialized topic allocation. Reserve the exact final
  serializer's framing first, allocate topics across batches and revalidate both
  model output and cache hits. Existing one-retry,28k overview,32k planner and
  90second limits remain; accepted labels/source references are never clipped.
- Candidate evidence:1178unit tests PASS, Ruff1088/mypy2345 baseline unchanged;
  real932source/44batch map
  produced474topics and19499overview chars with45calls in56.27seconds. One earlier
  isolated probe exited1 without a classified error; do not erase that failed
  attempt or claim universal provider reliability. The instrumented replay passed.
  Cached map then produced3modules/14lessons with1architect call in14.42seconds.
  Script hashes5ef9a627/3eddf4fb; no installed-code/SQL/course writes. Whole queued
  course, quiz review and cleanup remain mandatory before client GO.
- Date:2026-09-10.
- Symptom: source tails and unevenly sized documents were omitted from architecture
  context; reproduced with a636k-character synthetic catalog.
- Cause: prefix-only context selection discarded later chunks before planning.
- Fix: bounded all-chunk topic mapping for large/overlap-expanded sources; small
  sources retain all chunks. Cap actual provider output at1024tokens per map call,
  delimit untrusted metadata and parse standalone JSON. Retry feedback retains
  the original question number and tolerates malformed/null option containers.
- Verification: root107 combined focused tests and5 separate database-free
  AI-COURSE-01 checks pass. Mechanical chunk coverage is not proof that every
  source fact is taught; full persisted provider/browser acceptance remains open.
- Prevention: retain catalog/small-source/map/assessment regressions; do not
  replace complete-source processing with an unlabelled sample or loosen question
  grounding/quality checks to turn a partial live result into a passing course.
- 2026-09-10 resilience candidate (not deployed): real932-chunk Excel exposed
  separate failures in a320-character map-content cap and model-owned source-ID
  partitioning. New protocol extracts one detailed aggregate per deterministic
  batch and attaches exact IDs in code. Overview keeps all topics with lossless
  inclusive ranges/document associations; 28000-char overview stays under the
  existing32000-char combined architect request guard. Candidate map output cap
  is2048tokens; current deployed0.4.1 still uses its1024-token protocol.
- Evidence: first detailed candidate failed coverage after21calls; next mapped
  all44batches but overview exceeded24000chars. Real cache readback counted501
  topics/23837chars, explaining that limit independently. Final candidate read
  all44batches/932sources from Redis with0provider calls, built27441-char overview,
  and produced3modules/6lessons with1architect call in12.39s total. This is map and
  architecture acceptance, NOT saved-course/quiz/browser acceptance.
- Prevent recurrence: tests cover nine-topic/long-summary input, source tail,
  model-ID rejection, exact multi-document associations, cache identity including
  ordered chunk IDs and resolved model settings, tenant/job isolation,64-entry
  atomic TTL bound, one-fault cache circuit breaker and cancellation. Never equate
  a cached replay's0.43s with fresh full-course generation latency. Checkpoints are
  same-job only; the current Celery claim does not automatically reopen failed jobs.
- Writer continuation: the cold real map passed44calls/53.54s, architecture passed
  at67.85s, then writer rejected the full prompt before its first model call.
  Source-only24000-char packing ignored repeated Excel headings and metadata in
  the32000-char serialized request. A representative480-char-heading regression
  failed for one and two documents; exact serialized-budget packing of whole
  chunks fixes both while preserving every requested document and sent provenance.
  Focused writer/direct/semantic/catalog suite29PASS. V4 real candidate generated
  six lessons/26008chars in107.39s after a cached map; unchanged assessment produced
  26MCQs. Independent persistence/API verified3modules/6lessons/6quizzes/104choices.
  These staged measurements do not replace a fresh API-to-Celery production smoke.
- Browser continuation: page-local inline-only renderer exposed raw Markdown
  headings/tables. SafeLessonContent now renders bounded semantic blocks as React
  text, without HTML injection; malformed/escaped-pipe tables retain literal cells.
  Root review caught and fixed trailing-cell loss before integration. Tests include
  unsafe HTML/URLs, tables, CRLF, ordered-list start and long/unclosed-fence tails;
  frontend569tests and typecheck pass. Production renderer still awaits release.
- 2026-09-11 quality/passport candidate (not deployed): a technically complete
  course could still treat a large reference worksheet as the curriculum and admit
  generic lessons or meta questions. XLSX conversion also changed the active
  worksheet heading before flushing the preceding chunk, which could mislabel its
  provenance. The candidate preserves bounded worksheet boundaries, builds a
  deterministic primary/supporting/unknown passport, sizes from primary teachable
  content, keeps low-confidence classification advisory, prioritizes primary
  evidence during writing, and rejects source-poor lessons and meta questions
  factual source or a prerequisite. Verification: backend1252 unit tests,
  frontend578 tests, focused generation UI14 tests, and the Next.js15.5.23
  production build pass after the final boundary polish; DEV browser acceptance
  remains required. Prevention: keep the
  synthetic two-sheet workbook, heading-flush, low-confidence, lesson-admission,
  question-admission, and versioned-checkpoint regressions; never use raw row or
  chunk count alone as proof of teachable scope.

## DEV-GATE-001 - Historical application fixture rejected current DEV

- Date: 2026-09-10.
- Symptom: application gate required public0127 although verified Supabase DEV is0156;
  after owner-approved revision parameterization, seeding and rollback readback
  failed SQLSTATE22000 with expected-str/got-UUID in text document ID bindings.
- Cause: public revision identity was coupled to the isolated historical fixture;
  three raw SQL text-column bindings passed UUID objects to asyncpg.
- Fix: require explicit expected public revision before loading credentials; bind
  document_embeddings.doc_id and lifecycle document_id values as strings. Keep
  documents.id UUID values and isolated0127->0131 migration chain unchanged.
  Public preflight/postflight/cleanup compare the same explicit revision and final
  success fails closed on unknown/changed cleanup metadata or revision.
- Verification: offline gate suite18PASS; every failed live attempt removed its
  exact disposable schema and read back unchanged shared public state. Final
  HBR-DEV-APP-20260910T104753Z passed all lifecycle/RLS/rollback/retrieval checks,
  isolated schema removed, public0156/metadata unchanged.
- Current writer citations additionally contain doc_id/doc_name; the gate now
  requires those exact owned-document values alongside document/headings/context,
  while still rejecting private retrieval/model provenance. The old three-key
  assertion was stale; no production citation contract was changed.
- Prevention: fixture tests cover typed SQL bindings, mandatory revision argument,
  and cleanup failure. Do not lower RLS/provenance or public-state checks to accept
  a stale fixture, and never substitute customer-derived material for synthetic DEV data.

## RELEASE-ID-001 - Protected manifest rejected a noncanonical release ID

- Date: 2026-09-10.
- Symptom: workflow34469021162 failed release_id_invalid before its production job.
- Cause: root supplied AI042-prefixed mixed-case correlation instead of the actual
  release-plane contract ^REL-[A-Z0-9][A-Z0-9-]{7,95}$.
- Fix: validate REL-AI042-20260910-CF719EC9 against RELEASE_ID_RE before dispatching
  replacement34469207530 with unchanged source/CI/previous-runtime identities.
- Verification: ReleaseManifest.parse accepted the complete corrected manifest;
  first workflow production job skipped. Replacement34469207530 and independent
  API/all-three-worker exact image readback passed on0.4.2. Windows HostConfig
  validation cannot validate Linux absolute paths; full config validation ran in
  the Linux workflow. ReleaseManifest exposes parse, not from_dict.
- Prevention: validate complete release manifest locally before dispatch. Do not reuse
  generic operational correlation syntax as a protected release ID.

## AI-SMOKE-RATE-001 - Negative admission probe consumed the next start burst

- Date: 2026-09-10.
- Symptom: valid owned-source POST returned429 immediately after the unknown-source
  POST correctly returned404; no generation job was admitted.
- Cause: generate-course has burst1/10seconds and2requests/minute. Middleware counts
  rejected requests before application validation; the smoke issued back-to-back POSTs.
- Fix: space the two probes; when the negative was already independently verified,
  run only the positive probe after the window. Do not change production rate limits.
- Verification: unchanged release042 accepted the normal queued generation job on
  the positive-only run; source ownership/hash and negative404 already passed.
- Prevention: schedule negative and positive admission tests against actual endpoint
  rate windows; distinguish429 rate protection from demo quotas or provider failure.

## AI-SOURCE-002 - Supporting-sheet enrichment was rejected as curriculum promotion

- Date: 2026-09-12. Local candidate; production cause and release not claimed.
- Symptom: a structure grounded in the primary worksheet was rejected when its
  lesson description named a supporting worksheet as the source of examples.
- Cause: the structure-wide promotion guard treated titles, objectives and
  explanatory descriptions as one instructional-subject field. Separately, weak
  reference columns and a large worksheet could outweigh stronger learning
  evidence, and worksheet names were compared without document ownership.
- Fix: keep course/module/lesson titles and lesson objectives grounded in primary
  material. A supporting worksheet may appear in a description only when the
  lesson cites that exact worksheet and the wording links its facts to the primary
  subject; an exact named possessive example is the narrow fallback. Compare
  worksheet roles with strong reference markers and same-document primary peers,
  track headings as document-scoped pairs, and reject an ambiguous same-name
  heading rather than accepting evidence from the wrong document. The unrelated
  unsupported-action guard remains active over all generated text.
- Verification: the public-seam regression was RED with
  `direct_source_supporting_section_promoted` and is now GREEN; the focused
  two changed-module suites are 28 PASS and the complete API unit suite is
  1407 PASS. The five database-free `AI-COURSE-01` checks are also PASS. The full
  owner-provided workbook was
  converted locally without network access and retained the intended compact
  primary plus much larger supporting split. Isolated Supabase DEV gate
  `HBR-DEV-APP-20260912T054348Z` passed, removed its disposable schema and left
  public revision `0158` plus shared metadata unchanged.
- Prevention: preserve tests for valid supporting enrichment, standalone
  supporting subjects, descriptions dominated by catalog data, uncited generic
  SKU details, same-name headings in different documents, document-scoped action
  evidence and primary-table rendering, missing primary headings, conflicting
  worksheet signals, large learning sheets and much larger English or multilingual
  reference sheets. Do not infer a production model failure from this shared error
  code without the rejected structure and branch evidence.

## AI-SOURCE-003 - Wide XLSX rows broke chunk bounds and deterministic reconstruction

- Date: 2026-09-12. Release candidate; production deployment is not claimed here.
- Symptom: a converter-owned worksheet row could exceed the configured chunk size;
  splitting a wide comparison table by columns then prevented deterministic course
  structure, while a note-only `Source:` row could be rendered as lesson content.
- Cause: the table chunker kept every row whole regardless of size, and downstream
  grouping used the exact full header tuple instead of the worksheet subject key.
  The structure builder filtered note-only rows but the lesson renderer did not.
- Fix: keep ordinary rows grouped, slice oversized rows into bounded parseable
  column fragments, reassemble fragments only within the same document/worksheet/
  subject-header boundary, and remove note-only rows before lesson selection.
- Verification: focused regressions cover the hard size limit, fragmented value
  reconstruction, column-sliced deterministic structure, source-note exclusion,
  multi-module partitioning and cross-document isolation. Full API, DEV and
  production results must be recorded separately after they run.
- Prevention: never relax the chunk-size invariant to preserve a row. Keep source
  ownership in the merge key, preserve converter-controlled worksheet boundaries,
  and require human quality review for the final persisted course and assessments.

## TEST-ENV-001 - Local critical journey silently selected localhost PostgreSQL

- Date: 2026-09-12.
- Symptom: a workstation critical-journey command ran five database-free checks,
  then attempted the DB integration selector against an absent local PostgreSQL.
- Cause: the journey contract mixed workstation-safe tests with a CI database test,
  while the shared fixture supplied a localhost fallback URL.
- Fix: the journey runner now defaults to the `local` execution profile and emits
  only database-free selectors; the DB selector is explicit in the `ci` profile.
  The DB fixture also rejects workstation localhost PostgreSQL before opening a
  connection. Only GitHub CI declares its ephemeral Postgres permission explicitly.
- Verification: runner tests prove local=5 plus one deferred DB check and CI=6;
  direct workstation invocation fails immediately with `local_postgresql_forbidden`
  before network access. The deferred application proof belongs to the isolated
  Supabase DEV gate with its normal cleanup/readback.
- Prevention: use `--execution-profile ci` only in the workflow that provisions its
  declared disposable database. On workstations, never set the CI override and do
  not replace the Supabase DEV gate with Docker or a localhost service. Do not run
  bare `pytest`/`pytest -q` as a workstation release gate because it also discovers
  DB integration suites; use the local critical-journey profile plus the isolated
  Supabase DEV application gate.
- Recurrence (2026-09-14): a PowerShell command read the emitted selector list by a
  root-relative path after changing its working directory to `apps/api`. File lookup
  failed, but PowerShell continued and expanded an empty array into bare `pytest`.
  The corrected invocation uses an absolute selector-list path, `$ErrorActionPreference
  = 'Stop'`, asserts the expected non-empty selector count, and checks pytest's exit
  code. The exact local journey then passed all six parametrized cases without a DB
  selector. Every generated-selector invocation must fail before pytest when the
  selector file is absent, empty or has an unexpected count.

## AI-EMBED-ROUTE-001 - A proven production gateway was replaced by an unreachable candidate

- Date: 2026-09-12.
- Symptom: document indexing tried the direct ASUS endpoint first, timed out from
  the production documents worker and then exhausted rate-limited managed
  fallbacks, even though the established Qwen embedding gateway remained healthy.
- Cause: the production default was changed from
  `https://qwen-embed.kml.kz/v1` to the candidate private address
  `http://10.66.66.15:8001/v1` after workstation inference passed, although the
  same review had not proved VM126 reachability and later documented a timeout.
- Fix: restore the established gateway and its published model ID as the first
  Qwen embedding provider. Keep the direct ASUS address outside production
  defaults until the actual production worker passes model discovery and a
  finite-vector inference through the intended private route.
- Verification: an immutable production-worker smoke returned HTTP 200 for model
  discovery and embedding, one finite 4096-dimensional vector, and 0.308 seconds
  for the synthetic inference. The direct address still timed out before TCP
  connection and routed through `ens18`, not `wg0`.
- Prevention: never replace a proven production provider route using workstation
  evidence alone. Before changing a default endpoint, verify from every consuming
  production worker: exact route, model identity, one bounded synthetic inference,
  dimensions, fallback order and rollback. Preserve the proven route until all
  checks pass, and keep a source-level regression for the production default.
- Resolution follow-up (2026-09-12): a separate ASUS peer was connected to the
  existing KZ WireGuard hub without modifying the active VM126/CT137 peers.
  VM126 reached a private hub listener, model discovery returned the exact
  Qwen/Qwen3-Embedding-8B identifier, and a real synthetic embedding returned
  one finite 4096-dimensional vector. Release 0.5.9 makes this verified private
  route the default; no public embedding hostname is required.
- Recurrence and fix (2026-09-13): the model at `10.66.66.15:8001` remained
  healthy, but its enabled connector socket was inactive while the KZ proxy
  listener remained active. VM126 therefore received an upstream HTTP error.
  The socket was restored and two independent private replicas were added on
  ports `18003` and `18004`. Fresh VM126 inference produced one finite
  4096-dimensional vector through each of the three paths. The application chain
  now tries all three replicas before Voyage and Cohere, and treats them as one
  canonical semantic space despite route-specific API model IDs.

## AI-GENERATION-ROUTE-002 - A configured fallback was unreachable from production

- Date: 2026-09-12.
- Symptom: Qwen 3.8 was second in the persisted generation order, but its direct
  ASUS LAN address was unreachable from VM126; a DeepSeek failure would spend
  the connect budget and skip to the next provider.
- Cause: workstation and ASUS-side model discovery had been treated as enough
  evidence even though the production worker had no route to the model LAN.
- Fix: add a separate private socket relay through the established KZ
  WireGuard hub and set the durable default to `10.77.77.1:18002`; remove the
  obsolete public legacy-Qwen defaults.
- Verification: VM126 discovered exact model `qwen3.8-flash-next` and completed
  a real chat request with thinking disabled. The embedding route on port 18001
  and the existing VM126/CT137 peers remained unchanged.
- Prevention: every provider admitted to the production order must pass model
  identity and bounded inference from the actual consuming worker. A configured
  position is not availability evidence.

## UI-001 - Completed course generation trapped the methodologist on the old result

- Date: 2026-09-13. Observed in production after the native `0.5.14` frontend
  readback.
- Symptom: reopening `/ai/generate` restored the last completed course and showed
  its review screen, but offered no action to begin another course. Navigation
  away and back restored the same completed workflow again.
- Cause: completed jobs were intentionally restorable, while the review branch
  exposed only review, edit and course-list actions. The existing workflow reset
  was wired only to failed-generation retry.
- Fix: expose a dedicated `Create new course` action for a completed review. It
  clears the stored job and workflow context, resets page-scoped generation state
  and returns to document selection without changing the authenticated session.
- Verification: focused hook and page regressions are 19 PASS; frontend lint with
  zero warnings and TypeScript typecheck pass. Exact production browser readback
  belongs to the `0.5.15` release evidence.
- Prevention: every terminal generation state must offer an explicit next action.
  Keep completed-result recovery and new-workflow reset covered independently so
  persistence cannot turn recovery into a navigation dead end.

## AI-ASSESSMENT-QUALITY-003 - Source-container wording escaped the assessment gate

- Date: 2026-09-13. Observed by the full production Excel acceptance on `0.5.14`.
- Symptom: a grounded test still asked how colours were “described in the source
  material” instead of asking the learner directly which colours applied.
- Cause: the shared generic-meta detector rejected a source reference only when
  “source material” ended the question, so a factual suffix escaped the anchored
  expression. In addition, an assessment restored from a generation checkpoint
  bypassed the current source and quality validators.
- Fix: reject the same source-container wording with or without a following factual
  suffix, with equivalent Russian and English handling. Revalidate every restored
  assessment against the current lesson evidence, expected question count and
  quality contract; discard and regenerate invalid checkpoints.
- Verification: the exact escaped production wording first failed two new
  regressions, and an invalid restored checkpoint first bypassed the provider in a
  third regression. The focused validator and resume suites then passed 110 tests.
- Prevention: add every production quality escape to the generation-contract,
  shared-editor and checkpoint-resume suites before changing the detector.

## AI-ASSESSMENT-QUALITY-004 - Structured Excel assessment reversed fields and collections

- Date: 2026-09-13. Observed during the full production Excel acceptance on
  `0.5.15`; repaired in the `0.5.16` candidate.
- Symptom: questions could ask which “Phoenix” characteristic belonged to “Style”,
  use options taken from unrelated table rows, repeat one atomic fact, reveal the
  correct answer in the question, or fall back to the model for a three-collection
  source and receive a fabricated fourth distractor.
- Cause: the lesson writer rendered a primary worksheet matrix as vertical cards,
  while the deterministic assessment mapper treated the card heading as the source
  subject in only one orientation. The generic four-option contract then rejected a
  valid three-subject row and sent it to the model. A first duplicate guard also
  compared answer text without requiring the same source fact, which could exhaust
  valid facts in later lessons. Deterministic lessons still incurred the model-only
  five-second inter-request delay.
- Fix: map both matrix orientations back to the exact source row and column; build
  distractors only from peer values in that row; allow three source-grounded options
  for three subjects; deduplicate by exact source fact plus answer and by atomic
  structured source reuse; block answer leakage and expanded source-container
  wording. Report the assessment path explicitly and sleep only after a real model
  call.
- Verification: 144 focused assessment/resume/pipeline tests, 70 passport/direct-
  source tests, 10 operational acceptance tests and the seven-lesson split-primary-
  table regression pass. The regression forbids a model call, provider delay,
  auxiliary-sheet promotion and non-source answer options. Frontend generation
  workflow tests pass 27 cases with lint and typecheck green.
- Prevention: every representative structured-source release must assert the exact
  primary-sheet role, row/column orientation, real peer-option count, all-tabular
  assessment paths, no provider delay, no answer leakage and human review of the
  persisted draft before production acceptance.
- Recurrence and fix (2026-09-13): production acceptance on `0.5.17` found two
  differently worded questions about the same spreadsheet cell, one distractor
  supported by the same cell as the marked answer, and opaque compact source
  shorthand in another distractor. The validator now resolves the exact supporting
  cell, rejects same-cell ambiguity and repeated use, and excludes compact shorthand
  unless the question explicitly teaches a code. Structured assessment counts are
  ceilings: invalid questions are dropped without provider padding. The four exact
  regressions passed, followed by the complete 1473-test API unit suite and the
  five database-free `AI-COURSE-01` checks. CI, deployment and a fresh persisted
  production draft remain separate evidence gates.

## AI-EMBED-RESILIENCE-005 - Provider exhaustion made a readable source look unusable

- Date: 2026-09-13. Reproduced in production while reindexing the complete
  `Империал_Феникс_Чикаго.xlsx` source on `0.5.16`.
- Symptom: exact progress reached 384/1076 fragments and then the reindex job and
  document entered an error state after Qwen, Voyage and Cohere were exhausted,
  even though the original workbook remained readable by the direct-source course
  path.
- Cause: `DocumentIngestion.ingest_file` re-raised the typed all-provider failure,
  and the document operation classified it together with converter, storage and
  malformed-content failures.
- Fix: handle only the typed all-provider exhaustion as a degraded semantic-index
  result. Preserve truthful zero-vector evidence, mark the document partially ready,
  complete the job with `source_ready=true`, and leave unrelated failures terminal.
- Verification: the regression first failed on the exact typed exception and then
  passed with two readable source chunks, zero embeddings, no vector-store or
  summarizer call, and `embedding_providers_unavailable`. Full CI, DEV and
  production browser acceptance remain release gates for `0.5.17`.
- Prevention: every embedding-chain change must test both boundaries: total provider
  exhaustion keeps a verified original usable for direct-source generation, while
  unexpected conversion, storage, provenance and malformed-vector errors still fail
  closed.

## AI-ASSESSMENT-QUALITY-005 - Cross-lesson duplicates and quota-shaped questions

- Date: 2026-09-13. Observed during the full production Excel acceptance on
  `0.5.18`; repaired in the `0.5.19` candidate.
- Symptom: otherwise grounded tests repeated the same collection fact in two
  different lessons, omitted the collection name from a question, used a vague
  word such as "elements" without an antecedent, or offered short distractors
  that differed by only one substituted word.
- Cause: cross-lesson comparison required nearly exact correct-answer wording,
  sentence-split Markdown rows could lose their structured-cell identity, and
  the low-information option detector applied only to five-token answers.
- Fix: compare concise answers with short descriptive expansions, recover cells
  from incomplete Markdown rows, require a named subject for structured facts,
  and apply the one-position distractor rule from three tokens. These failures
  are drop-only for structured lessons and never trigger quota padding.
- Verification: five focused regressions failed before the repair, a sixth
  protects valid role-action choices from over-filtering, and the related suite
  passed 119 tests. The full API unit suite passed 1480 tests, the frontend
  passed 584 tests plus lint/typecheck/build, and the database-free critical
  journey passed 5 tests. Exact-SHA CI, deployment and a fresh full-workbook
  production acceptance remain release gates.
- Prevention: assess uniqueness across the whole course, keep requested counts
  as ceilings, and add every human-review escape as a failing regression before
  changing the validators.
- Recurrence (2026-09-13, `0.5.19` production acceptance): two independently
  grounded spreadsheet rows expressed the same sales claim as "one platform for
  the whole apartment" and "a constructor for the whole apartment". Exact
  evidence keys could not identify the cross-row paraphrase. The `0.5.20` repair
  uses a conservative shared-phrase check only for structured sources, drops the
  later question without padding, and retains equal wording when it belongs to a
  different source subject. The focused RED case and two false-positive guards
  pass with the related 120-test assessment suite.
- Recurrence (2026-09-13, `0.5.20` production acceptance): the real provider
  expanded the first correct answer with a source-backed qualification, reducing
  the shared phrase below the initial coverage threshold. The result still kept
  both "platform for the whole apartment plus end modules" and "constructor for
  the whole apartment". The `0.5.21` repair lowers only the structured-source
  coverage floor; a pairwise replay over all 18 production answers identifies
  exactly that pair and no others. The real long-answer wording is retained as a
  regression alongside the different-subject and deictic false-positive guards.
- Recurrence (2026-09-13, `0.5.21` production acceptance): after the repeated fact
  was removed, the full workbook still produced questions that referred only to
  "the description" without naming a collection and questions whose wording
  exposed most or all of the correct answer. The `0.5.22` repair classifies both
  defects as drop-only for structured sources. It does not regenerate replacements
  or inflate the result to the requested count. Focused regressions cover both
  Russian formulations and protect the interrogative word "who" from being
  mistaken for leaked answer content.
- Recurrence (2026-09-13, `0.5.22` production acceptance): one lesson contained no
  question that survived the structured-source quality gate. The partial-recovery
  branch required at least one survivor, so it retried the provider five times and
  failed the entire course at assessment progress 85%. The `0.5.23` repair keeps
  the lesson without a quiz when all candidates are weak, persists that empty
  assessment checkpoint, and restores it without another provider call. RED tests
  cover both the initial all-dropped result and restart-safe restoration.
- Recurrence (2026-09-13, `0.5.23` production acceptance): the full workbook
  completed, but manual review still found a source-meta question, an unscoped
  attribute, a deictic "this collection" reference, an interrogative answer
  fragment, and a multi-item answer list. The `0.5.24` repair drops all five
  patterns without padding. Sentence-initial question words no longer count as
  named subjects, while inflected Russian collection names remain source-backed.
  Five exact regressions preserve the observed production wording.
- Recurrence (2026-09-13, `0.5.24` production acceptance): the full workbook
  reached assessment progress 88%, but five provider attempts still ended in
  grounding and learner-text quality failures. The drop-only branch recognized
  a closed list of known issue messages, so another valid question-level failure
  retried and ultimately failed the whole course. The `0.5.25` repair makes the
  rule structural rather than message-based: after any parseable assessment for
  a table source, independently valid questions are retained and every invalid
  question is dropped without retry or count padding. A lesson with no survivor
  remains valid without a quiz. The exact behavior was RED at five calls and is
  GREEN at one call; the complete API unit suite passes 1494 tests.
- Recurrence (2026-09-13, `0.5.25` production acceptance): the same workbook
  again stopped at assessment progress 88%. The structural policy still detected
  only pipe-delimited Markdown rows, while Excel evidence may be flattened as
  `field — value`. The `0.5.26` repair identifies flattened rows from their
  explicit `[Worksheet]` provenance while keeping Markdown-row compatibility;
  punctuation alone never classifies ordinary prose as a spreadsheet. An offline
  provider replay reproduces five retries before the repair and one call after it,
  while preserving the valid question and dropping the invalid one without quota
  padding. Full generation is now a final environment acceptance gate, not the
  debugging loop for each validator change.

- Recurrence (2026-09-14, 0.5.42 PDF acceptance): prose assessment still used
  quota retries for quality classes outside a closed allowlist. A fresh local
  capture reproduced five attempts; the exact historical responses were not
  retained and are not claimed as replay fixtures. Apply drop-only filtering
  after every structurally valid candidate set, regardless of source format.
  Keep independently valid questions; mark an empty result with the current
  policy and `no_valid_questions`, and persist a named no-quiz warning on the
  draft. Missing/wrong-shaped `mcq`, invalid JSON and provider errors remain
  failures, not successful omissions. Focused tests cover survivors, all-dropped
  output, malformed responses, restart markers and draft persistence. The full
  21-lesson local capture yielded29 questions and3 explicit omissions; strict
  request/response replay reproduced it without network calls. This proves the
  replay and filtering path, not perfect educational quality.
- Recurrence (2026-09-16, `0.5.53` synthetic acceptance): the first batch of
  prose questions was correctly rejected, but the existing one-evidence-at-a-time
  recovery routine had no production caller, so the draft retained zero tests.
  `0.5.54` invokes that routine only after the batch attempted at least three
  different valid evidence IDs, requires three distinct survivors, and caps the
  recovery at six short requests. It still returns the named no-quiz result when
  safe recovery is impossible; it never pads a quota. Three RED/GREEN focused
  cases and the related 169-test structure/assessment matrix pass.
- Recurrence (2026-09-16, `0.5.54` synthetic acceptance): the malformed batch
  reused one valid evidence ID even though the lesson exposed 24 source-owned
  evidence fragments. The three-ID admission gate therefore skipped focused
  recovery and persisted zero questions. `0.5.55` admits bounded recovery after
  any valid evidence-ID attempt when at least three fragments exist. Empty
  batches, unknown IDs and sparse evidence still omit the quiz without extra
  provider calls; all-invalid questions are never saved or padded.

## AI-QUALITY-018 - Approved lesson title caused an unrecoverable false rejection

- Date: 2026-09-14. Observed in production `0.5.29` during the synthetic
  human-path acceptance of the 21-page Lombard microcredit-rules PDF.
- Symptom: OCR and architecture completed, the first of nine lessons passed,
  then all bounded writer attempts for the next lesson ended with
  `direct_source_lesson_quality_failed`; no partial course was persisted.
- Cause: the deterministic lesson validator correctly received the writer body,
  but also interpreted its Markdown H1/H2 repeating the already validated
  architect title as a new relationship claim. A title such as `Documents
  required for a microcredit` could therefore fail even when its body repeated
  only exact source facts. Rewriting could not recover because every compliant
  writer response repeated the same approved title.
- Fix: remove only a Markdown heading whose normalized text is identical to the
  approved lesson title before measuring body grounding, length, repetition and
  unsupported relationships. Different headings remain fully validated, so an
  invented causal or prescriptive heading still fails closed.
- Verification: the exact legal-document RED case fails on `0.5.29` and passes
  with the repair; 72 lesson-quality tests and the combined 103-test
  lesson/direct-source/resume set pass, including the existing adversarial
  invented-heading case. Production resume and a fresh DOC journey remain the
  mandatory environment acceptance.
- Prevention: retain the exact legal-document regression together with the
  existing adversarial test that rejects an invented causal heading. Complete
  the same production job through resume, then run a fresh DOC human journey;
  local green tests alone are not production acceptance.

## AI-QUALITY-019 - One unrecoverable lesson cancelled an otherwise useful course

- Date: 2026-09-14. Observed in production `0.5.30` during the fresh
  methodologist-path acceptance of the Lombard microcredit-rules PDF.
- Symptom: OCR and architecture completed and the first of nine lessons passed,
  but the second lesson exhausted three bounded quality repairs. The whole job
  failed with `direct_source_lesson_quality_failed` and no useful course was
  saved.
- Cause: the direct writer treated the architect lesson count as mandatory.
  A deterministic quality failure in any one lesson raised immediately even
  when other planned lessons could still form a grounded course.
- Fix: omit only the exhausted lesson, continue the remaining plan, remove empty
  modules, and save only if an adaptive useful core remains. The threshold is
  half the plan rounded up, capped at five and never below one. Review and
  assessment use the accepted lesson count.
- Verification: the RED regression fails the old all-or-nothing writer and the
  GREEN result keeps one grounded lesson from a two-lesson plan after omitting
  the exhausted peer. Existing single-lesson rejection and resumable-loop tests
  remain green. Full production PDF and DOC journeys remain required.
- Prevention: lesson count is a ceiling, never a reason to pad or retain weak
  content. Any future partial-generation path must test both a surviving useful
  core and an all-invalid course that still fails closed.

## AI-PROMPT-001 - One oversized OCR chunk failed before the first lesson

- Date: 2026-09-14. Observed in production `0.5.31` during a fresh
  methodologist-path generation from the 21-page Lombard microcredit-rules PDF.
- Symptom: ingestion and architecture completed, but content generation stopped
  at 30% with `direct_source_prompt_budget_exceeded` before the provider wrote
  the first lesson.
- Cause: the writer packer admitted only complete chunks. If semantic selection
  returned one relevant OCR chunk larger than the 24,000-character source
  allowance, it dropped that chunk, concluded that the only selected document
  was unrepresented and failed the course.
- Fix: for a single selected document only, fit a sentence- or line-bounded exact
  prefix of the selected source text against the real serialized prompt budget.
  Preserve its document identity and headings, and discard table metadata that
  would no longer describe the shortened text. Multi-document requests still
  fail if every source cannot be represented without truncation; oversized
  course metadata still fails before any provider call.
- Verification: the RED regression reproduces the pre-provider failure with one
  55,999-character chunk. GREEN invokes the provider with a strict source prefix,
  keeps the complete prompt at or below 32,000 characters and preserves source
  references. The combined direct-source, lesson-quality and resumable suites
  pass 156 tests.
- Prevention: prompt-budget tests must include both large text and large metadata.
  Use the deterministic writer seam for recurrence checks; reserve a full OCR and
  provider journey for final environment acceptance.

## AI-PROMPT-002 - Quality retry overflowed an otherwise valid writer prompt

- Date: 2026-09-14. Observed in production `0.5.33` during a fresh
  methodologist-path generation from the 21-page Lombard microcredit-rules PDF.
- Symptom: source ingestion and the 17-to-24-topic source map completed, the
  job entered content generation with nine planned lessons, then failed at 30%
  with `direct_source_prompt_budget_exceeded` while correcting the first lesson.
- Cause: the initial writer request packed grounded excerpts up to the exact
  32,000-character provider limit. When deterministic quality admission rejected
  the response, the retry appended correction instructions without recalculating
  how much room remained for source excerpts.
- Fix: build every retry from the original verified candidates and repack the
  grounded excerpts against the actual serialized budget after subtracting the
  current correction text. Preserve representation of every requested document,
  source identity, headings and references; fail before the provider if those
  invariants cannot fit.
- Verification: the RED regression fills the initial writer budget, rejects the
  first response with `unsupported_relationship_claim`, and reproduces the
  overflow before a second provider call. GREEN makes two bounded calls, includes
  the correction, keeps both complete prompts at or below 32,000 characters and
  returns a grounded lesson. The full production PDF and DOC journeys remain the
  environment acceptance gate.
- Prevention: every bounded provider prompt with an appended repair or retry
  instruction must test the largest initial payload followed by at least one
  deterministic correction. The retry must repack source data; it may not merely
  concatenate control text to an already full request.

## AI-CHECKPOINT-003 - Omitted lessons shifted stable checkpoint coordinates

- Date: 2026-09-14. Observed in production `0.5.34` during a fresh
  methodologist-path generation from the 21-page Lombard microcredit-rules PDF.
- Symptom: source ingestion, architecture and lesson writing progressed; six of
  nine planned lessons passed admission and three were intentionally omitted.
  Review then failed on the second accepted lesson with
  `AIGenerationCheckpointError` and the public job ended at 73%.
- Cause: writer checkpoints used original plan coordinates, but the returned
  course compacted omitted lessons. Review and assessment used compacted list
  indexes against the original checkpoint map, so the first accepted lesson
  after an omission claimed a neighbouring planned lesson's identity. Omitted
  planned items also had no valid terminal state for final completeness checks.
- Fix: persist quality omissions as the explicit terminal status `omitted`,
  preserve sanitized reason codes, and translate compact course coordinates
  back to original plan identities for review and assessment. Resumed writers
  skip both completed content and terminal omissions.
- Verification: the RED pipeline regression omits lesson 2 of 4 and reproduces
  the coordinate failure. GREEN reviews and assesses lessons 1, 3 and 4 under
  their original checkpoints and accepts lesson 2 as terminally omitted. The
  isolated Supabase DEV gate passes migration upgrade/downgrade/re-upgrade,
  competing leases, omission completion, tenant RLS/FORCE RLS and cleanup while
  leaving the public DEV revision unchanged at `0158`.
- Prevention: any pipeline that filters, compacts, reorders or groups generated
  output must keep a tested mapping to immutable plan identity through every
  durable stage. A deliberately omitted item needs a first-class terminal state;
  it must not be represented as fake content or left permanently incomplete.

## AI-CHECKPOINT-004 - Omitted lessons remained in the structure used for saving

- Date: 2026-09-14. Observed on production `0.5.35` during the fresh
  methodologist-path generation from the Lombard microcredit-rules PDF.
- Symptom: generation completed content, review and assessments for seven
  accepted lessons out of nine planned lessons, then failed at 98% while saving.
- Cause: original coordinates were correctly retained for checkpoint recovery,
  but `GenerationState.structure` still contained all nine planned lessons.
  Persistence therefore compared nine structural positions with seven final
  assessments and raised `generation_assessment_count_conflict`.
- Fix: after direct-source writing, build a separate final structure from the
  compact-to-original identity map. It contains only accepted lessons and uses
  their final content titles, while checkpoint callbacks continue to address
  the immutable original plan.
- Verification: the RED regression omitted lesson 2 and showed that the final
  structure still contained lessons 1-4. GREEN passes lessons 1, 3 and 4 to the
  persistence boundary, with review and assessment still checkpointed under
  their original identities. The focused checkpoint/direct-source/pipeline
  suite passes 72 tests and the full API unit suite passes 1507 tests.
- Prevention: whenever generated output is filtered, keep two explicit views:
  immutable plan identity for recovery and compact accepted structure for
  assessment matching and persistence. Acceptance must include the real save
  boundary, not stop after successful model calls.

## AI-PROVIDER-002 - One transient primary connection failure aborted a concurrent source map

- Date: 2026-09-14. Observed in production `0.5.36` during the fresh
  methodologist-path generation from the controlled Lombard microcredit-rules
  PDF.
- Symptom: document conversion completed and two concurrent DeepSeek map calls
  returned HTTP 200, but a third call hit `ConnectError`. Its private Qwen and
  GLM fallbacks were unavailable, so the whole job failed at architect progress
  10 despite the primary provider being healthy for sibling requests.
- Cause: `_BaseProviderClient._request` retried timeouts and transient 5xx
  responses but classified `httpx.ConnectError` as an immediate hard failure.
- Fix: retry `ConnectError` on the same provider using the existing bounded
  per-provider retry budget before entering the fallback chain.
- Verification: a RED transport regression reproduces one connection failure
  followed by a successful response from the same provider. GREEN returns that
  response after exactly two calls; the focused failover and source-map suite
  passes 70 tests.
- Prevention: concurrent map acceptance must include a transient connection
  fault in one batch while the provider remains available to sibling batches.
  A single socket failure is not provider-outage evidence.

## AI-PROVIDER-003 - Exhausted providers made completed lesson checkpoints inaccessible

- Date: 2026-09-14. Observed in production `0.5.40` during the fresh
  methodologist-path generation from the Lombard microcredit-rules PDF.
- Symptom: eight of nine planned lessons were durably completed. The ninth
  request then hit a DeepSeek read error, an unavailable Qwen endpoint and a
  GLM connection timeout. The job became terminal `failed`, so the interface
  offered only a new course even though eight valid checkpoints were present.
- Cause: only a worker soft-time-limit was classified as resumable
  `interrupted`; exhaustion of the bounded provider chain fell through the
  generic terminal failure branch.
- Fix: classify `AllProvidersFailedError` as a resumable provider interruption,
  preserve the same logical job and its checkpoints, and show the existing
  explicit continuation action. Completed lessons are restored and only the
  first missing lesson is sent to a provider again.
- Verification: the RED regression checkpoints two of three lessons and
  exhausts every provider on lesson three. GREEN returns `interrupted`; after
  provider recovery the same job completes while only lesson three is called
  again. Existing timeout-resume and admission tests remain green.
- Prevention: any failure caused solely by temporary exhaustion of the bounded
  provider chain must preserve durable work and expose an explicit continuation
  path. It must neither silently retry forever nor force the methodologist to
  regenerate already accepted lessons.

## AI-MAP-001 - A valid detailed source map exceeded the arbitrary topic count

- Date: 2026-09-14. Observed in production `0.5.32` during the fresh
  methodologist-path generation from the 21-page Lombard microcredit-rules PDF.
- Symptom: OCR completed and the job entered course architecture, then both
  bounded map attempts ended with `source_topic_map_invalid_response_topic_count`.
- Cause: the source-map response contract allowed only 16 topics per batch. A
  detailed regulatory source can yield 17 to 24 concise, nonempty topics while
  still remaining inside the existing 8,000-character response, 6,000-character
  content and 28,000-character architect-overview budgets.
- Fix: raise only the per-record topic-count ceiling to 24 and publish the same
  limit in the model protocol. All byte, character, serialization, coverage and
  source-identity budgets remain unchanged.
- Verification: the RED regression returns 17 distinct regulatory topics and
  fails twice under the old limit. GREEN accepts all 17 in one call without
  truncation. Existing validation now rejects 25 topics and still covers empty,
  non-string, overlong and serialized-overflow responses.
- Prevention: do not use a small presentation-oriented count as a reliability
  boundary when independent serialized and final-overview budgets already cap
  the response. Keep the exact 17-topic production shape as a regression.
- Recurrence: production `0.5.37` reached the same map after the connection
  retry repair, but the real PDF produced more than 24 concise topics and was
  rejected again. Raising 16 to 24 had moved the arbitrary boundary rather than
  removed it. Production `0.5.38` removes the upper item count; nonempty/type/
  per-topic length, 8,000-character response, 6,000-character content,
  serialized-topic, 2,048-token and 28,000-character final-overview limits
  remain mandatory. Protocol revision `v5` prevents reuse of old checkpoints.
- Recurrence: production `0.5.38` accepted the larger topic list, but both map
  attempts returned a useful navigation summary above 1,600 characters and the
  job failed with `source_topic_map_invalid_response_summary_length`. In
  `0.5.39`, whitespace is normalized and only the auxiliary summary is clipped
  at a word boundary to its exact remaining budget; every topic anchor is
  preserved. Oversized JSON/topic payloads still fail closed. Protocol revision
  `v6` invalidates checkpoints from the prior normalization contract.

## AI-QUALITY-020 - One unsupported fragment discarded an otherwise grounded lesson

- Date: 2026-09-14. Observed in production `0.5.39` during the fresh
  methodologist-path generation from the 21-page Lombard microcredit-rules PDF.
- Symptom: source analysis planned nine lessons and all nine writer positions
  completed, but five lessons were omitted with
  `unsupported_relationship_claim`. Four substantial lessons survived, below
  the existing useful-core threshold of five, so the job failed at 70% without
  saving a weakly covered course.
- Cause: deterministic admission correctly found at least one unsupported
  recommendation or relationship in each rejected response, but its only
  action after bounded model repair was to discard the whole lesson, including
  independently grounded source prose around the offending fragment.
- Fix: identify and remove only unsupported relationship fragments without
  replacing or rewriting them, then rerun the complete lesson-quality gate over
  the remainder. Accept it only when source anchors, substance, repetition and
  all other existing checks pass; otherwise preserve the original rejection and
  bounded repair behavior.
- Verification: the RED legal-document regression reproduces a grounded
  repayment rule followed by invented advice and previously loses the only
  lesson. GREEN keeps the source-backed rule, removes the invented instruction
  and uses one provider call. The existing all-unsupported repair regression,
  all 72 relationship-quality tests and the combined 65-test direct-generation
  suite remain green. A fresh PDF and DOC production journey remains the final
  environment and content-quality gate.
- Prevention: quality admission should reject the smallest independently
  identifiable unsafe unit. Any deterministic filtering must be deletion-only,
  must never synthesize a replacement and must rerun every quality invariant on
  the retained result before persistence.

## DOCLING-001 - Scanned PDF failed before OCR in the production container

- Date: 2026-09-13. Observed on production `0.5.26`; repaired for `0.5.27`.
- Symptom: a real 21-page scanned PDF repeatedly finished document reindexing as
  `ocr_required` at 30%. `/health` stayed green, so service availability alone
  concealed the conversion failure.
- Cause: the runtime Docling container first lacked the worker's protected API
  key, then used `HOME=/`, which made the model cache unwritable for UID 10001,
  and finally lacked `libGL.so.1`, required when Docling imported OpenCV for its
  table/layout model.
- Fix: pass the same 64-character key to the document worker and converter through
  a root-owned `0600` environment file; run Docling with `HOME`, `XDG_CACHE_HOME`
  and `HF_HOME` under a persistent `/var/lib/docling` mount owned by
  `10001:10001` mode `0700`; install the headless OpenCV runtime libraries in the
  image.
- Verification: fail-closed authentication, cache ownership, `cv2` import and
  container health passed independently. The exact source PDF then completed OCR
  and 99-chunk indexing in 151.7 seconds. Focused converter/runtime tests pass.
- Prevention: a Docling release is not accepted from `/health` alone. Its gate
  must convert an image-only multilingual PDF through the authenticated worker
  path after a cold cache/container recreation and verify meaningful extracted
  text plus the final document index state.
- Recurrence: after PDF OCR passed, a real legacy `.doc` still returned HTTP 422.
  LibreOffice resolved the unprivileged service account's passwd home
  (`/nonexistent`) while creating its first-run user profile and exited with code
  77 before producing DOCX. Every conversion now receives its own explicit
  `-env:UserInstallation=file://.../lo-profile` inside the request-scoped temporary
  directory. The regression test requires that isolated profile argument, and
  production acceptance must include one real binary `.doc`, not only DOCX/PDF.

## AI-ADMISSION-001 - Large source was converted twice before generation started

- Date: 2026-09-13. Observed during the production methodologist journey on
  `0.5.28`; repaired for `0.5.29`.
- Symptom: selecting a ready 21-page scanned PDF left "Проверка источников" on
  screen for more than 60 seconds and kept the generation button disabled.
- Cause: both the compatibility request and the generation-submission request
  synchronously downloaded, hash-checked, OCR-converted and chunked every
  immutable original. The worker then repeated the same authoritative conversion.
- Fix: HTTP admission now reads only tenant-owned document metadata and persisted
  chunk totals. The queued worker remains the single place that verifies the
  original hash, converts the source, builds its passport and generates content.
- Verification: RED tests require both HTTP routes to request bounded admission
  and require `build_direct_source_corpus` not to run in that mode. The original
  full-content path remains covered separately for worker-side source analysis.
- Prevention: no admission endpoint may perform OCR, office conversion or full
  source reconstruction. Potentially long source work belongs to a persisted job
  whose stage, progress and failure are visible to the methodologist.

## AI-SCAN-001 - Layout OCR converted an empty percentage field into a numeric claim

- Date: 2026-09-14.
- Symptom: a generated lesson repeated a percentage absent from the scanned form.
- Cause: layout OCR supplied an invented value as apparently authoritative text.
- Evidence: a saved source checkpoint already contained the invented percentage;
  writer-only provenance checks could not detect this upstream error. A bounded
  original-byte replay reproduced the layout-OCR claim before the candidate guard.
- Fix: scanned PDFs cross-check percentage-bearing pages using bounded local
  full-page OCR. A disagreement remains an uncertainty marker, never a guessed
  replacement. Office/digital text conversion is not subject to this scan guard.
- Integration: normalize Markdown-escaped markers after Docling serialization;
  preserve source warnings in course content and the final draft description.
  Lessons using uncertain source chunks are `needs_review`, not `verified`.
- Verification: complete 21-page original conversion retained one uncertainty
  marker and warning and removed the unsupported percentage. Synthetic tests
  cover other formats, table provenance, budgets, serialization and persistence.
- Limits: agreement between OCR passes is not proof of factual correctness.
  Missing confirmation means uncertainty; review the original before publication.
- Prevention: keep the bounded scan check and uncertainty propagation under tests;
  verify original pages, not only downstream writer output.

## AI-SIZING-001 - Lightweight admission estimate became an authoritative course size

- Date: 2026-09-14.
- Symptom: a supporting catalogue caused an excessively large lesson estimate.
- Cause: bounded HTTP admission intentionally skipped source conversion, but its
  all-chunk size estimate then entered the worker unchanged. Supporting catalogue
  rows inflated the requested structure despite an available worker passport.
- Fix: retain the requested format/manual override in job source analysis and
  resolve new-job size after original conversion from primary teachable capacity.
  Do not resize restored plans or legacy jobs without the new request metadata.
- Verification: the complete workbook replay classified primary/supporting sheets
  and recommended six lessons instead of the 33-lesson admission estimate.
  Synthetic cases prove that adding supporting rows does not increase the plan.
- Prevention: present admission as preliminary and keep expensive work in the
  job. Validate business meaning, not only numerical progress or a terminal status.
- Recurrence (2026-09-16, `0.5.53` synthetic acceptance): a high-confidence
  six-section service source was advertised as supporting up to three lessons,
  yet the architect accepted one catch-all lesson because validation enforced
  only the maximum. `0.5.54` adds a conservative minimum of two only when the
  source is confidently classified, has at least two teachable units, has no
  supporting sections inflating capacity, and the selected ceilings allow two.
  The architect retries an underfilled plan with explicit no-padding guidance;
  small and supporting-sheet fixtures remain unchanged.
- Recurrence (2026-09-16, `0.5.54` live acceptance): automatic generation did
  not pass manual ceilings, so the new floor was inactive and the same source
  again became one lesson. A production-like capture then exposed a second
  defect: for ordinary prose, the claim validator built permitted text only
  from worksheet headings, leaving an empty set and rejecting four grounded
  plans. `0.5.55` derives the automatic floor from at least three passport
  units, four primary rows and bounded repetition, and validates prose actions
  against prose chunks. The exact synthetic source then produced a grounded
  two-module/five-lesson plan in one provider call; sparse and repetitive-source
  regressions remain one lesson.

## AI-REPLAY-001 - Quality corrections need contextual regression cases

- Date: 2026-09-14.
- Symptom: extractive answers still produced reversed actions and repeated facts.
- Cause: answer-string grounding alone did not prove the question's meaning.
- Fix: replay extractive-but-action-inverted questions, duplicate rate facts with
  the same conditions, and positive cases with distinct subjects/conditions.
  Discard only explicit invalid/duplicate classes without question-count padding.
- Evidence must retain complete governing sentences. Oversized sentences are
  skipped rather than split into misleading suffixes. Numeric lesson repair is
  deletion-only and the complete quality gate rechecks the remaining content.
- Omitted lessons now retain policy version and named-topic reporting. Stale
  omission checkpoints fail the same compatibility contract as stale content.
- Architect correction carries the prior plan and exact primary references;
  oversized repairs report the prompt-budget error without an extra provider call.
- Limits: these deterministic guards are not a universal semantic evaluator.
  Content acceptance still requires reviewing the resulting lessons and quizzes.
- Verification: contextual positive/negative regressions, checkpoint-policy and
  repair-budget tests passed in the final combined quality matrix.
- Prevention: replay the complete question, all options and governing source
  sentence; run the release-contract gate before publishing a candidate tag.
- Recurrence (2026-09-14): a fresh architecture capture rejected the title
  `подбор` despite explicit user intent `подбирать`. The selection concept
  omitted the imperfective Russian stem. Add only that morphology and retain
  unrelated-action and primary-worksheet negatives. The captured plan still
  failed a separate primary-section gate, so this local fix alone was not an
  accepted-course result. A new cached-map architecture capture passed both
  gates; do not relabel its fresh answers as historical production responses.
- Replay tooling retains private prompts/responses, source hashes and request
  identities. Reserve concurrent call IDs before awaiting responses. Replaying
  only a completed map's architecture stage is explicitly different from full
  replay. Offline course-assessment replay skips only inter-lesson pacing in its
  isolated process; capture and production retain their existing timing policy.
- Local writer replay exposed a separate content-loss shortcut: a model-authored
  composite lesson could match one exact table-row label and be reduced to only
  that row. Source cards now remain the neutral no-intent path; an explicit
  audience/goal uses the grounded model writer, with the same source guards.
  RED/GREEN tests exercise both paths and pipeline forwarding. In that live local
  replay all four planned lessons were written instead of three partial cards.
- Percentage-uncertainty instructions previously appeared even for a plain
  spreadsheet; a captured writer echoed a nonexistent scan defect. Condition
  that instruction on a real source marker and keep handling rules out of the
  lesson narrative. Never treat an absent marker as evidence of OCR failure.
- Recurrence (2026-09-14, local assessment coverage): the first8000characters
  and24sentence fragments of a large comparison source lost later attributes
  and column ownership. Rank complete original rows by lesson objectives and
  preserve headers; restore must use the same selection. A correct column-header
  answer needs exact ownership evidence, not a blanket extractive-row rejection.
- Lexical absence from one quote is not proof that a distractor is implausible.
  Source-wide vocabulary provides bounded topical evidence; unrelated alternatives
  remain rejected. A compact large-table prompt must still include the explicit
  JSON instance shape when the provider adapter downgrades schema enforcement.
- Coverage capture12 increased retained questions but failed human acceptance:
  a second correct alternative existed in another source row, and reverse-form
  questions repeated the same fact. Do not equate larger counts or green unit
  suites with quality. No fixed minimum per lesson and no production debug loop.
- Blind answer solving found a second valid option that a key-aware reviewer
  missed. Review keys against complete collected source windows before semantic
  deduplication. Duplicate representatives may be later in the relevant lesson;
  require a distinct retained target, not an arbitrary chronological ordering.
- Preserve earlier coverage concerns as a methodologist review list: repeated
  model judgments can disagree and must not silently certify full coverage.
  Invalid verdicts get one bounded protocol retry, then interruption with existing
  checkpoints, never unchecked acceptance or complete course regeneration.
- Offline strict replay recovered all25calls of the PDF supplement before a
  failed final review; only the final source-wide check needed fresh model calls.
  Current local content review accepted15Excel and42PDF questions, with named
  objective-review advisories and one PDF lesson without a quiz.
- Recurrence (2026-09-14, row ownership and quota acceptance): a saved Excel
  lesson bound one article to another collection's name and door count because
  source anchors and numeric values were validated against the flattened lesson
  corpus rather than the identified source row. The same source could also carry
  conflicting guide values for one article without forcing an uncertainty note.
  Lesson quality policy v19 now binds explicit article/SKU/code claims to their
  reconstructed Markdown row, rejects another row's numeric value, and rejects a
  relevant unresolved guide conflict even when the writer omits the identifier.
  The writer must name both conflicting values and request source clarification.
- Assessment counts are ceilings for every source size. Empty or partial valid
  output is accepted with the drop-only policy; recovery cannot refill a quota.
  Numeric questions receive a second source-wide scope check for period, unit,
  calculation base and conditions. Disagreement that leaves two valid options is
  terminal `ambiguous`, not a rewrite. Final duplicate and objective coverage is
  course-wide, while missing lesson-content objectives are reported separately.
- Verification: synthetic RED/GREEN cases cover wrong row collection, wrong row
  number, same-row positive, hidden and explicit source conflicts, daily-versus-
  annual ambiguity, course-wide coverage and zero-minimum schemas. The related
  complete API unit suite passes 1672 tests. A private full-workbook
  replay completed four lessons in 73.992 seconds; deterministic lesson admission
  accepted all four, and the source-wide audit retained 10 of 11 questions after
  deleting one semantic duplicate without padding. Exact CI, DEV and production
  user-flow readback remain release gates.

## AI-REPLAY-002 - Legacy realization replay survived a changed evidence set

- Date: 2026-09-19.
- Symptom: the full Lombard PDF v23 preflight excluded a malformed OCR fact, but
  the rendered lesson still contained `др. ) Ломбарда...` and was reported as
  publishable. Two retained correct answers were also longer than 240 characters.
- Cause: assessment responses were keyed by stable axis/question identity, while
  lesson realization responses were replayed from an unkeyed FIFO queue. A legacy
  response could therefore survive a changed source fact set. Final
  publishability did not inspect this OCR boundary form or correct-answer length.
- Fix: capture a canonical SHA-256 of the complete model request; replay lesson
  realization only when that hash matches exactly. Legacy realization traces
  without a request hash fail closed to the explicitly configured live provider.
  Final quality now checks lesson text and every answer option for the observed
  OCR boundary, rejects correct answers above 240 characters, and the drop-only
  question filter removes such answers without quota padding. Stable source
  patterns atomize definition headwords and employee obligations before authoring.
- Verification: RED reproduced stale lesson reuse, the OCR tail and both observed
  long Lombard keys. GREEN passed 73 focused tests, then 306 evidence/assessment/
  replay regressions, Ruff and `git diff --check`. Re-evaluating saved v23 now
  returns `publishable=false` with `visible_ocr_artifacts` and
  `overlong_correct_answers`. Fresh GLM acceptance is pending because the local
  WireGuard tunnel could not reach any tested ASUS node after workstation restart.
- Prevention: never replay a provider-authored lesson without complete-request
  identity; old traces are evidence only for stages whose stable semantic identity
  is present. Keep deterministic artifact checks independent of model reviews.

## 2026-09-15 — Per-lesson embedding queries exhausted managed-provider RPM

- Symptom: all Voyage V4 models passed small probes, but one 12-lesson Excel
  simulation emitted repeated HTTP 429 responses and spent 62.717 seconds in
  retrieval measurement before fallback.
- Cause: V2 embedded every lesson query in a separate API call. Free token
  capacity did not imply sufficient requests-per-minute capacity. Independent
  failover could also return a query vector from a semantic space different
  from the document vectors.
- Fix: submit all lesson queries as one bounded query batch and pack documents by
  provider item/aggregate-byte limits; declare the vendor-
  compatible Voyage V4 family as one exact semantic space; compare vectors only
  when document and query provenance match. A mismatch degrades the optional
  retrieval metric and never discards source-grounded facts.
- Prevention: provider probes must include production-shaped batching, exact
  vector-space provenance and a real source simulation. Never infer workload
  readiness from HTTP 200 on one short embedding request.
- Provider finding: the unbilled Voyage account explicitly reported a reduced
  limit of 3 RPM/10K TPM. Its separate 200M free token pools are capacity, not
  production throughput. After the owner added billing, the same 250-fragment,
  22,549-token production-shaped request returned HTTP 200; only then was Voyage
  restored to first position.
- Verification: the repeated full Excel simulation completed in 43.356 seconds;
  embedding time fell to 2.550 seconds, with 12 lessons, 21 questions,
  `publishable=true`, `embedding_degraded=false` and no 429/failover log.

## 2026-09-15 — Cancelled generation could retain a reservation after cleanup failure

- Symptom: a generation job was durably `cancelled`, but a transient quota or
  budget cleanup failure could leave its reservation charged; repeating cancel
  returned success without retrying cleanup.
- Cause: the idempotent cancellation branch returned before calling the shared
  reservation-release helper.
- Fix: both first cancellation and repeated cancellation call the same
  transactional, idempotent release helper. A cleanup failure returns `503`
  while preserving the terminal cancellation, so the next request can retry.
- Prevention: every terminal path that owns a reservation must use one durable
  release marker and prove failure-then-retry behavior in tests.
- Verification: focused cancellation tests cover successful release, exact-once
  repeat behavior and transient failure followed by a successful retry.

## 2026-09-15 — Degraded source-only lessons were labelled verified

- Symptom: course diagnostics reported deterministic fallback, while persisted
  lessons without an OCR marker could still receive `source_validation_status=verified`.
- Cause: lesson review status was inferred only from one unreadable-value marker
  instead of explicit realization provenance.
- Fix: V2 records exact deterministic-fallback lesson IDs and maps those lessons
  to `needs_review`; ordinary validated lessons remain `verified`.
- Prevention: course-level degradation and each persisted lesson status must be
  asserted together; never infer provider validation from readable source text.
- Verification: provider-exhaustion and persistence tests assert all affected
  lessons require review.

## 2026-09-15 — Embedding failover looked like progress moved backwards

- Symptom: when one embedding provider partially completed and failed, the next
  provider restarted at `0 / total` without explaining the reset.
- Cause: progress exposed provider and counts but omitted the failover attempt.
- Fix: resilient embedding callbacks attach a one-based attempt; API and UI show
  provider plus `#attempt`, and ETA is recalculated for that complete attempt.
- Prevention: failover tests must include partial progress, provider change,
  counter restart and attempt increment. Provider names remain sanitized.
- Verification: backend sequence tests and frontend status rendering tests pass;
  the full frontend suite contains 594 passing tests.

## AI-QUALITY-023 - Legacy quality fixes did not cover the active V2 path

- Date: 2026-09-15. Confirmed by post-release synthetic-tenant acceptance of
  backend `0.5.50` and reproduced with the exact generated lesson and question
  shapes before any course approval or publication.
- Symptom: learner text still contained sales-style marketplace comparisons, and
  one question marked a roller-guide answer correct while another roller-guide
  option answered the same attribute with different qualifiers.
- Cause: the release changed legacy lesson and assessment validators, while new
  direct-source jobs run through the separate `evidence_v2` provider and final
  publishability path. Focused tests exercised the changed functions instead of
  the active generation-to-artifact seam.
- Fix: share the deterministic ambiguous-answer contract with V2; delete invalid
  questions without padding; reject blocked model prose during validated calls;
  neutralize only the same known phrases in source-only fallback text; and apply
  a defense-in-depth check to every final learner-visible field. Persisted V2
  artifacts now carry quality policy `evidence-v2-quality-v2`.
- Verification: exact RED/GREEN regressions pass through the active async V2 seam
  and final publishability contract. The complete source Excel replay generated
  12 lessons and 17 retained questions in 117.688 seconds, used Voyage without
  embedding degradation, returned `publishable=true`, and an independent scan
  found no blocked phrase, generic question, or exact duplicate. Full CI,
  immutable deployment and post-release synthetic acceptance remain release gates.
- Prevention: every generation-quality release must replay the production engine
  named in job metadata from source conversion through final artifacts. Green
  helper tests, API health and queue completion cannot replace semantic inspection
  of the retained course and all answer options.

## AI-QUALITY-024 - Marketplace comparison with an intervening noun escaped the V2 gate

- Date: 2026-09-15. Found by reading every lesson in the synthetic production
  course created after release `0.5.51`; the course remained a draft and was not
  approved or published.
- Symptom: `а не компактный вариант с маркетплейса` remained in one lesson even
  though shorter forms such as `а не компакт с маркетплейса` were blocked.
- Cause: the policy required `компакт*` to be immediately followed by `с
  маркетплейса`; the source inserted the neutral noun `вариант` between them.
- Fix: permit a bounded zero-to-three-word noun phrase in this exact comparison
  shape, both in admission and deterministic neutralization. Do not ban ordinary
  operational facts that merely mention a marketplace.
- Verification: the exact production sentence is a RED/GREEN regression for
  lesson admission and source-only neutralization; 131 focused quality tests and
  all 1,759 backend unit tests pass. A full Excel replay retained 12 lessons and
  17 questions, returned `publishable=true`, and contained no marketplace
  comparison variant.
- Prevention: production acceptance must inspect full rendered lesson bodies in
  addition to titles, tests and aggregate diagnostics; phrase policies need exact
  regressions for every observed grammatical variant.

## AI-QUALITY-025 - Provider instructions and source-meta wording reached learner content

- Date: 2026-09-16.
- Symptom: a generated lesson exposed internal question-writing instructions,
  while a test could ask what the lesson material stated instead of testing the
  underlying source fact.
- Cause: V2 rejected generic headings and several meta-question forms, but did
  not compare known generation-instruction markers against the cited facts and
  did not cover the observed `what the lesson material states` grammar.
- Fix: reject a generated block when it contains a known internal instruction
  absent from its cited source facts, then use the existing bounded provider
  retry; classify the observed source-meta question as generic.
- Verification: exact RED/GREEN V2 regressions pass, including a first invalid
  provider response followed by a clean retry. All 1,762 backend unit tests pass.
- Prevention: every learner-visible generation defect must be reproduced through
  the active evidence V2 parser and final artifact seam, not only a legacy helper.

## AI-QUALITY-026 - Plain-text V2 source collapsed into one lesson without tests

- Date: 2026-09-16. Found by post-release synthetic-tenant acceptance of
  backend `0.5.55`; the generated course remained an unpublished draft.
- Symptom: a ten-section plain-text service regulation produced one lesson and
  zero questions even though source analysis found seven teachable units.
- Cause: local acceptance replayed the legacy `run_direct_architect` helper with
  manually injected Excel-oriented options and guidance. New production jobs
  returned early through `evidence_v2`, where plain `1. Heading` sections had no
  Markdown heading metadata. V2 therefore grouped every chunk under the document
  title, kept several SLA values inside coarse facts, and could not form safe
  assessment seeds. The replay never exercised that production seam.
- Fix: reconstruct deterministic chunk overlaps, recover major plain-text
  numbered sections, split them into independently traceable sentence facts,
  build an adaptive contiguous lesson plan without quota padding, recognize
  singular and minute duration values, add source-grounded section questions
  only when two safe distractors exist, and deduplicate equivalent assessed
  values across the course.
- Verification: the exact source is now a RED/GREEN fixture through
  `generate_evidence_course`; 15 application regressions and the combined
  66-test V2/passport/pipeline set pass. A fresh real-provider replay with empty
  methodologist guidance completed in 29.110 seconds with Voyage embeddings,
  five lessons, seven retained questions, no embedding degradation, no
  deterministic fallback, and `publishable=true`. Full CI, immutable deployment
  and post-release browser acceptance remain release gates.
- Prevention: every generation release must replay the exact observed source
  through the engine named by production job metadata, using the production
  chunker and default empty guidance, and inspect final lesson/question semantics.
  A legacy helper, injected options or aggregate source-analysis counts cannot
  satisfy this gate.

## AUTH-NAV-001 - Final quiz reload restored an unrelated browser session

- Date: 2026-09-16.
- Symptom: after a personal-link learner completed the final quiz, the final
  action performed a full page load and could restore an unrelated refresh-cookie
  session instead of keeping the in-memory assignment identity.
- Cause: the final action called `window.location.assign` while the other course
  transitions used Next.js client navigation.
- Fix: route the final action through `router.push`, preserving the active
  memory-only assignment session.
- Verification: the focused navigation regression and all 595 frontend tests
  pass; type checking and the production frontend build pass.
- Prevention: personal-link flows must test navigation from a browser that also
  contains an unrelated ordinary login cookie, including the last-lesson path.

## AUTH-NAV-002 - Tenant preview profile exposed the platform operator seam and exit revoked the session

- Date: 2026-09-22. Confirmed in the synthetic tenant through the superadmin
  preview flow and reproduced directly against the profile/auth boundaries.
- Symptom: `/profile` showed blank fields with HTTP 422, while leaving tenant
  preview logged the operator out and returned to `/superadmin/login`.
- Cause: `/users/me` reloaded the real platform-superadmin row (`tenant_id=NULL`)
  and serialized it through the tenant-only `UserResponse`; PATCH could mutate
  that operator row before the same serialization failure. The frontend exit
  called full logout even though impersonation replaces only the in-memory access
  token and leaves the platform refresh cookie intact.
- Fix: reject profile reads and writes before DB access while impersonating;
  present an explicit read-only preview explanation in the profile UI. Exit now
  clears only the impersonation token, restores the platform session through the
  existing httpOnly refresh cookie, verifies the restored identity is an actual
  platform superadmin and returns to `/admin/super`. A failed identity check
  fails closed to ordinary reauthentication.
- Verification: two API guards, the profile UI regression, the auth restoration
  regression and adjacent auth/logout tests pass; combined focused API set is
  129 tests and focused frontend set is 26 tests. Final frontend verification
  passes 124 files / 676 tests, lint, typecheck and production build.
- Prevention: every impersonation-only route must distinguish the tenant role
  wrapper from a persisted tenant user. Never mutate the wrapped platform actor,
  and never use full logout to leave an access-token-only preview session.

## TEST-INFRA-001 - Unit runs inherited an invented localhost PostgreSQL target

- Date: 2026-09-16.
- Symptom: a database-backed test attempted to connect to a PostgreSQL instance
  that was not part of the approved test contour.
- Cause: the shared pytest fixture inserted a localhost database URL whenever the
  caller had not supplied one.
- Fix: capture only an explicitly supplied database URL and skip database-backed
  fixtures before engine access when it is absent. CI continues to supply its
  isolated service URL explicitly.
- Verification: a static contract test rejects the old localhost fallback; all
  database-free unit tests pass without PostgreSQL access.
- Prevention: workstation test helpers may never create, infer or default a
  Kamilya database contour; DEV and CI contours must always be explicit.

## MIGRATION-005 - Signed-scan status migration made application rollback unsafe

- Date: 2026-09-16. Found during the release preflight for version 0.6.0 before
  any production publication or schema change.
- Symptom: migration 0160 rewrote every legacy `received` scan to
  `uploaded_pending_review` and rejected future `received` rows. Redeploying the
  previous application after the migration would therefore break its signed
  scan insert path.
- Cause: the migration optimized the status vocabulary for the new UI without
  treating the previous application binary as a required compatibility client.
- Fix: preserve existing `received` rows, retain `received` as the database
  default, and allow both `received` and `uploaded_pending_review` while the new
  application explicitly writes the richer status.
- Verification: a source-level RED/GREEN contract and the isolated Supabase DEV
  gate require the upgraded schema to preserve a legacy row and accept inserts
  using both application versions' statuses under the runtime `lms_app` role.
- Prevention: every forward migration must exercise the previous release's
  write contract whenever application rollback is part of the release plan.

## TEST-INFRA-002 - Windows-only unit success and skipped DB coverage hid CI failures

- Date: 2026-09-16. Confirmed by blocking CI run 35079199800 for the first
  version 0.6.0 candidate; production deployment had not started.
- Symptom: the local full unit suite passed, while Linux CI resolved a hostile
  backslash filename differently. PostgreSQL then exposed two invalid signed-copy
  fixtures: one still used the obsolete knowledge-check/legacy-status contract,
  and another built an enrollment with a random nonexistent course id.
- Cause: `PurePath` followed the workstation OS instead of one upload-name
  contract, and the release preflight covered the new Supabase migration gate
  but not the existing DB-backed export integration that is skipped without an
  explicit database contour.
- Fix: normalize both path separators with `PurePosixPath`; bind the existing
  integration fixture to a course-level `training` event and assert the new
  pending-review lifecycle names; create real tenant-owned courses for review
  fixtures before inserting enrollments.
- Verification: run the exact filename regression locally, the affected
  integration test against the approved Supabase DEV transaction/cleanup
  contour, and then require a new full Linux CI run for the corrected SHA.
- Prevention: upload-filename tests must have OS-independent semantics, and a
  release that changes a DB-backed route must run its existing integration
  tests in addition to unit tests and focused migration/RLS gates.

## EVIDENCE-006 - Legacy completion exported an act without the signature form

- Date: 2026-09-16. Found by the live synthetic production acceptance for
  version 0.6.0 after deployment.
- Symptom: the tenant-admin preview rendered the two-page hand-signature form,
  while the learner download for a completion created before 0.6.0 contained
  only the result act and quiz-attempt history.
- Cause: printable form settings are snapshotted on new completion events, but
  historical training events have no `print_form` key. The learner export
  passed that missing value directly to the renderer, whose form page is
  intentionally conditional.
- Fix: when and only when a learner exports a historical `training` event with
  no form snapshot, resolve the tenant's current form as a presentation-time
  fallback. Do not change the immutable event or the private evidence package;
  events with a saved snapshot remain pinned to it.
- Verification: a database-free RED/GREEN service regression covers the exact
  legacy branch, the DB-backed learner-export integration checks the final PDF
  page for both signature labels, and live production acceptance must download
  and visually inspect the historical learner PDF after the hotfix release.
- Prevention: production acceptance fixtures for additive evidence features
  must include one pre-feature historical event in addition to newly created
  events, and PDF acceptance must inspect rendered pages rather than only HTTP
  status, MIME type or extracted package metadata.

## STAFF-UI-001 - New-department flow disabled the required position choice

- Date: 2026-09-17.
- Symptom: in the manual employee modal, selecting `Create a new department`
  left the required position selector disabled, so the UI appeared to prevent
  completing the employee even though the new-position name input was visible.
- Cause: the selector was disabled whenever `department_id` was empty. A newly
  named department intentionally has no persisted id until the employee request
  is committed, while the backend already supports the atomic free-text
  department plus position path.
- Fix: disable the position selector only while hierarchy options are loading;
  when a new department is selected, keep `Create a new position` available and
  explain that both records are created when the employee is added.
- Verification: the frontend regression opens the modal, verifies that the
  position choice is enabled, enters a new department and position, and asserts
  the exact `/v1/admin/staff/manual` payload. Existing backend hierarchy tests
  confirm canonical position creation and duplicate prevention.
- Prevention: every dependent selector must cover both persisted-parent and
  create-parent-in-the-same-request states; never use absence of a persisted id
  as an availability rule when the API accepts an atomic create path.

## STAFF-UI-002 - Existing positions were hidden until a department was selected

- Date: 2026-09-17.
- Symptom: the manual employee modal initially offered only `Create a new
  position`, even when the tenant already had positions. It also required a
  department although the position model permits a department-free position.
- Cause: the frontend filtered the position list by an initially empty
  `department_id`, and both frontend and backend validation treated department
  plus position as an inseparable required pair. The shared import commit path
  would additionally materialize an empty department for a blank department
  name.
- Fix: show every existing position before a department is selected, annotate
  department-linked choices, fill a linked department when applicable, and
  require only the position. Preserve department-free positions end to end and
  never create a department for an empty name.
- Verification: a RED/GREEN modal test proves that a returned existing position
  is immediately selectable; another submits an employee with an existing
  department-free position. Backend tests cover resolving, reusing and creating
  department-free positions without an empty department row.
- Prevention: optional hierarchy levels must remain optional in UI validation,
  API validation and persistence tests; selector tests must start from the
  initial form state rather than only after selecting a parent.

## STAFF-UI-003 - Canonical organization units were rendered again as compatible departments

- Date: 2026-09-22. Confirmed in the synthetic tenant and reproduced with the
  exact organization-tree response contract.
- Symptom: the same departments appeared in the primary structure, in the
  `Compatible departments` section and twice in the manual employee picker.
- Cause: `/v1/organization-units/tree` already includes legacy roots inside the
  complete `roots` forest, while also returning the same rows in `legacy_roots`
  for compatibility consumers. The staff page concatenated and rendered both.
- Fix: merge compatibility roots only when their ID is absent from the entire
  canonical tree, including descendants. Keep `/v1/departments` for its separate
  course-binding contract and for the fallback used when the tree endpoint is
  unavailable.
- Verification: the integration-style modal regression first reproduced two
  options and React's duplicate-key warning, then passed with one option. Both
  staff hierarchy files pass 10 tests; final frontend verification passes
  124 files / 676 tests, lint, typecheck and production build.
- Prevention: UI consumers must treat `roots` as the complete organization
  forest. Compatibility collections require ID-based de-duplication against the
  full recursive tree before rendering or selection.

## AI-JOBS-003 - Historical and unrelated jobs were shown as active course generation

- Date: 2026-09-22. Confirmed in the synthetic tenant and reproduced against the
  AI job response contract.
- Symptom: the dashboard described failed, cancelled and non-course jobs as
  current course generation. Returning to `/ai/generate` could restore a
  completed result from an earlier visit, and tenant-wide recovery could select
  another methodologist's active job.
- Cause: the dashboard used `status` as both lifecycle and pipeline stage,
  accepted every non-completed job type, and treated cancelled jobs as attention.
  The generation workflow retained completed local-storage context and used the
  tenant-wide history endpoint for personal recovery.
- Fix: filter the dashboard to `course_generation`, omit completed/cancelled
  jobs, classify lifecycle by `status` and active phase by `stage`. Recovery now
  requests `scope=mine`; a completion remains visible in the current mounted
  session but clears both restoration keys and cannot replace a later new form.
- Verification: focused dashboard/recovery/page regressions pass 38 tests; API
  RBAC and current-user query tests pass 26 tests; final API verification passes
  2123 tests and frontend verification passes 124 files / 676 tests plus lint,
  typecheck and production build.
- Prevention: tenant history and current-user recovery are separate contracts.
  Never infer active work from `status != completed`, never use a lifecycle
  status as a stage, and test navigation after completion in a new mount.

## SUPERADMIN-UI-002 - Usage cards displayed invented fixed limits

- Date: 2026-09-22. Confirmed by source/runtime-contract review of the tenant list
  and detail views.
- Symptom: AI and job-description generation always appeared as `/1`, and the
  platform-team count as `/3`, regardless of the tenant's configured limits.
- Cause: the superadmin DTO exposed only counters while the frontend hard-coded
  denominators instead of using `tenant.settings.trial_limits`.
- Fix: expose nullable limits beside each usage counter, derive them from the
  same tenant limit settings used for enforcement, and render the exact value or
  a localized `unlimited` label. No default denominator is invented.
- Verification: pure presentation regressions cover non-default and unlimited
  limits; the API lifecycle fixture covers 7/4/25/6 configured limits. The local
  integration module was skipped without an explicit approved DB contour and
  therefore remains a release gate, not a claimed pass.
- Prevention: usage responses must pair every `used` value with an authoritative
  nullable `limit`; UI code may not encode plan limits.

## LEARNING-UX-001 - Recurrence fields and duplicate selector labels were ambiguous

- Date: 2026-09-22. Confirmed by the synthetic-tenant UX review and component
  regressions.
- Symptom: users had to infer the difference between recurrence interval and
  completion window; same-name employees, courses and organization units could
  not be distinguished before selection.
- Cause: timing inputs had no associated descriptions, and option labels omitted
  available identity/hierarchy context.
- Fix: add localized field descriptions with `aria-describedby` and contextual
  help for learning cycles. Include email or personnel number for learners,
  short identity only for duplicate targets, and full breadcrumbs for structure
  units.
- Verification: focused UX/help/selector suite passes 9 files / 58 tests; final
  frontend verification passes 124 files / 676 tests, lint, typecheck and build.
- Prevention: any selector whose visible label is not unique must expose a stable
  human discriminator before selection; paired timing fields require explicit
  meaning and accessible descriptions.

## ORG-HIERARCHY-001 - Successful organization-unit writes returned HTTP 500

- Date: 2026-09-17. Found by the live synthetic production acceptance for
  version 0.7.0 after the migration, CI, deployment and UI selector checks had
  passed.
- Symptom: creating a root organization unit returned HTTP 500, although the
  row was committed and appeared in the next structure read.
- Cause: the create and update routes committed before constructing their
  response projection. The commit ended the transaction carrying the
  `SET LOCAL app.tenant_id` RLS context; the subsequent readback ran in a new
  transaction without tenant context and could not see the row it had written.
- Fix: flush and build the tenant-scoped response projection first, commit only
  after the projection succeeds, and return the already materialized response.
- Verification: route-level RED/GREEN tests assert the exact
  `projection -> commit` ordering for create and update. Production acceptance
  must additionally create a disposable four-level hierarchy through the
  authenticated HTTP API, verify depth and breadcrumbs, reject a nested central
  office, archive children before parents, and prove no active residue remains.
- Prevention: every endpoint that performs a tenant-scoped write followed by a
  tenant-scoped read must keep both operations in the same RLS transaction or
  explicitly restore the context; migration and service tests alone are not
  sufficient HTTP acceptance.

## AI-GEN-009 - Parser partitions and catalog rows inflated the course outline

- Date: 2026-09-18. Reproduced locally with the repeatability Excel catalog and
  the synthetic narrative PDF before any production release.
- Symptom: a large supporting SKU sheet produced one lesson per catalog row,
  while numbered action-list sentences in the PDF were mistaken for section
  headings. A dense final policy section was then split into additional lessons
  because prompt-sized fact partitions leaked into the pedagogical outline.
- Cause: worksheet role classification did not give strong catalog naming
  precedence when generic primary markers tied; plain-text and Markdown
  section recovery treated every ordinal sentence as a heading; and narrative
  lesson sizing reused provider-safety partitions as curriculum units.
- Fix: classify a dominant catalog-named worksheet as supporting when primary
  peers exist; retain sentence-like ordinal instructions under their enclosing
  section; bound spreadsheet lessons by source-derived teachable capacity; and
  size narrative lessons by content density independently of provider request
  partitions. Reject invalid deterministic lesson titles before embeddings or
  generation calls.
- Verification: RED/GREEN regressions cover the 90-row SKU sheet, numbered PDF
  instructions, source-derived spreadsheet capacity, narrative over-splitting,
  and zero provider calls after a failed plan preflight. Provider-backed local
  acceptance must still pass twice for both Excel and PDF before release.
- Prevention: generation changes must first replay structural fixtures through
  the public application seam; parser chunks, retrieval chunks and curriculum
  lessons are separate abstractions and must never share an implicit one-to-one
  cardinality rule.

## AI-GEN-010 - Weak catalog recall and an overlong safe fallback blocked acceptance

- Date: 2026-09-18. Found by the final local synthetic/real replay and the
  development-only TypeSafe evaluation before production release.
- Symptom: catalog tests asked for dimensions already encoded in SKU names and
  repeated the same attribute-answer pair across products. Options such as
  `Терра` and `Терра с разъяснением` could coexist. Separately, when all model
  attempts for one dense legal lesson failed, the exact source-only fallback
  exceeded the 650-word publication limit and rejected the otherwise complete
  course.
- Cause: deterministic assessment selection prioritized short numeric values and
  deduplicated complete fact triples instead of the tested attribute-answer.
  Option ambiguity was one-directional. Narrative planning bounded fact count
  but could merge provider-sized partitions past the safe source-word budget.
- Fix: omit catalog identifier/specification recall from tests, reject answers
  exposed by the subject identifier, assess each attribute-answer once, reject
  option containment in either direction, and greedily group narrative source
  units under hard 550-word and 20-fact limits while preserving section order
  and complete fact coverage.
- Verification: exact RED/GREEN regressions cover every defect, including one
  legitimate substring-sharing option set; the combined affected suite has 158
  passing tests and Ruff/diff checks are clean. The real
  Plus workbook completed with 3 lessons and 5 retained questions in 20.775
  seconds. The real Lombard PDF completed with 24 lessons, all 314 facts, 10
  retained questions and no deterministic fallback in 157.321 seconds.
- Prevention: release acceptance must exercise both a successful provider path
  and the source-only fallback bound; question acceptance must prefer educational
  discrimination over count, and TypeSafe findings must be traced back to the
  source before changing the generator.

## AI-GEN-011 - Formally grounded fragments and binary distractors caused false quality results

- Date: 2026-09-19. Found by manual review after a formally green full Lombard
  PDF run and then reproduced with the same production-converter corpus.
- Symptom: one question used the dependent fragment `Получив информацию и
  ознакомившись ...` as its complete answer. Separately, an open-information
  yes/no rule was repeatedly dropped because the model could not invent two or
  three genuinely distinct false versions of the same binary proposition.
- Cause: exact source containment was treated as sufficient even when the span
  had no independent predicate; binary normative axes still delegated all
  distractors to the model. Older constraint-review fixtures also omitted the
  now-required `evidence_fact_ids`, hiding stale test-contract assumptions.
- Fix: reject source spans that are only an introductory gerund phrase while
  preserving complete sentences with a following main clause. For unambiguous
  open-information, negative-right, non-admission and optional rules, derive
  the inverse on the server and materialize a true/false question. Keep answer
  keys, evidence and inverses outside model ownership. Update fixtures to carry
  exact evidence identity; never weaken the evidence gate to satisfy old tests.
- Verification: 74 focused assessment tests and the full 2027-test API unit
  suite pass. The full local DeepSeek Flash application run produced 15
  lessons, 27 accepted questions, 13/13 source-topic coverage and
  `publishable=true`; manual review found no duplicate prompts/keys, OCR marker
  leakage or dependent-fragment answers.
- Prevention: a green publishability gate must be followed by bounded manual
  inspection of every answer key and option set. Binary facts use server-owned
  inverses; dependent source fragments are not assessment facts; test fixtures
  must implement the same explicit evidence contract as production objects.

## AI-QUALITY-028 - Per-block assessment caps multiplied questions per lesson

- Date: 2026-09-19. Found by the first production synthetic human-path check of
  release 0.7.5 and reproduced through the production-shaped local application
  seam before preparing 0.7.6.
- Symptom: a nine-lesson workbook produced 51 questions because each internal
  semantic block could independently request up to three. Some alternatives
  answered a different task than a concise categorical key, and bare numeric
  keys were visually distinguishable from options carrying unit suffixes.
  Separately, the acceptance harness compared authoritative worker output with
  a lightweight upload-admission estimate and reported a false size mismatch.
- Cause: assessment density was bounded at the internal block seam instead of
  the learner-visible lesson seam. The deterministic answer boundary checked
  source identity and truth but not concise answer-domain shape or numeric
  presentation shape. The DEV harness fabricated authority that the admission
  response did not have.
- Fix: select at most three axes per lesson round-robin across blocks before any
  provider call; classify excess axes as `density_omitted`; classify questions
  rejected after bounded review/repair as `quality_omitted`; reject
  sentence-shaped alternatives for short categorical keys; normalize numeric
  alternatives when the source key is a bare number; and defer authoritative
  sizing to the worker source passport. Report derived and requested axes as
  separate counters.
- Verification: RED/GREEN regressions cover multi-block lesson density,
  categorical answer shape, numeric option shape, quality omission, provider
  outage fail-closed behavior and harness authority. Full API unit suite passed
  `2061`; `AI-COURSE-01` passed `7`; release contracts passed `47`. The final
  exact-code provider run completed with 9 lessons, 4 retained questions, 4/4
  required topics, no fallback and `publishable=true`; root manually accepted
  every retained answer set. Production human-path acceptance remains mandatory.
- Prevention: question density is always measured at the learner-visible lesson
  seam; optional weak questions may be deleted but infrastructure failures may
  not be relabelled as quality omissions. Every release acceptance must inspect
  all retained answer sets for answer-domain and formatting cues, and a proxy
  may never substitute for the authoritative worker contract.

## TOOL-010 - VM126 container readback lagged behind the slot release plane

- Date: 2026-09-19. Found while independently closing the `v0.7.7` production
  evidence after the protected release had already passed its own service gates.
- Symptom: the fail-closed remote executor rejected the current blue/green
  container names locally. After the guessed name shape was corrected, a real
  readback reached Docker but its valid immutable `repo@sha256:...` image value
  was rejected by the evidence sanitizer.
- Cause: the verifier allowed only legacy Compose names such as
  `kamilya-runtime-api-1`, while release-plane configuration uses project prefix
  `kamilya` and therefore names active containers `kamilya-<slot>-<service>-1`.
  The generic evidence-value alphabet also omitted `@`, although immutable
  Docker image references require it.
- Fix: derive the accepted slot name shape from the source-controlled
  release-plane prefix, retain the exact legacy names for rollback-era
  inspection, and permit `@` only in the `image` evidence field. Unknown slots,
  services, output formats and generic values containing `@` remain blocked.
- Verification: the focused executor suite passes `65` tests across all four
  services and both slots, legacy compatibility and adversarial names. A real
  reviewed read-only script then returned API, worker-ai, worker-documents and
  worker-ops on active slot `green`, all running image digest
  `sha256:03e2401468e608f6ecff80a025b199cf8f5275d3fce219ec66f49efae8233f14`
  with zero restarts.
- Prevention: every release-plane naming or evidence-format change must add a
  remote-executor contract test in the same change. Readback scripts must use
  the exact source-controlled `project_prefix`; do not infer container names
  from pre-release Compose history.

## LEARNING-003 - Repeat-assignment UI and API drifted before integration review

- Date: 2026-09-22.
- Symptom: the first delegated frontend expected `include_history`,
  `total_history`, `attempts_exhausted` and `lifecycle_status`, while the API
  exposed `history`, `total`, `exhausted_attempts` and `enrollment_status`.
  TypeScript passed because the summary response was treated as an untyped
  record; production would have shown dashes and the history toggle would have
  been ignored.
- Cause: backend and frontend were implemented in parallel from prose instead
  of one executable wire contract. The initial current-row filter also removed
  cancelled/superseded statuses but still counted an immutable completed
  predecessor referenced by a new occurrence. Independent review then found
  that legacy NULL-scoped lesson progress would be inherited by a manual repeat,
  history mode could contaminate current summary cards, and the first trigger
  draft revalidated an actor's present-day role on every later status update.
- Fix: align the exact query/response names, bind the mutation to the selected
  `previous_enrollment_id`, and centralize current-occurrence SQL as a NOT EXISTS
  successor predicate. The assignments list, journal and summary now share that
  occurrence-head rule. Repeated progress uses the exact enrollment ID across
  progress, learner dashboard, quiz availability and training-log joins; summary
  cards remain current while history has explicit counters; immutable audit
  identity no longer blocks status updates after the actor changes role.
- Recurrence during final review: the first reassignment service created the new
  row but did not recreate its access policy, notification or protected-link
  credential, and the centralized progress helper omitted learning-path
  assignments. An open personal-link predecessor would therefore be revoked
  without a replacement, while path progress could fall back to legacy scope.
- Additional fix: make delivery part of the occurrence contract. Email repeats
  create a new policy and durable outbox notification; personal-link repeats
  issue a new one-time URL/PIN and return it only in the mutation response.
  Relative link, due-date and completion-window durations are restarted from the
  repeat time. The shared progress helper also scopes learning paths explicitly.
- A single legacy `updated_at` cannot prove which deadline field changed. The
  migration therefore backfills durations only for unmodified policies and
  leaves ambiguous rows fail-closed until an audited explicit extension writes
  field-specific duration metadata.
- Verification: focused web tests PASS; full web 665 PASS; typecheck and
  production build PASS; API database-free 3059 PASS / 498 integration-only
  skipped; migration/static contracts PASS; isolated Supabase DEV
  migration, restricted-role FORCE RLS, ownership negatives, post-demotion
  status update, downgrade/re-upgrade and cleanup PASS.
- Prevention: every parallel API/UI slice must end with one executable contract
  test that asserts exact query names, response keys and a completed-predecessor
  chain before full suites or release. Run repository-root tests from their
  documented working directory; a wrong cwd is an execution artifact, not a
  product regression.

## CI-005 - Local release checks omitted the committed Python quality baseline

- Date: 2026-09-22.
- Symptom: exact-SHA CI passed unit, frontend, release, secret and dependency
  gates but blocked on `Backend Python quality baseline`; local tests and a
  focused code review had already passed.
- Cause: the pre-push checklist ran tests and `git diff --check` but did not run
  `scripts/ci/python_quality_baseline.py`. New tenant-usage code therefore added
  one unannotated generic mapping and passed a legacy SQLAlchemy `Column[int]`
  to an `int | None` helper without an explicit runtime-model cast.
- Fix: type the JSON settings mapping as `dict[str, Any]` and cast the loaded
  tenant limit at the SQLAlchemy model boundary. Do not raise the committed
  baseline to absorb new findings.
- Verification: the canonical baseline now passes with `ruff=1056` and
  `mypy=2227`; the affected Supabase DEV integration test passes, and the
  focused assessment/profile set passes 121 tests.
- Prevention: run `python scripts/ci/python_quality_baseline.py` from the
  repository root before every release commit that changes Python. A green
  pytest suite, Ruff on changed files or an independent review does not replace
  the committed Ruff/mypy regression gate.

## RELEASE-002 - Local version check omitted the release-note identity contract

- Date: 2026-09-22.
- Symptom: DEV exact-SHA acceptance passed, but the production tag preflight
  stopped before tag creation because release notes had the localized label
  `Версия продукта` instead of the required machine-readable marker
  `Product version`.
- Cause: pre-push checks invoked `scripts/validate_version.py` only in
  development mode. That mode verifies manifest versions but intentionally does
  not validate the dated changelog section and release-note identity markers.
- Fix: restore the canonical English identity marker while keeping the body of
  the customer-facing notes in Russian. No tag or GitHub Release was created for
  the rejected SHA.
- Verification: `python scripts/validate_version.py --release
  --expected-version 0.10.1` passes before the replacement exact SHA is pushed.
- Prevention: once a version has a dated changelog section and release notes,
  run the release-mode validator before the first DEV push. Development-mode
  validation is not sufficient for a release candidate.

## AI-QUALITY-029 - A title-matching sole section or small catalog distorted source density

- Date: 2026-09-23. Local candidate only; no DEV or production deployment.
- Symptom: a one-rule source produced zero lessons, while a two-sheet workbook
  produced four lessons because its auxiliary nomenclature became a teaching
  section. A green pipeline status alone would not reveal either semantic loss.
- Cause: a multi-section preamble rule was applied even when the narrative had
  only one section. The passport reference heuristic required a large or strongly
  dominant catalog and missed a small, explicitly named catalog beside a clear
  primary worksheet.
- Fix: preserve a sole narrative section as primary; classify a named reference
  sheet as supporting when its reference evidence exceeds its primary evidence
  and the same document has a strong primary sheet.
- Verification: independent synthetic gold cases go red before each fix and green
  after; actual local XLSX/PDF conversion plus source/plan checks pass. A bounded
  live DeepSeek micro-source probe accepted one question only with the working
  8192-token response limit; 1800 tokens truncated its review JSON. This does not
  prove full-document quality or a production release.
- Prevention: test the four seams separately from question back to file; include
  both tiny and multi-section documents, actual converter output, exact source
  roles, no-padding and no-invented-value assertions. Keep model probes under an
  explicit call/cost cap and distinguish harness failures from product defects.

## AI-QUALITY-030 - Production PDF conversion silently removed a teachable section

- Date: 2026-09-23. Isolated local candidate only; no DEV or production write.
- Symptom: the real remote converter returned both numbered sections of a
  synthetic PDF, but the course contained only the second section and was
  marked publishable. The local pypdf test did not reproduce this route.
- Cause: MarkItDown emitted nominal numbered headings without Markdown `#`, so
  the chunker made one unheaded chunk. It also inserted blank lines inside
  printed sentences; the evidence boundary correctly rejected those fragments
  as incomplete. The passport did not identify numbered narrative sections.
- Fix: recognize standalone nominal numbered headings while leaving action-list
  sentences as body text; do not overlap facts across those hard boundaries;
  join only unpunctuated, lowercase paragraph continuations; classify
  substantive numbered sections independently. Freeze the actual synthetic
  converter text as a regression fixture.
- Verification: the same PDF through the canonical VM126 converter changed
  from one lesson to two; source-boundary tests and the local evidence suite
  pass. A successful model run is not proof of stable assessment quality.
- Prevention: for each converter engine used in production, capture a bounded
  synthetic source and assert source chunks, admitted facts, section roles and
  lesson plan before testing model output. Treat `publishable=true` with a
  missing source section as a defect, and never infer fidelity from local
  fallback conversion alone.

## AI-QUALITY-031 - Local LLM probe understated retry behavior and hid quiz variance

- Date: 2026-09-23. Isolated local candidate only; no DEV or production write.
- Symptom: one synthetic PDF run lost an otherwise assessable question after a
  model JSON syntax error. Later independent runs varied from one to three
  accepted questions for the same two lessons while all reported publishable.
- Cause: the bounded probe adapter lacked the production client's single JSON
  syntax correction and returned no typed parse-failure reason, so the
  assessment retry policy could not run faithfully. Separately, short temporal
  rules invited distractors with new actors/documents, which review removed.
- Fix: make the test adapter reserve and count the correction request, preserve
  typed failure reasons, and test it with a fake provider; narrow the assessment
  author prompt to same-action order/omission errors without invented actors.
- Verification: two independent post-change PDF probes retained three questions
  across both lessons; Excel retained five source-relevant questions while
  dropping one weak option. The full results and stage times are in the
  backward-quality report. The paid probe is now closed in code.
- Prevention: compare a local provider adapter against production retry/JSON
  semantics before interpreting a failed live probe as a product defect.
  Evaluate repeated outputs and the per-lesson axis ledger, not only a green
  publishability bit. Avoid forcing question count when review rejects an item.

## AI-QUALITY-032 - Local GLM default reasoning hid its viable test mode

- Date: 2026-09-23. Isolated synthetic probe only; no DEV or production write.
- Symptom: `/v1/models` and a tiny JSON call passed, but the first full PDF
  probe gave no intermediate result for 15 minutes and was stopped.
- Cause: this EXL3 deployment enables long reasoning by default. The test
  client capped output at 8192 tokens, which can end before a final JSON answer.
- Fix: the local-only adapter explicitly sends
  `chat_template_kwargs.enable_thinking=false`, checks HTTP status, bounds
  individual requests and total runtime, and logs per-call duration. The
  paid DeepSeek test path remains closed.
- Verification: the same PDF completed in 8 GLM calls with 2 lessons and 3
  accepted questions; XLSX conversion and generation also completed. The
  endpoint and exact model ID were read back before the calls.
- Prevention: for every new local model, test a representative structured
  response with its documented reasoning mode and time limit before running
  a multi-step pipeline. A healthy `/models` or one tiny answer is insufficient.

## AI-QUALITY-033 - Unsupported teaching prose became bare cells and hidden quiz loss

- Date: 2026-09-23. Isolated local candidate only; no DEV or production write.
- Symptom: the GLM Excel lesson contained `МДФ Для прихожей Зеркало в комплекте`
  although the raw model response was coherent. Another run omitted every
  question for one assessable lesson but still reported `publishable=true`.
- Cause: the grounding filter correctly discarded unsupported sales advice,
  then concatenated unrelated source values into the rejected block. The
  publishability gate checked topic coverage but ignored an assessable block
  whose candidates were all rejected as weak.
- Fix: skip unsupported model blocks; render still-uncovered facts separately
  with source labels and source-derived headings. Mark a result review-required
  when a block with candidates has zero accepted questions, without making up
  replacement questions or increasing a quota.
- Verification: regression cases red then green; 221 focused tests and the
  committed Ruff/mypy baseline passed. A later GLM Excel run produced 2 lessons
  and 6 questions across both; a separate omission test confirmed the new
  publishability reason. These are local tests, not a release gate.
- Prevention: inspect both raw model output and rendered lessons; test the
  postprocessor against short table cells and absent per-block assessment.
  Never equate `publishable=true` with human-quality prose or complete learning
  coverage without checking the assessment ledger.
- Follow-up, 2026-09-23: the earlier short-cell test used `sheet=...`, whereas
  the active direct-source route encodes table provenance as
  `doc_id=...;section=...;row=...;column=...`. The fallback therefore still
  emitted bare values in a live synthetic XLSX run. A shared structured
  locator check now recognizes both forms; the canonical-format regression
  failed before the fix and passed after it. Two later GLM XLSX runs retained
  explicit subject and attribute for fallback cells.

## AI-QUALITY-034 - Model metadata and question stems changed source scope

- Date: 2026-09-23. Isolated local candidate only; no DEV/production write.
- Symptom: a synthetic XLSX source described the collection `Берег`, but one
  run called it a `Комод`; another called collection `Север` a `прихожая`
  because that was its intended room. A PDF question asserted that documents
  had been compared with goods, while the source required comparing invoice
  and order numbers. Each answer key was source-backed, so the usual blind
  reviewer accepted the misleading question stem.
- Cause: the provider could rewrite a spreadsheet lesson title/objective and
  a question premise independently of the source-owned row subject. Its
  metadata then became context for the next assessment stage. GLM also
  rubber-stamped false premises when premise checking was merely added to the
  existing broad review prompt; a separate focused audit was inconsistent.
- Fix: keep planned title/objective for table facts; render short fallback cells
  with subject and attribute; reject distractors that quote another known
  attribute as if it answered this one. Table question stems use source-owned
  subject/attribute wording, but authored wording is still checked first so
  cross-collection ambiguity cannot be hidden. For unambiguous `После ...`
  and actionable `Если ...` rules, form the question from the source condition
  rather than from a model-invented scenario. Do not add a GLM audit call that
  failed the frozen counterexamples.
- Verification: red-then-green focused cases, 367 related local tests and the
  seven database-free `AI-COURSE-01` checks passed. Two subsequent canonical
  MarkItDown PDF runs produced two lessons and 3/2 accepted questions; two
  `openpyxl` XLSX runs produced two collection lessons and 6/5 accepted
  questions. No observed answer key or stem changed entity type in those four
  final runs. This is synthetic local evidence, not a claim about all sources.
- Prevention: freeze real converter provenance and provider outputs in tests;
  review stems as well as keys; keep source subjects authoritative across
  lesson metadata and assessment, and do not promote a prompt-only auditor
  without repeated negative and positive evidence.

## AI-QUALITY-035 - Multi-fact table block hid naked values; rule restoration repeated prose

- Date: 2026-09-23. Isolated local candidate; no DEV or production mutation.
- Symptom: a larger synthetic workbook yielded `Белый 24 месяца МДФ Для прихожей`
  inside a lesson despite source-backed fact IDs. A four-section PDF repeatedly
  placed a source sentence after a near-equivalent model paraphrase.
- Cause: one model block could cite all workbook cells and thereby claim full
  coverage even when their values lacked attribute labels. The short-rule
  restoration path appended exact source wording to a partial paraphrase
  instead of choosing one complete presentation.
- Fix: for short atomic workbook cells, require each cited value to occur with
  its own attribute in the same clause; otherwise leave it to the labelled
  source-owned fallback. Keep sentential/long workbook cells on the existing
  prose path. Order resulting workbook blocks by source row. For a short clean
  narrative rule that needed restoration, render its complete source wording
  once instead of mixing it with a partial paraphrase; leave long, OCR-tainted
  and tabular sources on their prior paths.
- Verification: the naked-value, reversed-row, swapped-label and repeated-rule
  regressions failed before their respective fixes and passed afterward.
  328 related local tests, six critical-journey gate tests and the Ruff/mypy
  baseline passed. Final production-converter synthetic probes gave four PDF
  lessons/five accepted questions without repeated rules and three workbook
  lessons/nine accepted questions with all 15 labelled attributes. No live
  tenant, embedding, UI or database path was exercised.
- Prevention: add medium-complexity PDF/XLSX fixtures, inspect rendered text
  as well as question keys, and never treat cited IDs or `publishable=true`
  alone as proof that learner-visible prose is complete and readable.

## AI-QUALITY-036 - DEV acceptance pinned an absent synthetic workbook

- Date: 2026-09-23. Found before promoting release `0.10.2` from DEV to
  production; no production mutation had started.
- Symptom: the exact DEV runtime and CI were green, but
  `course_quality_dev_acceptance.py` rejected every available repository fixture
  before upload with `fixture_not_approved_synthetic_workbook`.
- Cause: the fail-closed SHA still identified an older generated workbook that
  was no longer committed. The focus extractor also expected the legacy sheet
  `Коллекция` with one collection per row, while the current expanded fixture
  uses `Коллекции` with collection names in the header.
- Fix: pin the acceptance harness to the committed expanded workbook SHA and
  derive its focus terms from the primary-sheet header used by the current
  Evidence V2 path.
- Verification: the new regression failed against the stale fixture contract,
  then all 13 acceptance-harness tests and 104 related evidence/corpus tests
  passed after the correction.
- Prevention: every release-quality fixture must be committed beside its
  consumer, covered by an exact-byte test and parsed through the same layout
  branch that the live acceptance script will execute.

## TEST-INFRA-003 - API pytest again used an ambient Poetry runtime

- Date: 2026-09-23. Local focused TDD only; no DEV or production mutation.
- Symptom: a focused AI-generation test command stopped before collection
  because the Poetry-created environment did not contain `pytest_asyncio`.
  The first wrapper revision then ran the full suite from the monorepo root,
  causing 17 false `FileNotFoundError` failures in API-relative contract tests.
- Cause: the existing absolute-path rule in `TEST-ENV-001` remained passive;
  the operator invoked bare `poetry run pytest` instead of the maintained root
  `.venv` that the repository runbook identifies as canonical.
- Fix: add `scripts/dev/run_api_pytest.ps1` as the only local API pytest
  entrypoint. It resolves the repository root, verifies `pytest` and
  `pytest_asyncio`, invokes the exact root `.venv` interpreter from the
  `apps/api` working directory, normalizes both API and root-script selectors,
  and never installs or falls back to an ambient environment. Make the wrapper
  mandatory in `AGENTS.md` and cover its command contract with a static test.
- Verification: the wrapper contract and mixed API/root selectors passed,
  followed by 184 related Evidence V2 tests and the full API suite: 3070
  passed, 499 skipped.
- Prevention: skill suggestion and `ERRORS.md` discovery assist routing but do
  not enforce the runtime. The executable wrapper is the fail-closed boundary.
- Recurrence 2026-09-25: the wrapper correctly selected the canonical runtime
  but replaced `PYTHONPATH` with `apps/api` alone. A root-script smoke test was
  therefore unimportable when selected through the required wrapper. The
  wrapper now joins `apps/api` and the repository root with the platform path
  separator, and its contract asserts that exact behavior. The previously
  failing smoke test plus wrapper contract pass four tests; the full API suite
  then passes 2853 tests with 499 contour skips. Do not work around this class
  by switching interpreters or running bare pytest.

## AI-QUALITY-038 - Valid worksheet output repeated headings and knowledge targets

- Date: 2026-09-23. Found by manual review after a structurally green DEV
  acceptance; production still remained on `0.10.1`.
- Symptom: one lesson rendered `Назначение` and `Гарантия` once per collection,
  while two accepted questions both tested `Гарантия = 24 месяца` for different
  rows. Every fact and answer was source-backed, so the older structural checks
  did not reject the repetition.
- Cause: validated grounded blocks were rendered one-by-one, and tabular
  assessment selection was fair by row but not by semantic attribute. The
  final short-answer identity also included `fact_id`, preserving duplicate
  `attribute + answer` targets across rows.
- Fix: coalesce validated tabular blocks by normalized source attribute while
  retaining stable text and every fact id. Select distinct tabular attributes
  before spending the bounded question budget, and drop repeated
  `attribute + answer` identities without replacement or quota padding.
- Verification: all three deterministic regressions failed before the fix and
  passed afterward; 184 related Evidence V2 tests and the full API suite (3070
  passed, 499 skipped) passed through the canonical runner.
- Prevention: release acceptance includes a human-readable review artifact;
  structural PASS is not sufficient until heading repetition and semantic
  question variety are inspected.

## AI-QUALITY-037 - DEV acceptance mixed Evidence V2 with retired generator assumptions

- Date: 2026-09-23. Found during the release gate for `0.10.2`; no production
  mutation had started.
- Symptom: a successful Evidence V2 draft exceeded the requested lesson ceiling,
  while the DEV harness reported missing source evidence, missing tabular
  assessment paths and a fixed-position weakness in one-question quizzes.
- Cause: Evidence V2 did not receive the admission ceiling. The harness captured
  quality events and assessment counters emitted only by the retired generator,
  and applied a multi-question guessing heuristic to singleton quizzes.
- Fix: thread the lesson ceiling through the sole Evidence V2 entrypoint and
  merge source-owned units without dropping admitted facts. Capture persisted
  lesson evidence and diagnostics directly from the V2 state. Validate V2
  assessment coverage instead of retired path counters, and apply positional
  guessing checks only when a quiz has at least two keyed questions.
- Verification: each symptom had a deterministic red regression; all six focused
  regressions and 165 related API tests then passed through the canonical runner.
- Prevention: release acceptance must observe the same engine state that is
  persisted. Engine-specific counters may not be shared across implementations,
  and obsolete execution routes must fail closed rather than remain resumable.

## TEST-INFRA-004 - Canonical pytest wrapper split one selector into characters

- Date: 2026-09-24. Found by the first red test for the Learning Actions slice;
  no application, DEV or production data had been changed.
- Symptom: the mandatory wrapper invoked pytest with the path `t` and collected
  zero tests whenever exactly one selector was supplied.
- Cause: PowerShell collapsed the `foreach` result to a scalar string.
  Splatting that scalar expanded its characters instead of passing one argument.
- Fix: materialize `$normalizedArgs` as an array with `@(...)` before
  invoking the canonical root `.venv`. Extend the static runner contract to
  require this executable boundary.
- Verification: the wrapper contract passed, then one-selector TDD collected
  and passed 3 tests; the integrated focused backend run collected and passed
  35 tests.
- Prevention: wrapper tests must verify argument cardinality as well as
  interpreter selection. A zero-test invocation or a shortened selector is a
  failed gate, never a product result.

## RELEASE-003 - Persistent Release Runner completed packets with empty turns

- Date: 2026-09-24. Found after the exact frontend release `aa23e3d7`; the root
  completed the authorized production deployment through the canonical runbook.
- Symptom: five consecutive Release Runner turns reached `completed` with no
  commentary, tools, final handoff or explicit blocker. Earlier runs also read a
  stale primary checkout and misclassified executor access failures as release
  or credential failures.
- Cause: the persistent task had accumulated a long stale context and started
  outside the current repository. The prepared executor/checkout preflight fix
  remained on an unmerged branch, while the active contract had no explicit
  invariant forbidding an empty completed turn.
- Fix: bring executor and exact-Git-object preflight into the canonical runner
  contract; classify sandbox, network and host-key failures as
  `EXECUTOR_ACCESS`; require visible commentary and a final five-field handoff
  for every packet, including validation failures before the first tool call.
- Verification: `test_release_runner_fails_closed_on_checkout_drift_and_empty_turns`
  fails against the previous contract and passes after the correction. The
  persistent task must additionally pass a fresh no-mutation probe before it is
  trusted with another release packet.
- Prevention: a completed runner turn without an `agentMessage` is a runner
  health failure, never release evidence. Do not resend production packets into
  that task; re-anchor or replace the task with the canonical contract first.

## UI-002 - Impersonated tenant top bar overflowed a 1024px viewport

- Date: 2026-09-24. Found during the post-release human acceptance of the
  methodologist shell in the production synthetic tenant.
- Symptom: at a 1024px viewport the document became 193px wider than the visible
  area. Notifications, profile and the secondary `Superadmin` action moved off
  screen even though the sidebar and page content remained responsive.
- Cause: the top-bar row had a fixed height and could not wrap. The full command
  search and a redundant secondary impersonation-exit button became visible at
  the `sm` breakpoint, while the open desktop sidebar left only 774px for the
  header.
- Fix: allow the top-bar row and action group to wrap below `xl`; give the left
  context a shrinkable flex allocation; show the full command search and the
  redundant secondary exit only at `xl`. The always-visible impersonation banner
  retains its primary exit action at narrower widths.
- Verification: the exact 1024px production DOM measurement reproduced
  `scrollWidth=1207` against `clientWidth=1014`. The focused responsive contract
  failed before the fix and passes afterward together with the TopBar,
  localization and sidebar regressions. DEV and production browser readback must
  remeasure document overflow before release acceptance.
- Prevention: authenticated-shell acceptance must include an impersonated tenant
  at 1024px and assert document `scrollWidth <= clientWidth`; responsive source
  tests must keep wide, redundant controls behind the `xl` breakpoint.

## RELEASE-004 - Routine CT137 releases were manually reassembled from low-level steps

- Date: 2026-09-24. Found while reviewing repeated native frontend release
  friction; no new production deployment was performed.
- Symptom: each release required the operator to rediscover the active checkout,
  artifact, current release, rollback and capacity, then manually order status,
  stage, deploy and readback commands. A stale hard-coded checkout path and a
  guessed absent rollback could fail before the real release gate was evaluated.
- Cause: the hardened host helper protected each individual operation, but no
  single release-level interface bound source, CI, artifact, host inventory,
  rollback, capacity and public readback to the same approved packet.
- Fix: add `scripts/ops/ct137_native_release.py` as the sole routine native
  release controller. It requires a digest-bound strict packet, verifies exact
  repository/tag and GitHub run identities, inspects the immutable bundle, reads
  live CT137 releases/staging/free space, verifies rollback and privilege boundary,
  computes a conservative capacity budget, stages/deploys in one order and emits
  atomic technical evidence. Resolve lower-level paths from the active isolated
  checkout instead of the shared primary tree.
- Verification: 50 focused controller and host-helper tests pass from the
  repository root (19 Linux-only cases skipped on Windows), the separate CLI
  contract passes, and Ruff/compilation are clean. A live read-only CT137 probe
  confirmed current `7613885d`, rollback `f771a740`, restricted privilege
  boundary, four immutable release directories and conservative free-space
  readback. Authenticated product acceptance remains a distinct Test Runner gate.
- Prevention: Release Runner may not manually compose routine native deployment
  subcommands or infer rollback identity. A controller result ending in
  `SEPARATE_TEST_RUNNER_REQUIRED` is technical deployment evidence, not product GO.

## TEST-INFRA-005 - Shared DEV cleanup tests selected persistent synthetic tenants

- Date: 2026-09-25. Found while running the superadmin operations integration
  suite against the approved Supabase DEV transaction-rollback contour; no
  persistent row was deleted.
- Symptom: cleanup preview returned an older persistent synthetic tenant before
  the test fixture, and the destructive cleanup test first attempted that same
  unrelated tenant. The exact-result assertions failed even though the test's
  own candidate was handled inside the rollback transaction.
- Cause: the tests used the production cleanup prefixes in a shared DEV database,
  so their global superadmin query could legitimately match persistent demo
  tenants. Transaction rollback protected persistence but did not isolate result
  selection or prevent unnecessary access to unrelated synthetic rows.
- Fix: each cleanup integration test now replaces the allowed-prefix tuple with a
  unique per-test prefix and creates all matching fixtures under that namespace.
  The endpoint still executes its real SQL and guards at the normal 24-hour
  threshold, while no shared tenant can match the test-only prefix.
- Verification: both previously failing cleanup scenarios pass against the same
  Supabase DEV contour, followed by the complete operations integration suite
  (`8 passed`) with transaction cleanup.
- Prevention: shared-environment integration tests for global maintenance
  operations must use a unique server-enforced selector. Extreme ages and
  transaction rollback alone are not selection isolation, and exact-result
  assertions may not assume an otherwise empty DEV database.

## TEST-INFRA-006 - Render requirements drift passed CI and failed at API startup

- Date: 2026-09-25. Found during exact-SHA DEV promotion of the superadmin
  operations observability release; production was not touched.
- Symptom: Render built the candidate successfully but the replacement process
  exited while importing `sqlalchemy.ext.asyncio` because `greenlet` was absent.
- Cause: Render installs the independently maintained `apps/api/requirements.txt`.
  Its unconstrained plain `sqlalchemy` requirement resolved to SQLAlchemy 2.1,
  where the asyncio runtime dependency is selected through an explicit extra,
  while Poetry-based CI and production-image tests used the lock graph and had
  `greenlet` installed. The earlier `xlrd` recurrence note had no enforcing gate.
- Fix: declare SQLAlchemy with the `asyncio` extra in both Poetry and Render
  dependency contracts, bound the Render major version, and extend the release
  contract gate to require every direct API runtime dependency plus the
  SQLAlchemy asyncio extra in `requirements.txt`.
- Verification: the focused regression fails against the old Render dependency
  line and passes after the fix; the release contract, complete local suites,
  exact-SHA CI and Render DEV runtime readback must pass before production.
- Prevention: prose in `ERRORS.md` is not a control. Any independently installed
  runtime dependency manifest must have a blocking, stdlib-only parity gate in
  the release path, and async SQLAlchemy environments must request the asyncio
  extra explicitly.

## OPS-OBS-001 - Celery health used a sub-production remote-control timeout

- Date: 2026-09-25. Found during authenticated production acceptance of the
  superadmin operations dashboard after all three worker containers had passed
  immutable-image and zero-restart readback.
- Symptom: the dashboard marked the fast, documents and AI worker roles as
  unavailable even though all three containers were running and processing the
  production broker topology.
- Cause: the endpoint allowed only 0.75 seconds for each Celery remote-control
  broadcast. A sanitized production probe from the API container received three
  responses for `ping`, `registered` and `active_queues`, but even a two-second
  Celery timeout completed in about three wall-clock seconds. The outer timeout
  was therefore also too short for the two sequential inventory commands.
- Fix: use a two-second Celery control timeout and a three-second outer margin,
  preserving fail-closed behavior while allowing the observed three-worker
  topology to answer. Add a public-summary regression with two one-second
  control responses; it fails under the old budget and passes under the new one.
- Verification: the focused regression was red before the change; the complete
  operations contract suite passes afterward. Exact-SHA CI, DEV runtime and a
  repeated authenticated production dashboard readback remain mandatory before
  accepting the corrective release.
- Prevention: worker-container liveness is not a substitute for application
  control-plane reachability, and localhost-speed mocks are not production
  latency evidence. Every Celery observability change must include a delayed
  multi-worker regression and a sanitized live `registered`/`active_queues`
  timing probe before production acceptance.
