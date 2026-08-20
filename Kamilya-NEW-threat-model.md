# Модель угроз Kamilya LMS

Дата: 2026-08-20
Состояние исходников: `Kamilya-NEW` / `master` / `288124d35e438b60ee781cbd126f751f60269dc9` с незакоммиченными параллельными изменениями
Метод: репозиторно-привязанный анализ архитектуры, потоков данных, публичных маршрутов и существующих защитных мер. Активная эксплуатация production не выполнялась.

## 1. Краткий вывод

Kamilya LMS — интернет-доступная мультитенантная система, в которой обрабатываются сведения о сотрудниках, учебные материалы, результаты тестирования, доказательства обучения и документы клиентов. Наиболее важная граница безопасности проходит не только между Интернетом и API, но и между тенантами, между доверенным приложением и загруженным клиентом контентом, а также между обычным входом и публичными capability-ссылками.

Архитектура содержит хорошие базовые меры: tenant-контекст до ORM, роли из действующего назначения в БД, `FORCE RLS` для значимых таблиц, криптографически случайные публичные токены, Argon2 для PIN, ограничение попыток, короткие JWT и tenant-scoped storage keys. Основные остаточные риски связаны с четырьмя путями злоупотребления:

1. сохранённый HTML/Markdown урока может выполнить JavaScript в браузере пользователя;
2. знание URL киоска и табельного номера достаточно для выпуска обычного пользовательского JWT;
3. SCORM-контент либо сейчас блокируется собственными заголовками защиты, либо при ослаблении заголовков окажется недоверенным JavaScript на origin API;
4. тяжёлые и архивные документы попадают в конвертеры без полного архивационного бюджета и запускаются в контейнерах с избыточными привилегиями.

До расширения коммерческой эксплуатации рекомендуется закрыть TM-01, TM-02 и TM-03, обновить monitoring на фактический KZ production и после этого провести пентест в изолированном production-equivalent контуре.

## 2. Область и допущения

### Включено

- Next.js-приложение `app.kml.kz` и публичный landing `www.kml.kz`;
- FastAPI API, PostgreSQL/RLS, Valkey, Celery workers, файловое хранилище;
- загрузка документов, Docling/LibreOffice, AI-генерация и pgvector;
- tenant admin, методист, сотрудник, superadmin;
- приглашения, assignment access, candidate assessment, kiosk, evidence share;
- CI/CD, контейнеры, backup/restore и пассивные production-проверки.

### Не включено

- эксплуатация уязвимостей на production;
- password spraying, brute force, social engineering и физический доступ;
- безопасность Vercel, Cloudflare, Proxmox и провайдера LLM за пределами наблюдаемой конфигурации проекта;
- Kamilya CRM, Docvoice и другие репозитории;
- юридическая квалификация категорий данных.

### Консервативные допущения

- production доступен из Интернета и обслуживает несколько юридически независимых тенантов;
- документы и учебные материалы могут содержать персональные и коммерчески чувствительные данные;
- пользователи с ролью методиста доверены только в пределах своего тенанта, но не считаются доверенными администраторами инфраструктуры;
- публичные ссылки могут пересылаться, попадать в историю браузера и сканироваться автоматическими системами;
- точный 12-месячный масштаб, наличие ИИН/биометрических/медицинских данных и предпочтительная площадка пентеста на момент отчёта владельцем не подтверждены. При изменении этих допущений ранжирование следует пересмотреть.

## 3. Модель системы

### Компоненты

| Компонент | Назначение | Доверие |
|---|---|---|
| Vercel frontend | UI администратора, методиста и сотрудника | Доверенный код, публичная поверхность |
| Public landing | Маркетинг и lead form | Публичная поверхность |
| Cloudflare/proxy/WireGuard | Маршрутизация к KZ production | Инфраструктурная граница |
| FastAPI | Auth, tenant/RBAC, бизнес-функции, публичные ссылки | Критический enforcement point |
| PostgreSQL 17/pgvector | Tenant data, evidence, задания, embeddings | Главный защищаемый datastore |
| Valkey/Celery | rate limit, очереди, фоновые задания | Внутренний контур |
| Object/file storage | Исходные документы, результаты и сканы | Недоверенный вход, чувствительное хранение |
| Docling/LibreOffice | Разбор недоверенных документов | Высокорисковый parser sandbox boundary |
| LLM providers | Генерация курса/теста | Внешняя/частная модель, prompt-injection boundary |
| Email | OTP и приглашения | Внешний канал доставки capability |

### Основные потоки данных

1. Пользователь входит по паролю/коду; API выдаёт access token, refresh хранится в `httpOnly` cookie.
2. Tenant admin/методист загружает штатную структуру и документы; API валидирует и сохраняет объекты.
3. Worker извлекает текст, создаёт embeddings и вызывает LLM; результат сохраняется как редактируемый черновик курса/теста.
4. Методист публикует и назначает обучение; сотрудник входит обычным способом или через ограниченную ссылку/PIN.
5. Результат обучения записывается в evidence ledger, экспортируется в PDF/сертификат и может сопровождаться подписанным сканом.
6. Публичные candidate, assignment, kiosk и evidence-share маршруты разрешают строго ограниченный доступ без обычной интерактивной аутентификации.

### Границы доверия

- TB-01: Интернет → Vercel/landing/API.
- TB-02: frontend → API; браузер и его DOM считаются потенциально скомпрометированными.
- TB-03: tenant A → shared API/DB → tenant B.
- TB-04: загруженный файл/SCORM → parser/converter/runtime.
- TB-05: извлечённый текст → LLM → сгенерированный HTML/quiz.
- TB-06: публичный токен/PIN/табельный номер → ограниченная authenticated session.
- TB-07: API/workers → PostgreSQL/Valkey/storage/SMTP/LLM provider.
- TB-08: CI/CD и registry → production artifact.
- TB-09: backup archive → restore target.

## 4. Активы и цели защиты

| Актив | Цель |
|---|---|
| Tenant isolation | Ни один запрос, worker или export не пересекает границу тенанта |
| Учетные записи и роли | Роль определяется сервером из действующего назначения |
| Персональные данные | Минимизация, конфиденциальность, контролируемое логирование |
| Документы клиентов | Целостность, приватность, безопасный разбор |
| Результаты и evidence | Неизменность, авторство, воспроизводимость, retention |
| Курсы/тесты | Защита от подмены, XSS и prompt injection |
| Capability-токены | Непредсказуемость, expiry, revoke, узкий scope |
| Availability | Устойчивость к resource exhaustion и злоупотреблению публичными маршрутами |
| Production artifact | Воспроизводимость, происхождение, отсутствие секретов |
| Backup | Конфиденциальность, целостность, проверяемое восстановление |

## 5. Модель атакующего

- неаутентифицированный интернет-пользователь;
- сотрудник одного тенанта, пытающийся получить доступ к другому;
- методист/администратор тенанта, загружающий специально подготовленный документ;
- получатель пересланной публичной ссылки или наблюдатель табельного номера;
- вредоносный/скомпрометированный LLM provider либо prompt injection внутри документа;
- злоумышленник в цепочке поставки npm/Python/Docker/GitHub Actions;
- оператор инфраструктуры с доступом к логам, backups или runtime secrets.

Не предполагаются права администратора гипервизора или физический доступ к серверу: при них контроль приложения недостаточен.

## 6. Точки входа

- `/login`, refresh, регистрация и OTP;
- `/assignment-access/*`, `/candidate-assessments/public/*`, invitations;
- `/kiosks/{token}` и `/kiosks/{token}/identify`;
- evidence-share и learner evidence export;
- lead form;
- documents upload, SCORM upload/launch/commit, signed scans;
- импорт штата/структуры;
- AI generation и regeneration;
- superadmin и tenant admin API;
- worker queues, Docling API, storage callbacks;
- CI workflows, Docker images, migrations и deployment secrets.

## 7. Сценарии злоупотребления

### TM-01 — Stored XSS через содержание урока

- **Актор:** скомпрометированный методист, вредоносный документ или LLM output.
- **Предусловие:** возможность сохранить содержание урока.
- **Путь:** HTML попадает в `simpleMarkdown`, затем напрямую в `dangerouslySetInnerHTML` в `apps/web/src/app/courses/[id]/page.tsx:688,885`.
- **Влияние:** выполнение JavaScript в контексте `app.kml.kz`, действия от имени пользователя, чтение доступных данных и API-вызовы.
- **Существующие меры:** access token не хранится в localStorage; API авторизует действия серверно.
- **Пробел:** HTML не экранируется/не очищается; frontend не задаёт CSP.
- **Митигация:** безопасный AST renderer или allowlist sanitizer; регрессионные тесты XSS; CSP с nonce после инвентаризации inline-кода.
- **Обнаружение:** CSP reports, audit событий редактирования и публикации.
- **Приоритет:** P0 / High.

### TM-02 — Захват kiosk session по табельному номеру

- **Актор:** посетитель офиса, сотрудник, получивший URL, удалённый пользователь при утечке ссылки.
- **Предусловие:** URL киоска и угадываемый/наблюдаемый табельный номер.
- **Путь:** публичный `POST /kiosks/{token}/identify` считает URL и табельный номер достаточными credential (`kiosk_router.py:299-317`), после lookup выпускается обычный role-bearing JWT (`kiosk_service.py:343-350,480-489`).
- **Влияние:** доступ к курсам и действиям другого сотрудника; возможность enumeration; компрометация privacy.
- **Существующие меры:** случайный kiosk token, короткая session, tenant RLS, scope по должности, audit log.
- **Пробел:** нет PIN/OTP/одноразового QR, per-person lockout и узкого kiosk scope; различимые причины отказа; raw personnel number в логах.
- **Митигация:** второй фактор уровня сотрудника, generic response, hash-based lockout, отдельный kiosk-scoped principal/JWT, редактирование PII в логах.
- **Обнаружение:** корреляция неуспешных идентификаций по kiosk/personnel hash/IP.
- **Приоритет:** P0 / High.

### TM-03 — Выполнение недоверенного SCORM-кода на доверенном origin

- **Актор:** methodologist или автор SCORM-пакета.
- **Предусловие:** загрузка SCORM ZIP.
- **Путь:** приложение встраивает SCORM без `sandbox` (`page.tsx:619-624`), API отдаёт package HTML/JS на origin API. Одновременно middleware задаёт `X-Frame-Options: DENY` и `frame-ancestors 'none'` (`security.py:16,30`), что делает текущий flow функционально конфликтным.
- **Влияние:** при ослаблении headers — same-origin script execution и доступ к API; при сохранении headers — отказ функции.
- **Существующие меры:** traversal/file-count/uncompressed-size/compression-ratio checks.
- **Пробел:** нет выделенного untrusted content origin и sandbox/message bridge.
- **Митигация:** отдельный origin без auth cookies, sandboxed iframe с минимальными разрешениями, строгий `postMessage` contract, CSP для SCORM origin.
- **Обнаружение:** CSP reports, блокирование неожиданных network destinations.
- **Приоритет:** P0 / High.

### TM-04 — Resource exhaustion через документ/архив

- **Актор:** пользователь с upload permission или скомпрометированная учётная запись.
- **Предусловие:** разрешённые DOCX/XLSX/SCORM/PDF.
- **Путь:** API читает файл целиком (`documents/router.py:538`); DOCX/XLSX проверяются только по `PK` magic; converter запускает сложные parsers.
- **Влияние:** память API, CPU/RAM worker, очередь, диск и availability всех тенантов.
- **Существующие меры:** 50 MiB cap, MIME/magic allowlist, SCORM archive budgets, Docling semaphore/timeouts.
- **Пробел:** нет OOXML archive budget; контейнеры root; Docling key fail-open when empty.
- **Митигация:** streaming upload, OOXML preflight, per-tenant quotas, non-root/cap-drop/read-only FS/pids/memory/CPU/network limits, production fail-fast для service auth.
- **Обнаружение:** queue depth, conversion duration, memory, decompression rejection metrics.
- **Приоритет:** P1 / High.

### TM-05 — Межтенантный доступ из-за ошибочного query/worker context

- **Актор:** пользователь tenant A или дефектный background job.
- **Предусловие:** забытый tenant predicate/context.
- **Путь:** shared schema и общие workers.
- **Влияние:** утечка данных tenant B, несанкционированное изменение/экспорт.
- **Существующие меры:** tenant context, DB roles, `FORCE RLS`, ownership triggers, tenant-gate и integration tests.
- **Пробел:** runtime RLS suite не выполнен в текущем окружении без PostgreSQL; source-only PASS не доказывает production grants.
- **Митигация:** обязательный disposable-DB integration gate, nightly cross-tenant suite, миграционный policy inventory.
- **Обнаружение:** tenant mismatch audit events, canary tenant records.
- **Приоритет:** P1 / Medium-High.

### TM-06 — Обход/DoS rate limit

- **Актор:** неаутентифицированный клиент.
- **Путь:** неверная runtime trusted-proxy настройка либо регрессия verified
  principal/public capability classification может снова объединить клиентов,
  разрешить IP spoofing или открыть fail-open route.
- **Влияние:** разбиение/засорение bucket, tenant-targeted DoS, неверное объединение клиентов за reverse proxy.
- **Митигация:** bucket по проверенному principal после auth либо по IP до auth; trusted-proxy configuration; fail-closed для всех credential-issuing routes; route-specific composite keys.
- **Текущее состояние:** локально реализовано; production readback точного
  `FORWARDED_ALLOW_IPS`, Nginx header chain и socket peer остаётся release gate.
- **Приоритет:** P1 / Medium.

### TM-07 — Prompt injection и утечка через AI pipeline

- **Актор:** автор документа или внешний LLM provider.
- **Путь:** инструкции внутри документа влияют на generation; ошибочный ответ частично пишется в log (`ai/router.py:822,904`).
- **Влияние:** нежелательный контент курса, вывод чувствительного текста в logs, попытка выхода за structured contract.
- **Существующие меры:** schema parsing, human review/publish boundary, tenant-scoped source provenance.
- **Пробел:** raw response fragments в logs; нет формализованной prompt-injection regression corpus/provider data policy evidence.
- **Митигация:** не логировать source/output text, строгий structured output, content-policy checks, provenance, adversarial eval suite, provider retention controls.
- **Приоритет:** P1 / Medium.

### TM-08 — Supply-chain compromise

- **Актор:** скомпрометированный package/image/action.
- **Путь:** mutable Action/Image tags, mixed npm/pnpm locks, unpinned tooling, non-blocking gates.
- **Влияние:** malicious build, секреты CI, production artifact подменён.
- **Митигация:** один package manager, pin Actions by SHA, pinned base-image digest, SBOM, provenance/signature, blocking SCA/SAST/type/lint gates.
- **Приоритет:** P1 / High.

### TM-09 — Невосстановимый или подменённый backup

- **Актор:** ransomware, operator error, storage attacker.
- **Путь:** backup/restore failure либо изменение ciphertext без authenticated encryption.
- **Влияние:** потеря production data или восстановление некорректного архива.
- **Существующие меры:** strict permissions, encrypted archive, decrypt/`pg_restore` validation, guarded restore.
- **Пробел:** runbook описывает старый Supabase production; нет свежего KZ restore proof; AES-CBC не даёт встроенную authenticated integrity; offsite isolation не подтверждена.
- **Митигация:** новый KZ restore drill, immutable offsite copy, AEAD/Encrypt-then-MAC, измеренные RPO/RTO.
- **Приоритет:** P1 / High.

## 8. Реестр рисков

| ID | Вероятность | Влияние | Риск | Приоритет |
|---|---|---|---|---|
| TM-01 Stored XSS | Высокая | Высокое | Критичный для браузерной сессии | P0 |
| TM-02 Kiosk impersonation | Средняя-высокая | Высокое | Высокий | P0 |
| TM-03 SCORM trusted-origin | Средняя | Высокое | Высокий | P0 |
| TM-04 Document resource exhaustion | Средняя | Высокое | Высокий | P1 |
| TM-05 Cross-tenant regression | Низкая-средняя | Критическое | Высокий | P1 |
| TM-06 Rate-limit bypass/DoS | Средняя | Среднее | Средний | P1 |
| TM-07 AI prompt/log leakage | Средняя | Среднее | Средний | P1 |
| TM-08 Supply chain | Средняя | Высокое | Высокий | P1 |
| TM-09 Backup/restore | Низкая-средняя | Критическое | Высокий | P1 |

## 9. Обоснование ранжирования

P0 присвоен сценариям, для которых уже существует прямой путь от разрешённого пользовательского входа к выполнению кода/выдаче сессии либо фундаментальный конфликт доверия. P1 — рискам, требующим дополнительного условия или не подтверждённым runtime-exploit, но способным затронуть несколько тенантов, availability или восстановление. Отсутствие активного exploit не понижает риск там, где source path однозначен.

## 10. Приоритетные меры

### P0 — до расширения использования

1. Убрать raw HTML rendering уроков и добавить XSS regression corpus.
2. Переделать kiosk authentication: второй фактор, narrow principal, lockout, generic errors, PII-safe logs.
3. Вынести SCORM на отдельный untrusted origin; до этого отключить либо явно ограничить запуск SCORM.
4. Исправить production monitoring, чтобы он проверял `api.kml.kz`, а не старый Render endpoint.

### P1 — ближайшие 1–2 спринта

1. OOXML/Docling sandbox и resource budgets.
2. Rate-limit identity/proxy hardening.
3. Обновление уязвимых Node-зависимостей и нормализация lockfile.
4. Сделать Ruff/mypy/security gates блокирующими после baseline cleanup.
5. Удалить PII/raw AI fragments из logs.
6. Провести KZ backup restore drill и подтвердить offsite/immutable copy.
7. Запустить disposable PostgreSQL RLS/integration suite.

### P2

1. SBOM, build provenance, image signing и immutable digests.
2. Adversarial AI evals и формальный provider privacy contract.
3. Нагрузочное профилирование API, worker, DB и converter отдельно.

## 11. Остаточный риск и проверка

После исправлений нужны четыре независимых доказательства:

- unit/integration regression для каждого TM-ID;
- production-equivalent cross-tenant/RBAC/RLS suite;
- authenticated DAST/pentest с тремя тенантами и capability-link abuse cases;
- restore drill и load test с измеренными SLO/RPO/RTO.

Пентест следует проводить на disposable клоне с синтетическими данными. Production допускается только для ограниченного passive/low-impact этапа с согласованными IP, временем, лимитами запросов, аварийными контактами и stop conditions. Методические ориентиры: [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/), [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x00-header/) и [OWASP WSTG](https://owasp.org/www-project-web-security-testing-guide/).
