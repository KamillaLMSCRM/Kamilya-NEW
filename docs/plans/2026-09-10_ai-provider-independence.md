# AI provider independence — execution graph

Owner: root orchestrator. Product owner: current user. Updated: 2026-09-10.
Baseline: course-approval-policy-readback worktree at 299481ec1518729bcec199e8aaa2fdfe5c74c1e3.
Main LMS and landing dirty work preserved; landing excluded. Four prior document-error UI paths retained and integrated only after review.
Contract: ../product/ai-provider-independence/EPIC_V1.md.

| Node | Writer | Dependencies | Status | Exit gate |
|---|---|---|---|---|
| KEYS | Root | none | DONE | Created through encrypted API; both API/worker resolve DB keys and auth HTTP200 on 2026-09-10 |
| DIRECT | Document worker | contract | LOCAL_VERIFIED | Implemented, negative tests and independent review complete; live E2E pending |
| BYOK | Provider worker | contract | LOCAL_DEV_VERIFIED | Implemented and real isolated migration/RLS passed |
| UI | Root | BYOK contract, DIRECT contract | LOCAL_VERIFIED |109files566tests and build passed; browser acceptance pending |
| TEST | Root/Test Runner | DIRECT,BYOK,UI | BLOCKED_EXTERNAL | Free-provider requests429/404; live browser/source-course journey not verified |
| RELEASE | Root/Release Runner | TEST | NOT_STARTED | Exact authorized package, applicable migration approval, CI/build/readback |

Approvals: owner explicitly authorizes production transfer of two existing keys; removal of unavailable embedding Qwen; generation independence; tenant-owned models; increased synthetic course/staff limits; canonical OpenRouter key with free models only. No billing tier change, paid OpenRouter fallback, real-customer test data, infrastructure change or blanket quota removal.
Synthetic fixture target: existing kamilya-production-smoke, exact identity + is_demo + marker verified before writes; max_users=10000, max_courses_per_month=1000. Keep safety concurrency/rate/file limits. Existing values read before update; test-created data cleaned without deleting the persistent fixture.
Production key operation: create only absent Voyage/Cohere via existing superadmin API; preserve existing keys. Rollback only IDs created by this operation after identity check. No forced document retry.
RUNTIME-DERIVED: production key IDs Voyage28241197-fa49-4690-8315-98b51ade7c39 and Cohereed253280-ab31-41a7-a375-b4dd10c8423e active. Independent remote readback SHA a2d20577124aff79babeb805f77c7d74b32563259ac113703020dd3f3c06ce69 confirms both readable in API/worker and provider auth200. No inference yet. Synthetic max_users20->10000, max_courses_per_month50->1000, exact demo marker/slug checked; original settings recorded here for rollback. Qwen removal remains code/release work, not complete.
Evidence: main deliverables/incidents/document-upload-20260909/provider-keys-20260910.md (authenticated local keys, production absent). Graph query resolved AI clients/ingestion/provenance; index Sept09 is navigation only, verify sources and update AST after patch.
Stop: unexpected ownership, missing migration/RLS proof, paid route, new external/data boundary, stale runtime; preserve state and record root decision before resuming.

## In-progress verification — 2026-09-10

- BYOK worker: 48 focused tests passed; compileall and owned Ruff checks passed. Root review requested fixes for provider-switch key reuse, dimensions propagation, embedding free-router validation, and validation-error key echo. These findings are not accepted as release-ready until fixed and rechecked.
- Root: admin UI/API/error tests 11 passed; new admin HTTP boundary tests 5 passed; quiz draft routes/prompt tests22 passed plus tenant factory forwarding1 passed. New tenant-admin UI TypeScript and focused ESLint passed. Not browser acceptance.
- Existing quiz modules Ruff reports60 legacy findings; no quality gate claim until baseline comparison. No unrelated cleanup.
- OpenRouter authenticated key endpoint200/free tier; catalog21 zero-price generation and3 embedding models. Synthetic gemma generation429; nvidia embedding404. Bounded alternate Liquid generation/embedding each404 with explicit privacy-policy/no-endpoints flags. All requests forced max_price=0, allow_fallbacks=false, data_collection=deny. No successful free inference; no privacy/billing settings changed. Do not report functional E2E or zero measured usage without successful usage readback.
- No new app production deployment, migration0157, commit or push performed by this work packet.

### DEV database verification

Actual0157 applied to a disposable Supabase DEV schema, checked with the canonical separate `DATABASE_URL` lms_app connection (not owner-side SET ROLE). Runtime reports non-superuser/non-BYPASSRLS; own-tenant CRUD passes; missing-context read and cross-tenant read/insert/update/delete denied. Cross-tenant insert specifically checks SQLSTATE42501. Public migration revision unchanged. Owned temporary schema removed and absence read back.

Final check timestamp:2026-09-10T02:40:51.989973Z. Migration SHA256:0ff71293dddecd3bfa2767e01244329bdc5eb31a6bf961b5da7c522a3851ad83. Disposable schema digest:1d3f89f70d3ec6c2d62c2f913b61bdc9ffc601fd7f8b0e535bb1292e60445ff6. Script:scripts/ops/tenant_ai_providers_dev_gate.py.

Earlier owner-side SET ROLE attempts correctly failed42501 and cleaned their owned schemas; this Supabase limitation and the separate runtime connection procedure were already documented in ERRORS.md and learning_insights_dev_check.py. No role memberships or shared-schema objects were changed.

### Contract integration decisions

- `output_dimensions` is reserved/null-only for V1; unsupported values are rejected server-side and no nonfunctional dimensions field is shown in the admin UI. Native vector dimensions/provenance remain controlled by the existing embedding adapter.
- New course admission uses `analysis_mode=direct_source`. The original-file corpus supplies chunk/language metadata; no indexed metadata is substituted. An unverified multi-source set requires a shared learning goal and is never described as semantically compatible or incompatible.
- Frontend full suite after integration:109files/566tests PASS. This is automated regression evidence, not browser acceptance or real-provider E2E.
- Native local Next.js15.5.23 production build PASS (63pages); nothing built on CT137/proxy, nothing deployed.
- Combined backend targeted suite115PASS; provenance/assessment/failover suite91PASS (overlapping suites, do not sum as unique tests). Five database-free AI-COURSE-01 gates PASS; real document-operation/provider journey remains unverified.
- Canonical Python baseline PASS:ruff1088/mypy2353, no increased allowed baseline. Root independently verified missing key/provider-switch constraints, HTTP roles/secret-safe responses, direct original admission, quiz tenant factory forwarding, OpenRouter routing guards on actual embedding payload. Final independent direct-source review pending.

Final local/DEV handoff:docs/product/ai-provider-independence/VERIFICATION_2026-09-10.md. Updated combined API suite163PASS; independent review finding (conversion endpoint overload) fixed with explicit verified-principal rate limits and fail-closed limiter, reviewed accepted. Official OpenRouter free router also returned429; do not retry indefinitely. Runtime acceptance remains blocked; no production code release claim.

### Owner-authorized DeepSeek follow-up, 2026-09-10

Owner now authorizes the existing DeepSeek key for test generation when OpenRouter is unavailable. This updates test-provider authority only, not production deployment or tenant settings. Live provider calls succeeded; the strict course/three-question content acceptance failed on grounding/answer-quality recovery. Full persistence/browser acceptance remains unverified.

Root and two reused agents repaired hard-bounded document chunking and bounded unordered-list evidence context. Combined70focused tests and five separate database-free journey checks pass (overlapping). Actual approved Plus Excel was downloaded read-only and reference-chunked in memory into1,000 chunks of at most1,000characters with complete non-whitespace source reconstruction; no customer content was sent to an LLM or DEV DB in this follow-up.

New release-blocking regression: `test_direct_source_catalog_coverage.py` fails because first20,000characters omit middle/tail catalog topics. Next implementation must address whole-source coverage and remaining question-quality failures before a new live/database/browser acceptance. Do not call a sampled or two-question recovery result a full requested course success. Detailed evidence and provider-call/token totals are appended to `docs/product/ai-provider-independence/VERIFICATION_2026-09-10.md`.

### Owner ASUS refinement and root acceptance, 2026-09-10

The owner's new route supersedes old-Qwen removal for embeddings only:
ASUS `Qwen/Qwen3-Embedding-8B` on `10.66.66.15:8001/v1` first, then configured
Voyage/Cohere. Documents raw; exact English instruction on Qwen queries only;
L2 normalization and exact embedding-space provenance. Hooke (terra/medium)
implemented, root reviewed response-index and unrelated-provider input-limit
corrections. Root65 embedding/failover/provenance tests pass. Live candidate
adapter on the workstation passes synthetic three-document retrieval in2.92s.
VM126 documents-worker access is blocked by timeout; route selects the LAN
gateway192.168.1.1. No infrastructure or deployment change is authorized by this
diagnostic result.

Whole-source map replaces the original failing catalog regression; independent
review confirmed1000 source IDs covered in order but raised output-token and
untrusted-metadata/JSON issues. Banach (sol/high) owns their bounded repair;
root owns final acceptance. Root's assessment retry numbering/null-options fix
passes29 tests and Hooke's independent read-only review.

Remaining gates: finish map review; integrate/verify embedding-first selection
with a compatible active index and whole-source DIRECT fallback; approved
worker-to-ASUS connectivity; deployed synthetic persisted course/quiz/browser
acceptance; exact separately authorized production release. No global semantic
coverage/quality improvement percentage or completed production journey claim.

Final increment: root107 combined focused tests and5 separate database-free
journey checks pass. Map output cap now reaches actual provider request via a
validated downward per-call override; strict JSON and metadata boundaries are
implemented/reviewed. Those map-review findings are closed locally, not the
remaining network / full deployed journey / release gates above.

### Owner release authorization and acceptance refresh — 2026-09-10

Owner: persist the verified ASUS route repair, quick test, then release the product
changes; explicitly check visibility of tenant-admin own-model settings. This
supersedes the earlier NOT_AUTHORIZED production state, not the required gates.
API/migration0157 precedes native CT137 application frontend. Landing, mail,
billing tiers, proxy compute, customer data and other dirty work remain excluded.

| Node | Writer / reviewer | Current state | Remaining gate |
|---|---|---|---|
| ASUS route | Root artifact / existing ASUS owner review+execution | IN_REVIEW | Permanently remove only dead peerB .15/32 assignment on gx10-a721; preserve peers/keys/interfaces/services; exact config backup and watchdog |
| Tenant-admin UI | Root / Parfit luna-medium | LOCAL_VERIFIED | Fresh13 tests pass; files absent from HEAD explain deployed invisibility; real active-admin browser test remains |
| Semantic selection | Parfit / root | IN_PROGRESS | Whole-source architect retained; compatible embedding retrieval for lesson evidence, original-source fallback; no unsafe centroid admission |
| Assessment repair | Root | IN_PROGRESS | Live7-call test returned2/3 questions in19.87s; no quality weakening; actionable option-length feedback regression red then green |
| Product release | Root / Test Runner / Release Runner | WAITING_GATES | Exact committed scope, journey, CI/version/0157/rollback and production readback |

BYOK V1 remains generation of courses/tests plus document embeddings. Existing
editor/learner assistants and HR/JD generation are not silently added to this
release scope. UI active-admin and API scoped-superadmin conventions are deliberate.
The accepted EPIC is not rewritten; the semantic selection refinement is recorded
as an owner-requested addendum after independent review.

The earlier runtime-only ASUS test succeeded and restored the original config.
Persistent repair is not yet applied. Production VM126 still requires a verified
secure route to the new endpoint; workstation/ASUS gateway reachability alone is
not that proof. Do not repoint the unauthenticated legacy public embedding ingress.

Outdated artifact proposal, awaiting owner approval: production-deploy skill still
describes Vercel production. The newer canonical CT137 frontend runbook governs
this release; no skill text was changed without approval.

### Current stop and safe handoff

- ASUS permanent artifact d0d2038436bbfd893fd60a85046445c14facb2faec09975cb4069bc3277cf4ca
  stopped before any mutation/state creation. Read-only diagnostic variant
  d09d6fbac12b18d4368f153a5e4e76ed00c22fc792cb1195a25ec8f139b936a6
  identified exact guard: wg0.conf root:root mode0644, not private. Config remains
  SHA93d8763fc19bcfb927a18dbd4cfa94ceb9abb589c76668dd35913404a14d6a8f;
  original peers/services preserved, transferred scripts/pyc removed, no watchdog.
  Tightening this credential-bearing file to0600 needs owner approval beyond
  the exact AllowedIPs-only operation. Do not retry old immutable artifacts.
- Root wired trusted tenant_id into the direct writer. Fresh24 selector/writer/
  pipeline tests pass and focused Ruff passes. Additional144 focused API tests,
  seven pipeline/persistence unit tests and five database-free journey checks
  pass (overlap; not additive unique totals). Full DB/provider/browser not proven.
- Assessment option-length feedback and recovery cardinality/dedup regressions
  are red-then-green. Latest bounded live test:19.41seconds,7requests,3questions,
  prompt/completion18534/3872; automated content-only PASS, but root HUMAN_REVIEW
  rejects two paraphrased questions testing the same fact. Do not advertise full
  acceptance or repeat live generation without a targeted repair. Parfit has
  read-only diagnosis scope for the remaining duplicate-fact gap.
- Four bounded live synthetic runs this turn: provider reported prompt71232 /
  completion14996 tokens,28requests. No saved course, customer data or invitations.
- Independent public readback still API0.3.1/SHA299481ec1518729bcec199e8aaa2fdfe5c74c1e3,
  frontend healthze463527cd8f5e67e987c44d8d769f337714bd25f, HTTP200 each.
  New BYOK page/API/migration remain uncommitted/unreleased. Migration0157 hash
  still matches the earlier isolated DEV evidence; shared PROD schema not changed.
- Existing Render DEV metadata:free/not_suspended, deployment2578f0eceac45f46980263fe27de15980c793f31,
  no DATABASE_URL/CELERY_BROKER_URL. Do not treat that deployment as a usable
  candidate worker journey, reactivate paid capacity or alter its plan.
- Release verdict remains NO_GO: permission gate above, secure VM126-to-new-ASUS
  route, duplicate-fact quality repair and full persisted/browser acceptance.
  No commit, push, production release, migration or model gateway change this turn.

Resume review notes: Parfit proposes same validated evidence ID + normalized
correct-answer dedupe in both full-set validation and recovery. Existing CaseN
fixtures reuse one fact and need realistic distinct-fact fixtures, not weakened
assertions. Review is a proposal, not an implemented or general semantic guarantee.
Root final selector review also flagged the new writer total-budget rejection:
legacy lexical selection can overshoot a per-document chunk boundary; apply the
existing bounded round-robin selector to the fallback before rejecting, retaining
every requested document. Add a large lexical-source regression before acceptance.
These local findings must close before release; do not treat the23/24 focused
selector passes as whole-source production readiness.

### Release preparation refresh — 2026-09-10

Owner approved the exact0600 correction and continuation to production.
ASUS peer repair executed once with separate owner-agent runtime readback:
config0600/SHA23fbe0d5d5002e6c805646b2364c35327ca84ff0c7064187b7d6554feed7b344,
B assignment empty, A/addresses/old models unchanged, new embedding4096finite,
watchdog absent. Private rollback backup retained. No public ingress/VM126 change.

Local findings closed: root added a red-then-green large lexical fallback test
and bounded whole-chunk selection; Parfit independently reviewed it. Parfit
luna/medium implemented evidence+answer fact dedupe with realistic fixtures;
root reviewed validation and recovery. Fresh unit suite1122passes; separate124
AI/provider/API tests pass (overlapping). Web109files566tests, typecheck/lint,
Python baseline1088Ruff/2345mypy, tenant gate295queries0violations and release
contract all pass. A missing mandatory field in two newly added journal entries
was corrected without weakening the journal gate.

One final live synthetic DeepSeek content run:19.49seconds,7requests,
prompt18383/completion4007tokens,1lesson/3questions on distinct source facts.
The previous repeated-fact finding no longer reproduces in this sample. One
distractor has awkward Russian wording; generated content remains a draft for
human review. This is content-only evidence, not database/browser acceptance.

Prepared product version0.4.0 and client-facing release notes. No tag or deployed
version is inferred from local files. Feynman terra/medium owns only the new
opt-in isolated content-persistence gate and its local contract tests; external
execution requires root review. Those unfinished operational files are excluded
from the first product commit.

Fresh canonical restricted CT137 readback: webkml/kamilya-admin, service started,
old frontend e463527cd8f5e67e987c44d8d769f337714bd25f,2802032KiB free;
`/usr/local/sbin/kamilya-web-deploy` absent. Never repurpose the landing helper,
build on the1GiB frontend host, or silently broaden SSH/doas privileges.
Root needs the exact controlled web-helper bootstrap/recovery approval before
that path can release the frontend. Full persistence/browser, current-schema
restore/rollback and exact CI/deployment readbacks remain independent gates.

New ASUS production authentication also remains separate: existing cloudflared
ingress points at old localhost8001 without local auth, supervision unresolved.
Do not repoint it blindly or imply the new Qwen is reachable from VM126.
