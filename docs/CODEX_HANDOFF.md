# Kamilya LMS: handoff для следующего Codex

**Обновлено:** 2026-10-01
**Primary anchor:** `C:\Kamilya New\Kamilya-NEW`, только sync/coordination
**Кандидат:** `C:\Kamilya New\.worktrees\daily-learning-20260930`
**Репозиторий:** `KamillaLMSCRM/Kamilya-NEW`, branch `feature/daily-learning-20260930`

## Daily learning: production0.11.23 — quiz guard repair, bounded acceptance GO

- result: exact `36826eda76844188b230d22c57935f51e7a130fd` /0.11.23 is live
  on DEV and production. Original DEV exhausted2/2 reproduction now PASS;
  production methodologist/navigation/mobile and GET-only API acceptance PASS.
- changed: frontend attempt-history fail-closed guards, RU/KK/EN alert and9quiz
  regressions; exact-count async assignment assertion stabilized. No backend
  policy, migration, attempts reset, tenant recreation, customer/mail/AI/billing
  mutation. Root reconciled watchdog expectedSHA/image with retained config backup.
- verified: persistent Test Runner local131files/742tests,9quiz/16assignment,
  lint/typecheck/66-page build PASS; independent live DEV2/2blocked/1/2usable,
  no submission, console0, permanent stand before/after PASS. Exact DEV/master
  CI36803962465/36804107063 all7SUCCESS; native36804192290/artifact11137041709;
  protected36805040867 SUCCESS, actual image
  `ghcr.io/kamillalmscrm/kamilya-api@sha256:cc4646aad09f09ef951c70f4c818b731f5ff3f61c78e87cd2ecdd3c9d73de5d3`.
  Root independent API+3blueworkers exactSHA/image running/restarts0; CT137
  RELEASE_OK exact current/marker/Nginx/public identity. CT1250168 fresh encrypted
  verified backup; no new restore drill. Watchdog exit0/timeractive; last10m
  bounded logs errors0. Test Runner live production focused1of5/show-all5/
  completed2/in-progress0 and truthful reminder histories, console0; mobile
  doc/body380/internal table scroll, desktop restored. Root API before/after PASS,
  counters unchanged/business mutations0. Release Runner local deterministic
  technical+acceptance reconciliation READY; its socket-denied executor did not
  deploy. Root used the same canonical controllers in the authorized executor.
- blockers: no defect within the original accepted quiz-guard/methodologist scope.
  Owner-approved exact synthetic access reissue executed once; root initial
  learner PIN entry/course view PASS,0of5, no completion/mail/AI. Extended learner
  acceptance PARTIAL: worker cannot see root's task-scoped browser; root reload
  restores old methodologist refresh context. ADR0022 memory-only/no-refresh
  assignment contract and AUTH-NAV-001 explain this boundary; no auth-policy
  fix or second rotation. Durable learner reload/mobile/nonzero assessment,
  real worker mail/task and fresh restore drill NOT VERIFIED. CT137 free888660KiB; next conservative
  ~1.39GB native release requires a fresh scoped recoverable capacity plan.
- next: preserve retained DEV/production stands and rollback images/releases;
  no automatic cleanup or plan change. Decide separately whether to change the
  restricted assignment-session persistence contract; never store JWT in localStorage
  or silently weaken TTL/role/enrollment boundaries. Current authoritative details: `docs/PRODUCTION_READINESS.md`;
  ignored evidence `REL-QUIZ-ATTEMPT-GUARD-20261001`, native `REL-QUIZ-ATTEMPT-GUARD-PROD-20261001`.

## Historical: production0.11.22 — bounded API/mobile acceptance GO

- result: exact production SHA `1af72b19999363885995f5e067fbf05b6b894f14` is live;
  bounded GET-only synthetic API, mobile/desktop geometry, and browser click chain PASS.
- changed: immutable `0.11.22`, PyJWT2.15.1 and urllib3 2.8.0 pins; no JWT/auth
  policy change, migration, business writes, provider/billing change, or pruning.
- verified: CI36748097801 all7 SUCCESS (backend3499PASS/2SKIP, coverage74.44%,
  no-DB1946PASS, RLS42PASS, no known audit vulnerabilities); release contract190
  unique entries PASS; focused auth/security40PASS and web functional738PASS.
  Native36748175697/artifact11114020032 SUCCESS;
  protected backend36749221904 SUCCESS, immutable image
  `ghcr.io/kamillalmscrm/kamilya-api@sha256:fdc6cfc63d3b6734adefdf4c7ee43c0396fed4398cbe63ed19800ad2b12ac190`.
  VM126 public/private API and3workers exact SHA/image, running/restarts0; CT137
  sole-controller frontend-execute.json RELEASE_OK and current/marker/Nginx/public
  healthz exact SHA; rollback359d7cda and c239/image26e46c7a retained. CT125
  revision0168 fresh encrypted verified backup PASS; no migration/restore drill.
  Watchdog oneshot exit0/timer active. Production smoke retained tenant only:
  list/summary/CSV agree, failed/exhausted0, own1/foreign0, unauthenticated401,
  invalid422; counters unchanged, no business writes. 390x844 body380 and
  1440x1000 body1430; mobile/desktop screenshots visually inspected. Browser chain
  dashboard0exhausted -> exhausted journal0 -> dashboard -> failed0 -> failed
  journal0 -> actual first operations link, course
  `67d782f2-0478-4555-9c19-99d4bc071789`, enrollment
  `da07381b-9346-4c34-a28e-376cb2b1c111`, selected course, focused1of5 row;
  console errors0. No command buttons clicked.
  Independent last10m/500line API+3worker scan found0 ERROR/CRITICAL/FATAL/
  traceback events and0restarts; watchdog config SHA/image matched, backup retained,
  oneshot exit0/timer active. Repeated API smoke17:21:08Z PASS; counters unchanged,
  business writes0, VM126 lock absent and rollback image present.
- blockers: production nonzero assessment, learner browser, and real maintenance/mail
  task remain NOT VERIFIED. No fresh restore drill. Evidence:
  `.release-evidence/REL-DAILY-MOBILE-PROD-20260930-1AF72B19/`.
- next: for any future native release, plan exact recoverable artifact cleanup
  before its ~1.39GB build budget; do not auto-prune or change provider plans. Use
  the retained synthetic stand without recreation/reset. Keep production nonzero,
  learner-browser and real mail-task flows NOT VERIFIED until separately evidenced.

### Historical handoff snapshots (superseded by current0.11.23 status)

#### Historical: production 0.11.20, мобильная/security поправка 0.11.22 в проверке

- result:0.11.21 ea1a8ad5 source-published, NOT deployed; CI36746148434 FAIL.
- changed:0.11.22 candidate includes PyJWT2.15.1 three-surface pin/Poetry lock,
  malformed/deep JWT auth regressions and unique journal ID RELEASE-007.
- verified: fresh independent Luna investigation/review READY; local40tests PASS,
  baseline ruff1010/mypy2200 unchanged; complete release contract190entries PASS.
  Seven malformed signed NumericDate cases RED TypeError on2.14 -> GREEN401
  beforeDB; nested payload/ordinary controls PASS. Native36746472002 SUCCESS for
  failed0.11.21 is NOT a deploy gate. Fresh audit found CVE-2026-101918; no ignore.
- blockers: new exact-SHA CI/build/protected/native gates and real mobile geometry
  remain required. Production still c239de80/0.11.20; stands/customer data preserved.
- next: publish new immutable0.11.22 after fresh gates; do not move0.11.21 tag.

- result: owner-authorized0.11.20 exact c239de80d7f9d292492fde20601381cdbe6a334f
  is live on VM126 API+3workers and native CT137. Responsive acceptance is incomplete:
  mobile390 pageWidth725 reproduced; bounded0.11.22 follow-up in progress.
- changed: urllib3-only2.8.0 pin/lock/compatibility contracts; standard immutable
  release, no migration, customer mutation, mail/AI or provider/billing change.
- verified: CI36738812896 all7 SUCCESS; backend3488PASS/2SKIP, RLS42PASS,
  no known vulnerabilities; native36738991107 artifact11109147129; protected
  backend36740593404 attempt2 SUCCESS same image26e46c7a. Independent public/private
  API+all4blue services exact SHA/image, running/restarts0; CT137 native RELEASE_OK
  exact public body/header+host marker; watchdog oneshot exit0/timer active.
  Synthetic methodologist read/API+desktop navigation PASS, exact focused1of5row;
  foreign0/no-auth401/invalid422; enrollment notification counters unchanged.
- blockers: mobile overflow (new follow-up scope). Production nonzero assessment
  and learner browser NOT VERIFIED; corresponding DEV permanent-stand evidence
  retained. Real maintenance task NOT VERIFIED under no-mail scope.
- next: verify minimal mobile patch, fresh immutable0.11.21 SHA/CI/release gates,
  then repeat production geometry and bounded business smoke. Retain both stands;
  never recreate/reset for smoke. Source/archive/script/artifact hashes retained
  under `.release-evidence/REL-DAILY-LEARNING-PROD-20260930-C239DE80/`.

All subsequent release/approval statements are historical and superseded above.

### Historical production attempt 0.11.19 — NO_GO (2026-09-30)

- result: owner requested production rollout and final test; exact release
  candidate `0.11.19` / `0b69e81ecbad05f0181dfa114bef273cff7d7c45` is published
  to master/feature/tag, but NOT production-deployed.
- changed: standard release metadata only above accepted DEV functional payload;
  no production mutation. Primary fast-forwarded safely; clean master and remote
  identity independently confirmed, with sanitized push receipts preserved.
- verified: full web 131 files / 737 tests PASS; release validator PASS;
  native CI36736269388 SUCCESS. Fresh master CI36736107879 FAIL in production
  audit: urllib3 2.7.0, CVE-2026-97687/97688/97689, reported fix2.8.0.
  Protected backend36736621137 SKIPPED; CT137 not switched. Public production
  API/frontend remain exact `e15dc8dd8a0d93a451fbf32bc5a453fc28b08687` /0.11.18;
  active green API+3workers share immutable digest18e39b30, running/restarts0.
- blockers: fresh dependency audit; candidate production browser acceptance
  NOT VERIFIED. No audit ignore, alternate deploy or tag rewrite.
- next: obtain approval for bounded urllib3 repair, fresh exact-SHA CI and new
  release identity, then resume protected backend/native frontend gates and
  synthetic production test. Evidence:
  `.release-evidence/production/REL-DAILY-LEARNING-PROD-20260930/`.

The production request supersedes older statements below that no production
approval existed; the current candidate stopped at the failed audit gate.

### Current continuation — permanent DEV QA stand (2026-09-30)

- result: exact `de37faba938f0dc660fb7de7010d7710d7e9a160` promoted to DEV
  with fresh exact owner approval; controller RELEASE_OK, DEV CI36730755381
  all7 SUCCESS, Vercel/API/worker exact SHA. Permanent `kamilya-dev-qa` retained;
  no tenant recreation, attempt reset or cleanup. Browser navigation PASS.
- changed: one owned synthetic stand retained; canonical IDs in
  `docs/testing/fixtures/kamilya-dev-qa.json`; one-time bootstrap and fail-closed
  read-only smoke in `scripts/ops/dev_qa_stand.py`. Never bootstrap again or reset
  attempts to make smoke green. Credentials stay process-local in primary `.env`.
- verified: two users/courses/assignments, failing attempts1/2, failed2/exhausted1,
  list/summary/CSV, true deadlines and canonical continuation; zero notification
  attempts; Supabase lms_app READ ONLY, no super/BYPASSRLS, revision0168. Ten new
  local contract tests PASS; independent Luna source review READY. Helper source
  and contracts are included in the deployed revision's green exact-SHA CI;
  the helper is run from the checkout, not a new API endpoint or worker task.
  On freshly reloaded DEV frontend, dashboard exhausted1 -> journal -> assignment
  operations reached `/assignments` with exact course/enrollment query IDs,
  selected course and one focused QA learner row. No dashboard redirect or command.
  Before/after-browser API verification PASS, latest14:50:11Z; same IDs/attempts,
  notifications0. API3+1/worker2+0 and RedisDB1 unchanged; plans Hobby/Free unchanged.
- blockers: none for the approved assignment-navigation release/readback.
  Actual maintenance task remains NOT VERIFIED because
  recurring materialization can dispatch mail; worker health is not queue proof.
- next: ordinary smoke uses `verify --expected-sha <exact-live-dev-sha>`.
  Evidence: ignored `.release-evidence/dev/REL-QA-NAV-DEV-20260930-DE37FABA/`;
  prior failure retained under QA-STAND-20260930. No production approval, master
  merge, further redeploy, migration, mail or automatic stand deletion implied.

The following candidate notes retain earlier static/isolated acceptance history;
their older next/release statements are superseded only by the DEV facts above.

- result: реализованы RPT/ACT/LRN из принятого EPIC_V1; активная поправка
  continuation safety V2. База `bf858214573387128a20ba03e72d90d13ff6dfab`.
- changed: assessment drill-down; browser-only action focus; планы не выдают себя
  за отправленные письма/назначения; переход к существующим операциям; дедлайн,
  основание и безопасный следующий шаг ученика. Нет миграций, новой отправки,
  player/progress/quiz/SCORM write changes или расширения ролей.
- verified: 58 focused API tests; 87 affected web tests; final full web suite
  131 files / 737 tests; final lint PASS and Next production build PASS (66 pages);
  Python quality baseline unchanged
  (ruff 1010, mypy 2200); version/release-contract gates; synthetic Playwright
  2/2 at 1440/390 px and visual inspection, API mocked and commands blocked.
  Независимое source review: READY for local acceptance; no release claim.
  Continuation: 79 auth/JWT/deadline/SCA contract tests PASS; canonical Supabase
  DEV revision `0168`: existing reporting regression 24 PASS and assembled daily
  chain 3 PASS (66.31s). Effective `lms_app` is non-super/non-bypass, six read
  tables FORCE RLS; foreign tenant/user/enrollment reads denied. Both gates
  ended with zero fixture tenants and unchanged public revision, outer rollback.
  Runtime candidate `a838464adda2cff646e6b55bc381c65f4757da7c`: exact-SHA CI
  `36713494647` SUCCESS, all 7 jobs. Backend full 3475 PASS / 2 SKIP, coverage
  74%; unit 1933 PASS; PostgreSQL17/pgvector RLS gate 42 PASS; production
  dependency audit found no known vulnerabilities in the exported graph.
- blockers: no candidate CI/isolated DEV blocker at that SHA. Prior CI
  `36709677536` for `2c038da452e08ec720e6b08c586a381d52b75e92`
  failed dependency audit (PyJWT 2.13.0) and a stale source-location guard after
  extracting the shared deadline model. Bounded remediation pins only PyJWT
  2.14.0 across all dependency surfaces and corrects that guard; the replacement
  exact-SHA CI above passed. Production/browser deployment readback not performed.
- next: отдельное разрешение владельца на release и deployed browser readback.
  Не обещать произвольный occurrence launch: canonical resolver guard обязателен
  также для enrollment-restricted dashboard reads.

PR: https://github.com/KamillaLMSCRM/Kamilya-NEW/pull/15. Project-token PR
permission was rechecked after the owner update and PR creation succeeded.
Final evidence closeout changes documentation only after the tested runtime SHA;
the final PR head must still retain green exact-SHA CI, read directly from PR/CI.
DEV evidence is rollback-isolated synthetic read-chain acceptance, not deployed
DEV browser acceptance or a production/customer journey. No audit bypass,
migration, provider spend or merge is authorized by this continuation.

Delegation ledger (English-only handoffs; root owns integration and Git):
inventory/review used requested gpt-5.6-luna medium; learner used requested
gpt-6-luna medium; action navigation used requested gpt-5.6-luna medium.
At most two leaf workers wrote disjoint files. Both writing scopes needed
corrections; root independently verified final deltas. Observed provider model,
token/cost counters, exact duration and root rework time: NOT AVAILABLE; do not
infer savings or first-pass acceptance. No nested delegation.

Graphify code-only update: 21354 nodes / 50841 edges / 1293 communities; 54 source
files produced no nodes, no large graph HTML. Derived navigation evidence only,
not tenant/runtime verification; bounded source remains authoritative. Bounded
daily_learning fixture query confirms the real release helper/ORM neighbors;
21/153 nodes returned (truncated). CLI 0.9.23 versus skill 0.9.58 warning retained,
no shared tool upgrade performed.

## Сначала прочитать

1. [`AGENTS.md`](../AGENTS.md)
2. [`ERRORS.md`](../ERRORS.md)
3. [`PROJECT.md`](../PROJECT.md)
4. [`PROJECT-CONTEXT.md`](PROJECT-CONTEXT.md)
5. [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md)
6. [`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)
7. [`PROJECT_INTERNAL_DOCUMENTATION.md`](PROJECT_INTERNAL_DOCUMENTATION.md)
8. [`BACKUP_RESTORE_RUNBOOK.md`](BACKUP_RESTORE_RUNBOOK.md)
9. [`PRODUCTION_FRONTEND_RUNBOOK.md`](PRODUCTION_FRONTEND_RUNBOOK.md)

Не использовать старые commit reports, ТЗ и переписку как описание текущего
production. Они удалены из рабочего дерева и при необходимости доступны в Git
history.

## Ранее записанный контур — срез 2026-09-07

Таблица ниже сохранена как исторический handoff, не как свежий readback
2026-09-30. Для release факты проверяются заново по каноническому environment
map и `PRODUCTION_READINESS.md`; локальный daily-learning кандидат их не обновляет.

| Контур | Состояние |
|---|---|
| Canonical Git branch | `KamillaLMSCRM/Kamilya-NEW`, `master`; exact remote SHA всегда читать заново |
| Production frontend | CT137 `webkml` на Proxmox node `pve3`; native Next.js/OpenRC/Nginx без Docker |
| Frontend ingress | `app.kml.kz` -> Cloudflare DNS-only `92.38.49.167` -> KZ proxy/WireGuard -> CT137 |
| Frontend release readback | exact SHA `e463527cd8f5e67e987c44d8d769f337714bd25f`; `/healthz` и `/login` HTTP 200 после переноса CT137 с `pve2` на `pve3` |
| Production API/workers | VM126 в KZ-контуре; public API `https://api.kml.kz/api`; current health exact SHA проверять перед каждым release |
| Production DB | Native PostgreSQL 17 + pgvector на CT125, private-only; текущую Alembic revision читать отдельно |
| Dev/demo | Vercel `kamilya-lms-dev`, Render и Supabase DEV/test; не production |
| Frontend rollback | Vercel project `web`, сохранённый CNAME и Proxmox snapshot; не текущий runtime |
| Public landing | `kml.kz`/`www.kml.kz` на CT137 через KZ proxy; native Next.js service `kamilya-landing`, exact source SHA `e70534f4814fd743edef16363d7393361fe874c7` |

Технический P0 и прикладной synthetic tenant journey закрыты. Перед
подключением конкретного клиента остаются только условные gates для реально
заявляемых SCORM/kiosk/KZ-data/capacity возможностей. Подробности:
  [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md). Точные CI, worker, DB,
backup и monitoring states не копировать из старого handoff: читать их заново
из production и канонического реестра.

## Продуктовая модель

Kamilya LMS:

```text
документы компании
  -> ingestion/AI
  -> курс и тест
  -> публикация
  -> правило или ручное назначение
  -> обучение
  -> тест
  -> сертификат
  -> журнал обучения
```

### Роли

- `superadmin`: платформа и tenants;
- `admin`: организация tenant, системные пользователи, интеграции;
- `methodologist`: контент, сотрудники, правила, назначения и результаты;
- `student`: обучение.

`teacher` и `org_admin` удалены. Не восстанавливать их для обратной
совместимости: реальных пользователей этих ролей нет.

Один пользователь может иметь несколько ролей, но использует одну active role.
Не объединять capability всех ролей.

### Канонические поверхности

- `/admin/team`: только системная команда tenant;
- `/staff`: сотрудники, структура, импорт;
- `/training-rules`: правила организации/отделов/должностей;
- `/positions`: должность, инструкция и профиль квалификации;
- `/assignments`: ручное назначение;
- `/training-log`: прохождение и доказательства;
- `/documents`: библиотека источников;
- `/ai/generate`: генерация с выбранными источниками.

Tenant admin не занимается курсами, тестами, обучающимися и назначениями.

## Техническая архитектура

- `apps/api`: FastAPI, SQLAlchemy async, Alembic, PostgreSQL/pgvector.
- `apps/web`: Next.js 15.5.23, React, TypeScript.
- Production frontend: CT137, native Node.js/OpenRC/Nginx, без Docker.
- Production DB: PostgreSQL 17 + pgvector на CT125; Supabase — dev/test.
- Queue/cache and workers: Valkey и Celery на VM126.
- Email: Resend.
- Document conversion: Docling.
- AI jobs: Celery; provider fallback определяется модулем.

Tenant isolation требует одновременно:

1. `tenant_id`;
2. backend ownership checks;
3. RLS policy;
4. FORCE RLS;
5. runtime DB role без `BYPASSRLS`;
6. cross-tenant test.

## Локальные секреты

- Файл: `.env` в корне репозитория.
- Файл игнорируется Git.
- Значения не печатать в чат, docs или test output.
- В `.env` есть именованные пути доступа к production/dev providers и
  инфраструктуре. Использовать только target-specific credential согласно
  `PROJECT-CONTEXT.md`, не перебирать значения и не выводить их.
- Перед добавлением переменной сверять `.env.example`.

## Проверки

Backend:

```powershell
cd "C:\Kamilya New\Kamilya-NEW\apps\api"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m alembic heads
```

Frontend:

```powershell
cd "C:\Kamilya New\Kamilya-NEW\apps\web"
pnpm test
pnpm typecheck
$env:NEXT_TELEMETRY_DISABLED='1'
pnpm build
```

Перед release:

1. проверить worktree;
2. прогнать focused tests и полный suite по риску;
3. проверить migration head;
4. push в `master`;
5. дождаться CI;
6. проверить exact frontend runtime SHA на CT137, API/worker image и DB revision
   независимо; Vercel/Render проверять только для dev или выбранного rollback;
7. пройти public и role-specific production smoke.

HTTP health не доказывает, что worker, migrations и пользовательский flow
актуальны.

## Git

- Commit author: `kamilla_lms_crm@proton.me`.
- Push выполнять токеном из `.env`, без Git Credential Manager.
- Не коммитить `.env`, Playwright artifacts и локальные outputs.
- Не откатывать чужие незакоммиченные изменения.
- История выполненных работ хранится в Git, а не в папке с устаревшими
  финальными отчётами.

## Следующий порядок работ

1. Сверить release parity с `PRODUCTION_READINESS.md`.
2. Для CT137 использовать подтверждённый restricted key-only path через
   proxy/WireGuard; Proxmox console оставлять только bootstrap/recovery путём.
   Landing deploy допускается только через exact root-owned helper; общий sudo,
   парольный SSH и размещение runtime на proxy запрещены.
3. Брать следующий P1 из `PRODUCT_BACKLOG.md` по одному
   каноническому workflow.
4. Любое изменение UI обновляет пользовательское руководство.
5. Любое долговечное архитектурное решение получает ADR.
