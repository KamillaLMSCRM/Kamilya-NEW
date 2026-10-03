# Production client acceptance and tool-efficiency epic

Owner: root. Date: 2026-10-03, Asia/Qyzylorda (+05).
Owner request: stronger CodeGraph rules; live all-declared-feature/screen/help/
control/UX acceptance; accumulate repairs in one release package and deploy;
measure actual use of CodeGraph, Graphify, selective ECC and CodeBurn.

## Scope and truth

- Repository: Kamilya-NEW only; writer daily-learning-20260930,
  feature/methodologist-workbench-20261001, starting0a52b99f6d7edfe7b8f1f96d1d17f2bf6cecc47b, clean.
- Primary coordination anchor: master6cb22874c16973530950c7a53b76e84d829ae177,
  clean/aligned at initial guard. No direct primary source editing.
- Production UI app.kml.kz; API api.kml.kz; canonical release/runbook paths only.
  Last documented backend29/source32, frontend28/source64, schema174 are historical
  inputs until fresh readback. DEV used only for approved existing-tier verification.
- No landing/other repository changes, OS/model installations, global hooks/MCP,
  billing change, customer mutation, reset of retained QA, or blanket cleanup.
- Root begins production read-only. Business mutation tests require a named
  synthetic fixture packet with preservation/cleanup; generic "full test" does
  not authorize real customer actions, paid calls or external mail.

## Ownership and dependencies

| Scope | Writer / executor | Reviewer |
|---|---|---|
| Governance/runbook, integration, release | root | independent bounded reviewer |
| Source screen/control/help inventory | production_ui_inventory, read-only | root live verification |
| Tool baseline/methodology | tool_efficiency_inventory, read-only | root |
| Regression evidence/UX ledger | Test & Evidence Runner on exact packet | root |
| Prepared deterministic release packet | Release Runner on exact packet | root production readback |

`RULES -> REGRESSION -> RELEASE -> LIVE-RETEST`

`UI-CATALOG -> LIVE-AUDIT -> REPAIR-BATCH -> REGRESSION`

`TOOL-BASELINE -> MATCHED-NAVIGATION -> TOOL-CLOSEOUT`

## Nodes

| Node | State | Exit gate / evidence |
|---|---|---|
| RULES | PASS30 | Useful mandatory CodeGraph rules, freshness/fallback/exclusions and deterministic checks published on masterd8ab25d6 |
| UI-CATALOG | IN_PROGRESS | Finite declared-feature/role/route/control/help matrix; static != live proof |
| LIVE-AUDIT | IN_PROGRESS | Fresh exact runtime + role/tenant identity; per-control outcome/help/purpose/accessibility, desktop/mobile, failures retained |
| REPAIR-BATCH | IN_PROGRESS | Reproduced observations, bounded owned fixes + regression tests; no unrelated feature/voice release |
| REGRESSION | PASS30;31_PENDING | Frozen C825web/9Node/141Python and all local gates PASS; tiny31 needs fresh frozen matrix |
| RELEASE | TECHNICAL_PASS30;31_PENDING | Exactd8/CI/native/protected controller/public identity PASS; original receipts retained; no tier change |
| LIVE-RETEST | PARTIAL | Mobile wizard guards PASS but valid Next premature validation found;31 required; missing role/token/AI journeys not PASS |
| TOOL-BASELINE | IN_PROGRESS | Version/scope/cold+warm timing/output/usefulness/correction metrics and real token availability |
| MATCHED-NAVIGATION | PARTIAL | Known-file lookup/consumer discovery pilot complete; presence oracle only, asymmetric rg path knowledge, truncation/freshness disclosed |
| TOOL-CLOSEOUT | NOT_STARTED | Root+children accounting; no estimated API USD == subscription saving; current-turn PARTIAL until finished |

## Execution notes

- Natural-expiry30 SPA test at04:50-04:53Z: operations failed, tenant overview
  then loaded count10 without reload/login, revisit operations loaded. Canonical
  transport recovery works on overview; operations rawfetch was a missed shared
  consumer. No cleanup/recovery/requeue mutation. Frozen31A intentionally stopped
  before matrix completion; all15 source hashes unchanged, ownership released.
  CodeGraph exact-file apiFetch callers7/26ms/nontruncated:4preview/load and3
  explicit mutation calls, independently confirmed in source. Extend31 before
  replacement full gates; no claim of complete long-session acceptance yet.

- Initial browser connection timed out once; fresh reconnect succeeded, created
  production login tab. Browser/tenant sessions are root-owned, never parallelized.
- Selected ECC means existing deterministic release bridge and scoped-retrieval/
  compact-handoff patterns, not assumed full plugin activation.
- All agent packets and handoffs English-only; no more than two independent leaf
  workers. Raw credentials/session payloads excluded from evidence.

## Completion gate

One complete repair/release package, final production per-screen/control/help
coverage with explicit gaps and safe fixture cleanup; tool measurements attached.
Move durable results to canonical readiness/runbook/UX/test ledger and remove this
temporary plan only after the required nodes actually close.

## First production UI pass (root, 2026-10-03; not final acceptance)

Fresh public identities: frontend64c8bfebf44a296281d0db3202deaa44bea36e84 /
version28; API32e1331d9b24621de71213ba1150375a261b0464 / version29.
Normal methodologist identity and retained synthetic tenant
83552ce6-8058-4561-abe3-cfbda14e030a independently verified. Retained completed
enrollment9118bc66-7a3e-42c5-ac5b-e78939855856, predecessor
da07381b-9346-4c34-a28e-376cb2b1c111 and existing PDF preserved.
These observations do not exercise writes or establish full journey PASS.

| Screen | Exercised safe controls / finding | Disposition |
|---|---|---|
| Dashboard | Help open/close; metrics/attention read; help heading mismatch, API jargon and wrong below-reference | Copy repaired locally; final live pending |
| Workbench | Default-example preview returns clarification; no confirm; no H1/help, example is actual initial value, RU-only UI | Local localized blank-input/H1/purpose repair; final live pending |
| Documents | Upload and YouTube dialogs open/cancel, required-input disabled; lifecycle tabs, help | Misleading no-documents on filtered/attention/deleting tabs repaired; source-actuality help corrected |
| AI generation | Synthetic source preflight; advanced/module fields; help; generation NOT RUN | Accessible audience/language labels repaired; external AI execution gated |
| Courses | Create and SCORM dialogs open/cancel; published action disclosure; no publish/archive | Accessible labels and blank-title disabled repaired; detail/templates still pending |
| Quizzes | Create/settings/question dialogs open/cancel, quiz questions read, help | Labels and configured time-limit copy repaired; whitespace-title regression found and being repaired |
| Learning programs | Existing published program all four steps, four audience modes, summary, help | Published immutability clear; no new version/assignment |
| Assignments | Existing course/current and completed lists, email/PIN mode timing, reminder status GET, help | No recipient submission/reassignment/delete/access-link issue; delivery/link/absolute deadline help corrected |
| Learning cycles | Course/program target switching, completed-period deadline-history GET, help | Program prerequisite and deadline-history empty-state repaired; loading/error empty-hint guard being repaired |
| Staff | Structure; manual form open/cancel; import stages, no file; help | Distinct new department/position labels and adaptive-import help repaired |
| Positions/detail | Create open/cancel; existing synthetic card all five tabs; upload chooser no file | Missing help and nested nav repaired locally; existing profile/competencies/rules/history untouched |
| Cohorts | Existing group selection, membership read, help | Help incorrectly implied direct course assignment; corrected to programs/rules |
| Candidate assessments | Campaign fields and published-course options; create disabled; help | Help incorrectly selected position; corrected published-course campaign flow; no invite/PIN |
| Mandatory training | Summary, origin disclosure and missing-assignment filter apply; help | Plain-language subtitle repaired; protected manual/program assignments preserved |
| Training log | Current/history toggle12 records; help; signed confirmation read; CSV attempted | Search label repaired. Checkbox action falsely reported failure but fresh URL/history state confirmed success. CSV download event timed out; no product console errors, completion NOT VERIFIED |
| Training procedures | New draft default, type switch to attestation, advanced fields, cancel; help | Setup vs completed proof/OTP vs signature separation being corrected; no save/activation |
| Retention | Empty approved-policy view and help | Explicit methodologist read-only; no policy changes |
| Profile | Fields/security/about; RU/KK/EN switch and restore RU | No name/password save; missing help repaired locally |
| Competencies | Empty registry/new form/name/course selection controls; no create | Missing source-faithful help being added |
| Training rules | Source-registered organization route, department/position tabs and prerequisite controls | No add/remove/apply; missing help being added |
| Invitations | Source-registered route; demo guard and empty history | GATED by existing demo configuration, not a PASS for invitation creation |
| Global controls | Command palette filter and actual position navigation, notifications empty, support dialog open/cancel | No support submission or read-status writes; desktop1440x900, initial mobile409px; responsive retest pending |

Ordinary production admin/student credential paths unavailable after targeted
canonical inventory; earlier retained read-smoke also marks learner credential
NOT_VERIFIED. Owner asked asynchronously for existing safe credentials only; no
accounts/roles/PINs reset or impersonation used. Existing superadmin normal login
remains available for read-only platform coverage. Public/token journeys and
ordinary admin/student role acceptance remain pending, not inferred from source.

Two browser harness resets occurred (initial state timeout and CSV download-event
timeout). Some exact-label/summary/checkbox locator mismatches and bounded-output
truncations required corrective reads. Include this overhead in tool closeout;
do not report only successful query timings. In-memory UI observations were lost
on the second reset; this sanitized root record preserves verified observations
from tool results without replaying or inventing successful download evidence.

## Extended production pass (root, 2026-10-03; still not final acceptance)

| Surface | Verified safe observation | Boundary / disposition |
|---|---|---|
| Course template | Information-security template, required policy/incident-channel answers, examples disclosure, optional sources, blank create disabled | No draft/create submit or AI call; in-page guidance visible |
| Published course editor | Existing retained course structure, first lesson edit/preview, approval entry, AI side-panel open/close | No edits saved; unnamed AI controls/modal keyboard handling repaired locally |
| Course approval | Methodologist opens actual approval route, published course and approval controls visible | No policy/request writes; help role corrected to admin and methodologist |
| Public login/registration | Password/code tabs; trial registration labels, prerequisites and blank submit guards; legal links | No OTP, tenant creation or terms acceptance. Duplicate login skip link repaired |
| Public legal RU/KK | Terms/privacy document headings and language-specific links | Read-only UX observation, not legal-content/compliance certification |
| Public certificate | Existing synthetic certificate KML-2026-013EA89B75C0 valid with expected course; invented negative code not found; reset/retry controls | No new certificate. Wrong initial guessed route was a harness error, resolved from canonical source |
| Platform overview | Normal existing superadmin login; ten existing tenants | First-tenant onboarding wrongly displayed on nonempty platform; local loading/error/nonempty guard repaired |
| Synthetic tenant detail | Existing retained tenant only; fields, dates, capacity, current plan/status and historical trial metrics | Label associations repaired; no impersonation, plan/status/role/user changes |
| Platform operations | Loaded aggregates, worker queues, resource indicators; refresh GET | No cleanup/requeue/repair actions. Old AI/document failures and CRM pending indicators observed, not silently repaired or claimed clear |
| Provider keys | Existing masked-key table; add-key dialog open/cancel | Accessible field labels repaired locally; no key creation/check/deactivation/deletion or model calls |
| Generation model order | Loaded three configured models, mandatory first DeepSeek, move/enable controls and new-task scope copy; cancel | No ordering/toggle/save. This is UI coverage, not successful provider execution |

Ordinary admin and learner journeys still require existing normal credentials.
Token-based invite/kiosk/candidate/access/course-review journeys were not exercised
without existing safe tokens. Invitation creation remains gated by the retained
tenant's demo setting. Writes, paid/usage-based AI execution, all-role completeness
and CSV download completion must not be labelled PASS from these observations.

One delegated provider-label leaf accidentally edited and tested the primary
checkout instead of the specified writer. Root detected the missing writer diff
before freeze; only the leaf's exact own hunks were reapplied in the writer
and reversed in primary. Root independently verified primary clean; writer
provider tests3/3 and ESLint passed. Include this
correction in delegation/tool overhead; earlier wrong-checkout results are invalid
for this package.

Packet TEST-CLIENT30-20261003-A was explicitly stopped/superseded before the
matrix ran. Production platform overview/list failed after a long authenticated
session; full page reload restored the same session and loaded the list without
a new login. Canonical access TTL is15minutes. Source raw platform fetch paths
bypass the canonical api refresh-on-401 transport; correction is in the same
frontend package, not an authentication-policy or server change.

Tenant list filtering to the retained synthetic slug worked after session restore.
New-tenant form open/cancel exercised no creation. Its blank first step incorrectly
advanced to administrator entry. Source already has type=button on Next: the
verified defect is absent prerequisite validation, not default submit type. Create
and search fields lack names; an existing custom-plan display exposed a dictionary
key. Local repairs and regression follow; no tenant, billing or role changes.

Root read-only native host preflight: current/marker64c8bfebf44a296281d0db3202deaa44bea36e84,
web running; inventory free734672KiB. Read-only cleanup-plan independently confirms
actual rollback30693e45e1338772bf09577461e3f7615d38a73b from protected current backup.
Additional retained359d7cda1fba310a4e2e890fbfc48fef89a3f357 and
299481ec1518729bcec199e8aaa2fdfe5c74c1e3 preserved. No stage/deploy/delete executed.
Any capacity cleanup waits for exact new immutable artifact budget and all standing
oldest-successful-obsolete/off-host-recovery/readback conditions, not this estimate.
Initial API-test Python lacked Paramiko; no installation. Matching native runbook
identified the existing canonical kamilya-agent-tools runtime; that path succeeded.

Final local root corrections before packet B: translation key/type errors fixed;
canonical api adapter regression exercises401refresh/retry for four platform
routes with synthetic tokens, no network. Targeted27+10 tests, scoped ESLint and
typecheck PASS. Provider transport preserves error-body display; optional admins
HTTP failure stays optional while network failure remains a page load error.
Tenant final submit also rejects whitespace/too-short names. No source auth,
cookie TTL, server permission, provider key or real tenant writes changed.
Independent benchmark review hardened subprocess credential environment and
future co-located oracle, while offline/egress and historic timing limitations
remain explicit. Full Test Runner matrix and production release are still pending.

Packet B stopped with823/824 tests,138/139 files after one stale static fetch
credentials assertion. HARNESS_FAILURE addendum and unchanged56frozen hashes
preserved by Test Runner; all dependent gates unrun. Root replaces the obsolete
literal check with binding to canonical api POST and actual withCredentials;
adapter401replay additionally checks impersonation method/body with synthetic
fixtures only. No production impersonation exercised. Packet C supersedes B.

Production30 technical release completed: source d8ab25d6940eee4d388f3e32c820eb5ee57b169b,
CI37095250011/native37095272118, archiveba37acc5e839ee527f0f45fd60ab4bbbde06c5d07ccf3a4793b6bec0e3d5770d,
execute receiptb0c72c6c6a72e21bc1f6229fcd06a9d7d16a80f1c8d6746087f71c4801841dba.
Root independent public body/header exactsource and API29/source32e unchanged.
Release Runner wrong-path and executor network failures preserved; same protected
bridge executed by authorized root, Runner local technical reconciliation only.
Local published-tag absence corrected with canonical exact fetch before retry.
Standing exact successful obsolete25 cleanup+staged pair removed with verified
original recovery; current28/actualrollback27/extras preserved. Cleanup readback
free1462988KiB; after30 free734240KiB, all five expected releases preserved.
Primary hygiene fast-forwarded clean to d8ab25d6 with no reset/delete/stash.

Live30 mobile platform: scoped synthetic tenant list loaded with no page overflow,
named search/fields, blank and whitespace company Next stayed on step1. Valid
Next reached step2 but triggered native required-field popup without explicit
Create click (same AX button119 changed to submit; first-name focus). Root
canceled; no creation/POST/recovery mutation exercised. Final acceptance held;
small frontend31 correction required rather than rewriting published30 artifacts.
