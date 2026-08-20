# Kamilya LMS — отчёт по безопасности и secure-by-default практикам

Дата: 2026-08-20
Scope: `Kamilya-NEW` и `kamilya-landing`
Метод: white-box review Python/FastAPI и JavaScript/TypeScript/Next.js, SCA/SAST, CI/container/backup review, безопасные локальные тесты и пассивные HTTP-проверки production. Активная эксплуатация production не выполнялась.

## Итог

Исходный аудит выявил 6 High, 8 Medium и 2 Low/Informational группы замечаний. Четыре P0 — stored XSS в содержании уроков, kiosk impersonation, небезопасная граница SCORM и monitoring старого Render endpoint — исправлены локально вместе с P1 hardening. Полный security sign-off для масштабирования на новые тенанты всё ещё требует production rollout/readback, свежего disposable KZ restore, первого DB-backed PostgreSQL 17 RLS gate и production-equivalent pentest.

При этом фундамент tenant isolation сильный: серверный tenant context, действующие role assignments, `FORCE RLS`, ownership triggers, криптографические capability-токены, Argon2 PIN и integration/source gates существенно уменьшают вероятность простого IDOR/cross-tenant доступа.

## Проверенная база

| Проверка | Результат |
|---|---|
| Backend unit tests | PASS — 323 passed, 2 deprecation warnings |
| Web Vitest | PASS — 76 файлов / 319 тестов |
| Web typecheck / lint / production build | PASS / PASS / PASS |
| Landing tests / typecheck / lint / build | PASS — 22 теста, 18 SSG pages |
| Alembic graph | PASS — single head `0120` |
| Release contract gate | PASS |
| Tenant query gate | PASS — 246 queries, 0 static violations |
| Python dependency audit | PASS SNAPSHOT — ранее известных уязвимостей не найдено; свежий повторный `pip-audit` недоступен в текущем runtime |
| Bandit | PARTIAL FAIL — 2 false-positive MD5 и 1 реальный XML hardening issue |
| Backend Ruff baseline | PASS — blocking upper bound 1 140 legacy findings |
| Backend mypy baseline | PASS — full analysis, blocking upper bound 2 429 legacy findings |
| Web production SCA | PASS — 0 high / 0 critical |
| Landing production SCA | PASS — 0 high / 0 critical |
| Tracked secret signature scan | PASS LIMITED — 1 098 tracked files, 0 известных key signatures |
| Full detect-secrets | BLOCKED — локальный полный scan превысил безопасный лимит времени |
| PostgreSQL integration/RLS runtime | LOCAL/CI CONTRACT PASS, RUNTIME BLOCKED — blocking PG17 gate добавлен; локально нет Docker/PostgreSQL test service |
| Backup validation harness | PASS — GPG tamper/env/offsite/retention/restore contracts зелёные; реальный KZ drill остаётся gate |
| Active load/pentest | NOT RUN — production не является разрешённой тестовой площадкой |

## Findings

### SEC-001 — Stored XSS в рендеринге содержания урока

- **Severity:** High
- **Статус:** исправлено локально; production rollout/browser readback остаётся gate.
- **Расположение:** `apps/web/src/app/courses/[id]/page.tsx:688`, `:885-889`; `apps/web/next.config.js`.
- **Доказательство:** `simpleMarkdown()` заменяет переносы и выделение, но не экранирует HTML. Результат передаётся в `dangerouslySetInnerHTML`.
- **Влияние:** сохранённый контент из editor/импортированного документа/LLM может выполнить JavaScript в контексте `app.kml.kz`. Даже при memory-only access token XSS может выполнять запросы от имени жертвы и читать доступные ответы.
- **Исправление:** перейти на Markdown AST/component renderer без raw HTML либо применять поддерживаемый allowlist sanitizer после server-side normalization; добавить corpus с `<script>`, event handlers, SVG/MathML, `javascript:` URL и malformed HTML. После устранения inline-зависимостей включить CSP с nonce/`strict-dynamic`.
- **Критерий закрытия:** browser tests подтверждают отсутствие executable DOM; live frontend возвращает CSP; lesson functionality сохранена.

### SEC-002 — Kiosk impersonation по URL и табельному номеру

- **Severity:** High
- **Статус:** исправлено локально; migration/RLS runtime и production readback остаются gate.
- **Расположение:** `apps/api/app/modules/users/kiosk_router.py:299-317`; `kiosk_service.py:343-375,480-503`.
- **Доказательство:** комментарий маршрута прямо определяет kiosk URL как публичный credential и `personnel_number` как per-user credential. После поиска пользователя API выпускает role-bearing access token.
- **Влияние:** наблюдаемый/угадываемый табельный номер позволяет действовать от имени другого сотрудника. Различимые причины отказа помогают enumeration.
- **Исправление:** второй фактор (короткий PIN/одноразовый QR/OTP), per-kiosk+person lockout, единый внешний ответ, отдельный kiosk-scoped principal с минимальными claims и маршрутами, а не обычная роль пользователя.
- **Критерий закрытия:** украденный kiosk URL + табельный номер недостаточны; brute-force и enumeration tests проходят; JWT не принимается вне kiosk allowlist.

### SEC-003 — SCORM одновременно неработоспособен и небезопасен при очевидном обходе

- **Severity:** High
- **Статус:** исправлено локально fail-closed; отдельный content origin, DNS/TLS и malicious-package browser E2E остаются gate.
- **Расположение:** `apps/web/src/app/courses/[id]/page.tsx:619-624`; `apps/api/app/modules/scorm/router.py:564-714`; `apps/api/app/core/security.py:16,30`.
- **Доказательство:** SCORM встраивается в iframe без `sandbox`, но API всем ответам задаёт `X-Frame-Options: DENY` и CSP `frame-ancestors 'none'`. Если заголовки ослабить, tenant-uploaded HTML/JS будет исполняться на origin API.
- **Влияние:** текущий flow должен блокироваться браузером; попытка «починить» его удалением заголовков создаст trusted-origin XSS/API compromise.
- **Исправление:** отдельный untrusted SCORM origin без auth cookies, sandboxed iframe, минимальный `allow`, versioned `postMessage` bridge с origin/schema validation, отдельная CSP/network policy.
- **Критерий закрытия:** SCORM E2E работает без ослабления защиты app/API origin; malicious package не может читать API/cookies/top DOM.

### SEC-004 — Недостаточная изоляция парсеров документов и OOXML archive budgets

- **Severity:** High
- **Статус:** исправлено локально; Docling/VPS rollout и adversarial production-equivalent smoke остаются gate.
- **Расположение:** `apps/api/app/modules/documents/router.py:91-102,538`; `infra/docling-service/main.py:35,490-495`; `apps/api/Dockerfile`; `infra/docling-service/Dockerfile`.
- **Доказательство:** upload читается целиком в память. DOCX/XLSX проверяются только по `PK` magic и размеру compressed upload. API key Docling проверяется лишь когда env непустая. Dockerfiles не переходят на non-root user.
- **Влияние:** zip bomb/parser exploit/queue starvation/worker memory exhaustion; при ошибке production env внутренний converter становится unauthenticated.
- **Исправление:** streaming/spooled upload; OOXML entry-count, per-entry, total-uncompressed и compression-ratio caps; обязательный production key fail-fast; non-root, read-only rootfs, `cap_drop=ALL`, `no-new-privileges`, pids/memory/CPU/time/network limits; per-tenant quotas.
- **Критерий закрытия:** adversarial archive corpus отклоняется до converter; контейнер не root и не имеет ненужной сети; отсутствие key останавливает startup.

### SEC-005 — Production monitoring проверяет старый Render, а не KZ API

- **Severity:** High (операционный контроль)
- **Статус:** исправлено локально; production rollout и controlled staging fault injection остаются gate.
- **Расположение:** `.github/workflows/production-smoke.yml:31`; `scripts/ops/healthcheck.sh:8`; `docs/BACKUP_RESTORE_RUNBOOK.md:4`.
- **Доказательство:** smoke и default healthcheck используют `kamilya-lms-api.onrender.com`; runbook называет production PostgreSQL в Supabase. Каноническая текущая схема — `api.kml.kz` и KZ PostgreSQL.
- **Влияние:** CI/оператор может видеть зелёный старый dev/rollback endpoint при недоступном production. Restore выполняется по устаревшей документации.
- **Исправление:** один inventory источников окружений; smoke target из защищённой environment configuration с expected deployment identity/version; удалить production defaults на Render/Supabase; добавить alert на KZ API, worker, queue и DB readiness.
- **Критерий закрытия:** искусственное отключение production target делает smoke красным; dev/rollback не удовлетворяет production check.

### SEC-006 — Rate-limit key строится из неподписанного JWT и неоднозначного client IP

- **Severity:** Medium
- **Статус:** исправлено локально; production trusted-proxy readback остаётся gate.
- **Расположение:** `apps/api/app/core/rate_limit.py:204,208-224,313-342`; `apps/api/Dockerfile:24`.
- **Доказательство:** tenant ID извлекается без проверки подписи; IP берётся из `request.client.host`; явная trusted-proxy конфигурация в runtime command не видна.
- **Влияние:** forged token может разбивать/засорять tenant buckets; за reverse proxy все клиенты могут объединиться или, при неверном доверии к forwarded headers, spoof IP.
- **Исправление:** pre-auth bucket только по проверенному transport IP/device; tenant/user bucket после signature verification; явный список trusted proxy; composite limits для public credential routes; fail-closed для session-issuing endpoints.
- **Критерий закрытия:** forged JWT не влияет на чужой tenant bucket; proxy integration tests подтверждают реальный client identity.
- **Локальное доказательство:** middleware принимает principal bucket только
  после полной JWT signature/audience/issuer/expiry/type проверки; иначе
  использует `request.client`. Все invitation/kiosk/assignment/candidate/public
  lead routes fail closed при недоступном Valkey, capability token в Redis key
  хранится только как hash. KZ Compose требует exact
  `KAMILYA_FORWARDED_ALLOW_IPS=10.77.77.1`; raw `X-Forwarded-For` в route не
  разбирается. Focused suite `33 passed`, backend unit-suite `305 passed`.

### SEC-007 — Уязвимые production Node-зависимости и конфликт lockfiles

- **Severity:** High
- **Статус:** исправлено локально; production deploy/readback остаётся gate.
- **Расположение:** `apps/web/package.json`, `apps/web/package-lock.json`, `apps/web/pnpm-lock.yaml`; landing lockfile.
- **Доказательство:** `npm audit --omit=dev --audit-level=high` для web показывает 3 high advisory groups (Next.js, PostCSS, nanoid); landing `pnpm audit --prod` — high nanoid. `npm ls` сообщает invalid/extraneous дерево, одновременно используются npm и pnpm locks.
- **Влияние:** известные уязвимости runtime/build chain и невоспроизводимая установка зависимостей.
- **Исправление:** выбрать pnpm как единственный менеджер, удалить альтернативный lock отдельным согласованным изменением, обновить Next/PostCSS/nanoid по официальным advisory с regression/build/E2E, закрепить package manager и `--frozen-lockfile`.
- **Критерий закрытия:** один lockfile; clean install; production SCA без high/critical; тесты/build проходят.
- **Локальное доказательство:** LMS web и landing закреплены на `pnpm 10.26.1`
  и frozen install; web `package-lock.json` удалён, CI/Vercel используют pnpm.
  Next web обновлён до `15.5.23`, PostCSS/nanoid/sharp закреплены на исправленных
  версиях. Оба production audit дают `0 high / 0 critical`; web — `319 passed`,
  typecheck/lint/build с 57 routes; landing — `22 passed`, typecheck/lint/build
  с 18 pages. Linux container build и production deployment не выполнялись.

### SEC-008 — CI разрешает merge при провале Ruff и mypy

- **Severity:** Medium
- **Статус:** blocking debt-baseline реализован локально; CI run остаётся gate.
- **Расположение:** `.github/workflows/ci.yml:65-70,145-168`.
- **Доказательство:** lint/format и mypy помечены `continue-on-error`; mypy дополнительно завершается из-за duplicate module; локально Ruff выдаёт 1 149 ошибок.
- **Влияние:** регрессии качества и части security-relevant type contracts не блокируют release; зелёный workflow не означает успешный анализ.
- **Исправление:** зафиксировать baseline/поэтапно очистить; исправить module layout; сделать новые нарушения blocking; затем убрать `continue-on-error`/`|| true`.
- **Критерий закрытия:** намеренная lint/type ошибка делает CI красным.
- **Локальное доказательство:** `explicit_package_bases` устраняет duplicate
  module stop; mypy выполняет полный анализ. Committed baseline хранит верхнюю
  границу per-file/per-code: Ruff `1140`, mypy `2429`. CI job больше не имеет
  `continue-on-error`/`|| true`. Текущий gate PASS; unit contract `4 passed`,
  включая seeded `F401`, для которого CLI возвращает 1. Полный legacy cleanup
  не заявляется; первый GitHub Actions run остаётся release gate.

### SEC-009 — XML parser для SCORM manifest не hardened

- **Severity:** Medium
- **Статус:** исправлено локально; malicious SCORM corpus/browser E2E входит в release gate SEC-003.
- **Расположение:** `apps/api/app/modules/scorm/router.py:16,119`.
- **Доказательство:** Bandit B314 на `xml.etree.ElementTree.fromstring()` для tenant-uploaded manifest.
- **Влияние:** нежелательные XML parser behaviours/resource consumption; размер manifest ограничен, поэтому риск ниже SEC-003.
- **Исправление:** `defusedxml.ElementTree`, explicit parser limits и adversarial XML tests.
- **Критерий закрытия:** Bandit finding исчезает; entity/billion-laughs corpus отклоняется.

### SEC-010 — Неограниченная структура SCORM CMI commit

- **Severity:** Medium
- **Расположение:** `apps/api/app/modules/scorm/schemas.py:36-37`; `apps/api/app/modules/scorm/router.py:720-743`.
- **Доказательство:** `cmi: dict[str, Any]` принимается и merge-сохраняется без видимого allowlist/depth/key/value/serialized-size budget.
- **Влияние:** JSONB bloat, чрезмерные payloads и мусорные ключи; ухудшение availability/целостности progress.
- **Исправление:** typed allowlist SCORM fields, request/body/depth/string-size caps, total serialized budget, rejection metrics.
- **Критерий закрытия:** oversized/deep/unknown CMI payloads дают 422/413 и не изменяют запись.

### SEC-011 — PII и фрагменты клиентского контента попадают в logs

- **Severity:** Medium
- **Статус:** исправлено локально; aggregator/Sentry readback остаётся gate.
- **Расположение:** `apps/api/app/modules/users/kiosk_service.py:353,468`; `apps/api/app/modules/ai/router.py:822,904`.
- **Доказательство:** логируется raw personnel number и первые 200 символов некорректного LLM output.
- **Влияние:** чувствительные данные попадают в централизованные logs/debug buffer и расширяют круг операторов/retention.
- **Исправление:** personnel HMAC/hash для корреляции, structured event IDs, no source/output text, централизованный redaction filter и log review tests.
- **Критерий закрытия:** synthetic secrets/PII не появляются в captured logs.
- **Локальное доказательство:** общий redactor установлен на root handlers,
  stdout/stderr tee, superadmin debug buffer и Sentry `before_send`; raw LLM
  fragments, filenames/document names и provider/parser exception strings
  удалены из call sites. Негативные tests покрывают email, телефон,
  JWT/Bearer/capability token, personnel number, PIN/password, extras, nested
  telemetry и traceback. Focused suite `53 passed`, backend unit `312 passed`.
  Production aggregator/Sentry canary readback не выполнялся.

### SEC-012 — Supply-chain артефакты не полностью закреплены

- **Severity:** Medium
- **Расположение:** GitHub workflows, `apps/api/Dockerfile:1,8`, `infra/docling-service/Dockerfile:1`.
- **Доказательство:** Actions/base images используют mutable tags; Poetry устанавливается без версии; SBOM/provenance/signature gate не найден.
- **Влияние:** непредсказуемый rebuild и повышенный риск compromise зависимостей.
- **Исправление:** pin Action commits и image digests, pin installer tooling, генерировать CycloneDX/SPDX SBOM, подписывать image/artifact и проверять signature при deploy.
- **Критерий закрытия:** rebuild exact SHA воспроизводит dependency/image identities; неподписанный artifact не разворачивается.

### SEC-013 — Backup имеет хороший baseline, но нет актуального KZ restore proof

- **Severity:** Medium
- **Статус:** код и локальные security contracts исправлены; operational KZ restore/offsite evidence остаётся gate.
- **Расположение:** `scripts/backup.sh`; `scripts/kz-restore-drill.sh`; `scripts/tests/backup_restore_validation.sh`; `docs/BACKUP_RESTORE_RUNBOOK.md`.
- **Доказательство:** backup переведён на GPG symmetric encryption с companion SHA-256, обязательным decrypt/`pg_restore --list` до публикации и проверяемым MinIO round-trip/governance retention. Drill всегда отвергает production/non-empty target, проверяет RPO/RTO, Alembic `0120`, pgvector, FORCE RLS и агрегаты, затем подписывает JSON evidence. Негативные env/tamper/source-contract tests проходят.
- **Влияние:** ложная уверенность в восстановлении; operator/environment drift; незамеченная подмена ciphertext.
- **Открытый gate:** выполнить свежий drill реального KZ backup в утверждённой disposable PostgreSQL 17 + pgvector DB, подтвердить immutable offsite readback и сохранить подписанный отчёт. Production DB для drill не использовать.
- **Критерий закрытия:** первый и затем квартальный restore drill с hash/count/schema/RLS checks, измеренными RPO/RTO и проверенной подписью отчёта.

### SEC-014 — Security headers неполны на frontend/landing

- **Severity:** Medium
- **Расположение:** `apps/web/next.config.js`, landing Next config/Vercel responses.
- **Доказательство:** пассивный HTTP check подтвердил HSTS, но не обнаружил CSP, `X-Content-Type-Options` и frame policy на frontend/landing; API эти headers возвращает.
- **Влияние:** меньше защиты от XSS/clickjacking/MIME confusion; особенно важно при SEC-001.
- **Исправление:** централизованные Vercel/Next headers, CSP report-only → enforce, `frame-ancestors`, `nosniff`, Permissions-Policy и подходящая Referrer-Policy.
- **Критерий закрытия:** header tests на app/landing/API и browser functional regression.

### SEC-015 — Secret scanning имеет неполное покрытие

- **Severity:** Low
- **Расположение:** `.github/workflows/ci.yml:330-335`.
- **Доказательство:** tracked signature scan не нашёл известных ключей, но CI устанавливает unpinned `detect-secrets`, исключает часть путей; полный локальный scan не завершился в установленный лимит.
- **Влияние:** нет доказательства отсутствия всех secret formats/history leaks.
- **Исправление:** pinned scanner, committed reviewed baseline, diff scan blocking, periodic full history scan в выделенном job, provider-side secret scanning/rotation playbook.
- **Критерий закрытия:** seeded canary secret блокирует PR; scan runtime контролируем.

### SEC-016 — Тестовое и runtime-доказательство tenant isolation неполное в текущем окружении

- **Severity:** Informational / assurance gap
- **Статус:** blocking CI contract реализован; первый DB-backed run и production read-only inventory остаются gate.
- **Расположение:** `.github/workflows/ci.yml`; `scripts/ci/run_rls_release_gate.sh`; RLS migrations/integration tests.
- **Доказательство:** static tenant gate PASS (246 queries/0 violations). CI использует ephemeral `pgvector/pgvector:pg17`; gate допускает только `APP_ENV=test`, точное подтверждение `EPHEMERAL_POSTGRES_ONLY` и localhost URL. Он проверяет PG17/pgvector/Alembic `0120`, атрибуты роли `lms_app`, FORCE RLS, cross-tenant CRUD, evidence/share, staff import, worker claim и superadmin isolation. Source-contract tests проходят, но локальный Docker daemon недоступен.
- **Влияние:** сильный source-level контроль не доказывает актуальные grants/policies production.
- **Исправление:** получить первый зелёный DB-backed GitHub Actions run на ephemeral PostgreSQL 17/pgvector и отдельно снять read-only inventory production policies/grants.
- **Критерий закрытия:** clean CI DB run и отдельный read-only production policy inventory.

## Положительные меры, которые следует сохранить

- JWT secret length/algorithm/issuer/audience/expiry validation.
- Tenant context до ORM и роли из активного назначения в БД.
- `FORCE RLS`, ownership triggers и tenant-scoped unique constraints.
- Memory-only access token и `httpOnly` refresh cookie.
- Candidate/assignment tokens с высокой энтропией, Argon2 PIN, expiry, revoke и lockout.
- Evidence-share hash tokens, expiry/download caps и fail-closed limiter.
- Signed-scan storage key не возвращается через API; запись append-only.
- File MIME/magic/size validation, duplicate hashes и compensation cleanup.
- SCORM ZIP traversal/file-count/uncompressed/compression-ratio controls.
- Backup permissions, encrypted archive, decrypt/`pg_restore` validation и guarded restore.
- Human review/publish boundary для AI-generated course/test.

## Рекомендуемый порядок исправлений

1. Завершить operational gates локально исправленных SEC-001..SEC-009, SEC-011 и SEC-013: KZ rollout/readback, isolated SCORM E2E, trusted-proxy/log canary, подписанный disposable restore.
2. Получить первый зелёный DB-backed PostgreSQL 17 RLS gate для SEC-016 и Linux container build; production DB в тестах не использовать.
3. Закрыть оставшийся hardening SEC-010, SEC-012, SEC-014 и SEC-015: typed/bounded SCORM CMI, pinned supply chain + SBOM/provenance, frontend headers/CSP, полный secret scan.
4. После этого провести production-equivalent load test и пентест по утверждённым rules of engagement.

Локальный remediation R-001..R-011 выполнен в общем рабочем дереве без commit/push/deploy и без production mutations. Это не является доказательством rollout: operational gates перечислены выше и в сводной карте аудитов. Для контрольной базы использовать [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) и [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x00-header/).
