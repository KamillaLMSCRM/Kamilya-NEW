# Error and Recurrence Prevention Log

Current as of: 2026-09-02.

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

- Date: 2026-08-20; revised 2026-08-31 after production synthetic acceptance.
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
  The model writes a concise answer and grounded explanation. Deterministic checks
  require lexical support, atomic wording, plain learner-visible text and topical
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
- **Prevention:** Do not assume `uv sync` installs Poetry-only dependency metadata. Before API test work, use the maintained root `.venv` and verify it contains the packages declared by `apps/api/pyproject.toml`, or first migrate the API package to an explicitly supported dependency-manager contract. Never fall back to a local Docker/PostgreSQL database for Kamilya dev when the canonical Supabase dev path is required.

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
- **Vercel recurrence:** A READY deployment in the dev project does not prove the
  custom production alias moved. Before and after a frontend rollout, resolve
  `app.kml.kz` to its actual Vercel project and deployment, then verify that
  deployment's exact Git commit. On 2026-08-26 the owning production project was
  `web`, not `kamilya-lms-dev`.
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
