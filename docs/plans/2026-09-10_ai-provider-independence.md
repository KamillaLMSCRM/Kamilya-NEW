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

### Git publication / exact external gates

Product-only69-file commit2c76e84235b3b5ce6af0d4a48be847443714bce0 published
to fix/course-approval-policy-readback-20260909 at07:08:03Z and master at07:09:21Z;
both independently read back with canonical KamillaLMSCRM root-env/gh credential
path, fast-forward only. Sanitized push receipts saved under owner-authorized
memory notes. PR creation was denied by the project token; no retry, credential
fallback or permission mutation. Existing owner-approved direct master path used.
CI34448558428: six jobs passed at latest readback; backend coverage job still
running. No final CI success, release tag, GitHub Release or deployment claimed.
Fresh local production frontend build passes63pages including/admin/settings/ai.
Graph AST refresh15882nodes/38206edges; source query confirms currentwriterL653.

Fresh CT125 privileged read-only backup report: live0156, backup timer active,
20260910T022423Z encrypted archive checksum valid/mode0600. Latest signed restore
report remains20260907T091821Z for0155, not0156. The previous no-restore exception
was bound to the0.3.1 no-migration release and is not reused for0157.
Need exact owner approval for disposable restore DB
`kamilya_ai040_restore_20260910` and its cleanup before migration.

Need exact CT137 restricted web-helper bootstrap approval; no arbitrary shell
grant, no proxy compute, no build on CT137. Any temporary console-mode change
must restore original state and needs its bounded restart/downtime authorization.
For new ASUS public path, propose authenticated/asus/v1 on existing embedding
hostname, retaining legacy paths, using existing capacity only. No such ingress,
credential, cloudflared supervision or VM126 setting was changed.

Feynman returned two local untracked persistence-runner files with5contracttests;
root has NOT accepted or executed them. Its suggested2-choice English fixture
is not the actual Russian4-choice live output and must not replace it in evidence.
Worker closed; files preserved outside the committed product packet. Resume by
reviewing actual schema safety/DDL, using faithful synthetic output and explicit
evidence labels. No DB/public/queue/browser execution occurred in that sidecar.

### Owner ordering 2026-09-10: customer release first

OWNER-CONFIRMED current instruction: deploy the approved product changes, prove
the real production customer workflow, then perform the three proposed follow-ups
(fresh restore drill, permanent CT137 web helper, authenticated ASUS ingress).
For this exact 0.4.0 / 2c76e84235b3b5ce6af0d4a48be847443714bce0 / 0157 release,
the restore drill is deferred by the owner; it is NOT reported as passed. The
fresh encrypted backup/checksum and installed migration backup gate remain in
place. No gate implementation, billing, credentials, or access privileges are
changed by this exception. Existing Voyage/Cohere/DeepSeek paths permit release
without the deferred ASUS ingress.

Fresh readback: API and three workers remain healthy on299481ec, active blue,
image digest133f080fe6947ce2bfe24e75c0456f47dc28eb44fb4dc507bda51bebaccc622e.
CT137 restricted SSH works, frontend remains e463527c, 2802032KiB free,
/usr/local/sbin/kamilya-web-deploy absent. Direct canonical Proxmox connection
timed out before TLS; browser navigation was blocked by the browser client.
No console, privilege, reboot, service, or infrastructure mutation attempted.

CI34448558428 blocked this candidate: live GitHub log showed the first
test_document_compatibility_api failure at07:12:00Z and then no progress after
manager_feedback at07:12:12Z. Root cancelled this owned failed/hung run at07:28Z
to obtain logs. No successful CI or production release is claimed. The old
multi-document fixtures contain index rows but no verified original blobs and
expect index failure to forbid generation, contradicting the approved new
contract. Their concurrent-session override also fails to roll back on request
error, a potential test-only lock wait (production get_db does roll back).
Planck owns the two integration-test files and truthful in-memory blob fixture;
root owns CI fail-fast/15-minute bound and review. No application validator is
weakened. Fresh database-free direct-source/HTTP checks:33passed in4.89s.
Socrates prepares only off-host Alpine-compatible frontend build packaging, not
the deferred production helper. CT137 remains native Node/OpenRC without Docker.

### Production 0.4.0 released; real Excel acceptance found follow-up defects

OWNER-CONFIRMED Proxmox is unavailable to owner too; continue API independently.
CI34451635048 passed all7jobs for5b95a31662ea40762f04c9c3baad55a8d7b8e454.
Exact annotatedv0.4.0 tag and publishedGitHubRelease independently verified.
Protectedworkflow34452263315 / REL-AI040-20260910 deployed at07:56:53Z.
Fresh encrypted backup kamilya_staging_20260910T075632Z.dump.gpg checksumPASS0600;
restore drill remains explicitly OWNER-DEFERRED, never PASS.
Independent APIprivate/public and all3workers readback:0.4.0/5b95a316,activegreen,
image4749ab370702312c2c9bac5696e73d4355aa02284790f24ff857396c15d3b175,
allrunning/restarts0. CT125 independently0157,tenant_ai_providersRLS+FORCERLS,
lms_app nonsuper/noBYPASSRLS. Old133f080image retained; no rollback needed.
Readback script mainrepo deliverables/incidents/document-upload-20260909/
release040-postdeploy-readback.sh SHA79857fe7b14f1f154c0441819a121b2fd340473bdc9965fd7d9f9cd347f882f8.

Nativebundleworkflow34452404698 PASS LinuxAlpineNode20.20.2,exact5b95a316,
tarSHA3ed774888afccb15c1d40c7403edafe0240700c18912d1c8d4a13e6cdcad4bd6,
login+adminAIroutes200HTML in native runtime. Packaging required optionalpublic
directory creation; build-onlyfix5a7aff86 published separately. Not deployed:
CT137helper absent and canonicalProxmox unavailable; no permissions bypassed.

Production tenant-AI API CRUD acceptance PASS on exact syntheticfixture: admin200,
unauth401,methodologist403,invalidconfig422,write-onlykeynotreturned. Bothpurpose
configs createdDISABLED with synthetickeys,noinference; deletedandabsenceverified.

Real owner-approvedPlusExcel copied only to synthetictenant83552ce6-8058-4561-abe3-cfbda14e030a.
Customer documents unchanged. Ownedtestdoca1a0da10-2bfa-41da-ad73-69075fe0a901,
indexjob6aa8e348-dcb9-4300-99af-b69025462196. Fixturelimits10000users/1000courses;
is_demo temporarilyfalse underexactowner test-limit approval; MUSTrestoretrue.
Coursejob15bd05ed-255f-475b-b56b-1a03d89d02d6 accepted202withindexpending,failed
source_topic_map_batch_budget_exceeded. Exact runtime conversion646179chars,
932chunks/831890chunkchars/480headingchars,74batches. No coursecreated.
Source metadata repeated perchunk causedlimitoverhead. Rootred/green932synthetic
regression nowpasseswithbatch-localmetadatalegend,alltextandIDspreserved.
Real syntheticDeepSeek additionallyexposedoverlongsummarybudget; addedonebounded
repair onlyaftervalidschema/coverage,exactsourcegroupsretained,90s/3concurrency.
Two live40source/twobatchmapsPASS2.1s/2.22s. No customercontentinlocalLLMprobe.

Currenthotfix0.4.1 candidate3c0519310d2c435de740eb5aad098b07bf012b1f publishedmaster
andindependentremoteSHAverified08:16:43Z; exactpushreceiptsinowner-authorizedmemory.
1126unitPASSfromcandidate/apps/api; quality1088/2345PASS;21version/releasecontractsPASS.
An earlierunitinvocationfromreporootfailed3cwd-dependentmigrationfixturelookups;
correctcanonicalcwdre-runPASS,notproductdefects. LunaHelmholtzindependentreviewPASS,
correctedstalediff/test-gapclaimsagainstrootactualmulti-IDtest; agentclosed.
WaitinglatestCI beforev0.4.1tag/release/deploy(no-migration0157). Do notdeploy808b768a
intermediatecandidate; it lacksoverlongresponsefix. Customergo-aheadstillWITHHELD.
Afterhotfix: reuseexactownedExceltestdoc/hash,runrealcourse+questions,cleanupowned
objectsandrestorefixtureis_demo. Thenfrontendacceptanceonceauthorizedaccessreturns.

## 2026-09-10 08:35 UTC continuation

0.4.1 CI34454290773 PASS; tag v0.4.1 independently peeled to3c051931,
GitHubRelease published. Protected production run34454809016 SUCCESS,
releaseREL-AI041-20260910. Independent readback f98c44a3 script PASS:
API/all3workers3c051931 running/restarts0, private/public0.4.1healthy,
activeblue image sha256:317056d226a21a5d8be100ab9162336135e9fdcfb6b0c5ae9e47a3617e319303.
CT1250157 unchanged; previous4749ab image retained. No migration in hotfix.

Reused ownedExcel a1a0da10-2bfa-41da-ad73-69075fe0a901 nowembeddingSUCCESS.
Job d5575852-929e-47bc-940f-e458ad7f96a0 failed14s with
source_topic_map_invalid_response. NO coursecreated, customerunchanged,
customergo-aheadWITHHELD. LunaRawls01a08a73-e778-7113-8763-151a431155ac
investigates production-vs-synthetic LLM formatting read-only.

Native frontend build34454506724 PASS; manifest0.4.1/3c051931/musl/linuxx64,
archive155423605bytes SHA43b0cd1d311cdeaa77e566ffbacfe4408d7b10ab085651962c02a597f07fbc14.
Streamed toCT137 /home/kamilya-admin/incoming/frontend-native-3c0519310d2c435de740eb5aad098b07bf012b1f.tar.gz;
remotehashPASS, proxytransportonly/noarchivewrittenonproxy. NOT switched yet.

Owner explicitly now authorizes permanent restricted frontendhelper setup
and logged root into existingCT137ProxmoxChromeconsole. Root verifiedid0/webkml.
Installed distro python3.14.7 (previouslyabsent) as helperdependency, noDocker/build.
TerraPasteur01a08a72-7d26-7151-b9cd-f4f848b0edc2 owns new
infra/deploy/kamilya-web-deploy.py and scripts/ops/test_kamilya_web_deploy.py.
Root owns transport/bootstrap/production. Existingfrontend e463527c stillactive.
CLIProxmox old certificatepin mismatches currentendpoint; NOT bypassed/changed.
Browserauthorizedsession used. Required cleanupstillfixtureis_demoTRUE + ownedtestdoc.

## 2026-09-10 final native-deploy acceptance and remaining Excel failure

### Completed and verified

- API, all three workers and CT137 frontend now serve product 0.4.1 at exact
  `3c0519310d2c435de740eb5aad098b07bf012b1f`. Public app `/healthz` agrees.
- CT137 has root-owned `/usr/local/sbin/kamilya-web-deploy` (0750), SHA256
  `a6379cefe5e558fd9537f4144555d8776804c66b15823957402e01814d23291a`.
  Exact-command doas allows restricted deployment; generic root execution is denied.
  Actual frontend deployment and subsequent independent readback used SSH + doas,
  without Proxmox login or an interactive password. Proxy remained transport-only.
- Helper checks immutable archive/manifest snapshots, hashes, path/link safety,
  disk headroom, exact old SHA and new routes; retains the old release and includes
  rollback handling. Native CT137 helper tests: 16 PASS. No production rollback
  drill was performed; rollback-state coverage is a fixture test.
- Native Node runtime is 24.18.1; bundle was built with Node 20.20.2 musl.
  Runtime was not changed. Real health/UI checks pass, but version alignment remains
  a documented follow-up; do not claim matching build/runtime Node majors.
- Operational code, tests, transport CLI and runbook committed separately as
  `f46535ca4a2c485d63fcc16170b3bb8328b6e507`, pushed with KamillaLMSCRM through
  canonical process-local credentials; independent origin/master readback matches.
  CI 34458799808 completed SUCCESS, including native helper safety tests.
  This ops commit does not change the deployed product SHA above.
- Synthetic tenant admin UI displayed generation and embedding connection forms.
  Disabled dummy DeepSeek and Voyage configs saved, read back after re-entry, and
  did not expose stored keys. Native delete confirmation stalled browser control;
  exact owned configs were instead removed via guarded API, followed by empty-list
  readback (2 deleted, 0 remaining, 0 customer mutations). User refreshed the page.
- Fixture `83552ce6-8058-4561-abe3-cfbda14e030a` restored to `is_demo=true`,
  with independent DB readback PASS. Increased test limits retained. Restore script:
  `deliverables/incidents/document-upload-20260909/excel041-fixture-restore.sh`
  in the main repository, SHA256
  `a4fd3f54e32833f8ff9e06cffd7060c6628402d05be07c69ef4c3208e88e747c`.

### Not accepted: real large Excel course generation

- Owned Excel test document `a1a0da10-2bfa-41da-ad73-69075fe0a901` indexed
  successfully, but course job `d5575852-929e-47bc-940f-e458ad7f96a0` failed
  `source_topic_map_invalid_response`; no course was created.
- Full input: 932 chunks, 42 map batches. Three real initial batch probes produced
  valid JSON but too many topics per record. Initial prompt omitted parser limits.
- Three isolated full-input prompt-repair candidates subsequently failed:
  overview budget (10 calls / 10.55s), overview budget (51 calls / 53.07s), and
  invalid response (14 calls / 13.68s). No candidate code was installed in production.
- Experimental changes in `source_topic_map.py` and its unit test remain local and
  uncommitted. Their 21 unit passes are NOT real-document acceptance. Stop blind
  prompt tuning; next work requires diagnosing the exact rejected invariant and a
  robust bounded mapping design without losing source coverage.
- Owned source copy is retained in the synthetic tenant for ongoing diagnosis.
  Customer original document and settings were not modified. Customer go-ahead
  remains WITHHELD. Fresh restore drill remains owner-deferred, not passed.
- Helper and prompt-investigation subagents are closed; unrelated dirty work remains
  preserved. Permanent deployment procedure is in
  `docs/runbooks/ct137-native-frontend-deploy.md`.

## 2026-09-10 source-resilience implementation packet

Owner requested a detailed plan and implementation after the proposals. Active
contract: `docs/product/contract-modules/AI-SOURCE-RESILIENCE-01/MODULE_INDEX.md`.
Root owns mapper/caller integration and acceptance; Terra implemented the checkpoint
adapter, Luna/Terra provided independent reviews. All workers communicated in English
with narrow scopes and are closed. Token/cost counters unavailable, not zero.

### Plan and current status

| Step | Result / exit gate | Status |
|---|---|---|
| Reproduce exact failure class | red tests for9topics/>320chars +932source corpus | DONE; initial2FAIL captured |
| Separate extraction/overview | detailed map + all-topic compact rendering; no clipping | IMPLEMENTED |
| Assign provenance deterministically | server-owned batch IDs, explicit document ranges | IMPLEMENTED |
| Selective retry/checkpoints | one malformed-batch retry, scoped cache, bounds/cancellation | IMPLEMENTED; real Redis replay PASS |
| Neighbor/regression checks | unit, pipeline persistence/failover, quality and contracts | PASS as below |
| Representative map + architect | real owned Excel -> all932sources -> validated3modules/6lessons | PASS in isolated candidate process |
| Full saved course/assessment | actual texts/questions, DB readback and methodology UI | PASS staged candidate; normal queue smoke remains |
| Repeat fresh full run | independent result quality and total cold-run latency | NOT VERIFIED |
| Candidate release | commit/CI/exact-SHA deployment + production user flow | NOT PERFORMED |

### Source-derived changes

- Mapper protocol now returns exactly summary/topics for one deterministic batch;
  server attaches source IDs. Model-generated IDs/extra fields are never accepted.
- Output formatting faults have one full-source retry using a closed reason-code
  set. Auth/provider failures, cancellation and total deadline are not retried here.
- Detailed map cap8000chars/2048tokens, topics<=16x160chars, summary<=1600;
  independent overview28000chars remains under existing combined architect32000.
- Compact rendering omits summaries explicitly, never topics, and uses lossless
  inclusive source ranges with document mappings. Full records remain in checkpoint;
  original source corpus remains the lesson writer's grounding source.
- Same-job checkpoint namespace binds tenant/job/resolved route+generation options;
  batch digest covers protocol/prompt/text/revision/ordered chunk identities.
  Atomic Redis hash cap64fields, TTL1h, per-operation1s bound, outage circuit breaker,
  schema revalidation on every hit. No model/key info or cached text in user responses.
- Pipeline wires store lifecycle, clears on completion/cancellation, closes client;
  failure retention expires. Existing failed/terminal Celery jobs are NOT automatically
  reopened and a new UI-generated job does not reuse another job's checkpoints.
  Do not advertise cross-job or automatic worker-crash resume as completed.

### Actual feedback, not synthetic success substituted for acceptance

1. Detailed V1 real probe: coverage fault21calls/38.78s,17successful batches.
   Root changed protocol to server-owned IDs (MAP_ADDENDUM_V2).
2. Server-owned V2 mapped44batches; overview24000 limit still failed after55s.
3. Real Redis-backed attempt retained44validated batches; safe zero-inference
   readback counted501topics/23837chars,480unique/22967chars,23732summary chars.
   This proved24000 could not fit topics plus provenance. Root accepted28000
   overview allocation (OVERVIEW_BUDGET_ADDENDUM_V3), kept combined32000 cap.
4. Final exact candidate probe `source-resilience-map4.sh`, mainrepo deliverables
   incident directory, SHA256
   `225a914cdae64e9bb92364fc77b960bcbb221df59da4e1459d1fa4344426a20d`:
   all932sources,44records,overview27441chars,cache retrieval/replay0LLMcalls/0.43s;
   architect produced3modules/6lessons with1LLMcall,12.39s total. Exact document
   references validated. Redis TTL verified, owned key deleted/absence verified.
   Customer mutations0; courses_created0. This is NOT full-course generation speed.

### Verification and independent review

- Final `pytest tests/unit tests/test_ai_pipeline_existing_course.py
  tests/test_llm_failover.py -q`:1204PASS/5existing deprecation warnings/17.55s.
- Separate KB-RAG schema-contract fixture test:1PASS.
- Python quality baseline PASS: Ruff1088/mypy2345; no baseline increases.
- Release contracts PASS:155revisions/head0157, Celery registry, migration ownership,
  85unique sanitized error entries. This is not production migration/restore evidence.
- Root verified agent's64slot cache would collide; revised to atomic capped hash,
  regression proves64colliding-old-slot digests all retained and65th rejected.
- Independent review caught missing source/document association and chunk identity
  in cache digest; both fixed with regressions. Later suggested terminal schema errors
  was rejected by root: schema is formatting, both attempts reject extra fields and
  no model-owned provenance is accepted. Retry predicate made explicit/closed.
- Legacy prompt-specific tests were replaced with V3 interface regressions, not
  weakened grounding/coverage checks. Updated consumer fixture uses real V3 output.

No commit/push/deploy, migration, provider configuration, customer modification,
mail/invitation or publication occurred for this packet. Production still exact
3c051931/0.4.1 (guarded by each remote probe). Synthetic fixture stays is_demo=true;
owned Excel copy remains for full acceptance. All test checkpoint keys removed.
Root keeps client GO withheld until full saved-course/questions/browser acceptance.

Final AST refresh:16108nodes/38698edges. Multigraph diagnostics report no dangling,
missing-endpoint or exact-duplicate edges. Representative checkpoint query resolves
pipeline/store/test seams matching the accepted module map. Graph is undirected;
call direction was verified in source. Fourteen non-code/fixture inputs extracted
zero nodes, a retained index limitation, not evidence that their behavior is absent.

### Continuation: full writer/assessment acceptance

- Root owns critical provider/writer repair and exact synthetic-tenant persistence;
  Terra read-only sidecar reviewed DEV persistence helper. Customer-derived content
  must not be relabelled synthetic or exported to Supabase by that helper. Its
  nonnegative-count readback is insufficient for real course acceptance.
- Existing KZ Redis holds only an exact scoped temporary acceptance artifact (TTL1h)
  between bounded test stages; no installed runtime code replacement. The existing
  synthetic tenant and owned Excel copy remain the only write/test-data scope.
- `source-resilience-writer1.sh` SHA e9af16ee0da513c14c90cf4c3efa01df383806c72eaadd73cedb415ce5bc9695:
  real cold map44calls/53.54s, architecture3modules6lessons/67.85s, then
  direct_source_prompt_budget_exceeded before writer inference. No course created.
- WRITER_BUDGET_ADDENDUM_V4 accepted: exact full-request packing, unchanged limits,
  whole chunks and all requested documents. Synthetic480-char-heading fixture
  reproduced2FAIL; repaired focused suite29PASS. Independent Luna review accepted.
- `source-resilience-writer2.sh` SHA a7e817069f4af2f10f9aba8a2924649a9e38daa6a858bd25d365eecca9adfb1b:
  PASS: cached map0calls/0.40s; architecture+six lessons7calls/107.39s,
  26008 lesson characters. Its serializer uses dataclasses.asdict for CourseStructure.
- Existing reviewer and assessment path then produced26MCQs/104choices across
  six lessons (two bounded runs74.97s and75.81s); scores8-9. All26source quotes
  occur in their lesson;14correct answer strings occur literally in the original
  grounding chunks. Remaining paraphrases are not independently fact-certified.
- Unchanged production persistence function hash verified before invoking the
  candidate in a non-dispatching isolated process. Exact draft course
  38790494-722d-4ca6-aba0-72a2e39c955b and completed test job
  5b06993c-bfed-4892-8968-3cf3433855bc in the existing synthetic tenant only.
  Independent DB and normal methodologist API readbacks:3modules/6lessons/
  6quizzes/26questions/104choices; all reviews required, no publish/assignment.
- Browser methodologist-role acceptance confirms outline, first/last lessons,
  six quiz groups and first quiz options/explanations. Browser exposed raw Markdown
  headings/tables; V5 adds an inert React renderer with malformed-table literal
  fallback (extra cells never discarded). Terra revision accepted after root review.
  Integrated frontend suite110files/569tests PASS; typecheck PASS.
- Final backend suite1208PASS; quality baseline Ruff1088/mypy2345 PASS.
  Actual Supabase DEV isolated reindex-worker integration1PASS, public revision0156
  and tenant/document/job counts unchanged. Customer-derived material never sent to DEV.
  Owner approved parameterizing stale public DEV revision in the application gate;
  isolated0127->0131 fixture baseline and all cleanup guards remain mandatory.
- Cleanup pending: exact acceptance draft/job and expiring KZ Redis artifact
  ai:acceptance:source-resilience:d92ec4ba-f289-478d-8018-8a6edf7b4cf0.
  Source-map checkpoint already absent. Owned Excel copy retained for final queue test.
- Remaining dependency: writer -> reviewed assessments -> persistence/API/browser
  -> release/journey gates -> exact production deployment and queue-worker smoke.
  No client GO until that chain passes; production still guarded exact3c051931.

### Release042 prepublication gate

- HBR-DEV-APP-20260910T104753Z runtime PASS, fingerprint
  95b21017d29897d38c62f8be28fd038649ff478b1997dc610fe81fc6b2b167d5.
  Public0156 unchanged; isolated historical upgrade/downgrade/re-upgrade, FORCE RLS,
  negative tenant checks, CAS concurrency, active-only retrieval, rollback and
  exact schema cleanup pass. Only synthetic data; no inference/provider calls.
- Approved gate repair also fixes three UUID-to-text fixture bindings and checks
  current safe citation projection; offline18PASS. Release contracts86entriesPASS.
- Browser first and last generated quiz inspected; all26quotes match lesson text.
- Frontend lint/typecheck PASS; full110files/569tests PASS. Backend1208PASS and
  Ruff1088/mypy2345 baseline unchanged. Graph16145nodes/38777edges, no dangling or
  exact duplicate edges; representative component/page link verified in source.
- Independent preflight: API and all3workers exact3c051931/0.4.1, zero restarts;
  CT137 exactsameSHA, native service running. CT1250157. Backup gate created a
  fresh encrypted checksummed archive. VM126 available8801MiB disk/13162MiB RAM.
  No migration in this release; new restore drill not claimed.
- Source042 commit/push, exact CI/native artifact, protected deployment and normal
  queued large-Excel smoke remain the next mandatory gates.
