# Error and Recurrence Prevention Log

Current as of: 2026-08-21.

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

## AI-002 - Assessment retry lost source and free-form citation weakened grounding

- Date: 2026-08-20.
- Symptom: initial disposable course produced two JSON/HTTP/REST questions. Later
  fail-closed runs rejected altered quotes, schema descriptions with
  `MCQ count is 0`, answer paraphrases not verbatim in evidence, a question without
  a shared lexical stem, and colon-terminated incomplete evidence.
- Cause: original retry used prior output and lost lesson source. Later validation
  still required fragile verbatim quote and lexical-prefix reproduction.
- Fix: rebuild every retry from immutable lesson, never raw prior output. Server
  creates bounded `E01...E24` evidence from the same 8000-character source; model
  selects `source_quote_id`; server owns quote, sole correct answer, and explanation.
  Require source terms; reject unsupported JSON/HTTP/REST/API/schema/format terms and
  evidence-matching distractors. Use deterministic client at temperature `0.2`,
  server-owned title, no response-body logging, provider
  `response_format=json_schema`, lexical fallback wording, incomplete-fragment
  exclusion, and deterministic Markdown stripping.
- Verification: unit suite `267 passed`; focused assessment/failover/release tests
  passed. Production Qwen without structured output returned schema keys and
  `mcq=0`; with `json_schema`, first attempt returned exactly 5 MCQs and empty
  true/false/matching. Full production job awaits exact-commit release. Direct Qwen
  3.8 from VM126 remains unavailable and cannot enter free pool before network gate.
- Prevention: successful job and valid JSON are not quality evidence. Verify every
  question's source and run disposable production generation; retry must preserve
  source boundary and never learn from invalid output.

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
