# Kamilya LMS: текущий контекст проекта

> Living document. Значения секретов здесь не хранятся.
> Обновлено: 2026-10-19.

## Источники правды

| Область | Документ |
|---|---|
| Продукт и функциональные границы | [`PROJECT.md`](../PROJECT.md) |
| Текущий production и release-gates | [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) |
| Открытый backlog | [`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md) |
| Роли admin/methodologist | [`ADR-0012`](adr/0012-rbac-admin-vs-methodologist.md) |
| Auth/session/active role | [`ADR-0008`](adr/0008-auth-strategy.md) |
| Пользовательские сценарии | [`USER_DOCUMENTATION_RU.md`](USER_DOCUMENTATION_RU.md) |
| Внутренняя архитектура | [`PROJECT_INTERNAL_DOCUMENTATION.md`](PROJECT_INTERNAL_DOCUMENTATION.md) |
| Эксплуатация worker | [`INFRA_CELERY_WORKER.md`](INFRA_CELERY_WORKER.md) |
| Доступ и сервисы VPS | [`VPS_CONNECTION_GUIDE.md`](VPS_CONNECTION_GUIDE.md) |
| Production frontend и rollback | [`PRODUCTION_FRONTEND_RUNBOOK.md`](PRODUCTION_FRONTEND_RUNBOOK.md) |
| Backup и restore | [`BACKUP_RESTORE_RUNBOOK.md`](BACKUP_RESTORE_RUNBOOK.md) |
| OCR и KZ infrastructure migration | [`INFRA_KZ_OCR_MIGRATION_ANALYSIS.md`](INFRA_KZ_OCR_MIGRATION_ANALYSIS.md) |
| Подтверждённые ошибки и профилактика | [`ERRORS.md`](../ERRORS.md) |
| Правила для агентов | [`AGENTS.md`](../AGENTS.md) |

Старые планы, аудиты, отчёты веток и ТЗ не являются источниками текущего
поведения.

## DEV server OCR — 2026-10-20

Cloud DEV API/worker at0a9d8aa824c78422839017f7969389878cda0038 use the
existing SSH launcher with DEV_OCR_SSH_ENABLED=true. Fixed local18600 forwards
through the existing restricted private transport to VM12610.77.77.2:18601.
VM126 ingress permits only wg0/proxy10.77.77.1; no public converter gateway.
kamilya-dev-ocr.socket/service relays to the independently verified owned
kamilya-dev-ocr container IP on the separate internal kamilya-dev-ocr-private
network. Container recreation requires IP/unit synchronization. Runtime source
acb9b2267314bcaaa0428b6e223075b137f4bd43ca91811b66bb40556dddaa6f,
image5d875f436820e028c4ea4d4ae65dd54addbc2765b57b6ea61970e73935b99e84;
UID10001/read-only cache+root/4GiB/2CPU. Existing DEV API key is root0600 in
/etc/kamilya-dev-ocr.env; never use the production key. Source and credentials
are not supplied by the workstation at runtime. Authenticated conversion of both
original binaries (DOCX0.765s/PDF59.36s) and production-preservation checksPASS.
R24 CI39395120330SUCCESS; APIdep-dbbiknfavr4c73e0obm0,
workerdep-dbbiloo473hc73cgi9u0, frontenddpl_3yrePyi7Bhs7PNhmik5sVKu6CVPy,
controllerRELEASE_OK. Ordinary QA browser PDF reindex reached completed through
the cloud worker and private server OCR. Server-only scanned RU/KK/EN smoke
PASS3pages/6checks/11.568s. R24 whole-course quality remains incomplete:
DOCX44/44 and PDF94/95 questions. Independent review verified all138retained
question keys/options; it found one DOCX lesson qualifier loss (approved AND
current rates) and confirmed the PDF door-rule omission. R25 bounded pre-review
model-repair routing and source-qualification preservation remain local.
Runtime success and all-topic coverage do not close these quality defects.
Runtime availability is not quality GO.
Existing Free/Free/Hobby tiers unchanged. Production converter was
not updated. Source/course acceptance remains separate and OPEN.

## Historical DEV-only OCR correction — 2026-10-19 08:30UTC

Owner selected removal of the obsolete DEV converter reference, not recovery of
the former server. Existing API srv-d8rp8ej7uimc73fglid0 and worker
srv-dar2dvbncjis73bsda3g no longer have DOCLING_URL; all other environment values
are unchanged. Applied at the already-approved DEV source
8099de6606578db158ae8c25d3e6c612d8765397 (0.11.66), API
dep-dbat9dbbc2fs73cnee0g and worker dep-dbat9dmq1p3s73d19d20 both live; exact API
identity/worker health PASS. Existing Free/Free/Hobby retained; no production,
DNS, key, model-route, billing or resource change. Without configured OCR,
cloud DEV uses local conversion for supported sources; scans require OCR.
The existing local-only VM126 converter tunnel is available for bounded local
verification but is not a cloud DEV service connection. DEV66 quality acceptance
remains open; this configuration correction does not approve a production release.

## Current delivery checkpoint — production65 accepted,2026-10-19

Backend/native frozen00e41ca7001564574fb89d2de97f9636d7e5020f/v0.11.65;
image479f2235...8de06, CI39209823772/native39209870918/protected39210442155 SUCCESS.
Independent final07:07UTC actual API+3workers/restarts0/all4flagsON/public-private
health PASS. Foundation64 already applied0183;65 adds no migration. FORCE7,
legacy role/policy/ACL hash3882b298...61b3, runtime non-super/non-BYPASS and model
routingc016939b...a736/current owner-enabled reserveON unchanged. Previous64/c0d5e958
imagec78a29bed...fcca2 is marker-aware backend rollback/staffOFF; native previous62
is UI rollback only. Actual rollback NOT_RUN; do not use pre-kernel62 backend
after retained markers. Fresh signed183restore130tables/126FORCE/RPO43s/RTO19s,
owned DB/temp absent. Exact DEV65 API/worker/frontend and persistence PASS on
unchanged Free/Free/Hobby. New DEV packet execute owns worker rollout; reconcile
is only for existing/unknown operation and does not trigger auto_deploy=no.

First4 live synthetic production QA blocks PASS: actual-model date-only assignment
preview/confirm/receipt-reload;31runtime settings save/reload/controlled Cancel and
revert with all original values restored/revision3/audit retained; schema/roster/
employee+unit transfers preserve training and roles; corrected XLSX reload/commit,
accurate create/update counters/stable IDs and qualification-placement restore.
Prior21users/13units/31full journal rows unchanged, final24/20/33 includes retained
legitimate QA fixtures/history. Global retained markers0; live cross-tenant and
managed-retained-loss tests not claimed beyond isolated/CI evidence.

Only explicitly approved unused local failed63 image5e2cbc8d...ce3a2 removed after
GHCR index/amd64/13blobs and all12container reference proof. Protected65/64/62,
all containers/state/config preserved; lease released, no force/prune. Disk90→88%,
free3912663040bytes immediately after cleanup; warning85 remains/critical90 cleared.
Watchdog expected65 two keys only, byte-identical old backup retained, unchanged
thresholds, oneshot success0/timers2active. No voice/iSpring/ASUS/1C/model/reserve/
landing/DNS/rights/tier/resource changes. Full bounded scope/readiness: release65,
PRODUCTION_READINESS and TEST_RUN_LEDGER. Docs-only closeout is not a new runtime.

## Historical delivery checkpoint — foundation64,2026-10-19

Production backend foundation64/c0d5e95810ab14757416447449ace4ae052c88eb deployed
by39208080553; independently verified06:20UTC, imagec78a29bed...fcca2, API+3workers
staffOFF, schema183, FORCE7, global marker0, unchanged legacy roles/policies/model
route and prior QA21/13/31. Native remains62. DEV64 exact CI/rollout/persistence and
controlled Cancel/no-write PASS on existing Free/Free/Hobby. Activation65 is a
version/docs-only no-migration child, previous64 marker-aware backend rollback,
native62 UI rollback. Independent65 gates/live acceptance remain pending.
The following candidate/runtime62 sections are historical baselines, superseded
by this checkpoint; no voice/iSpring/ASUS/1C/routing/reserve change is authorized.

## Earlier DEV four-block candidate,2026-10-19

DEV ce95010ac4a24c9815bd57856a9c4908581cb720, CI39197219609 SUCCESS,
REL-FOUR-BLOCKS-DEV-R3-20261019 RELEASE_OK with exact API/worker/frontend parity.
Assignment date-only dialogue,31 audited runtime parameters, optional staff
schema/roster/safe transfers, import corrections and linked qualification restore
are accepted in the selected DEV journeys. Fresh tab12 runtime acceptance passed
save31/reload revision8, controlled Cancel/no-write, explicit target7 revert and
reload revision9; all31 originals/history suffix/routing remained unchanged.
Assignment plan ccc5ba46-04df-42fb-8616-7abfb2cc2a1e created one enrollment with
no notification and replayed identically; employee transfer plan6402f3e2 affected
one employee with added0/preserved1; empty-unit plan67bd2a8c affected0. Corrected
XLSX names/reload/approval/commit passed, and completed-wizard reload clears the
wizard by design. Do not infer production readiness from DEV proof: production
remains62/schema0181 and unchanged. New63 source delivery protocols were reviewed,
and exact1df25458 CI/DEV passed. Protected39204193182 failed0183 precondition
before commit/switch: non-BYPASS owner sees202users/0positions/0departments,
causing38false anti-join matches; privileged actual bad references0. Native63
preflightREADY was not executed. Superseding64 repair/gates pending; production
remains62/schema0181. No voice/iSpring/ASUS/1C/
model-route activation change is in this package.

## Historical runtime62 snapshot,2026-10-19

Production API/three BLUE workers/native frontend62 exact
1df269394ae6d0a2c7e6924e770c974ce0994651, tagv0.11.62; backend image
7fbbd472b5c01ac71e9135d25d9849b497beb697964fcd15d305870cadb7077c.
CI39187154582/native39187174163/protected39187598456 SUCCESS; nativeR4
REL-FORMS62-WEB-R4-20261019 RELEASE_OK. Final02:27UTC independent exact public/
private/container readback PASS/restarts0. GREEN61 API healthy/workers stopped;
native previous60/4bcc and additional59/protected359+299 retained. Actual rollback
switch NOT_RUN. Schema0181, FORCE-RLS/non-BYPASS role/controller/routingc016...
and current owner-enabled reserveON unchanged. Watchdog identity62 only, backup/
thresholds/checksuccess/timers preserved; existing signed restore181 reverified.
VM126 free4773834752bytes, native1054296KiB after install. Only obsolete native56
and exact staging pair cleaned under standing rule with verified offhost recovery;
no broad prune. Local capture-parser error reconciled independently, not retried.

Forms62 selectively integrated from accepted DEVd334e331, with narrow reviewed
projection/PDF-title/guide fixes. DEV contour untouched in this release. Ordinary
production QA admin/methodologist/student full forms scenario PASS; three actual
browser attempts and immediate/history/reload/template-change/restoration PDFs,
all prior30full journal rows/two legacy attempts preserved. Settings restored,
new legitimate QA history retained. Public instructions/help updated, existing
media preserved. Other DEV/iSpring/staff-v3/AI/model changes, voice/ASUS, landing,
DNS/rights/resources/tiers excluded. See readiness/release62/ledger for exact scope.

## Historical runtime61 snapshot,2026-10-18

Production API/three GREEN workers61 exact0fe7985bccb8f2464898f4e1fb7904a734f92a3d,
immutable imagec6120580b23678ed4df2ca70c7d4cbc804a3a0dabf9a537deccfa2a48739ffd5;
CI39147399472/protected39147841351 SUCCESS and independent public/private/container
readback PASS/restarts0. BLUE60 API healthy rollback/workers stopped. Native60/
4bcc64c0 remains unchanged; no frontend build/cleanup. Schema0181, FORCE-RLS,
runtime non-BYPASS, controller, routingc016939b... and owner-enabled reserveON
unchanged. Watchdog61 two keys only, backup retained/thresholds unchanged/check
success/timers active; signed restore181 verified. Final free5247016960bytes.
No voice/ASUS/rights/DNS/provider resources or billing changes.

DEV preservingb70dd4eb3 CI39143947829 and execute/reconcile PASS on Free/Free/Hobby.
Exact final release is docs-only child of tested3b77, application trees equal.
Actual DEV and production staff-import review/approval/commit/reload PASS on
synthetic records; repeated/additive/new-only/omission/duplicate/inactive/stale
approval verified. Production old17user identities/30full journal rows unchanged;
four new students soft inactive, only owned empty44c861bd... soft archived. Marked
QA units/positions/import sessions retained, no hard purge or notifications.
ADD_OR_UPDATE is not full replacement; omitted rows preserved, automatic hierarchy
transfer/reactivation not enabled. Bounded acceptance complete, not all-button/
legal/outbound claim. See readiness/current release61/ledger for exact proof.
Pre-existing production preview English technical labels are a UI follow-up;
experimental DEV staff-v3/iSpring/polished UI are not promoted wholesale.

## Historical runtime60 snapshot,2026-10-18

Production API/three workers/native frontend0.11.60 exact
4bcc64c0c686c6de0f3ffcf98268382fed42295c; protected39137346796/native bridge
REL-CABINET60-WEB-20261018 successful, independent exact public/private identity.
BLUE image8bf69416...e48c7d, GREEN57 API rollback healthy/workers stopped.
Native previous59 b0c612bf..., additional56/protected359+299 retained; obsolete55
and exact staging pair removed only after verified offhost recovery. No migration:
schema0181, runtime/RLS/controller unchanged. Current routing c016939b.../owner-
enabled reserve ON is authoritative; older OFF snapshots below are historical.
Voice/ASUS/DNS/rights/provider plans/resources unchanged. Watchdog identity60 only,
unchanged thresholds/two timers active/checksuccess0; signed restore181 reverified.

DEV preserving integration b54115e6ec07c1029f2d16f26c21d9b107f3469a accepted:
APIdep-dbadbojbc2fs73av5u30/workerdep-dbadcmdg1s2s73bm9lfg,
Verceldpl_2rGrDYe8GWdQSVwyjqerD4MByhq6, Free/Free/Hobby unchanged. Prior transient
broker/login outage recovered; old VPS is not a current prerequisite. For permanent
DEV QA use exact access-map methodologist identity and validate tenant a7a2c055...
before writes; current env email may name an older synthetic tenant. Never infer
tenant from password success alone.

Production bounded course generation-to-certificate and changed cabinet paths
passed with all29 prior journal projections unchanged/total30. Extended structure
acceptance remains open: manual new QA API CRUD/soft archive PASS, Excel preview
has wrong physical-cell refs and is not applied. Readiness/ledger own proof and
remaining gates; this snapshot does not claim all buttons or all historical cases.

## Historical guide59 snapshot,2026-10-16

Production frontend59 b0c612bfe4bfaf22346ef8763825512ce0de642e is deployed and live
guide/menu acceptance PASS; API/three workers remain57/schema0181 unchanged.
Visible methodologist link below logo: /guides/methodologist.html; eight approved
male Qwen MP4s/69steps/captions/downloads, old text guide retained. DEV and production
ordinary-role browser and independent32asset hash/range/VTT checks passed.
DEV now b35d11a2eb215c1468e1f1a090be3fda9d2432ad, preserving all14 prior DEV commits;
Vercel dpl_EpXhjs8iw7kYDF5Lca9DfknsFHry and existing Render API/worker live,
Free/Free/Hobby unchanged. AI58 semantics remain unaccepted; guide release did not
change production model settings/reserve/voice. Immediate frontend rollback56
8a612c19…; additional55/protected359+299 retained. Release59 notes/readiness own proof.

## Historical DEV candidate58 snapshot — production backend remains57,2026-10-16

DEV58 b73d08a1942f590c0dee1a2f9aeaf12e1da24d9e is deployed/reconciled:
Render APIdep-db8rndui0phs738pki9g, workerdep-db8roi6q1p3s7395j5vg,
Verceldpl_9MFrvXEpH5Y6pUT6mAHGHGdYjdiF, unchanged Free/Free/Hobby. It is NOT
accepted: actual multipart browser answer restores retention but misclassifies
an unrequested conditional authority difference. Further private conflict-proof
source delta is local only, not the current DEV or production runtime.

Owner-approved temporary ordinary methodologist for this DEV QA run only:
tenant a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0, user86054d41-47e3-44da-ae73-b1db7edd60e9.
Canonical no-mail superadmin creation/reset and ordinary login/me passed. Secret
only main.env DEV_DOCUMENT58_METHODOLOGIST_EMAIL/PASSWORD; do not print values.
Exact account/own-history cleanup remains PENDING after acceptance. Permanent
original methodologist has100tasks; do not raise cap/delete its history. Normal
DELETE only deactivates, so cleanup needs exact parent-row/cascade inventory and
independent absence; no blanket tenant cleanup or customer data. Voice/reserveOFF,
schema0181/native56/provider configuration unchanged. Active plan/CODEX_HANDOFF own
the candidate's still-open checks; production57 below has not been replaced.

## Current production — backend57, compatible native56,2026-10-16

Runtime/tag57 exactf6f1bc945e627287f8d5a9cf9040bcae1f73ea4a;
masterCI38827828941/DEVCI38828641350/protected38831182689 SUCCESS.
API+three GREEN workers imageb6d4bfec…674c/running/restarts0/flags unchanged;
native56/exact8a612c19 intentionally unchanged/compatible. BLUE56 API remains
healthy rollback, oldworkers stopped; actual switch/history service read NOT_RUN.
Fresh04:59UTC private/public/native checks passed. Schema0181/two dialogue
FORCE-RLS/runtime non-BYPASS/controller25fa90f7…a3d2e/routing-row7834c8c3…5da3f
unchanged, revision3/reserveOFF/voice unchanged. Existing ops57 identity/threshold
bytes/two timers active/checksuccess0; VM12681%/5953152KiBfree.

Historical DEV57 accepted42/42 actual-model semantic cases,95exact citations,280ordinary
audit checks/12downloads and Root4new browser replies/download/reload/reopen.
Existing free contours only: Render APIdep-db8msjmq1p3s738l2jh0,
workerdep-db8mtp2vcj2c73b1sp2g; Verceldpl_64D8gMPwgJ8fmJ7fuddWvHGNiFZgReady
(Free/Free/Hobby). Local3049API/58focused/web1163hash-linked unchanged; fresh
actual isolatedDEV44checks/45sources/cleanup/public-neutrality PASS.

Production acceptance PARTIAL:41/42 API questions source-faithful, H57-03 twice
terminal503/provider_unavailable. Root browser4completed KK replies/source DOCX+
PDF hashes/history reload/reopen passed; independent293-check preservation/access
audit retained both failed records/no pending,12downloads/oldhistories/11coursekeys
7completed rows unchanged/student403. Separate local60s probe found DeepSeek
completion8192/finishlength/content0; no runtime parameter change installed.
Compact-policy local probe returned37.875s/statussupported but missed both
requested retention periods/categories; independentPARTIAL/not deployed.
Request-local evidence_low remains low/8192/45s; overall60s, same model/key/order.
Final product GO remains open; never treat HTTP/deployment success as acceptance.

Fresh exact owner approval covered54regular proxy.deb cache files only after
offhost SHA256 recovery verification. Removed447214984bytes, preserved lock/partial/
othermetadata/services/config/packages, recovered~420MiB; Nginx+WireGuardactive.
All12synthetic uploads/indexes then ready; originals/failure receipts retained.
Recovery files intentionally retained offhost under DOCUMENT57/proxy-deb-recovery57;
no standing broad proxy-cleanup permission. No DB/customer/learning cleanup,
Proxmox/rights/DNS/billing/resources/nativebuild changes. Canonical detailed state:
PRODUCTION_READINESS/release57/CODEX_HANDOFF/TEST_RUN_LEDGER.

## Historical environment — backend/native/DEV56,2026-10-15

Runtime/tagv0.11.56 exact8a612c199423bb4839e03cfae3d8ce7f201ca332; masterCI38757324407,
DEVCI38758238172, native38757356879/artifact11983638875 and protected38759477177
SUCCESS. Native REL-DOCUMENT56-WEB-R3-20261015 RELEASE_OK. API+three blue workers
image74b95aa9…552b3/running/restarts0, public/private/native current/marker/body
exact8a. CT1250181 unchanged/two dialogue tablesFORCE-RLS, non-BYPASS lms_app,
all flags/controller25fa90f7…a3d2e unchanged. Saved routing entire row SHA
7834c8c373ade40508574aeac2ed69d2592fa63cc41d95196f73ba8f5165da3f unchanged,
revision3/order unchanged/reserveOFF. No voice/connector/provider tier change.

Bounded document-content Q&A now accepted, including contextual follow-up,
supported/not_found/conflict statuses, server-derived exact citation windows,
authenticated excerpt/original download and durable private reopen after reload.
Questions do not modify a course brief or execute an operation. Generation remains
a separate preparation/preview/confirm flow. Actual Supabase DEV44/44 isolated
checks/owned cleanup/guarded-public neutrality and full API3013/web1163 pass.
Six final real-model DEV questions on c78; apps/scripts/workflows/product-contract
tree equivalence to8a and fresh final8a browser/111 assertions separately accepted.
Existing DEV Free API dep-db8esblg1s2s73a1v7r0, Free worker dep-db8et9g473hc739h0tng,
Hobby Vercel dpl_DkEBKHKJviZVuHYxdazKEj1WfVB4; no resource/billing changes.

Production Root actual browser six replies/zero failures, conflict/abstention,
two-point simplification, no execution, original download exact SHA, full reload
and recent-task reopen passed. Separate Test Runner43 assertions passed:6 exchanges,
7 citations/excerpts, student403 four routes, old dialogue and seven selected
completed projections unchanged, empty brief/planNULL/no new course-generation job.
Bounded20 recent-job inventory has1 new job of unverified provenance; no all-row
equality or human-efficiency/latency guarantee. Retained QA documentae6b5de0…/
task81abbe1d…/revision13; originalSHA9ec7fb5e…a3638c. No real-tenant/business cleanup.

Signed0181 restore3d560730…9581f/RPO43/RTO19/126tables/122FORCE-RLS plus old private
task/3 exchanges restored; owned temporary DB/directories0 independently confirmed.
API immediate rollback55/green5c3a… healthy/oldworkers stopped, native actual55/381…
marker/boundary verified, extra53/18cc/protected359/299 retained; switchNOT_RUN.
Old55 cannot render56 answered history; preserve it and roll forward for new Q&A.
Standing-rule obsolete native51/exact staging cleanup only, recoverable offhost;
native postdeployfree1114716KiB. Watchdog56/image74b/thresholds unchanged, both timers
active/oneshots success; VM12680%/6412204KiB free. No Proxmox/rights/DNS/tier changes.
Detailed current proof/limits: PRODUCTION_READINESS/release56/TEST_RUN_LEDGER.

## Historical environment — backend/native/DEV55,2026-10-15

Runtime/tagv0.11.55 exact381692f9c6e8781a795c3542c19d649ffbc28f09. MasterCI38728397645,
DEV38729390192, native38729003184/artifact11968902851, protected38731305223 SUCCESS;
deployment7091942947. API+3green workers image5c3a61ae…57fada/running/restarts0,
public/private/native/current/marker exact55, all3existing flagsON. CT125 schema0181,
new task/exchange tables FORCE-RLS2, runtime lms_app non-BYPASS independently verified.
Saved routing entire row SHA7834c8c3…5da3f/order/revision3 unchanged/reserveOFF;
voice/connector/provider resources unchanged.

Durable source-bound document preparation, not general document Q&A. Root live
DEV and production3real-model messages/manualsave/fullreload/close-reopen/recent
task/explicitpreview/oneconfirm/samejob/draft result PASS. Separate ordinary-role
production API32checks including student403 list/detail PASS;7old selected completed
records unchanged, new draft0enrollments. Retained marked QA task/history/job/course;
no tenant recreation, customer writes, email, publication or learning reset.
Production3UI replies1.353–1.681s, persisted generation45.663s; synthetic sample only,
not SLA/human benchmark. Actual isolated DEV32 SQL/service checks/cleanup/public
neutrality/frozen28source hashes PASS; model mocked only in that isolated gate.

Existing DEV Free API dep-db8br6psrm7s73e3u7l0, Free worker dep-db8bs71srm7s73e4140g,
Hobby Vercel dpl_3qrXEQsEYZDDeU5m5xsrSuyJ27do exact381/all9flagsON; public181
explicit migration/readback PASS before rollout. Protected controller25fa90f7…a3d2e
upgrade38731073421 changes version-validation epoch only; backup/rights unchanged.
Fresh signed180/181 disposable restore reports acb9f782…/b9715cae… verified;181
126tables/122FORCE-RLS/RPO43/RTO20 plus actual synthetic task/3exchanges restored,
temporary DBs/work dirs absent. Backend immediate rollback54/image6f healthy/old3workers
stopped, native immediate rollback53/18cc independently boundary verified; extra51,
protected359/299 retained. Native R1 capacity BLOCKED preserved; standing-rule exact
obsolete50/recovery-verified cleanup only, then native R2 RELEASE_OK/free1114920KiB.
Watchdog55/image5c/thresholds unchanged, both timersactive/oneshots success0;
VM12678%/6868164KiB free. No Proxmox, DNS, paid tier/resource or reserve activation.
Scope/identity/limits: PRODUCTION_READINESS/release55/TEST_RUN_LEDGER.

## Historical environment — backend54/native53/DEV54,2026-10-15

API/threeworkers54/tagv0.11.54 exactaf5e9957a165dbdfb36f342afeb17a8f1ed3b15b,
masterCI38712412481/DEV38713165732/protected38714758072 SUCCESS; deployment7089185948.
Blue services running/restarts0, image6f542e2c…2cea6. Public/private API exact54,
native/public marker53/18cc unchanged and compatible. Schema0180 unchanged,
no controller/permissions/topology update. Existing three feature flags unchanged.
Saved ChatGPT reserve OFF; complete routing-row SHA7834c8c3…5da3f/order/revision3
unchanged. Connector53 remains installed/dormant, no voice change.

Existing DEV Free/Free/Hobby exactaf5: API dep-db89rpavcj2c738o6pgg, worker
dep-db89so8u01pc73f297vg, Vercel dpl_3agtJPZ2uiehMf1bsRHWnfUdeF62, all9flagsON.
Root full normal-role real-model dialogue/clarification/contextual correction/
preview/explicitconfirm/GET reload/learner access accepted in both environments.
Production found and repaired C-locale Unicode comparison at the two SQL
predicates; actual C-collated owned DEV/RLS/cleanup gate PASS. Production created1
synthetic assignment, DEV postfix created0/skipped1 and kept prior deadline.
No email/outbox/attempt, prior selected completed-learning projections preserved
(DEV1/prod7 completed). Both temporary QA position department fields restored;
retained QA courses/assignments remain for reproducible acceptance, no deletion/reset.

Signed fresh180 restore32df6c94…6da26/124tables/120FORCE-RLS/RPO43/RTO19 verified;
owned restore DB/temp absent. Backend immediate rollback53/image5771fe19… healthy,
oldworkers stopped; native rollback51 unchanged. Watchdog expects54/image6f,
thresholds unchanged, both timers active/oneshots success0. VM12677%/7313624KiB free.
No CT137 deployment/cleanup, Proxmox, DNS, provider tier/resource or reserve activation.
Actual source/runtime/limits: PRODUCTION_READINESS/release54/TEST_RUN_LEDGER.

## Historical environment — production53/DEV53,2026-10-15

Runtime/tagv0.11.53 exact `18cc41e3a8f9a72be85a0977e82bad11e484f6f3`:
CI38699232647/native38699262419/protected38702195538 attempt2 SUCCESS;
canonical REL-RESERVE53-WEB-20261015 RELEASE_OK plus separate Test Runner acceptance.
API+3workers green/image5771fe19…9952e exact53/running/restarts0; CT137 current,
marker, public API/native identities match. CT125schema0180 independently verified,
generation routing FORCE RLS and non-super/non-BYPASS lms_app unchanged.

Private official CLI0.146.1/gpt-5.6-luna connector installed on existing VM126,
immutable imageed5b65da…4981a9; fixed private edge10.77.77.2:18999/v1, no public
ingress. Protected dedicated managed-auth home/separate application bearer; no
auth in images/Git/reports or raw subscription-token/API-key substitution.
Runtime configuration is shared by API+3workers, private readiness true from all.
Superadmin AI providers → Reserve ChatGPT: configured/OFF, explicit readiness
ready, reload preserves OFF. Test Runner API20/20 and Root live browser PASS;
zero saved-route/business writes. Existing DeepSeek/Qwen/GLM order revision3 and
entire routing-row SHA7834c8c3…5da3f unchanged. No activation performed.
Database-free private acceptance with exact final API image returned real synthetic
model JSON5666ms after controlledprimary404; not an actual provider outage.
Managed auth readiness after restart PASS; forced refresh/quota/commercial hosted
eligibility NOT VERIFIED. Readiness is not an inference or entitlement guarantee.

DEV exact18cc, Hobby/Free/Free unchanged: API dep-db881a2j9qps73c0qdr0, worker
dep-db88295g1s2s739d6abg, Vercel dpl_7Vc3GqCwBaXbFbXm2t6yjnrC3jZ3; schema0180,
isolated14checks/owned cleanup/public neutrality PASS. Public Render intentionally
not connected to private VM126 relay; DEV UI OFF/not-configured, no public bridge.

Fresh179 encrypted backup/signature/disposable restore124tables/120FORCE-RLS,
RPO179/RTO19 and owned DB/plaintext-work cleanup PASS before0180. Controller
upgrade38700815356 installed6dfb51bf… with previouscfe727c8… backup; six other
payloads/rights/config unchanged. Backend/native immediate rollback51/85933,
old APIimage7505949a… healthy/old3workers stopped; native50/6d2 and protected359/299
additional recovery retained. Actual rollback switch NOT_RUN. Only qualified
obsolete native49/exact staging pair cleaned recoverably; no API-image prune.
Watchdog exact53/thresholds unchanged, both timers active/oneshots success0;
final VM126disk76%/7754832KiB free, CT1371115100KiB free. Failed attempt1 caused by
Root-owned empty advisory lock is preserved under RELEASE-007, not hidden as a
provider failure. No Proxmox/DNS/tiers/resources/voice/landing changes.
Evidence and limits: release53 notes/PRODUCTION_READINESS/TEST_RUN_LEDGER.

## Historical environment — production51/DEV51,2026-10-14

Runtime/tagv0.11.51 source85933da4b2bb48a43da4a380dfd36a73c5b195b7,
masterCI38574563481/native38574699131/protected38575499511 SUCCESS;
canonical REL-ASSISTANT51-WEB-20261014 RELEASE_OK. API+3workers blue/image7505949a…
71e9/native/public identities exact51/all3flagsON/restarts0. CT125schema0179 and
private actor-owned dialogue FORCE-RLS verified; signed179 restore124tables/
120force/RPO45/RTO20 and restored2QA pairs/temporary cleanup PASS. Current watchdog
51/timers2active/oneshots success0. Fresh watchdog0CRITICAL/0WARNING; disk72% after
exact owner-approved8 local image copies removed under owned lease, GHCR8manifest/
amd64/71blob recovery proof and all-container reference/preservation checks.
Actual3910396KiB reclaimed; protected51/49/47 and11remaining images independently
present, exact8absent. No threshold change/Proxmox/rights/tiers/resources.
Immediate native rollback50/6d2, additional49/3fe/protected359/299 retained;
backend rollback49/c3c healthy/oldworkers stopped, additional47 retained.
Obsolete native48/exact staging recovery cleanup is separate from the exact8 API
image cleanup; no broad prune, registry/DB/volume/file/backup deletion.

Existing DEV51 exact859, Hobby/Free/Free unchanged:
Vercel dpl_r7Rb5gmuFBcDwc8dAWDVBDXsLJrX,
API dep-db7o8pad0e5s73eiog70, worker dep-db7o9ps9v7es73cop9s0 live/all9flagsON.
Actual QA dialogue→reload→simpler follow-up→reload/private RU-KK history accepted
in DEV and production, no lesson/publish/assignment writes. Original QA bytes,
draft and zeroenrollments retained. History owner/context/limits and current
operational state: PRODUCTION_READINESS/release51/TestRunnerledger. Six other
release-plane files unchanged; separate approved controller upgrade38572755549
installed cfe727c8… with verified e0eaaac4… backup, no rights/config expansion.
Runtime859 is distinct from any later documentation-only master successor.

## Historical environment — frontend50/API49, DEV50,2026-10-14

Production native frontend50/tagv0.11.50 source
`6d2a043520044db01dd74f36d89a72ead9fe8d62` accepted through canonical
REL-ASSISTANT50-WEB-20261014, masterCI38554065318/native38551594406.
API/threeworkers intentionally remain49/source3fe/imagec3c; schema0178, backups,
flags, watchdog49 and ops timers unchanged/healthy. Immediate native rollback49/
3fe, additional48/3609 and protected359/299 retained; backend rollback47 unchanged.
Only obsolete native47 and exact staging pair cleaned recoverably under frozen50
standing capacity rule. No Proxmox, bootstrap, billing/resource/role/flag change.

DEV exact6d2/0.11.50, unchanged Hobby/Free/Free:
Vercel dpl_AWGhYXA9ji7trLi8tqYyrUx4QpyQ READY;
API dep-db7ls0ivcj2c73e4an30 and worker dep-db7lt0qvcj2c73e4dtgg live,
all9 existing flags verified. Ordinary QA actual model→source handoff/download→
sealed apply→reload/manual preservation passed in both contours; original QA text
restored, no publication/assignment/completed-learning/customer writes. Normal
audit/receipt/review timestamps retained, not an all-column or zero-row rollback.
Canonical current gate/limits: PRODUCTION_READINESS/release50/TEST_RUN_LEDGER.

## Historical environment correction — production/DEV49,2026-10-14

Production API/threeworkers/native frontend49 and DEV API/worker/Vercel exact
`3fe3c39acbd256d7e4fa65b91a0c22ce429c295f`, immutable tagv0.11.49.
Protected38527015529/deployment7059236386; actual imagec3c35fb…bef6b;
native38523095859/REL-ASSISTANT49-WEB-20261014. All4 production services running/
restarts0, current/marker/public identities and flags verified. Schema0178,
backup success/active timer unchanged; watchdog expects exact49/image, both ops
timers/checks success. Actual immediate rollback: API47/75d, native48/3609;
additional native47/protected359/299 retained. Actual rollback switch NOT_RUN.
Only obsolete successful46/exact staging capacity cleanup, original offhost
recovery retained; no Proxmox/on-host build/topology/DNS/rights/tier change.

Existing DEV remains Hobby/Free/Free,9flags unchanged:
Vercel dpl_5qnMYTaphXPzJPPYxT7iJ9FHZVRd READY;
API dep-db7i70mq1p3s73cjolhg; worker dep-db7i83t9fdbs73ebp1d0.
Permanent QA identities below unchanged. Root actual DEV/production ordinary-role
current-source download, real context-dependent dialogue and language/refusal
resets accepted with model-quality caveats owned by PRODUCTION_READINESS.
No apply/publish/assign/learning/source edits, no fresh full-row DB snapshot claim.
One prod/two DEV unexecuted synthetic previews retained existing TTL. Current file
is not historical byte proof; session history is not durable memory/command
authority/voice. Documentation closeout does not retag or redeploy3fe.

## Historical environment correction — native48/API47 and DEV48,2026-10-13

Production native frontend48/tag `v0.11.48` exact
`3609c8b31a506b1eb244ad62f335b2faf1544424`; canonical bridge
REL-GUIDE48-WEB-20261013, masterCI38395990168 and nativebuild38394888733 pass.
Production API/threeworkers stay47/source75d61a3857838f420d8ef8f4a7e3eb1bb270fac1,
image9f98e355…d8c8f; API47 public health independently checked. Intentional
frontend-only compatibility, no backend/DB0178/watchdog/flag/resource changes.
Native immediate rollback47/75d boundary-ready,46/f1f65 and359/299 preserved.
Only obsolete42 release/exact staging pair removed under standing rule; original
offhost recovery retained. No Proxmox, on-host build, topology/DNS or tier change.

Existing DEV frontend/API/worker exact3609/48, Hobby/Free/Free and9flags unchanged.
Vercel dpl_DTB3TaxwfubucUqUyGKfxiPdCDZ4; API dep-db71v93l550s73agn45g;
worker dep-db720arl550s73agptp0. Ordinary DEV QA identities below unchanged.
Guide/menu DEV and production live acceptance, scoped limits, initial failed
attempts and source identity owned by PRODUCTION_READINESS and Test Runner ledger.
Public Russian methodologist instruction `/guides/methodologist.html` is pinned
below logo only for active methodologist; public artifact contains synthetic
screenshots, no credentials/customer data. Documentation child does not retag or
redeploy native3609 and leaves DEV3609 intact. Older snapshots are historical.

## Historical environment correction — production/DEV47,2026-10-13

Production/DEV source `75d61a3857838f420d8ef8f4a7e3eb1bb270fac1`/0.11.47.
KZ API/threeworkers image9f98e355…d8c8f, native frontend exact75d; protected
38375015813 and native38371583217/canonical bridge verified. Existing schema0178,
backup/signedrestore and all3production flags unchanged. Immediate backend/native
rollback46f1f65 ready, actual switch NOT_RUN; native extra42/protected359/299
retained. Only exact obsolete38/39 and39staging removed with verified offhost
recovery under standing procedure. No topology/DNS/Proxmox/on-host build.

Existing DEV API/worker/Vercel exact75d, Free/Free/Hobby and all9 flags unchanged.
Render API dep-db6v1jaj9qps73alassg/worker dep-db6v2ic9v7es739u1so0 live;
Vercel dpl_AvBH2PA47Eo8gbv2rWK4siw4QRYS READY. Permanent DEV identities below
unchanged. No DEV admin credential created/reset; ordinary production QA admin
was tested. Browser help DEV37/prod50 PASS; source/role/error-recovery details and
limits owned by PRODUCTION_READINESS. All215 production QA rows/nine tables
unchanged; no new learning, mail/OTP, generation, policy or customer-data mutation.
Documentation-only closeout leaves runtime/tag75d unchanged; current statements
supersede historical46 snapshot below, not its retained quality measurements.

## Historical environment correction — production/DEV46,2026-10-12

Production API/threeworkers and native frontend exact
`f1f65c3de98ac2a6886a60498a3107c1c22218dc`/version0.11.46; schema0178 and existing
3flags ON unchanged. Protected backend38286173518 and native38284281979/ordinary
bridge pass. Runtime/backup/rollback and bounded multiformat acceptance are owned
by PRODUCTION_READINESS and the canonical course-quality benchmark, not by a
historical environment snapshot below. Backend previous45/8ad06921 and native
previous42/d415fd39 retained and independently ready; no actual rollback switch.
Existing older protected native releases also preserved; no cleanup or Proxmox.

DEV API/worker/Vercel exactf1f65, existing Free/Free/Hobby and all9flags unchanged.
Ordinary faithful PDF generation occurred onb06; actual unchanged AI/document/
generation/renderer Git objects and repaired certificate download/public verify
bind revised acceptance. Fixed DEV identity remains the persistent fixture
a7a2c055…/methodologist@kamilya-dev-qa.example.com and learner@kamilya-dev-qa.example.com,
using the existing documented password variable; similarly named env-email drift
must not silently select another tenant. No credentials/role/tier changes.
Free web-worker may sleep during long review: use readiness/reconcile-original
procedure DEV-WORKER-SLEEP-001, not keepalive resources or paid reactivation.
Existing completed production/DEV QA retained with unchanged nine-table old-row
hashes. No mail/OTP/signature or other project mutation. Documentation-only child
commits do not replace the deployed/tagged source SHA.

## Historical production39,2026-10-06 — bounded draft lesson correction accepted

Frontend/API/threeworkers exact `e355fdc6da82b1d276fbf182d37cc7f69ef30335`,
version0.11.39, schema0178 and all3flags ON independently read back. Protected
backend37409462508/deployment6875008426 and native REL-CORRECTION39-WEBB-20261006
passed; exact image0f741d44...f555. Ordinary methodologist browser proposal/apply/
receipt replay/manual edit/reload and review resets PASS; draft/no enrollment.
Wrong seal409, foreign resource/proposal404 and unchanged permanent-QA usage PASS.
Independent Test Runner J executed11 API readbacks; Release Runner reconciled
immutable supplied receipts locally, not independent external execution.
Timers/oneshots/watchdog39 and signed0178 restore RPO43/RTO19/cleanup PASS;
backend/native previous38 retained, actual rollback NOT_RUN. Obsolete frontend36
alone removed with verified offhost recovery, other releases/staging preserved.
No billing/resource/permission/topology/DNS/landing/customer-data changes.
Production decisions/fixture cleanup evidence are owned by PRODUCTION_READINESS;
this closes only the bounded Russian synthetic correction, not voice/whole product.
Documentation-only closeout commits do not replace the deployed source SHA.
Owned disposable tenant deleted204/fresh404; independent19-table/workflow/usage
absence and9unchanged permanentQA fingerprints PASS. Browser logged out. Tenant
login hourly20 was left intact; normal dedicated operator auth plus fresh exact
read-only owned inventory completed cleanup without an auth bypass.

## Historical correction DEV2026-10-06 — bounded live acceptance PASS

Existing Render API/worker and Vercel DEV frontend exact27a682ae9e38b7d4615dc00e7796cc670fd07c27
deployed after successful master/dev CI; public DEV schema0178 and all9 flags
verified. No provider plan/resource changes. Actual ordinary-methodologist source-
grounded proposal, explicit apply, same-receipt replays, later manual-edit
preservation/reload and draft/review markers PASS. Normal disposable cleanup204/
fresh404 plus independent17-table absence and9 unchanged permanent-QA fingerprints
PASS; browser logged out. Bounded acceptance hashbad3b4dd...a3e87; independent
Runner E reviewed supplied artifacts only. Speech/whole-product not accepted.
Protected native/backend flag contracts are local preparation. Fresh root
read-only production preflight confirms38/source370f56fb/image258acfa0/blue four
processes/schema0175/workbench+documentON/correction unsupportedOFF; no production
mutation. Exact contract links/evidence/frontier belong to the module index/plan.

## Historical correction DEV source promotion earlier2026-10-06

Exact e0bf8e65a1821cb1cc406bb0dc26bb4ef8b163a9 fast-forwarded to master;
independent remote readback/account record preserved. CI37399182927 completed
5SUCCESS/2failed dependency audits: source-map-js1.2.1 and multidict6.7.1.
Narrow successor pins1.2.2/6.9.1; frontend frozen install/audit/typecheck/lint and
928tests PASS, C-extension reference leaks20->0 per operator. Fresh successorCI
remains required before migration/activation. Existing Free/Hobby targets and
previous370f56fb API/worker exact identities were freshly verified; live Render
commands contain no Alembic. NonBYPASS READ_ONLY QA-before-B fingerprints cover
9 existing tables including2content releases,2enrollments and3attempts. This is
preflight, not an exercised rollback or public0178 proof. Production unchanged.

Canonical read-only DEV public-schema gate freshly found0175 and refused expected
0178; this is an explicit additive-upgrade gate, not an access failure. New local
DEV controllerV5 accepts correction flags with exact0178 receipt, complete9-flag
inventory and unchanged existing Free/Hobby targets. No provider writes or public
migration were executed. Owned synthetic learner-history proof27/35 source hashes/
exact cleanup/public-neutrality and independent local149/source16 PASS. Final
CI-only successor independently3 PASS with47 source bindings; no independent SQL execution or public-policy
equivalence is claimed. Existing production38 boundary below is a dated
release record, not fresh production readback. Exact contracts and execution
state are in the methodologist module index and approved AI-driven plan.

## Historical client38 boundary,2026-10-05 — RELEASED; bounded document acceptance PASS

Frontend/API/threeworkers version0.11.38/source
`370f56fb9e9ce9cdb173b7193e91dbd0f49675f1` deployed; schema0175 and both
workbench/document-draft flags are ON. Protected workflow37268909670,
deployment6852170372, image258acfa0...e54685; API+3workers/native frontend
blue/running/restarts0, public/private health, watchdog identity, timers and
oneshots PASS. Signed restore175 PASS (RPO44/RTO19), disposable restore DB/temp
cleanup PASS. Root bounded live draft/browser/source/replay/foreign404 checks
PASS. Independent Runner C readback/manual review PASS; frozen acceptance SHA256
`3b2b503ef7e6925440e2ce7a3493de68feac87ca2c779c3186e0c8ccf2c70e09`.
Normal disposable cleanup returned204/fresh404 and DB-after-cleanup confirmed
sixteen owned tables/workflow keys absent; retained QA history/course
fingerprints are unchanged. Browser session logged out and temporary viewport
reset. This is bounded document-draft acceptance, not whole-product or voice
acceptance. Exact-release sign-off belongs to the verified final root decision,
not this context summary. No rights, billing,
topology, landing or customer-data changes.
Detailed evidence belongs to `docs/PRODUCTION_READINESS.md` and the exact
`REL-DOCUMENT38-20261005` / `REL-DOCUMENT38-WEBB-20261005` evidence packets.

## Historical client37 boundary,2026-10-04

Frontend/API/threeworkers version0.11.37/source
`534ce7ef9a881e78a198e071c2cd79a55d39a9e0` deployed; schema0174 unchanged.
CI37182945835/native37183042764/protected37183317430 SUCCESS; protected imagea6c99741,
green4running/restarts0, public/private identity, worker control, FORCE RLS PASS.
Watchdog expects37/imagea6; retention/watchdog timers active, oneshots success0;
signed current174 restore and disposable drill absence PASS. Previous backend36/
image33b2/config retained. Frontend current37/previous36 and configured fallback35,
extras359/299 retained; only eligible obsolete34/exact staging pair removed under
standing recovery rule with offhost copies verified. No console/Proxmox or rights change.

Ordinary methodologist free-description and contextual deadline correction,
editable proposal/fresh server preview/human confirmation/receipt reload PASS;
exact1 assignment/no mail, persisted deadline and confirm replay/no duplicate PASS.
Atomic keyed publish/unpublish/replay/conflict PASS. Independent Test Runner7/7
ordinary role/receipt/release/foreign404/student403/retained100% history checks PASS.
Owned temporary tenant normal cleanup204/404 and ten-table+keys/module/lesson
absence PASS; retained QA14users/3courses/13enrollments and business fingerprints
unchanged. Acceptance is bounded to free-text-assignment/publication-idempotency,
not voice or whole-product AI quality. Existing DEV41e6849f/free tiers preserved;
no provider budget/tier/resource, DNS/landing/customer-data change. Details and
current gates belong to PRODUCTION_READINESS.md; docs-only commits are not runtime.

## Historical client36 boundary,2026-10-03

Frontend/API/threeworkers version36/sourceed349409d3385abdbceb65097bcc47c82fa27f4d
deployed. CI37135574141/native37135758994/protected37137457191 SUCCESS;
backend image33b2082a, blue4running/restarts0, public/privatehealth/schema0174/
FORCE-RLS/workercontrol PASS. Fresh signed174 restore and cleanup PASS;
watchdog36 and retention timers active/oneshots successful. TestRunner QA36F
ordinary retained learning/copy GET/history/localZIP PASS; Root actual browser
freshZIP handoff/acceptedcopy/100%/invitation controls/help PASS and exact retained
QA idempotentfalse PATCH200. Previousfrontend35 and packetrollback34/extras359/299
preserved; only obsolete successful32/exact staged pair removed, original offhost
recovery retained. Backendrollback29/96a and config backups preserved. No migration,
DEV deployment, new provider resource, plan/rights/DNS/landing or old learning reset.
QA stands are demo=false without global/RBAC/RLS/OTP/spend bypass. Mail simulation
accepted by owner; actual receipt NOT_VERIFIED. On2026-10-04 owner removed the
$1 test-run ceiling and authorized efficient paid testing. One fresh QA generation
completed in26.14s,1module/2lessons/2quizzes/4questions; diagnostics DeepSeek,
10chat attempts/no provider fallback. Root/TestRunner I source review bounded
PASS_WITH_OBSERVATIONS; not every source rule is assessed, no full-model claim.
New disposable source/draft cleaned by normal APIs; original history unchanged.
Existing provider/monthly budget untouched; actual cost/tokens unavailable.
LegalEDS NOT_TESTED; fullfeaturePARTIAL. Root gate-chain procedural defect
and fail-closed adapter documented DEPLOY-013; no retrospective preapprovalGO.
Readiness owns exact evidence and residual gates.

## Historical client35 boundary,2026-10-03

Frontend35/sourcef34eac00e79fcccbf3926627c23faac672c00edd deployed,
CI37123482507/native37123504506/protectedrelease PASS. TestRunner35A local862/
145files/build/type/lint PASS; corrected35B2 independent ordinary learning/
original history100%/certificate/PDF PASS. Root fresh34 real learner5lessons/
5quizzes/failure+retry/completion/certificate PASS retained; actual35 resultCTA
RU/KK/EN/click, quizhelp and sharedreader oneH1/mobile/desktop PASS. Active
bestscore live label/filehandoff/UIassignment/newPIN/token/mail/AI/voice/OTP/legal/
signed-copy/review/package notverified; legacyQA content semantics notaccepted,
not current model-quality proof. Full feature PARTIAL, not GO. Immediateprevious34,
packetfallback32/protected359/299 retained. Only obsolete31/exact staging pair
removed under conditional standing recovery rule; offhost pair retained. No more
cleanup; postboundaryfree907968KiB. API29/source32e/DB174/worker baseline unchanged,
no helper/runtime/access/tier/provider change. Readiness owns detailed current gates.

## Historical client34 boundary,2026-10-03

Frontend34/sourceb25653a2f30d0afdd3c81d8222ad1a38bf3753d7 deployed; exact CI37111000718/
native37111030285/protectedexecute/publicidentity and TestRunner34C ordinary-role/
retained-history/globalCSP PASS. Root actual canvas PDF bothadminroutes via menu,
1+2pages/accessibility/help/refresh/mobile/desktop PASS. File handoff NOT_VERIFIED;
full fresh learning-write/token/paid-AI acceptance stillPARTIAL. API29/source32e,
DB174/worker baseline unchanged. Actualprevious32/3f0f/extra31/572f/protected359/299
retained; only obsolete30/exact staged pair removed with verified offhost recovery.
No helper/Node/runtime/data/access/provider/tier changes. Readiness owns detailed
current gates; historical paragraphs below are not current runtime identity.

## Historical client32 boundary / candidate33,2026-10-03

Production frontend32/source3f0f120f1c5f5cd86af1c1e648272ad49a98e99c is deployed;
CI37105674665/native37105704341, exact protected technical and independent bounded
Test Runner C readback PASS. Immediate previous31/572f, extra30/d8ab/protected359/299
retained. Standing capacity rule removed only successful obsolete28/exact staged
pair after verified original recovery. Actual32 browser PDF remains blank; no full
feature GO. Candidate33 renders validated Blob bytes using locally bundled PDF.js,
restores restrictive global frame policy/Next navigation and updates freshly audited
frontend dependencies. No API/worker/DB/helper/data/access/billing changes. See
readiness for current gates; historical31 paragraphs below are not current identity.

## Historical client32 candidate boundary,2026-10-03

Production31 ordinary QA admin/student sidebar/read-only help coverage completed,
including zero-course learner state and browser admin-route denial. Live preview
returns200PDF but parent CSP blocks blob; exact-two-admin-route32 repair and PDF
type/signature guards are local only until the protected release. Role-safe links,
student refreshed API/retry/stale-result cleanup and RU/KK/EN help also integrated.
No new business/customer/provider/billing/credential writes. Full write/token/
paid-AI feature acceptance remains PARTIAL. Published31 remains immutable.

## Репозиторий и сервисы

Current frontend technical readback2026-10-03:0.11.31/source
572f0d9569dfbdce8dc662d5fc6bcf4a52f234a3, CI37099443141/native37099447416
SUCCESS, protected controller RELEASE_OK and independent public health/header
exact. Immediate previous30/d8ab25d6, extra rollback28/64c8bfeb and protected
359d7cda/299481ec retained. Only obsolete successful27/exact staging pair removed
under standing capacity rule with verified offhost recovery. Final client
acceptance PARTIAL: mobile wizard and operations natural-expiry31 SPA refresh
after16minutes PASS; remaining role/token/paid-AI journeys need separate proof.
API public health remains0.11.29/source32e1331d; no API/worker/DB deployment31.
Owner approved only two new ordinary QA admin/student accounts in retained
83552ce6-8058-4561-abe3-cfbda14e030a; random credentials stored only primary.env
PRODUCTION_SMOKE_ADMIN_*/PRODUCTION_SMOKE_STUDENT_*. Ordinary login and role
denials independently Test Runner E PASS; old users/enrollments unchanged,
no mail, existing password/PIN reset, tenant/plan change or new assignment.
Last independently verified2026-10-02: production backend0.11.29/source
32e1331d9b24621de71213ba1150375a261b0464, protected image96a1bc2c,
CT1250174, API+3workers ON; native frontend28/source64 was then live accepted.
Protected37032048857 rerun2 SUCCESS; exact owned A/B normal cleanup and independent
absence PASS, permanent QA history100%/certificate preserved. DEV29/0174 ON on
unchanged Free/Hobby tiers. Full identity/evidence: PRODUCTION_READINESS.md.
The compatibility paragraphs below are historical staged-release snapshots,
not current runtime evidence. No voice/LLM/STT or new paid resources enabled.

| Контур | Текущее размещение |
|---|---|
| Monorepo | `KamillaLMSCRM/Kamilya-NEW`, branch `master` |
| Production frontend | Native Next.js на CT137 `webkml` (текущее размещение: Proxmox node `pve3`); `https://app.kml.kz` через KZ proxy/WireGuard; exact release проверяется отдельно |
| Public marketing landing | Native Next.js на CT137, service `kamilya-landing`, internal Nginx `10.77.77.3:8080`; `https://kml.kz` и `https://www.kml.kz` через KZ proxy; exact source SHA проверяется отдельно |
| Dev frontend | Vercel project `kamilya-lms-dev`, branch `dev`, `https://kamilya-lms-dev.vercel.app` |
| Production API | FastAPI на VM126; публичный вход `https://api.kml.kz/api` через KZ proxy/WireGuard |
| Production PostgreSQL/pgvector | Native PostgreSQL 17 + pgvector на CT125, private-only path |
| Production files | Общий файловый runtime API/worker на VM126; backup отдельно |
| Dev/demo data | Supabase DEV/test PostgreSQL и Storage; не является production |
| Broker/cache | Valkey на VM126, наружу не опубликован |
| Background jobs | Три Celery worker на VM126: AI, documents и operations/notifications |
| Dev background jobs | `kamilya-lms-dev-worker` на Render Free Web Service; Supabase DEV и изолированный Redis DB `1`, очереди `ai,documents,maintenance`, concurrency 1, cold start; DB pool `2+0`, API pool `3+1`, общий максимум 6 из 15 session-mode подключений |
| Email | Resend, домен `notify.kml.kz` |
| Telegram | Kamilya bot/auth flow |
| Document conversion | Ограниченный локальный сервис: MarkItDown для Office/PDF с текстом, Docling для сканов/OCR, LibreOffice для старого `.doc` |

Supabase и Render используются только для разработки, интеграционных тестов,
контролируемой демонстрации или явно выбранного rollback. Production frontend,
API, worker, файловый runtime и PostgreSQL размещены в казахстанском контуре;
каждый из них сохраняет собственный release/backup/readback gate.

### Изолированный ASUS STT pilot — 2026-10-03

Владелец разрешил отдельный benchmark и указал актуальный источник доступа:
`C:\Hermes Workspaces\ASUS_LOCAL_ACCESS_STT_HANDOFF.txt`. Использовать именно
его локальную SSH-конфигурацию/alias, strict host checking; не старый WireGuard
маршрут, не VM126 executor и не credentials другого проекта. Перед повторным
запуском проверить текущую доступность/identity/capacity по этому handoff.

Verified на начало пилота: `gx10-d9c0`, `superuser`, aarch64/Python3.12.3,
NVIDIA GB10/driver580.159.03; available RAM116GiB, disk414GiB. Единственный
пилотный write root: `/home/superuser/projects/kamilya-stt-pilot-20261003`, свой
venv/cache/models/public corpus. Существующие проекты/venv/timers/services,
драйверы и ingress не меняются. No sudo, listening STT service или production link.
Известный book-service failure существовал до пилота и не относится к его scope.

Public Google FLEURS CC-BY-4.0 и MIT multilingual weights; inference offline,
внешнему ASR-провайдеру аудио не отправляется. CPU benchmark выполняется с одним
запросом/4threads. ARM `ctranslate2==4.8.2` wheel не содержит CUDA support; GPU
inventory не означает GPU execution. Production speech intake, QR microphone,
private-audio storage/TTL и новые платные ресурсы не включены. Packet/результаты:
[ASUS pilot V2](product/contract-modules/methodologist-workbench/contracts/ASUS_STT_PILOT_ADDENDUM_V2.md),
[текущий план](plans/2026-10-01_ai-driven-methodologist.md).

Render DEV API также работает на Free Web Service. Этот тариф не выполняет
`preDeployCommand`, поэтому schema-affecting DEV release до API/worker rollout
обязан пройти явный public-schema gate:
`<canonical-api-python> scripts/ops/dev_public_schema_gate.py --apply`.
Без точного readback `current_revision == repository head` DEV релиз считается
смешанным и останавливается.

Для кандидата methodologist-workbench с head0173 действует принятый
[двухэтапный контракт](product/contract-modules/methodologist-workbench/contracts/STAGED_COMPATIBILITY_RELEASE_ADDENDUM_V1.md),
compatibility A deployed on2026-10-02: `--workbench-phase expand --expected-revision 0169 --apply`
из0168 выдаёт только `EXPANDED_NOT_FINAL`; затем совместимый API/worker с
workbench OFF и независимая квитанция. Только после неё
`--workbench-phase contract --expected-revision 0173 --compatibility-evidence
<exact-root-receipt> --compatibility-sha <exact-compatible-release-sha> --apply`.
Default `--apply` не разрешает обойти этап совместимости. Финальный173 обязан
совпадать с head; промежуточный169 не является feature/isolation GO.

Исторический compatibility-A readback2026-10-02: DEV API/worker/frontend и KZ API/3workers
на exact23630036/0.11.26, оба DB-контура0169, workbench OFF. KZ frontend теперь
27/`30693e45e1338772bf09577461e3f7615d38a73b`, native CI36980536610;
независимый current/marker/public health совпадает. Native26 ранее остановлен
до переключения из-за sidecar-контракта; его исходные evidence сохранены.
Попытка административного обновления helper остановлена по замечанию владельца;
helper не установлен, doas/keys/TLS не изменены. Выпущен frontend-only27:
прежний восьмиполевой manifest плюс отдельный хеш-связанный build-config с
явным OFF, проверяемый до staging. Штатный путь не требует Proxmox.
Actual frontend rollback25/`3d1276443ad8735a5c0bf3dd029be5768c46ca6a` и
дополнительные359/299 сохранены. По отдельному явному подтверждению владельца
устаревший24 и его точные staging-дубликаты удалены с сохранением проверенной
внесерверной копии; свободно1463744KiB. Повторные одинаковые frontend-очистки
регулируются ограниченным standing rule в существующем native runbook.
Исходный неудавшийся пакет26 остаётся неизменным. Полный статус —
`docs/PRODUCTION_READINESS.md`. Root browser compatibility A: вход и сохранённое
завершение100%/действующий сертификат после reload PASS, OFF route возвращает в
обзор; business writes отсутствуют. Этот исторический snapshot относится к
A26/169/OFF и frontend27; current identity приведена выше и в readiness.

Последующий DEV readback2026-10-02: API/worker/frontend28 exact
`eb427100a53e96f45888203f6b46e8e9c24801a3`, public0172, три flags ON,
существующие Free/Hobby ресурсы. Реальный preview/confirm/replay/student/mobile
PASS; populated disposable tenant cleanup500 из-за TENANT-PURGE-004.
Принят [purge addendum](product/contract-modules/methodologist-workbench/contracts/POPULATED_TENANT_PURGE_RELEASE_ADDENDUM_V1.md):
кандидат0173/helper без новых прямых DELETE grants, DEV packetV3/0173 и
защищённый production169->173. Изолированный runtime gate
`scripts/ops/enrollment_purge_dev_gate.py --env-file <canonical-api-env>`
PASS12/cleanup/public-neutrality; public173 ещё НЕ применена и новый код НЕ
развёрнут. Normal API cleanup и новые exact-SHA DEV/production gates не закрыты.

На 2026-09-07 `kml.kz`, `www.kml.kz`, `app.kml.kz` и `api.kml.kz` направлены
DNS-only A-записями на KZ-IP `92.38.49.167`. Public proxy завершает TLS и по
WireGuard направляет лендинг и LMS frontend на разные внутренние listeners
CT137, а API — на VM126. `mail.kml.kz` остаётся отдельным почтовым контуром и
не изменялся при переносе web-ресурсов.

## Карта окружений и доступов

Текущий verified status2026-10-02: DEV API/worker/Vercel на
32e1331d9b24621de71213ba1150375a261b0464/version29, Supabase174, workbench ON;
worker/QA/browser gates PASS на существующих Free/Hobby. Production остаётся
64c8bfebf44a296281d0db3202deaa44bea36e84/version28/schema173/ON, nativefrontend28
не менялся. Protected37032048857 остановлен на docker pull timeout900s до
миграции/переключения. Independent old-runtime readback PASS; retention timer
восстановлен, watchdog old identity active. Authenticated GHCR manifest PASS;
основная причина задержки NOT_VERIFIED, токен не признан неисправным.
Normal synthetic A/B cleanup и final production acceptance остаются NO_GO;
fixtures сохранены, ручного owner DML нет. Исторические snapshots выше не current
truth. Полные gates — `docs/PRODUCTION_READINESS.md`; access/tariffs не менялись.

Этот раздел — краткий канонический ответ на вопросы «где взять доступ» и
«через какой узел идёт запрос». Значения токенов, паролей, private keys и DB URL
здесь не хранятся.

### Vercel: DEV и rollback

Vercel account/team: user `kamillalmscrm`, team
`kamillalmscrms-projects` (`team_EknCOCWEL771BUDea5UFM2Ba`).

| Назначение | Project | Git branch | Domain/alias | Состояние |
|---|---|---|---|---|
| Production rollback artifact | `web` (`prj_hJMzgp9QNFCwUMrsDEBZINpJJzBp`) | `master` | authoritative DNS не направляет `app.kml.kz` в Vercel | Сохранён для быстрого CNAME rollback; не является текущим runtime |
| Dev frontend | `kamilya-lms-dev` (`prj_JN1xM4BMmhoHzDt6joPaCBXvOSLk`) | `dev` | `kamilya-lms-dev.vercel.app` | Render DEV API `https://kamilya-lms-api.onrender.com/api` |

Канонический источник API-токена — корневой `.env`, имя `vercel_token`.

Для отдельного репозитория публичного лендинга provider credentials берутся
только из `C:\Kamilya New\kamilya-landing\.env.local`: GitHub token имеет имя
`github_landing_token`, Vercel token — `vercel_landing_token`. Не подменять их
`GITHUB_TOKEN` или Vercel credentials из `Kamilya-NEW`; перед mutation проверять
только наличие нужного имени без вывода значения.
Наличие одноимённой переменной в другом локальном env-файле не меняет источник
и не разрешает перебирать старые файлы.
Алгоритм работы агента:

1. проверить наличие имени переменной, не печатая значение;
2. загрузить значение в память процесса и использовать Vercel REST API с
   authorization header, а не передавать token в URL/CLI arguments;
3. перед мутацией прочитать project id, Git repository, production branch,
   domains, env targets и последний deployment;
4. после мутации повторно прочитать те же поля и проверить deployment exact
   SHA, состояние `READY` и HTTP/business smoke;
5. не использовать локальный `.vercel/project.json` как доказательство
   правильного проекта и не выполнять `vercel link` вслепую.

Dev project собирает только ветку `dev`; custom domain не назначен. Rollback
project `web` и его branch `master` нельзя менять в рамках dev-задачи. DNS
`app.kml.kz` управляется в Cloudflare и направлен на KZ proxy, а не на Vercel.
Vercel deployment содержит только committed Git SHA: dirty worktree туда не
попадает.

### GitHub

Для `KamillaLMSCRM/Kamilya-NEW` канонический credential — только
`GITHUB_TOKEN` из корневого `Kamilya-NEW/.env`; канонический account —
`KamillaLMSCRM`. Ambient/keyring account `askar0007amirkhanov` не используется
для push этого репозитория. Точная process-local auth/push-команда и правило
remote-SHA readback находятся в разделе «Git и release» файла `AGENTS.md` и в
`ERRORS.md`, `GIT-001`. После каждого подтверждённого push сохраняются только
repository, branch, local/remote SHA, account, имя credential path и timestamp;
значение token не сохраняется.

### Database verification

Общий Kamilya dev/test PostgreSQL-контур — Supabase DEV. На этой рабочей станции
не запускать PostgreSQL в Docker и не подменять им Supabase для integration,
migration или RLS evidence. Использовать только approved Supabase DEV isolation
и cleanup path; production CT125 остаётся отдельной release boundary. Локальный
Docker допускается для database-free image build/runtime probes. GitHub CI
service containers остаются частью отдельного CI-контракта.
`scripts/ci/critical_journey_gate.py` по умолчанию работает в профиле `local`:
он выдаёт только database-free pytest selectors, а DB-проверки оставляет
Supabase DEV application gate. Профиль `ci` разрешён только workflow, который
явно поднимает disposable PostgreSQL service и устанавливает его отдельный
CI-only признак; общий `db_session` останавливает workstation localhost URL до
попытки подключения. Bare `pytest`/`pytest -q` не является workstation release
gate: он обнаруживает DB integration suites. Локально использовать
`critical_journey_gate.py`, а DB-проверки выполнять отдельным approved Supabase
DEV application gate.

### Постоянный QA-стенд DEV

Владелец согласовал 2026-09-30 один постоянный synthetic tenant
`kamilya-dev-qa`. Его точные tenant/user/course/quiz/enrollment/attempt IDs
закреплены в `docs/testing/fixtures/kamilya-dev-qa.json`; это не customer tenant.
Состав: методолог, ученик, одна должность без автоназначений, два курса и два
personal-link назначения. Первый тест имеет одну неудачную попытку из двух,
второй — две из двух. Письма, AI-генерация и платные ресурсы не используются.

2026-10-03 владелец потребовал полноценные QA tenants без demo-ограничений.
У этого точного сохранённого DEV tenant `is_demo` изменён true→false через
штатный superadmin API; independent GET подтвердил false. Старый API29 вернул
500 уже после сохранения (исправление transaction boundary подготовлено локально),
PATCH не повторялся. Текущий внутренний plan free, настройки, лимиты и counts
стенда не изменены; provider Free/Hobby ресурсы не менялись. `dev_qa_stand.py`
теперь требует false и больше не создаёт урезанный demo-стенд. Это снятие именно
demo-ограничений, а не универсальный override всех feature flags, интеграций или
квот. Платная AI-генерация, email/OTP и остальные сценарии имеют отдельные gates.

Повторная API-проверка, из linked worktree каноническим root `.venv` Python:

```powershell
& 'C:\Kamilya New\Kamilya-NEW\.venv\Scripts\python.exe' scripts/ops/dev_qa_stand.py verify --expected-sha <exact-live-dev-sha> --evidence .release-evidence/dev/qa-verify.json
```

`verify` не создаёт и не удаляет tenant, пользователей, курсы, назначения или
попытки, не сбрасывает пароли и не исправляет drift. Допустимы только обычные
auth/session audit записи входа, GET API reads и одна READ ONLY транзакция
Supabase DEV как non-super/non-bypass `lms_app`. При missing/partial manifest,
несовпадении exact SHA, явно заданной revision, идентичности или состава — STOP, без
автоматического bootstrap/replenishment. После изменения схемы сначала обновить
контракт проверки, а не обходить gate. Для этого двухэтапного кандидата
`verify --expected-revision 0169` допустим только на принятом совместимом A,
`verify --expected-revision 0172` — на предыдущем B, `0173` — только после нового
purge-addendum B; отсутствие параметра по-прежнему
требует0168. Bootstrap остаётся0168-only; стенд не пересоздаётся.

Учётные записи: `methodologist@kamilya-dev-qa.example.com` и
`learner@kamilya-dev-qa.example.com`. Для этих двух synthetic QA identities
используется существующий `DEV_QA_METHODOLOGIST_PASSWORD` из канонического
primary `.env`, только process-locally; значения не сохранять в source/evidence.
Не менять пароль ранее существующей QA-учётной записи другого tenant.

Обычный браузерный smoke читает подготовленные состояния; не нажимать «Отправить
ответ», не завершать курс и не создавать action records. Сроки в fixture
фиксированные: с течением времени upcoming закономерно станет overdue; это не
повод автоматически менять дедлайн. Mutation journeys используют отдельно
разрешённые disposable fixtures. Стенд остаётся намеренно, его удаление требует
отдельного разрешения. Worker task execution не доказывается этим read-only
smoke: recurring materialization может отправить уведомление и в данном scope
не запускалась.

Зона `kml.kz` использует authoritative nameservers Cloudflare
`sureena.ns.cloudflare.com` и `syeef.ns.cloudflare.com`. Vercel verified domain
не означает управление DNS-записями: Vercel DNS records для зоны пусты. DNS
нужно менять только через подтверждённый Cloudflare account/API.

### Управляющие каналы VPS и Proxmox

| Target | Канонический источник доступа | Назначение и граница |
|---|---|---|
| Public proxy VPS, reachable target `92.38.49.167` | `C:\Kamilya New\.env`: `PROXY_VPS_HOST`, `PROXY_VPS_LOGIN`, `PROXY_VPS_PASSWORD` | SSH к proxy; target и host key проверяются до auth, пароль не выводится и не передаётся аргументом |
| Proxmox API | корневой `.env`: `VPS_URL`, `PVE_API_TOKEN_ID`, `PVE_API_TOKEN_SECRET` | VM/CT metadata и только явно разрешённые API/QGA operations; не является guest SSH |
| Legacy/общий VPS доступ | корневой `.env`: `VPS_LOGIN`, `VPS_PASSWORD`, `vps_root_password` | использовать только после точного сопоставления target; не подставлять для proxy/VM126/CT125 по догадке |
| Guest VM126/CT125 | подтверждённый host-specific SSH/WireGuard path | routine administration; если путь не подтверждён, это access gap, а не разрешение искать пароль |
| CT137 frontend | Proxmox node `pve3`; guest IPv4 `192.168.1.237`; WireGuard peer `10.77.77.3/32`; одноразовый bootstrap через Proxmox console | Routine path: proxy -> restricted key `kamilya-admin@10.77.77.3`; password auth отключён; отдельные exact helpers для web и landing. Frontend: `scripts/ops/ct137_native_deploy.py`, [runbook](runbooks/ct137-native-frontend-deploy.md); для штатного обновления вход в Proxmox не нужен |

Состояние на 18.08.2026: SSH-аутентификация к public proxy подтверждена,
`wg-quick@wg0` active, `10.77.77.2:8000/health` отвечает 200. На proxy создан
host-specific key `/root/.ssh/kamilya-vm126-admin`; через однократный
Proxmox/QGA bootstrap его public key установлен непривилегированному
пользователю `kamilya-admin` на VM126. Цепочка proxy ->
`kamilya-admin@10.77.77.2` с проверкой host key и `sudo -n` подтверждена.
`PermitRootLogin no` сохранён, ненужная копия ключа из root authorized_keys
удалена. Routine administration выполняется по SSH/WireGuard; console и QGA
остаются recovery/bootstrap-каналами, а не обычным способом deployment.

После двух последовательных ошибок одного доступа агент останавливается по
правилу `AGENTS.md`. Запрещено проверять старые `.env`, backup-файлы, соседние
репозитории, другие логины/пароли/порты или обходить host-key verification.
Встроенная Proxmox console/noVNC допускается только для явно разрешённого
bootstrap/recovery; она не является обычным способом deployment.

Историческое provider-имя `vds36463.vpsza500.kz` на 17.08.2026 возвращает
NXDOMAIN. Рабочий SSH/HTTP target берётся из `PROXY_VPS_HOST`; нельзя снова
переключаться на неразрешаемое имя. На 18.08.2026 новый Proxmox API token
подтверждён чтением VM126 и QGA `agent/info`; значения token id/secret в
документации и логах не сохраняются.

### Трафик: текущее состояние

```text
Production browser
  -> kml.kz / www.kml.kz / app.kml.kz
  -> Cloudflare DNS-only A 92.38.49.167
  -> proxy Nginx / TLS
  -> WireGuard -> CT137 Nginx
       app.kml.kz -> native LMS Next.js on 127.0.0.1:3000
       kml.kz/www.kml.kz -> native landing Next.js on 127.0.0.1:3001
  -> https://api.kml.kz/api
  -> proxy/WireGuard -> VM126 FastAPI/workers/Valkey/file runtime
  -> private DB path -> CT125 PostgreSQL/pgvector

Dev browser
  -> kamilya-lms-dev.vercel.app
  -> Vercel project kamilya-lms-dev / dev
  -> https://kamilya-lms-api.onrender.com/api
  -> Render DEV FastAPI
  -> https://kamilya-lms-dev-worker.onrender.com/
     wakes the free DEV-only Celery consumer for queues ai,documents,maintenance
     -> isolated DEV Redis DB 1 -> Supabase DEV

KZ production management/ingress path
  -> public proxy VPS (TLS/Nginx + WireGuard hub 10.77.77.1)
  -> app.kml.kz -> CT137 / 10.77.77.3
       native Next.js + Nginx, no Docker
  -> kml.kz / www.kml.kz -> CT137 / 10.77.77.3:8080
       separate native Next.js landing service, no Docker
  -> api.kml.kz -> VM126 / 10.77.77.2:8000
       API + Celery workers + Valkey + local file runtime
  -> private embedding replica pool:
       VM126 -> KZ hub / 10.77.77.1:18003, 18001, 18004
       -> ASUS connector / 10.77.77.4 on the same relay ports
       -> Qwen embedding runtimes / 10.66.66.25, .15, .7:8001
  -> private Qwen 3.8 generation fallback:
       VM126 -> KZ hub / 10.77.77.1:18002
       -> ASUS connector / 10.77.77.4:18002
       -> Qwen 3.8 runtime / 10.66.66.30:8888
  -> private DB path
  -> CT125: native PostgreSQL 17 + pgvector + encrypted backup
```

Для KZ production подтверждены API/worker/broker/file runtime на VM126 и database,
RLS, backup/restore на CT125. На proxy добавлен отдельный virtual host
`api.kml.kz`, который через WireGuard проксирует на `10.77.77.2:8000`.
17.08.2026 в authoritative Cloudflare создан DNS-only A-record на proxy,
выпущен сертификат Let's Encrypt, открыт HTTPS listener `443`, HTTP настроен на
redirect и внешний HTTPS `/health` вернул 200. После tenant/business smoke и
подготовки rollback production environment Vercel project `web` переключён на
`https://api.kml.kz/api`; новый deployment `dpl_5fYKAQhbzgDT3PfpmtvopJq8hre5`
имеет состояние `READY` и собран из того же exact SHA
`69ef25c3383ddd35443e621618c640d708c867ba`, что и предыдущий frontend.
Render/Supabase остаются dev/demo-контуром и не являются production backend
для `app.kml.kz`.

13.09.2026 production embedding route расширен до трёх приватных реплик.
Documents worker последовательно использует listener-ы `10.77.77.1:18003`,
`:18001` и `:18004`; KZ proxy выполняет только внутреннее проксирование к
WireGuard peer `10.77.77.4`, который передаёт запросы на Qwen embedding runtime
`10.66.66.25:8001`, `10.66.66.15:8001` и `10.66.66.7:8001`. Для каждого пути
из VM126 подтверждены model discovery и один конечный 4096-мерный вектор.
Публичный embedding hostname не нужен.

12.09.2026 тем же отдельным peer добавлен приватный маршрут к
`qwen3.8-flash-next`: VM126 обращается к 10.77.77.1:18002, а ASUS connector
передаёт запрос к 10.66.66.30:8888. Из VM126 подтверждены `/v1/models` и
реальный `/v1/chat/completions`. Старый публичный `qwen.kml.kz` не входит в
пользовательскую цепочку генерации и больше не является runtime-зависимостью.

### Действующая production-схема после frontend cutover 2026-09-07

Vercel сохранён как rollback artifact. Текущий production frontend работает на
CT137; API/worker/database topology не менялась:

```text
app.kml.kz
  -> Cloudflare DNS-only A 92.38.49.167
  -> proxy Nginx/TLS
  -> WireGuard 10.77.77.1 -> CT137 10.77.77.3
  -> native Next.js release
  -> api.kml.kz on the same public proxy
  -> WireGuard 10.77.77.1 -> VM126 10.77.77.2:8000
  -> VM126 API/workers/storage runtime
  -> CT125 PostgreSQL/pgvector по private-only DB path
```

Проверенный frontend baseline: exact Git SHA
`e463527cd8f5e67e987c44d8d769f337714bd25f`, Next.js `15.5.23`, native
Node.js/OpenRC без Docker. `app.kml.kz/healthz` и `/login` вернули HTTP 200;
synthetic production methodologist открыл `/dashboard` без page errors или
failed API requests. WireGuard, приложение и Nginx поднялись после restart.
Let's Encrypt renewal переведён на `webroot`, `certbot.timer` enabled/active.
Rollback CNAME и Proxmox snapshot `pre-kml-web-e463527c` сохранены. Подробный
release/rollback порядок — в `PRODUCTION_FRONTEND_RUNBOOK.md`.

Проверенный landing baseline: exact source Git SHA
`e70534f4814fd743edef16363d7393361fe874c7`, source archive SHA-256
`3c96987351c2fb763305e361c476ed24b60d4d6cf50aabf24f64cd8f443698ba`,
Next.js `15.5.23`. Сервис `kamilya-landing` слушает только
`127.0.0.1:3001`; CT137 Nginx публикует его в WireGuard на
`10.77.77.3:8080`. Public proxy обслуживает TLS/redirect для
`kml.kz`/`www.kml.kz`. RU/KK, robots, sitemap, lead validation, CSP, desktop и
mobile прошли production readback. Внешняя аналитика без согласия не
загружалась. `mail.kml.kz` и MX не менялись.

Cutover подтверждён внешним `/health`, production login bundle, API login,
`/users/me`, courses, documents, training log и staff-structure smoke под
контролируемой учётной записью tenant `too-lombard-sandyk`. CT125 имеет schema
head `0111`, private runtime roles без SUPERUSER/BYPASSRLS и активный ежедневный
encrypted backup. Render/Supabase сохранены как dev/demo-контур и rollback
destination; смешивать их очереди, данные или storage с KZ production нельзя.

19.08.2026 отдельно подтверждён исторический candidate assessment production
flow на прежнем Vercel frontend с manager/public candidate routes на SHA
`7b44f11`; VM126 API и
workers работают на image `kamilya-api:db797fd`, CT125 остаётся на `0111`.
Полный disposable journey на опубликованном release tenant Sandyk прошёл от
создания кампании и protected link/PIN до consent, результата и CSV; candidate
не создаёт staff user. Все synthetic записи после проверки удалены. Candidate
retention timer включён, активен и имеет последний успешный recovery run.

## Исторический Render/Supabase baseline (dev/demo fallback)

Application release `c4a5eb8bf58989eff4f4338272dc68941bd416bd`
был production baseline на 2026-08-06 и после KZ cutover сохранён только как
историческая dev/demo/rollback-точка:

- GitHub CI `31092967471` passed; production smoke `31092967755` passed;
- Vercel deployment `dpl_AYjE7QGd1n9hRv5tARDfvYx1WUAP` READY;
- Render deployment `dep-d9q623bm8hqs73e1r40g` live, health HTTP 200;
- VPS checkout `/opt/kamilya-worker` на exact application release;
- три Celery nodes `fast`, `documents`, `ai` отвечают и потребляют только свои
  очереди; AI concurrency 2, document concurrency 1;
- API допускает не более двух активных AI-задач на tenant; третья получает
  стабильный `429` с `Retry-After`, а UI показывает очередь только своей компании;
- converter routing `1.2`: digital PDF/Office идут через MarkItDown, сканы
  через Docling OCR; тяжёлая конвертация ограничена одним процессом;
- Architect/Writer удерживают взаимно исключающие границы уроков по всему
  курсу, а OCR lexical fallback приоритетно использует точные заголовки
  разделов;
- watchdog каждые пять минут проверяет сервисы, три worker и глубину очередей;
- dev/test Supabase остаётся текущей БД; KZ DB/storage для коммерческого клиента
  является отдельным release gate.

Проверка 50 одновременных digital-PDF запросов к converter прошла без ошибок.
Это не подтверждает SLA для 50 многостраничных сканов или 50 одновременных
генераций курсов. Проверенные пределы и расчёты находятся в
[`INFRA_CELERY_WORKER.md`](INFRA_CELERY_WORKER.md).

Технический и прикладной P0 закрыты для контролируемого первого pilot.
Отдельные условные gates сохраняются для SCORM, kiosk, KZ data residency и SLA
массовой нагрузки. Полный список находится в
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

## Роли

| Роль | Ответственность |
|---|---|
| `superadmin` | Платформа, tenants, AI providers, операционные действия |
| `admin` | Организация tenant, системная команда, интеграции и доступы |
| `methodologist` | Источники, курсы, тесты, сотрудники, правила обучения, назначения, результаты |
| `student` | Обучение, тесты, программы и сертификаты |

Удалённые роли `teacher` и `org_admin` не поддерживаются. Один пользователь
может иметь несколько назначенных ролей, но в сессии выбирает одну активную
роль. Навигация и API не объединяют полномочия всех ролей.

Канонические границы:

- tenant admin не создаёт курсы, тесты, обучающихся и назначения;
- methodologist владеет staff import, приглашениями и журналом обучения;
- `/admin/team` содержит только системную команду tenant;
- `/admin/enrollments` является legacy redirect, а не отдельной функцией;
- superadmin не получает tenant-возможности без контролируемого tenant context.

## Основные продуктовые потоки

### Регистрация tenant

1. Компания заполняет `/register-tenant`.
2. Если переход выполнен с публичного лендинга, UTM-метки, CTA-источник и
   referrer передаются в API и сохраняются в настройках tenant, lead и audit.
3. Создаются tenant, первый `admin` и trial limits.
4. Вход выполняется по email OTP через Resend или настроенному Telegram-flow.
5. Администратор создаёт системного пользователя с ролью `methodologist`.
6. Admin onboarding завершается после формирования системной команды; учебные
   шаги показываются только methodologist.

### Подготовка структуры

1. Методолог открывает `Сотрудники и структура`.
2. Сотрудники добавляются вручную или через Excel/CSV preview и mapping.
3. Backend нормализует `Department -> Position -> User`.
4. После commit отображается организационная структура.
5. Правила организации, отдела и должности материализуют назначения через
   общий recompute kernel.

### Курс из документов

1. Методолог загружает документы в каноническую библиотеку.
2. Ingestion извлекает текст и embeddings.
3. Совместимость источников проверяется до генерации.
4. Методолог выбирает один смысловой кластер либо явно задаёт цель объединения.
5. Для нового курса backend tenant-scoped проверяет, не использованы ли уже
   выбранные источники. Повторное использование требует явной причины до
   резервирования лимита; существующий draft с `course_id` продолжает штатную
   регенерацию без этого gate создания нового курса.
6. AI job создаёт независимый draft курса и тестов с трассировкой к источникам
   и, при повторном использовании, сохраняет `reuse_reason` в provenance.
7. В списке курсов непроверенный AI-draft имеет статус **Требует проверки**:
   прямое действие публикации недоступно до явного одобрения методологом.
8. Методолог проверяет, редактирует, одобряет и затем публикует курс.
9. В редакторе AI-помощник может дать read-only рекомендацию аудитории по
   текущей структуре tenant. Рекомендация не создаёт назначения или правила;
   для опубликованного курса она только ведёт на контекстный экран
   `/assignments?course_id=...`.

### Должностная инструкция

1. Инструкция привязывается к должности.
2. Из неё создаётся отдельный grounded-курс с provenance/version.
3. Курс входит в профиль квалификации должности.
4. Назначения пересчитываются для сотрудников этой должности.

### Отраслевая заготовка для финансовой организации

1. Методолог открывает карточку заготовки из списка курсов и выбирает русский
   или казахский вариант.
2. Версия `2026.1` создаёт обычный tenant-scoped draft: один модуль, восемь
   тематически разделённых уроков, восемь тестов и шестнадцать вопросов.
3. «70% готово» является продуктовой оценкой базового содержания, а не
   юридической оценкой соответствия. Оставшиеся восемь обязательных пунктов
   описывают системы, данные, доступы, удалённую работу, носители, проверку
   операций, канал инцидентов и различия филиалов/ролей конкретной компании.
4. Методолог может выбрать готовые документы своего tenant как источники для
   проверки. Их текст не вставляется автоматически и выбор не означает
   юридической экспертизы.
5. Повторное безопасное заполнение обновляет только неизменённый draft. Если
   структура или текст уже правились вручную, дальнейшая работа выполняется в
   редакторе курса без автоматической перезаписи.
6. Одобрение блокируется до 100% checklist. Затем действуют обычные review,
   publish, immutable release, assignment и evidence-контуры.

### Доставка и подтверждение

1. Отдельный курс назначается из карточки курса или сотрудника либо
   автоматическим правилом организации, отдела или должности.
2. Программа назначается человеку, группе, отделу или должности; cohort хранит
   только состав аудитории.
3. При подтверждении ручного назначения backend создаёт Enrollment, а для
   существующего сотрудника без подтверждённого способа входа создаёт связанную
   `UserInvitation` без второго `User`. Ссылка создаётся строго по выбранному
   `user_id`; нормализованный email уникален внутри тенанта. Bulk endpoint
   ставит доставку ссылки в Celery. UI показывает delivery status и сохраняет
   персональную ссылку для manual fallback при недоступном provider/broker.
4. Обучающийся открывает ссылку, проверяет кадровые данные в режиме чтения и
   подтверждает рабочий email шестизначным OTP. ФИО, табельный номер и пароль
   повторно не вводятся. Неверный или истёкший код показывает ошибку на том же
   экране и не сбрасывает пользователя на общий login. Успешная проверка
   создаёт access-сессию и защищённую refresh-cookie, после чего открывается
   единственный назначенный курс либо кабинет обучающегося.
5. Проходит уроки и обязательные тесты. После результата теста может вернуться
   в тот же курс или, при успешной попытке, сразу открыть следующий урок.
6. Backend сохраняет прогресс и завершает курс идемпотентно.
7. При выполнении условий выдаётся сертификат. В момент выдачи фиксируются имя
   сотрудника, название курса, настройки эмитента, срок действия и версия
   PDF-шаблона. Последующее изменение настроек tenant не меняет уже выданный
   документ.
8. Журнал обучения показывает назначение, его источник, прогресс, результат и
   доказательство.

### Процедуры, restricted share и retention

1. Methodologist создаёт versioned tenant procedure в `draft`, заполняет
   approval, legal/local basis, confirmation method и retention metadata.
2. `internal_attestation` нельзя активировать без snapshot rules состава,
   quorum и записи решения; `admission_decision` — без authority, записи
   решения и effective date. Это configuration gate, не workflow решения.
3. Generic evidence create/correction отклоняет `training`, `knowledge_check`,
   `internal_attestation` и `admission_decision`: system и regulated события
   создаются только соответствующим доверенным workflow.
4. Evidence share материализует точные PDF/ZIP bytes, SHA-256 и source event
   ids; ссылка имеет expiry <= 31 дня, download cap, revoke, Redis rate limit и
   non-PII access log.
5. Retention policy задаётся по procedure type. Dry-run/manual purge ограничен
   `max_roots <= 100`, использует persistent tenant cursor и не удаляет active
   legal hold или активную share-ссылку.
6. Scheduled purge и backup retention остаются backlog.

Сертификат формируется в A4 landscape, содержит номер, даты, QR-код и
каноническую ссылку `/verify/certificate/{number}`. Публичная проверка не требует
авторизации и возвращает только данные, напечатанные на сертификате, и статус
`active`, `expired` или `revoked`; email, внутренние идентификаторы и служебная
причина отзыва наружу не выдаются. PDF хранится с версией шаблона и SHA-256,
поэтому восстановление из storage выполняется только из снимка на момент выдачи.

Администратор tenant настраивает эмитента, подписанта, срок и примечание и видит
реальный PDF-предпросмотр без сохранения тестового сертификата. Методолог может
необратимо отозвать сертификат в tenant-контуре; операция и внутренняя причина
фиксируются в журнале аудита.

Меню методолога организовано по рабочему маршруту: источники и создание курса,
назначение, сотрудники, затем результаты. `/staff` и `/cohorts` находятся рядом
в разделе сотрудников, но остаются разными доменами: структура хранит штат и
иерархию, а cohort — только повторно используемый состав аудитории.
`/assignments` является видимым каноническим экраном назначения и доступа;
контекстные ссылки из курса и сотрудника лишь предзаполняют его. Самостоятельные
пункты `/competencies`, `/training-rules` и `/invitations` скрыты и открываются
из должности, отдела или сотрудника. Отдельное назначение `Quiz` не используется:
тест урока наследует доступ назначенного курса.

## Ключевые технические инварианты

- Каждая tenant-сущность имеет `tenant_id`, backend-проверку и RLS/FORCE RLS.
- Runtime использует роль БД без `BYPASSRLS`; миграции используют отдельный URL.
- Course/user/position/document IDs валидируются в текущем tenant.
- Завершённое обучение не удаляется при изменении автоматического правила.
- Повторный recompute не создаёт дублирующее назначение.
- Сертификат создаётся backend и идемпотентно.
- Несвязанные документы не смешиваются в один курс молча.
- При отсутствии релевантного источника grounded generation останавливается.
- AI generation и document ingestion показывают состояния queue/running/error,
  stalled и безопасное повторение действия.
- `/admin/super/operations` доступен только superadmin и показывает агрегаты
  очереди, документов, DB pool и процесса без tenant PII.
- Секреты хранятся только в `.env` и provider secrets.

## Локальная среда и секреты

- Локальный `.env` находится в корне репозитория и игнорируется Git.
- Runtime и migration DB URLs разделены.
- Render, Vercel, GitHub, Resend, Supabase и VPS credentials не печатаются в
  документацию или логи задачи.
- Перед добавлением новой переменной проверяется `.env.example`; значения не
  коммитятся.

## Правило документации

После изменения поведения:

1. обновить `PROJECT.md` или внутреннюю документацию;
2. обновить пользовательское руководство, если меняется UI/flow;
3. обновить ADR, если меняется долговечное архитектурное решение;
4. обновить `PRODUCTION_READINESS.md`, если меняется release gate;
5. обновить `PRODUCT_BACKLOG.md`, если задача открыта или закрыта;
6. не создавать отдельный исторический отчёт, дублирующий эти документы.
## Current exact KZ release — 2026-08-24

- `GIT-DERIVED`: backend application release
  `d17a9206086d8557f797a13563353c406d0ce9f4`; GitHub CI run `32743293275`
  passed all backend, unit, PostgreSQL 17 + pgvector RLS, release/security,
  frontend, quality and secrets jobs.
- `RUNTIME-DERIVED`: VM126 API and all three application workers use
  `kamilya-api:d17a9206086d`; public and private `/health` report
  `kz-production` and the full release SHA. All four application containers are
  running with zero restarts and no error-pattern matches after deployment.
- `RUNTIME-DERIVED`: live Alembic remains `0131 (head)`. This release did not
  run a migration and did not change CT125, tenant data, blob data, Valkey,
  Docling or the frontend. The prior exact release
  `760eeb72cac972a9ff2b2763d770f9cfc31d15eb` remains available as the rollback
  image and source directory.
- `RUNTIME-DERIVED`: the exact-SHA public endpoint verifier passed. A
  no-credential, no-file probe of `/api/v1/documents/upload` returned the
  expected HTTP 401 instead of edge HTTP 503 and created no application data.
  The first authenticated production upload is intentionally deferred to the
  owner-controlled synthetic tenant rehearsal.
- `RUNTIME-DERIVED`: the VM126 operational watchdog now expects the exact new
  SHA and image; its service and timer are successful, enabled and active.
- `BLOCKED`: the current push-capable GitHub PAT cannot read or update repository
  Actions Variables (`HTTP 403`), so no provider variable or manual workflow
  dispatch was changed. Scheduled `production-smoke.yml` does not consume that
  variable; it continues its independent public endpoint check.
