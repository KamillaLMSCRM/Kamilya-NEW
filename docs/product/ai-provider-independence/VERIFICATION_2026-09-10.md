# AI provider independence — verification and remaining gates

Date:2026-09-10. Base:299481ec1518729bcec199e8aaa2fdfe5c74c1e3. Scope:LMS only; unrelated main/landing edits preserved.

Latest refresh: local v0.4.0 preparation, not production. Unit1122PASS;
separate124focusedPASS; frontend566PASS; typecheck/lintPASS;
Pythonbaseline1088/2345PASS; tenant295queries/0violations; release-contractPASS.
Final synthetic DeepSeek content-only run19.49s/7calls/1lesson/3distinct questions,
prompt18383/completion4007. Whole-chunk source-budget and repeated-fact regressions
red then green, independent writer/root review complete. Full persisted/browser
journey and exact CI/release not implied. ASUS local permanent route accepted;
secure VM126 route and CT137 missing web-helper privilege gate remain open.
See the latest dated section in the existing plan for exact ownership/boundaries.

## Production changes completed

- Existing Voyage/Cohere keys activated through the production encrypted provider-key API. Independent API and document-worker readback confirmed usable DB-backed keys; provider authentication returned200. No key values are recorded here. Activation script and sanitized operational evidence remain in canonical `deliverables/incidents/document-upload-20260909/`.
- Only persistent synthetic tenant83552ce6-8058-4561-abe3-cfbda14e030a, slug`kamilya-production-smoke`, is_demo=true, approved marker verified: staff20→10000; monthly courses50→1000. Independent readback passed. No customer quota, billing plan, or concurrency/file/security cap changed.
- No new app code or0157 deployed to production. Qwen remains in the old deployed embedding fallback until code release; generation routing was not changed.

## Implemented locally

- Tenant-admin own-provider settings, separate generation/embedding purposes, encrypted write-only keys, server-owned official endpoints, tenant-scoped resolution, safe validation/readback, explicit override failing closed rather than switching to platform keys.
- Provider switches require a fresh key. OpenRouter free-only guards are tested on actual chat/embedding payload paths; paid automatic fallback is not permitted. V1 does not expose unsupported dimensions configuration.
- New course admission/pipeline reads every selected active tenant-owned original, verifies canonical SHA, converts bounded content and generates source-grounded course/assessment without calling embeddings or pgvector. Original-file failures remain failures; no fake vectors, readiness, semantic score or topic compatibility claim.
- Multiple unverified sources require a shared learning goal. Existing semantic retrieval/provenance behavior remains separate. Quiz draft and module/lesson generation factories receive trusted tenant identity.
- Source-validation endpoint has verified-principal limits6/minute,60/hour,3/10seconds and fails closed when its limiter is unavailable. This closes the independent review's repeated-conversion overload finding.

## Verified

| Gate | Result |
|---|---|
| Combined focused API tests, including direct negative paths and rate limits |163passed |
| Separate provenance/assessment/failover suite |91passed; overlapping, not an additive unique total |
| Database-free AI-COURSE-01 required tests |5passed |
| Full frontend regression suite |109files,566tests passed |
| TypeScript + focused ESLint |Passed |
| Native local Next.js15.5.23 production build |Passed;63static pages; no remote build/deploy |
| Canonical Python quality baseline |Passed:ruff1088,mypy2353; baseline not loosened |
| Independent direct-source review |Overload finding fixed and reviewed; no remaining finding in reviewed scope |
| Actual migration0157 + RLS in isolated Supabase DEV schema |Passed; real lms_app connection, non-superuser/NOBYPASS; own CRUD positive, cross read/insert/update/delete negative, missing-context read negative |
| DEV cleanup |Owned schema absent after cleanup; shared public revision unchanged |

Final DB check:2026-09-10T02:40:51.989973Z. Migration SHA256:`0ff71293dddecd3bfa2767e01244329bdc5eb31a6bf961b5da7c522a3851ad83`. Temporary schema digest:`1d3f89f70d3ec6c2d62c2f913b61bdc9ffc601fd7f8b0e535bb1292e60445ff6`. Earlier owner-side SET ROLE attempts failed42501 and cleaned their own schemas; canonical separate runtime credentials resolved the gate without altering any role membership.

## Not verified / release blockers

- **Real free-provider inference did not succeed.** Authenticated OpenRouter key/catalog checks200. Gemma free generation returned429, including one bounded retry. Liquid free generation and Liquid/Nvidia free embeddings returned404; classified alternate responses explicitly matched privacy-policy/no-endpoints errors. Official `openrouter/free` router also returned429 under zero-price/no-fallback/data-collection-deny controls. The exact origin/window of429 was not established; do not claim every free model is unavailable or that account credit is exhausted. No paid fallback or privacy/account change was made.
- **Full browser acceptance and database-backed source→course→quiz→review flow are NOT VERIFIED.** Unit fixtures, HTTP adapter tests and isolated migration/RLS checks are not substitutes for this journey.
- A shared DEV deployment/migration and ultimately a separate exact production release packet still require their applicable approval gates. Local build and isolated migration checks do not constitute deployment.
- No new commit/push in this work packet. Existing dirty changes remain preserved. Do not deploy this mixed worktree blindly.

## Next controlled steps

1. Obtain a usable free OpenRouter route/key under the existing privacy policy; do not enable paid routes or weaken data handling without separate owner approval.
2. Deploy the reviewed package into the approved test contour, apply0157 under the appropriate approval, then perform actual browser checks as synthetic tenant admin and methodologist: save/read/update/delete both model settings; no key echo; create a course from an unindexed synthetic source; inspect lessons/questions; negative corrupted source and cancellation; confirm cleanup/no invitations.
3. Only after that journey passes: assemble exact API→migration→frontend release, obtain required production approval and perform normal release/readback gates.

## Follow-up: owner-authorized DeepSeek tests, 2026-09-10 04:33 UTC

This dated update supersedes the earlier need to wait for a working free OpenRouter route **for test generation only**. The owner explicitly authorized the existing DeepSeek key if OpenRouter fails. No tenant-provider setting, production model chain, billing configuration, deployment, or migration was changed. DeepSeek does not replace embeddings.

### Actual provider and content result — NOT a passing full journey

- The existing local key successfully called the official DeepSeek endpoint. Requested model: `deepseek-v4-flash`; returned model identifier: `deepseek-flash`. Source: a synthetic 491-character instruction, not customer data.
- The candidate's actual `build_direct_source_corpus`, `run_direct_architect`, `write_direct_course`, and `generate_lesson_assessment` functions were exercised without embeddings or a database. Structure and lesson requests typically completed in roughly 2–4 seconds each.
- The strict one-module/one-lesson/three-question acceptance **failed**. Depending on the attempt, assessment recovery returned only two questions or reached the harness's eight-request limit. Successful HTTP responses are not successful course acceptance.
- Evidence and answer-quality checks were **not weakened**. Remaining failures include incomplete contextual evidence, correct-answer length cues, and implausible distractors. Numbered lists and context blocks beyond the 280-character evidence limit are not covered by the bounded unordered-list fix below.
- Five bounded diagnostic/pre-fix/post-fix runs made 34 successful provider requests: reported prompt tokens 68,426 and completion tokens 18,123. These are aggregate provider-reported token counters, not subscription usage or monetary cost. No saved complete course resulted. Further repeated live attempts were stopped.

### Local repairs and independent checks

- `DocumentChunker` now enforces its size bound for oversized paragraphs/table rows/cells. Root review caught and rejected an intermediate default-overlap infinite loop; the corrected implementation was independently retested, including the actual Excel source below.
- Bounded unordered Markdown lists now retain their preceding colon-introducer as exact contiguous evidence. Existing grounding checks, limits, retry policy and question-quality checks remain unchanged. This repair alone did not make live question acceptance green.
- Root combined focused suite: **70 passed**. Separate five database-free `AI-COURSE-01` checks: **5 passed**, overlapping the focused suite; do not sum them as unique tests. Focused Ruff and `git diff --check` passed. The database-backed worker journey was not rerun.
- New adversarial regression `test_direct_source_catalog_coverage.py`: **1 failed**, intentionally retained as an unresolved release blocker, not marked xfail or weakened. With 636,000 source characters, the architect sees the head topic but not middle/tail topics. The writer can retrieve later chunks only if the lesson query already names those topics. Document-ID inclusion is not complete topic coverage.

### Actual Plus Excel — read-only reference check

- Reused the existing exact health/tenant/source-SHA guarded download procedure. Approved original: 103,616 bytes, SHA256 `00783869f407800c94917053d84430091424de2cf36108d4e972540cf8bc52be`.
- Local read-only OOXML reference extraction: 310 nonempty rows, 2,183 nonempty cells, 636,490 rendered cell-value characters, 644,366 Markdown characters. These representation counts differ from the earlier raw-OOXML/production-converter counts; this is not a Docling equivalence claim.
- Corrected default chunker: **1,000 chunks, each at most 1,000 characters**. Ordered reconstruction covered all non-whitespace reference-source text. This proves bounded reference chunking, **not** complete course coverage or the production conversion/upload path.
- Workbook/customer content stayed in memory and was not sent to DeepSeek, OpenRouter, embeddings, or a DEV database. No customer objects/limits were modified; no fixture course/document was created in this follow-up. Normal authenticated access/audit events may exist.

### Remaining acceptance work

1. Replace prefix-only architecture context with explicit whole-source topic coverage and bounded provenance; do not label stratified sampling as complete coverage.
2. Resolve remaining assessment-context/answer-quality failures using saved synthetic regression cases, then perform one instrumented live acceptance rather than repeated blind reruns.
3. After local gates pass, run the approved deployed test-tenant upload → source → persisted course → questions → browser review → cleanup journey. It remains NOT VERIFIED. Production code and migration0157 remain unchanged.

Operational harnesses are local in the canonical incident folder: `deepseek-direct-content-smoke.py` (dry-run default, synthetic only), `excel-reference-chunk-check.py` (dry-run default, guarded read-only actual-source reference). They are not a production release package.

## ASUS embedding refinement — 2026-09-10

Owner-requested candidate routing: dedicated `Qwen/Qwen3-Embedding-8B` at
`http://10.66.66.15:8001/v1`, then configured Voyage, then configured Cohere.
Chat/generation provider order is unchanged. Explicit tenant overrides remain
isolated and do not silently acquire platform credentials.

- Documents remain raw. Only ASUS Qwen queries receive exactly
  `Instruct: Given a user question, retrieve relevant passages that answer the question`
  followed by a newline and `Query: {query}`. Voyage/Cohere retain native input types.
- Qwen vectors are L2-normalized; invalid/zero vectors are rejected. Indexed
  OpenAI-compatible responses are reordered and validated before attachment to
  source fragments. Fully unindexed legacy responses retain response order;
  mixed/duplicate/out-of-range indices are rejected.
- Qwen is bounded to 3-second connect / 12-second request timeouts with no retries;
  requests contain at most 32 inputs. Its 8192-byte per-input safety bound includes
  the query prefix. This is deliberately conservative, not a claim that bytes
  equal the server's advertised 8192 tokens. Source text is not silently truncated.
- Embedding provenance includes the query/L2 protocol revision. Existing SQL
  filters active document/source revision, provider, model, preprocessing revision
  and dimensions, then uses cosine distance. Switching provider does not make its
  vectors compatible with a previously indexed provider's documents.

### Live synthetic adapter check

`asus-embedding-probe.py --adapter` used the candidate's actual EmbeddingsClient
from this workstation, three synthetic Russian documents and one Russian query.
PASS: advertised context8192, dimensions4096, four vector norms within1e-6 of1,
correct top document. Scores:0.750115 /0.308469 /0.182558. Two embedding calls took
2.92seconds total, excluding model discovery. No customer material, database,
provider configuration or network configuration was changed. The first harness
attempt failed with an empty placeholder key; using the same non-secret
`not-needed` placeholder as the actual factory passed. This is not an authentication
change and no real key was supplied.

The earlier VM126 documents-worker probe failed with URLError before successful
inference. Production-worker reachability remains NOT VERIFIED; workstation
success does not close it. No production deployment or shared migration0157 in
this follow-up. Full persisted Excel-to-course/quiz/browser acceptance remains
NOT VERIFIED. The lost DeepSeek shell-session result is not counted as a pass,
and no additional DeepSeek run was started during this recovery.

### Additional local review

Root independently ran 100 focused tests covering embeddings/failover, vector
provenance/reindex storage, direct source/topic mapping, and assessment context.
This passed before the final response-index correction and map-review follow-up;
the final combined run must be recorded separately. The assessment retry repair
now preserves original question numbers even when preceding entries are malformed,
and accepts null options as an empty rejected example rather than crashing.
Its red case failed with TypeError before repair; 29 focused assessment tests pass
after repair. No grounding or question-quality threshold was lowered.

Independent map review reproduced1000 ordered source IDs with no missing chunks
but found two pending corrections: enforce the output-token bound at the actual
provider request, and delimit source-derived metadata / strictly parse complete
JSON responses. Neither full semantic completeness nor production readiness is
implied by mechanical source-ID coverage.

### Production-worker network classification

Second immutable diagnostic script SHA256
`4ba19747eb5de84f856bd98f1f8ff04c76a69f01560be3ec5c1402bfba7ca22e`
ran through the canonical VM126 helper. VM126 selects `ens18` via
`192.168.1.1` for `10.66.66.15`. The existing active documents worker's
`/v1/models` request timed out (`URLError` wrapping `TimeoutError`) before
embedding inference. This establishes a worker-to-ASUS reachability blocker,
not a defective model or proof of the precise gateway/firewall fault. No route,
WireGuard peer, firewall rule or service was changed. Repeating the same request
was stopped; network configuration requires a reviewed route/return-path and
appropriate explicit approval.

Root post-correction embedding/failover/provenance suite: **65 passed**.
This includes the final response-index and Qwen-only input-bound corrections.

### Final local integration check for this increment

Root combined suite after map/assessment/embedding corrections: **107 passed**
(the ten named focused files used above). Separate five database-free
AI-COURSE-01 checks: **5 passed**, not a complete DB-backed journey.
Map responses now carry a1024-token per-call cap, and the actual LLMClient
request test proves it reaches the payload without changing client defaults.
All source-derived map metadata is inside escaped untrusted boundaries; response
parsing requires standalone JSON. Root inspected these changes and the new
regressions. The two previously reported local map-review findings are resolved;
network, persistence/browser and release gates remain open.

## Release-request acceptance refresh

The owner authorized permanent ASUS route repair, quick testing and production
release. This does not turn incomplete gates into PASS. Current release decision:
**NO_GO**, no commit/push/deployment/shared migration performed in this turn.

- Root combined focused backend suite144PASS; post-review semantic selector,
  direct writer and trusted-tenant pipeline seam24PASS; separate existing pipeline
  suite7PASS; five DB-free journey checksPASS. These overlap, not additive totals.
  Focused Ruff and git diff --checkPASS. Independent tenant-admin UI13PASS.
- New writer prefers exact-space/source/tenant-bound semantic excerpts and falls
  back to verified original corpus. Optional offline seam retained. Whole-source
  architect/topic map unchanged. Real provider/index/browser acceptance pending.
- Assessment regressions reproduce missing length measurements, premature compact
  partial return and uncapped recovery. Local fixes pass30 assessment tests.
  Latest bounded synthetic DeepSeek run returned3questions in19.41s/7requests,
  but HUMAN_REVIEW_FAIL: two differently worded questions ask the same transfer
  fact. Automated PASS_CONTENT_ONLY is **not accepted** as complete quality proof.
  Four controlled runs total28requests, provider prompt71232/completion14996;
  no further blind live runs, no real data, no persisted course or invitations.
- Production readback remains API0.3.1 SHA299481ec1518729bcec199e8aaa2fdfe5c74c1e3;
  frontend /healthz=e463527cd8f5e67e987c44d8d769f337714bd25f; eachHTTP200.
  BYOK routes/page/0157 remain local, explaining missing production UI.
- ASUS permanent operation stopped **before mutation**. Separate read-only
  preflight identified root:root mode0644 on `/etc/wireguard/wg0.conf` as the
  exact gate. Owner approval for0600 tightening is required before continuation.
  Config/peers/services unchanged; transferred scripts/pyc cleaned; no watchdog.
  Full sanitized hashes/ownership are in the existing execution plan and main
  incident `asus-existing-route-20260910.md`.
- Old public embedding ingress remains unauthenticated and was not repointed.
  A secure VM126-to-new-ASUS path still must be established and verified before
  claiming that the new embedding service operates in production.
