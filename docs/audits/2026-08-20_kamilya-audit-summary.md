# Kamilya LMS — сводная карта аудитов

Дата: 2026-08-20 (Asia/Qyzylorda)
Режим: source/local test + passive production read-only. Никаких production mutations, exploit attempts или нагрузочных прогонов не выполнялось.

## Решение

Исходный аудит выявил четыре P0: stored XSS уроков, kiosk impersonation, SCORM
trust boundary и неверную цель production monitoring. Все четыре исправлены
локально вместе с P1 hardening, но формальный security sign-off ещё нельзя
выдать: нужны rollout/readback на KZ production, свежий disposable KZ restore,
первый DB-backed PostgreSQL 17 RLS gate и production-equivalent pentest.

## Сквозная карта результатов

| ID | Аудит | Слой | Результат | Доказательство / причина |
|---|---|---|---|---|
| A-01 | Архитектура и trust boundaries | source/docs | PASS WITH FINDINGS | `Kamilya-NEW-threat-model.md`, TM-01..TM-09 |
| A-02 | Python/FastAPI white-box security | source | LOCAL REMEDIATED | kiosk, limiter, parsing и logging fixes; rollout gates ниже |
| A-03 | Next/React security | source + passive live | LOCAL REMEDIATED | safe lesson rendering, isolated SCORM contract, dependency update |
| A-04 | Tenant query discipline | source | PASS | 246 queries, 0 static tenant-gate violations |
| A-05 | RLS/runtime tenant isolation | integration DB | BLOCKED | В локальном цикле нет PostgreSQL/Docker test service |
| A-06 | RBAC/public capability contracts | source/unit | PASS WITH GAP | Strong candidate/assignment/evidence controls; kiosk exception |
| A-07 | Files/AI/worker pipeline | source | LOCAL REMEDIATED | bounded OOXML/Docling sandbox + centralized redaction; rollout gate |
| A-08 | Backend unit regression | local test | PASS | final unit suite: 323 passed |
| A-09 | Web regression | local test | PASS | 319 tests; typecheck/lint/build pass; 57 pages |
| A-10 | Landing regression | local test | PASS | 22 tests; typecheck/lint/build pass; 18 SSG pages |
| A-11 | Migration/release contracts | local test | PASS | Alembic head 0120; focused migration/security gates pass |
| A-12 | Backend SCA | local scan | PASS | `pip-audit`: no known vulnerabilities |
| A-13 | Node production SCA | local scan | PASS | web/landing: 0 high, 0 critical after pinned pnpm update |
| A-14 | SAST | local scan | PASS WITH FINDINGS | XML boundary fixed; 2 non-security MD5 findings remain documented |
| A-15 | Lint/types | local test | PASS BASELINE | blocking Ruff 1140 / mypy 2429 upper bounds; legacy cleanup remains |
| A-16 | Secret hygiene | source/local | PASS LIMITED | 1 098 tracked files / 0 known signatures; full scanner timed out |
| A-17 | CI/CD/supply chain | source | PARTIAL REMEDIATED | blocking quality/RLS gates and one lock; actions/SBOM/provenance remain |
| A-18 | Container hardening | source | PARTIAL REMEDIATED | Docling non-root/auth fail-closed; broader image pinning remains |
| A-19 | Backup implementation | source/local contract | PASS WITH GATE | authenticated GPG, portable checksum, offsite round-trip + governance retention contract |
| A-20 | KZ restore readiness | operational | BLOCKED | fail-closed versioned drill готов локально; current signed isolated KZ restore/offsite proof отсутствует |
| A-21 | Production availability smoke | passive live | PASS SNAPSHOT | API/app/landing HTTP 200; это не SLO evidence |
| A-22 | Production monitoring correctness | source | LOCAL REMEDIATED | KZ identity/SHA verifier готов; rollout/fault injection gate |
| A-23 | Product disposable-tenant acceptance | prior production evidence | PASS SNAPSHOT | Existing 2026-08-20 acceptance plan records core menu flows; не заменяет новый security run |
| A-24 | Load test | staging | NOT RUN | k6/pgbench отсутствуют; профиль и изолированный target не утверждены |
| A-25 | Pentest | staging/production | NOT RUN | Требуются rules of engagement и production-equivalent environment |
| A-26 | Refactoring/maintainability | source | PARTIAL REMEDIATED | mypy runs, debt blocks growth, one package manager; legacy debt remains |

`PASS SNAPSHOT` означает наблюдение в определённый момент, а не непрерывную гарантию.

## Приоритетный remediation backlog

### P0 — блокирует security sign-off

| ID | Работа | Результат | Проверка закрытия |
|---|---|---|---|
| R-001 | Заменить raw HTML lesson renderer | XSS path устранён | XSS corpus + browser tests + CSP |
| R-002 | Усилить kiosk identity/session | URL+табельный номер недостаточны | brute-force/enumeration/scope tests |
| R-003 | Изолировать SCORM на отдельном origin | package code не доверен app/API | malicious SCORM E2E |
| R-004 | Перевести smoke/runbook на KZ production inventory | monitoring проверяет фактический prod | fault-injection smoke |

Текущий remediation status: R-001, R-002, R-003 и R-004 реализованы локально. Для R-002
runtime schema/RLS gate остаётся открытым до запуска migration/integration suite
на одноразовой PostgreSQL БД; это не заменяется mock-тестами. Для R-003
production launch намеренно fail-closed до отдельного DNS/TLS/reverse-proxy gate
для `SCORM_CONTENT_ORIGIN` и browser E2E из
`docs/architecture/2026-08-20-scorm-isolated-origin.md`. Для R-004 production
rollout и контролируемый staging fault-injection остаются gate; локальные
мониторы уже отвергают Render, redirect, неверный deployment и неверный SHA.
Полный локальный P0 regression завершён: backend unit `280 passed`, focused
kiosk/SCORM `15 passed`, web `319 passed`, typecheck/lint/build (57 страниц),
Alembic head `0120`. DB-backed RLS, production SCORM и monitoring rollout этими
локальными результатами не заменяются.

R-005 также реализован локально: upload/storage работают через stream; DOCX/XLSX
проходят bounded OOXML preflight на upload и conversion boundaries; Docling
fail-closed требует ключ, запускается не от root и имеет systemd sandbox/resource
limits. Целевой набор — `80 passed`, полный backend unit-suite — `292 passed`.
Закрытие production gate требует создать пользователя/state directory, безопасно
установить общий ключ backend/converter, развернуть unit/container и повторить
реальные DOCX/XLSX/legacy DOC/OCR plus adversarial archive smokes. Локальный
результат не подтверждает, что этот hardening уже работает на VPS.

### P1 — 1–2 спринта

| ID | Работа | Проверка закрытия |
|---|---|---|
| R-005 | OOXML preflight + Docling sandbox/non-root/required auth | LOCAL COMPLETE; production rollout/adversarial smoke gate |
| R-006 | Rate limit после verified identity + trusted proxy | LOCAL COMPLETE; production proxy-chain readback gate |
| R-007 | Обновить high Node dependencies и оставить один lockfile | LOCAL COMPLETE; deploy/readback gate |
| R-008 | Убрать PII/AI fragments из logs | LOCAL COMPLETE; aggregator/Sentry readback gate |
| R-009 | Починить mypy и включить blocking lint/type baseline | LOCAL COMPLETE; CI run gate |
| R-010 | KZ restore drill, immutable offsite, integrity authentication | LOCAL COMPLETE; signed isolated KZ drill/offsite rollout gate |
| R-011 | Ephemeral PostgreSQL 17/pgvector RLS suite | LOCAL/CI CONTRACT COMPLETE; first DB-backed CI run gate |

R-007 реализован локально для LMS web и отдельного репозитория landing:
оба проекта закреплены на `pnpm 10.26.1`, CI/Vercel используют
`--frozen-lockfile`, альтернативный web `package-lock.json` удалён. Next web
обновлён с 14.2 до 15.5.23, PostCSS/nanoid/sharp закреплены на исправленных
версиях. Frozen install проходит в обоих проектах; production SCA показывает
`0 high / 0 critical`; web — `319 passed`, typecheck/lint/build (57 routes),
landing — `22 passed`, typecheck/lint/build (18 pages). Next 15 dynamic-route
contracts исправлены. Production deploy/readback и container build на Linux
остаются отдельными release gates; локальный результат не подтверждает rollout.

R-008 реализован локально: logging handlers, stdout/stderr tee, superadmin debug
buffer и Sentry `before_send` используют общий bounded redaction contract.
Call sites больше не пишут фрагменты LLM, названия документов/файлов или raw
provider/parser exception strings. Негативный corpus проверяет email, телефон,
JWT/Bearer/capability token, табельный номер, PIN/password, structured extras,
nested telemetry и traceback. Focused suite — `53 passed`, полный backend
unit-suite — `312 passed`. Production log aggregator и Sentry readback с
синтетическими canary остаются release gate; реальные PII туда не отправлялись.

R-009 реализован локально без сокрытия legacy debt: mypy теперь использует
explicit package bases и анализирует `app` вместо остановки на duplicate module.
Коммитируемый baseline фиксирует верхние границы per-file/per-code для Ruff
(`1140`) и mypy (`2429`); уменьшение разрешено, любое увеличение блокирует CI.
Warn-only Ruff/mypy jobs заменены одним blocking gate без `continue-on-error` и
`|| true`. Unit test с искусственно добавленным `F401` подтверждает exit code 1;
gate на текущем дереве PASS, contract suite — `4 passed`. Полная очистка legacy
нарушений остаётся последующей работой; первый реальный GitHub Actions run —
release gate.

R-010 реализован локально как fail-closed эксплуатационный контракт. Backup
переведён с unauthenticated OpenSSL CBC на GPG symmetric encryption с companion
SHA-256, обязательным decrypt/`pg_restore --list` до публикации и, при включении
MinIO, побайтным round-trip плюс governance retention. Отдельный
`scripts/kz-restore-drill.sh` принимает только canonical `.dump.gpg`, всегда
отвергает production DB и непустую target DB, проверяет RPO/RTO, Alembic head,
pgvector, FORCE RLS и агрегаты, затем создаёт JSON evidence с проверенной detached
GPG signature. Shell security contracts и Python source-contract suite проходят
(`4 passed`). Operational gate остаётся красным до развёртывания точного script
на KZ узлах, проверки immutable offsite target и свежего восстановления реального
backup в утверждённую disposable PostgreSQL 17 + pgvector DB. Production DB в
этом цикле не читалась и не изменялась.

R-011 подготовлен как отдельный blocking CI gate на ephemeral
`pgvector/pgvector:pg17`; локальный compose также приведён к PostgreSQL 17.
Gate разрешает запуск только при `APP_ENV=test`, явном
`EPHEMERAL_POSTGRES_ONLY` и localhost database URL. Он проверяет PostgreSQL
major, pgvector, Alembic `0120`, атрибуты `lms_app`, FORCE RLS на критических
таблицах, cross-tenant CRUD, evidence export/share, adaptive staff import,
worker claim и superadmin isolation. Worker claim теперь выполняется под
`SET LOCAL ROLE lms_app`, а не под владельцем миграций. Source-contract suite —
`3 passed`; Ruff и shell syntax прошли. Реальный DB-backed набор локально не
выполнен, потому что Docker Desktop daemon недоступен. Поэтому R-011 нельзя
считать operational PASS до первого зелёного GitHub Actions run либо запуска
на отдельно поднятом ephemeral PostgreSQL 17 + pgvector; production DB не
использовать для этой проверки.

Финальная локальная регрессия после R-010/R-011: backend unit `323 passed`,
blocking Python quality baseline PASS (`ruff=1140`, `mypy=2429`), Alembic
`0120 (head)`, backup/restore shell contracts PASS, Bash syntax PASS, CI YAML
parse PASS и scoped `git diff --check` PASS. Ранее в том же remediation цикле
web прошёл `319` tests + typecheck/lint/build, landing — `22` tests +
typecheck/lint/build. Docker daemon на рабочей машине отсутствует; Linux image
build и DB-backed PostgreSQL 17 gate локально не заявляются как выполненные.

### P2 — hardening и эксплуатационная зрелость

- pinned Actions/image digests, SBOM, provenance и signature enforcement;
- CSP/Permissions-Policy/consistent security headers на app и landing;
- typed/bounded SCORM CMI schema;
- adversarial AI evals, provider privacy/retention evidence;
- наблюдаемость: p95/p99, queue depth/age, DB saturation, conversion duration, tenant quotas;
- плановое quarterly restore и semiannual penetration test.

## План нагрузочного аудита

### Цель

Не искать один «максимальный RPS», а отдельно определить безопасную ёмкость API, БД, очереди и document/AI pipeline.

### Контур

- production-equivalent staging с синтетическими tenant/user/document данными;
- PostgreSQL/Valkey/workers той же major version и близких лимитов;
- отдельные storage prefix и queues;
- production e-mail/LLM/CRM integrations заменены stubs либо жёстко квотированы;
- мониторинг CPU/RAM/disk/DB connections/locks/p95/p99/error rate/queue age.

### Профили

| Профиль | Сценарий | Начальная цель |
|---|---|---|
| L-01 | Login/refresh/course read | step 5→25→50 virtual users |
| L-02 | Staff structure/list/search | 10→50 concurrent readers, mixed writes 5% |
| L-03 | Assignments/progress/quiz commit | 20→100 learners с idempotent fixtures |
| L-04 | Candidate public exchange/attempt | 10→50 concurrent candidates |
| L-05 | Upload/document catalog | малый поток 1→5 concurrent, разные размеры |
| L-06 | AI generation queue | concurrency 1→worker capacity, измерять queue age |
| L-07 | Evidence/PDF export | burst 1→10, CPU/memory/profile |
| L-08 | Soak | 2–4 часа на 30–40% найденной ёмкости |

### Предлагаемые stop conditions

- error rate >1% в течение 2 минут;
- p95 API >2 s или p99 >5 s в течение 5 минут для обычных CRUD;
- DB connections >80%, sustained CPU >85%, free disk <20%;
- queue oldest age >5 минут без восстановления;
- обнаружена межтенантная ошибка, duplicate evidence или потеря данных — немедленный stop;
- никакого production load без отдельного разрешения владельца.

Финальные SLO должны быть согласованы с реальным ожидаемым количеством сотрудников/тенантов; приведённые числа — стартовый профиль, не обещание производительности.

## План пентеста

### Предварительные условия

1. Закрыты R-001..R-004.
2. Создан disposable clone с минимум тремя тенантами: attacker, victim, control.
3. Только синтетические данные и отдельные email/storage/queues.
4. Зафиксированы target domains/IP, окно, source IP, контакты и stop conditions.
5. Backup/snapshot и cleanup plan проверены до старта.

### Test cases

- auth/session/refresh/OTP enumeration и revocation;
- horizontal/vertical IDOR для всех CRUD/export/download;
- RLS/cross-tenant direct IDs, filters, background jobs и storage keys;
- candidate/assignment/invitation/evidence capability token replay, expiry, revoke и lockout;
- kiosk impersonation и enumeration;
- upload polyglots, archive bombs, malformed PDF/DOCX/XLSX/SCORM/XML;
- stored/reflected/DOM XSS, CSP bypass и SCORM origin escape;
- mass assignment, unknown fields, pagination/resource limits;
- CSRF/CORS/cookie policy и proxy/header spoofing;
- rate-limit bypass/concurrency/race/idempotency;
- AI prompt injection, tenant context leakage и output-schema bypass;
- superadmin isolation/audit/secret masking;
- dependency/container/config exposure.

### Разделение фаз

- Phase 1: SAST/SCA/config/source review — выполнено в текущем аудите.
- Phase 2: unauthenticated DAST на staging.
- Phase 3: authenticated role matrix + tenant abuse.
- Phase 4: file/parser/AI adversarial cases.
- Phase 5: ограниченная passive production verification только после отдельного разрешения.

Методика: [OWASP WSTG](https://owasp.org/www-project-web-security-testing-guide/), [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) и [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x00-header/).

## Рефакторинг и оптимизация: что делать, а что отложить

Сейчас не нужен массовый «рефакторинг всего проекта». Он увеличит риск поверх параллельных product changes. Нужны глубокие модули вокруг конкретных enforcement points:

1. единый `UntrustedContent` pipeline для lesson Markdown, documents и SCORM;
2. единый `PublicCapabilityPolicy` для candidate/assignment/invitation/evidence/kiosk с typed scope, expiry, attempts и limiter;
3. единый verified principal для auth + rate limiting;
4. environment inventory для health, deploy, backup, runbook и smoke;
5. один package manager и один reproducible build path;
6. постепенное разделение route parsing, policy enforcement и storage/worker side effects.

Оптимизацию SQL/React/worker concurrency следует делать только по профилю p95/queries/queue flamegraph. До измерений blanket caching, новые индексы и увеличение concurrency не обоснованы.

## Критерий готовности к следующему этапу

Минимальный `GO` на пентест и расширенный pilot:

- R-001..R-004 закрыты и regression tests зелёные;
- high/critical production SCA = 0 либо формально приняты с компенсацией;
- ephemeral DB tenant/RLS suite PASS;
- актуальный KZ restore drill PASS;
- monitoring указывает на фактический production;
- disposable production-equivalent tenant создан и после теста полностью очищается;
- rules of engagement подписаны владельцем.
