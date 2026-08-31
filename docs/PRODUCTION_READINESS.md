# Kamilya LMS: готовность первого production-тенанта

**Проверено:** 2026-08-08 по исходникам, CI и production-контурам
**Технический P0 baseline:** закрыт
**Режим запуска:** dev/test и контролируемая демонстрация; подключение первого
коммерческого tenant с персональными данными остаётся за отдельным KZ
DB/storage gate и приёмкой клиента
**Назначение:** единственный актуальный реестр production-gates. История изменений
остаётся в Git; отдельные датированные отчёты не используются как источник
текущего состояния.

## Staff Sync production release 2026-08-26

| Контур | Состояние | Подтверждение |
|---|---|---|
| Application release | PASS | exact SHA `7718615758a6cdbf25bf9faa2cc8bcf119ffb0a7` |
| CI | PASS | GitHub Actions run `32953790547` |
| Immutable package | PASS | `kamilya-release-7718615758a6.tar.gz`, SHA-256 `f16490ebf80a4cf6f18acc7f4b7cecf58c3b9c222aadc8d116f1a59f2edbe744` |
| CT125 backup | PASS | fresh encrypted archive `kamilya_staging_20260826T101849Z.dump.gpg`; mode and SHA sidecar verified |
| Signed restore drill | PASS | signed report `kz_restore_drill_20260826T102339Z.json`; signature verified; disposable database and temporary plaintext/passfiles absent |
| Database | PASS | Alembic `0132`; three Staff Sync tables, all three with FORCE RLS; zero Staff Sync rows after release |
| API and workers | PASS | API plus `worker-ai`, `worker-documents`, and `worker-ops` use `kamilya-api:7718615758a6`; public/private health return the exact full SHA and `kz-production` |
| Frontend | PASS | Vercel deployment `dpl_CZMyqgFJqBYLM9q5om2EHGgyCAZ3`, project `web`, READY; alias `app.kml.kz` resolves to this exact deployment and commit |
| Retention and watchdog | PASS | retention oneshot succeeded, timer active; watchdog readback `critical:0`, `warning:0` with exact expected release/image |
| Staff Sync auth boundary | PASS | unauthenticated credential GET and event POST both return HTTP 401; no credential, event, employee, or tenant row was created |

**Verdict:** technical production release GO. Enabling Staff Sync for a specific
tenant, issuing a credential, connecting its HR system, and processing real
employee data remain a separate tenant onboarding and data-processing gate.

## Временная доставка публичных заявок оператору 2026-08-13

Application patch `01373b14dad8ce338753956ae161cece8ec902c5` добавляет
вторичный канал уведомления о публичной заявке:

- после commit `TenantLead` и durable CRM outbox полная копия заявки
  отправляется через Resend на адрес из `PUBLIC_LEAD_NOTIFICATION_EMAIL`;
- письмо включает контактные и анкетные поля, UTM/GCLID, ROI-контекст, версию
  согласия, серверное время приёма и ID заявки;
- HTML экранируется, а стабильный provider idempotency key строится из ID
  заявки;
- недоступность почтового провайдера не меняет успешный ответ формы и не
  удаляет сохранённый lead; Google Sheets не используется.

Release evidence:

| Контур | Состояние | Подтверждение |
|---|---|---|
| Application CI | PASS | GitHub Actions `31695562054`; все jobs passed, включая PostgreSQL migrations/tests |
| API | PASS | Render deploy `dep-d9uqlj7qj5pc738931c0`, `live`, exact application patch |
| Database | PASS | Production Alembic `0108 (head)` после pre-deploy |
| Configuration | PASS | Render хранит точный временный Gmail-получатель; значение проверено без вывода секретов |
| API smoke | PASS | health `ok`; пустой публичный lead получил `422` без создания записи |
| Email provider smoke | PASS | синтетическое письмо с явной отметкой «не заявка клиента» принято Resend; получение в Gmail проверяется владельцем адреса |

Этот канал является временным и best-effort. Источниками истины остаются
PostgreSQL и durable CRM outbox; после принятия операторского интерфейса CRM
пересылка отключается пустым значением переменной окружения.

## Platform operator login hardening 2026-08-08

Application patch `472e5fb1e98f5542bc63b1366512d8410138c8a6` закрывает
публичное раскрытие операторского входа:

- `/login/demo` больше не содержит ссылку или текст о superadmin;
- `/superadmin/login` доступен только по прямому служебному URL, получает
  `noindex, nofollow, nocache` и не содержит имени оператора;
- приложение инициализирует email и password пустыми и отключает
  автозаполнение формы. Значения, которые Chrome всё же показывает из
  локального хранилища паролей, не передаются приложением;
- рабочая production-пара из локальных `SUPERADMIN_EMAIL` и
  `SUPERADMIN_PASSWORD` проверена без раскрытия значений: API вернул `200`,
  браузер перешёл на `/admin/super`, после smoke сессия завершена;
- tenant-admin credentials и сохранённая браузером устаревшая пара не являются
  реквизитами платформенного superadmin и закономерно получают `401`.

Штатный вход оператора: открыть прямой URL
`https://app.kml.kz/superadmin/login`, использовать актуальные значения
`SUPERADMIN_EMAIL` и `SUPERADMIN_PASSWORD` из локального `.env`. Эти значения
не коммитятся и не должны появляться в документации, скриншотах или браузерной
консоли.

Release evidence:

| Контур | Состояние | Подтверждение |
|---|---|---|
| Application CI | PASS | GitHub Actions `31233974461` |
| Production smoke | PASS | GitHub Actions `31233974447` |
| Frontend | PASS | Vercel `dpl_3NguzZwuTjvDDjFYfRnmzJSvFso6`, `READY`, alias `app.kml.kz`, exact patch |
| Browser regression | PASS | публичная ссылка отсутствует; operator form пустая и noindex; реальный вход и logout успешны |

## Demo reliability release 2026-08-08

Application patch `09612c270ae620226351c4d0444887c6be19faf4` устраняет
расхождение между фиксированным demo-обучающимся и очищаемыми sandbox-данными:

- `student` demo-login под блокировкой строки идемпотентно проверяет наличие
  назначения на опубликованный курс;
- при отсутствии назначения выбирается established опубликованный курс tenant,
  создаётся immutable release для legacy-курса и одно enrollment;
- если в demo-tenant нет ни одного опубликованного курса, вход закрывается
  явным `503`, а не открывает пустой кабинет;
- публичный экран предлагает только разрешённые production-роли
  `methodologist` и `student`; запрещённая backend роль `admin` больше не ведёт
  пользователя к ожидаемому `404`.

Release evidence:

| Контур | Состояние | Подтверждение |
|---|---|---|
| Application CI | PASS | GitHub Actions `31233221911` |
| Frontend | PASS | Vercel `dpl_Afzc1MtrfNPDuNG5mknmb5AyRjLN`, `READY`, exact patch |
| API | PASS | Render `dep-d9r8k4lbedkc73feri9g`, `live`, exact patch |
| Production data repair | PASS | demo student назначен на «Охрана труда для офисных сотрудников»; повторный dashboard вернул один enrollment и четыре урока |
| Browser smoke | PASS | `/login/demo` не показывает admin, student открывает `/my-courses`, видит курс и первый урок с AI-ассистентом |

Локально прошли 927 backend tests, 249 frontend tests, TypeScript typecheck и
Next.js production build. Исправление не меняет миграции или worker-код.

## Acquisition release 2026-08-07

Application patch `4d5cc7e9c8f9ccc9f196ae08276a5f47d650c1a7` сохраняет
рекламную атрибуцию от публичного лендинга до trial-регистрации и lead:

- `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term` и
  `referrer` проходят через `app.kml.kz/register-tenant`;
- атрибуция регистрации сохраняется в tenant settings, `TenantLead` и audit;
- demo/pricing/ROI lead сохраняет CTA section, plan и контекст оценки;
- backend ограничивает длину каждого публичного поля; production validation
  smoke подтвердил новые `utm_content` и `source_section` без создания данных.

Release evidence:

| Контур | Состояние | Подтверждение |
|---|---|---|
| Application CI | PASS | GitHub Actions `31166627289`: все 7 jobs passed |
| External smoke | PASS | GitHub Actions `31166627743` |
| Frontend | PASS | Vercel `dpl_9gwdhcPPXrgyW5yy3JLzRh98bU3M`, `READY`, alias `app.kml.kz`, exact application patch |
| API | PASS | Render `dep-d9qqi0c9v7es73ffqg60`, `live`, exact application patch; health `ok` |
| Landing | PASS | отдельный repo commit `a7b83855693642186d43ad9b35c79d9b2dd503d6`, Vercel `dpl_8zoX4aLGoDntNFvutwxpTQGLdNpn`, `READY`, aliases `kml.kz`/`www.kml.kz` |
| Landing QA | PASS | RU/KK, privacy, canonical/hreflang, JSON-LD, UTM CTA и отсутствие снятых legal/commercial claims проверены в production |

Для Vercel frontend и Render API commit-hook не создал deployment после push,
хотя Git integrations и auto-deploy включены. Оба deployment были запущены
через официальные API на точный проверенный SHA. Причину пропуска webhook нужно
наблюдать на следующем release; это не изменило содержимое текущего релиза.
Worker-код этим patch не затрагивался и не переразворачивался.

## Текущий production release

P1-контур и bounded document/AI pipeline выпущены в production на application
commit `c4a5eb8bf58989eff4f4338272dc68941bd416bd`:

1. append-only события обучения и проверки знаний, correction, revocation и
   legal hold;
2. purpose-bound email OTP для подтверждения конкретного результата;
3. learner own-read API и возобновление незавершённого подтверждения;
4. индивидуальные и групповые PDF/ZIP из журнала методолога;
5. tenant procedures с activation gates для acknowledgement/attestation/admission;
6. restricted immutable evidence share с expiry/download cap/revoke/rate limit;
7. retention policies, persistent cursor и bounded dry-run/manual purge;
8. bulk invitation Celery delivery с lifecycle/provider id/errors и manual fallback;
9. Telegram Redis Lua one-time atomic consume и production fail-closed.
10. локальный гибридный конвертер документов: MarkItDown 0.1.6 для Office и
    PDF с текстовым слоем, Docling для сканов/OCR и LibreOffice для старого
    `.doc`;
11. изолированные очереди `ai`, `documents`, `notifications`, `maintenance` и
    три Celery worker с AI concurrency 2 и последовательной индексацией.
12. tenant-fair admission для AI-генерации: не более двух `pending/running`
    задач на компанию, атомарная проверка до списания лимитов, tenant-relative
    позиция/ETA в UI и стабильный `429` с `Retry-After`.

Общая dev/test Supabase обновлена до Alembic `0089`. GitHub CI, внешний smoke,
Render API, Vercel frontend и VPS Celery workers проверены на exact application
release.
Telegram webhook защищён отдельным secret token, Telegram API сообщает нулевую
очередь и отсутствие ошибки webhook, а public auth capabilities возвращает
`telegram_login_enabled=true`. Полная прикладная приёмка ломбарда с его
пользователями и документами сознательно отложена до согласованного клиентского
теста; технический release evidence не подменяет эту приёмку.

## Проверенный release manifest

Manifest относится только к указанному SHA. Более новый commit требует новой
сверки каждого контура.

| Контур | Состояние | Подтверждение |
|---|---|---|
| Application release | PASS | `c4a5eb8bf58989eff4f4338272dc68941bd416bd` |
| CI | PASS | GitHub Actions `31092967471`: frontend, backend, mypy, secrets и security gates |
| External smoke | PASS | GitHub Actions `31092967755`; после Render rollout те же API/login endpoints отдельно подтверждены HTTP 200 |
| Frontend | PASS | Vercel production `dpl_AYjE7QGd1n9hRv5tARDfvYx1WUAP`, состояние `READY`, exact application release |
| API | PASS | Render deploy `dep-d9q623bm8hqs73e1r40g`, состояние `live`, exact application release; health `200` |
| Worker | PASS | `/opt/kamilya-worker` на exact application release; `fast`, `documents`, `ai` active/enabled; Celery ping, registration и active queues соответствуют routing |
| Document converter | PASS | `docling.service` active; routing `1.2`, Docling `2.106.0`, MarkItDown `0.1.6`, LibreOffice available; DOCX/XLSX/digital-PDF/OCR smoke и 50-request digital-PDF test passed |
| Telegram | PASS | Webhook `https://kamilya-lms-api.onrender.com/api/v1/telegram/webhook`, secret token настроен, pending updates `0`, ошибок нет |
| Database baseline | PASS (dev) | shared dev/test Supabase, Alembic `0089`; коммерческий KZ PostgreSQL остаётся отдельным release gate |

## Закрытые P0

### Public auth и rate limiting

- OTP и Telegram-коды не выводятся в application logs.
- Ошибки провайдера не возвращаются клиенту.
- Все public auth routes fail closed при недоступности Valkey.
- После краткого сбоя limiter повторно подключается через 5 секунд, поэтому
  login не остаётся заблокированным до рестарта API.
- Login/register/OTP всегда ограничиваются по IP; неподписанный JWT не может
  подменить bucket.
- Invitation, kiosk, assignment-link, candidate и public lead routes также
  fail closed при недоступном Valkey; capability в bucket сохраняется только
  как hash. Authenticated bucket создаётся только из полностью проверенного
  access/kiosk JWT.
- KZ Uvicorn доверяет forwarded headers только от точного WireGuard proxy
  `10.77.77.1`; route-код не читает `X-Forwarded-For` напрямую.
- Реально применяются burst, minute и hour windows.
- Production probe: четвёртый запрос в burst получил `429` и
  `Retry-After: 10`; после cooldown endpoint снова отвечал.
- Refresh credentials выдаются только в `HttpOnly` cookie; JSON-ответы содержат
  только короткоживущий access token. В БД хранится SHA-256 хеш refresh token,
  а не сам credential.
- Каждая refresh-сессия находится в tenant-scoped allowlist. Обновление
  атомарно потребляет старую запись и создаёт новую; повторное использование
  старого token и refresh после logout получают `401`. Платформенный
  superadmin использует отдельный подписанный `platform` claim и RLS-контекст.
- Post-deploy smoke для каждого релиза auth-кода: login -> reload -> refresh ->
  повтор старой cookie (`401`) -> logout -> refresh текущей cookie (`401`).

### Активация приглашения обучающегося

- Публичный view не раскрывает полный email и показывает кадровые ФИО,
  должность и назначенные опубликованные курсы только для чтения.
- Invitation OTP отделён от обычного login OTP, привязан к invitation ID,
  действует пять минут и удаляется после пяти неверных попыток.
- Resend принимает production-запрос отправки кода; при ошибке доставки код
  удаляется, а API возвращает контролируемый `503`.
- После успешной проверки фиксируются `email_verified_at`,
  `verification_method=email_otp`, IP и User-Agent; существующая карточка
  сотрудника активируется без создания дубля и изменения кадровых данных.
- `401` публичных email/invitation OTP не запускает общий session refresh,
  logout или redirect на `/login`; ошибка остаётся в исходной форме.
- Контрактный тест подтверждает выдачу refresh-cookie с `HttpOnly`, `Secure`,
  `SameSite=None`, `Partitioned` и `Path=/api/v1/auth`.
- Production smoke: public view `200`, полный email отсутствует, identity и
  один назначенный курс возвращены, request-code `200` с TTL 300 секунд.

### Trial concurrency

- Проверка и резервирование AI/JD generation выполняются атомарно.
- Лимиты курсов, обучающихся и системных пользователей защищены tenant row lock.
- Первый `TenantUsage` создаётся под тем же lock.
- PostgreSQL concurrency tests покрывают AI, course, learner и staff import.

### Backup и восстановление

- На VPS установлен только PostgreSQL client 17.10; production DB остаётся в
  Supabase.
- `kamilya-backup.timer` active/enabled, ежедневный запуск около 02:15.
- Backup хранится локально только в AES-256-CBC + PBKDF2 виде.
- Passphrase, pgpass и service env имеют режим `0600`; backup directory `0700`.
- Реальный архив `kamilya_20260727T072839Z.dump.enc`: 6 402 000 bytes,
  режим `0600`, внутренний TOC проверен `pg_restore`.
- Plaintext dump после backup не остаётся.
- Реальный restore drill выполнен в одноразовый PostgreSQL 17 + pgvector:
  Alembic `0078`, 56 public tables, агрегаты тестовых данных восстановлены.
- Portable Supabase restore явно исключает platform-owned
  `supabase_vault`/`vault` data и создаёт отсутствующую schema dependency
  `lms_app` как `NOLOGIN`. Runtime password/LOGIN на новом кластере задаётся
  отдельным provisioning-шагом.
- После drill одноразовый контейнер и локальная копия архива удалены.

### Наблюдаемость

- Superadmin console `/admin/super/operations` показывает агрегаты AI queue,
  документов, DB pool и процесса без tenant PII.
- Cleanup synthetic tenants выполняет dry-run по умолчанию и допускает
  удаление только demo tenant с фиксированным test-prefix, возрастом не менее
  24 часов и typed confirmation.
- `kamilya-ops-check.timer` active/enabled, запуск каждые 5 минут.
- Проверяются worker unit, Valkey unit, API, frontend, возраст backup,
  заполнение диска и реальный Celery inspect ping.
- Alert/recovery отправляются через Resend; неуспешная отправка не включает
  cooldown и будет повторена.
- Тестовое monitoring-письмо принято Resend.
- GitHub production smoke работает каждые 15 минут и на каждый push в `master`;
  при сбое открывает или обновляет incident issue, при восстановлении закрывает.
- Legacy `kamilya-trial-expiry.timer` отключён.

### AI-рекомендация аудитории курса

- AI-помощник методолога на экране редактора курса принимает явное действие
  **«Кому подходит этот курс?»** и распознаёт эквивалентный свободный вопрос.
- Backend строит tenant-scoped read-only снимок курса, структуры, групп,
  компетенций, правил и существующих назначений без ФИО и контактов сотрудников.
- Ответ содержит только существующие агрегированные области аудитории,
  численность, основания и ограничения данных.
- Для черновика переход к назначению недоступен. Для опубликованного курса
  помощник возвращает только ссылку на канонический `/assignments`; назначение
  выполняет методолог на этом экране.
- Production smoke на тестовом черновике вернул 47 подходящих сотрудников и
  0 существующих назначений. После запроса в БД осталось 0 `enrollments`,
  `position_courses`, `department_courses` и `organization_course_rules` для
  курса. Render request log подтвердил `POST /api/v1/ai/chat` с HTTP 200.

## Проверки кода и production-flow

- Финальный CI application release passed: GitHub Actions `31092967471`;
  production smoke `31092967755` также passed. После завершения Render rollout
  API health и frontend login отдельно вернули HTTP 200.
- Локально на том же application release прошли 903 backend tests; 36 focused
  AI/document tests отдельно подтвердили границы заголовков и course-wide
  anti-repetition contract.
- Для bounded pipeline локально пройдены 166 unit tests, 196 focused backend
  tests, 237 frontend tests и 3
  реальных document-operation integration tests на dev/test Supabase.
- На общей dev/test Supabase дополнительно пройдены критические DB/RLS suites;
  direct RLS assertion выполняется под runtime-ролью `lms_app`, а фабрики
  создают fixture-данные через владельца миграций.
- Focused backend P0 suites: 26 тестов канонической структуры штата и 17
  тестов invitation/SCORM contracts passed.
- Frontend architecture tests, typecheck и production build passed.
- Tenant/release/shell security gates passed.
- Graphify code graph обновлён после изменений.
- На VPS проверены routing и concurrency трёх Celery worker, authenticated
  converter smoke для DOCX/XLSX/digital PDF/scan, 50-request digital-PDF load,
  embedding batch из 50 фрагментов и две параллельные короткие LLM операции.
  Эти проверки не являются SLA для 50 OCR-сканов или 50 полных генераций.

## Production-приёмка первого пилота

27 июля 2026 года на production пройден удаляемый synthetic tenant journey:

1. регистрацию компании, email OTP, повторный вход и logout;
2. создание и вход `methodologist`;
3. загрузку и индексацию документа;
4. обычную AI-генерацию и генерацию по должностной инструкции;
5. review и публикацию обоих курсов;
6. ручное добавление сотрудника с каноническими `department_id`/`position_id`;
7. XLSX preview/commit;
8. правило должности и ручное назначение с проверкой идемпотентности;
9. приглашение обучающегося, получение OTP на кадровый email и принятие ссылки
   без изменения кадровых данных;
10. прохождение семи уроков и шести тестов;
11. завершение курса, проверку и скачивание сертификата;
12. JSON-журнал и Excel-совместимый CSV с русскими заголовками;
13. enforcement trial-лимитов `1/1` для обычного и должностного AI-курса,
    трёх обучающихся и двух системных пользователей;
14. удаление synthetic tenant и двух storage objects.

Все этапы завершились `PASS`. Это закрывает прикладной P0 для контролируемого
первого пилота; условные gates ниже остаются обязательными только если
соответствующая возможность продаётся клиенту.

### Evidence P0 и реальные документы ломбарда

30 июля 2026 года в production применена миграция `0081` и проверены:

1. неизменяемый `ContentRelease` с SHA-256 полного снимка опубликованного курса;
2. автоматическая привязка нового enrollment к текущему release;
3. полный immutable snapshot тестовой попытки и запрет неполной отправки ответов;
4. tenant ownership, RLS/FORCE RLS и DB-trigger на изменение evidence;
5. Render API, Vercel web и отдельный Celery worker на одном согласованном коде.

На тестовом tenant отдельно прогнаны два реальных источника ломбарда:

- PDF правил микрокредитования: исходник сохранён в object storage, OCR дал 99
  chunks, курс сформирован только по этому документу;
- legacy Word `.doc` должностной инструкции эксперт-оценщика: LibreOffice
  conversion, 17 chunks, курс по каноническому flow должности сформирован как
  3 модуля, 6 уроков и 18 вопросов.

Оба результата оставлены черновиками с `review_status=pending`. Это
подтверждает технический flow, но не заменяет содержательное одобрение
ломбардом и профильным юристом.

6 августа 2026 года на отдельном tenant `ТОО «Ломбард Сандық»` повторно
проверен реальный PDF правил микрокредитования: Docling OCR 2.106.0 обработал
21 страницу без fallback, создал 99/99 chunks и embeddings. Grounded generation
по единственному выбранному PDF создала draft из 4 модулей, 13 уроков,
13 тестов и 65 уникальных single-choice вопросов; у каждого вопроса ровно один
правильный вариант, порог 80%, лимит 3 попытки. Курс оставлен
`review_status=pending` для проверки методистом.

При приёмке обнаружено, что OCR lexical fallback сохранял пустой `chunk_id`,
хотя строки `document_embeddings` имели корректные идентификаторы. Исправлен
`VectorStore.get_all_chunks`, добавлен fail-closed guard для нетрассируемого
фрагмента и регрессионные тесты. Для созданного черновика 130 ссылок
восстановлены только после точного совпадения `doc_id`, текста и вычисленного
идентификатора; все 13 уроков теперь разрешаются до существующих строк индекса.

Повторная содержательная проверка выявила, что число уроков было приемлемым,
но четыре урока пересекали чужие тематические границы: заключительный урок
повторял общие положения, договор и обращения, а уроки о ставках, выплатах,
обеспечении и погашении частично дублировали друг друга. Черновик скорректирован
без публикации: 13 уроков и 65 вопросов сохранены, объём уменьшен с 9 580 до
7 357 слов, максимальное попарное пересечение шестисловных фрагментов снижено
с 18% до 6,9%. Десять затронутых вопросов заменены на вопросы в границах своих
уроков; у всех 65 вопросов осталось четыре варианта и ровно один правильный.
Изменённые уроки имеют `source_validation_status=needs_review`, а курс остаётся
`review_status=pending` до содержательного одобрения клиента.

17 августа 2026 года выполнен отдельный bootstrap реального tenant
`ТОО «Ломбард Сандық»` в KZ staging-базе `kamilya_staging` на Alembic head
`0111`. Импорт прошёл одной транзакцией через runtime-роль `lms_app` и создал:

- 12 сотрудников в двух филиалах по 6 человек, 4 должности;
- 2 исходных документа с совпавшими SHA-256 БД и object storage;
- 2 опубликованных и одобренных native-курса, 2 immutable release, 7 модулей,
  18 уроков, 18 тестов, 78 вопросов и 312 вариантов ответа;
- 6 правил должность–курс и 22 назначения.

Старые попытки, сертификаты, evidence-события, приглашения и временные
учётные данные не переносились; контрольные счётчики для них равны нулю.
Tenant RLS проверен runtime-ролью: при контексте нового tenant видны его 13
учётных записей (12 сотрудников и неактивный служебный импортёр), при чужом
tenant context — 0. API `/health` отвечает `ok`. На этапе bootstrap production
ещё не переключался; последующие methodologist/business smoke и cutover
зафиксированы ниже в отдельном разделе.

17 августа 2026 года создан изолированный Vercel project
`kamilya-lms-dev` (`prj_JN1xM4BMmhoHzDt6joPaCBXvOSLk`) для frontend dev-среды:

- Git repository `KamillaLMSCRM/Kamilya-NEW`, production branch проекта `dev`;
- root directory `apps/web`, framework Next.js;
- `NEXT_PUBLIC_API_URL` сначала был скопирован из действующего проекта, затем
  после закрытия DNS/TLS gate изменён на `https://api.kml.kz/api`;
- ignored-build contract разрешает сборку только для ветки `dev`;
- актуальный deployment `dpl_A3Jbt9fmYfQXowRQopQPsfs2punc` на exact SHA
  `69ef25c3383ddd35443e621618c640d708c867ba` имеет состояние `READY`;
- alias `kamilya-lms-dev.vercel.app` остаётся защищён Vercel Authentication;
  официальный `vercel curl` с автоматически выпущенным protection bypass
  получил `/login` и страницу Kamilya;
- собранный login chunk содержит `https://api.kml.kz/api`, не содержит Render
  hostname и содержит ожидаемый `/v1/auth/login`;
- CORS preflight от стабильного dev-origin через proxy возвращает 204 с одним
  набором allow-origin/credentials headers; `app.kml.kz` и `www.kml.kz`
  разрешены, неизвестный origin возвращает 400; безопасный invalid-login smoke
  дошёл до FastAPI и вернул ожидаемый 401;
- custom domains не добавлялись.

Vercel project `web` оставался привязан к `master`; на этом dev-этапе
`app.kml.kz` ещё не переключался. Dev deployment содержит только указанный Git
SHA и не включает незакоммиченные изменения рабочего дерева. Позднейший
production cutover описан ниже.

17 августа 2026 года подготовлен обратимый HTTPS ingress на proxy VPS для KZ
staging. Nginx virtual host `api.kml.kz` проксирует через подтверждённый
WireGuard peer на VM126 `10.77.77.2:8000`; `nginx -t`, reload, proxy-local и
external Host-header `/health` smoke прошли с HTTP 200. Перед изменением создан
root-only архив прежней Nginx-конфигурации, default site сохранён.

В authoritative Cloudflare создан DNS-only A-record
`api.kml.kz -> 92.38.49.167`; выпущен сертификат Let's Encrypt, активирован
`certbot.timer`, `443` слушает, HTTP перенаправляется на HTTPS, внешний HTTPS
`/health` вернул 200 с валидной проверкой имени сертификата, а
`certbot renew --dry-run` прошёл успешно. На этом ingress-этапе cutover ещё не
выполнялся: proxy-диск был заполнен на 82% (около 866 MiB свободно), а
Vercel production env и customer traffic не переключались. Затем был выдан
контролируемый KZ methodologist-доступ, выполнен business smoke и проведён
обратимый cutover, описанный ниже. Disk monitoring/cleanup proxy остаётся
обязательным операционным follow-up.

### Сертификаты

Baseline содержит версионированный PDF-шаблон, снимок данных выдачи, SHA-256
PDF, статусы срока/отзыва, предпросмотр настроек и публичную проверку по
номеру. Сертификат подтверждает внутренний результат Kamilya, но сам по себе
не является ЭЦП, государственной аттестацией или решением о допуске.

## Условные launch-gates

| Условие продажи | Что требуется |
|---|---|
| Коммерческий клиент загружает персональные данные | Создать отдельные KZ PostgreSQL/object storage, выполнить backup/restore и cutover smoke; общий Supabase оставить dev/test |
| Клиент использует внутреннюю аттестацию или допуск | Утвердить tenant-положение и форму, реализовать отдельный workflow решения комиссии/уполномоченного лица; результат теста не превращать в допуск |
| В пилот продаётся SCORM 1.2 | Пройти реальный пакет iSpring/Articulate: import, launch, resume, commit, completion, журнал |
| В пилот продаётся kiosk | Пройти privacy/auto-logout QA на реальном устройстве |
| Обещается 500 одновременных пользователей | Провести отдельный capacity test с p95, 5xx, DB connections, queue wait, CPU/RAM/disk |
| Нужен автоматический billing | До реализации использовать явно описанную ручную активацию superadmin |

Не заявлять ЭЦП, юридическое соответствие, SCORM, kiosk или локализацию данных как
закрытые свойства без прохождения соответствующего gate.

SCORM ingress must enforce a request-body limit no larger than
`MAX_SCORM_ZIP_BYTES`. Application defaults also cap ZIP file count, total and
per-entry uncompressed bytes, compression ratio, and manifest bytes; see
`apps/api/.env.example`.

## KZ production cutover: Lombard Sandyk (2026-08-17)

- Vercel project `web` production env использует
  `NEXT_PUBLIC_API_URL=https://api.kml.kz/api`.
- Production deployment `dpl_5fYKAQhbzgDT3PfpmtvopJq8hre5` имеет состояние
  `READY` и exact frontend SHA
  `69ef25c3383ddd35443e621618c640d708c867ba`; `app.kml.kz/login` отвечает 200,
  compiled login bundle содержит KZ API и не содержит Render hostname.
- Tenant `too-lombard-sandyk` активен в CT125, schema head `0111`; перенесены
  12 сотрудников, структура двух подразделений, 2 курса и назначения.
- Создана контролируемая methodologist-учётная запись. Её credential хранится
  только в локальном ACL-защищённом файле вне Git. Login, `/users/me`, courses,
  documents, training log и staff-structure API smoke прошли успешно.
- `kamilya-pg-backup.timer` active/enabled. После исправления проверки владельца
  временного dump ручной запуск завершился успешно; encrypted backup прошёл
  SHA-256 verification и сохранён с mode `0600`.
- Rollback-снимок прежнего Vercel production env хранится локально вне Git;
  предыдущий production deployment не удалён. Render/Supabase остаются
  dev/demo и rollback-контуром.

### Candidate assessment production verification (2026-08-19)

- Public manager и candidate routes присутствуют в Vercel production release
  `7b44f11a8b1494158609fec20c52c094a341fbc3`.
- KZ API и три Celery worker используют exact image `kamilya-api:db797fd`;
  CT125 остаётся на Alembic head `0111`, новых schema-изменений для исправления
  не потребовалось.
- На двух опубликованных immutable releases tenant `too-lombard-sandyk`
  подтверждён доступный candidate source: один курс содержит 12 тестов и 60
  вопросов, второй — 6 тестов и 18 вопросов.
- Полный удаляемый production journey прошёл: methodologist campaign create и
  activate, protected link/PIN, consent exchange, попытка, детерминированный
  score/pass, manager result и CSV. Candidate identity осталась изолированной
  от staff `users`.
- Найден и исправлен pre-context RLS defect публичного token exchange без
  выдачи `BYPASSRLS`: tenant UUID используется только для маршрутизации, а
  авторизация выполняется по полному token hash, PIN, expiry и revoke state уже
  внутри tenant context.
- После smoke campaign/candidate/credential/attempt удалены; residual state
  отсутствует. `kamilya-candidate-retention.timer` включён и активен, последний
  recovery service завершён с `success`.

Этот результат подтверждает production-работоспособность текущего candidate
assessment flow. Он не превращает score/pass в решение о найме: решение по
кандидату остаётся за клиентом.

Остаются эксплуатационные follow-up, не блокирующие вход методолога:
настроить штатный SSH/WireGuard admin path к CT125 вместо встроенной console,
проверить следующий автоматический backup по timer и добавить внешний alert на
возраст backup/health API.

## Открытые P1 release gates

### Юридические поверхности и согласия

Публичный минимум Document.KZ состоит из единого RU/KZ-уведомления о
конфиденциальности и обработке персональных данных, условий сайта и пробного
доступа, реквизитов в нижнем колонтитуле и контекстного согласия в формах.
Публичная оферта, отдельная cookie-policy, маркетинговое согласие и внутренний
приказ в этот пакет не входят. Коммерческая поставка оформляется только
индивидуальным B2B-договором и DPA из `docs/legal/`.

Миграция `0104` хранит неизменяемые версии и серверное время принятия
уведомления и условий при публичной регистрации; tenant/user ownership
проверяется триггером, RLS/FORCE RLS обязательны, а удаление связанного tenant
или пользователя ограничено до утверждённого архивирования. Публичная заявка
также принимает только каноническую версию согласия, а время фиксирует API.

Для текущего tenant основная БД, файловый runtime и резервные копии размещены в
KZ-контуре. Открытым договорным gate остаётся заполнение фактического реестра
внешних обработчиков и описание минимизированных внешних потоков (Vercel,
email и выбранные AI/LLM функции); нельзя заменять это утверждением, что вообще
все виды обработки происходят только в Казахстане.

Durable LMS→CRM lead outbox подготовлен миграцией `0094`: публичный lead и
outbox фиксируются одной транзакцией, payload подписывается по exact bytes,
retry ограничен, а superadmin видит только агрегаты. До production release
обязательны: применённая `0094`, одинаковый webhook secret в LMS/CRM,
зарегистрированные `crm.deliver_lead_outbox`/`crm.recover_lead_outbox`,
active/enabled минутный recovery timer и smoke
`landing submit -> CRM company/contact/deal/task` с повторной доставкой того же
`event_id` без дубля. До этой проверки рабочий код нельзя описывать как live.

AI course generation uses a durable, tenant-scoped execution claim. Duplicate
broker deliveries are skipped; a failed generation is terminal and is not
automatically replayed because a replay after provider work could duplicate
cost or draft content. Operations must use the existing job diagnostics and
an explicit user/superadmin recovery action after the root cause is resolved.

Код поддерживает опциональный бесплатный LLM-пул
`ThinkingCap -> Qwen NVFP4 -> существующий Qwen AWQ -> DeepSeek`, но это не
является доказательством его production-активации. Render сохраняет
`FREE_LLM_POOL_ENABLED=false`, потому что маршрут к приватным WireGuard
endpoint-ам с фактического Render runtime не подтверждён. Перед включением на
новом API/worker VPS обязательны `/v1/models`, неперсональный completion,
timeout/failover smoke и проверка журналов без prompt/response/tenant PII.

Автоматическая bulk delivery invitation link уже реализована в коде через
Celery. Invitation сохраняется до queue dispatch; lifecycle/provider id/errors
наблюдаемы, а copyable link остаётся manual fallback. До фактического deploy
не подтверждены worker registration/parity, broker/provider behavior и
end-to-end delivery smoke.

Также остаются открытыми scheduled purge, backup retention, отдельные
commission/authorized-decision workflows, KZ PostgreSQL/object storage и
реальный pawnshop acceptance test. OTP не ЭЦП; generic correction, completion
и quiz не создают training/knowledge/attestation/admission вне своих trusted
workflows. Остальной backlog ведётся в [`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md).
## KZ security release acceptance — 2026-08-22

Formal release and security verdict: **GO** for exact release
`c8381617bb510909f5a97e9de244744eee31db30`.

- `GIT-DERIVED`, `PROVIDER-CONFIRMED`: GitHub CI run `32564167526` passed,
  including full backend coverage, frontend gates, secrets detection, Alembic
  contract and disposable PostgreSQL 17 + pgvector RLS checks.
- `RUNTIME-DERIVED`: VM126 API and three workers run
  `kamilya-api:c8381617bb5`; public health returns `kz-production` and the exact
  release SHA; three Celery nodes answer ping; live Alembic is `0122`.
- `PROVIDER-CONFIRMED`: Vercel production deployment
  `dpl_9gp9F3vNmN1cxnSa5JSjnWQTKv6e` and dev deployment
  `dpl_CERmDcyPPCULfTrasWdiJHyx9wX5` are `READY` on the exact SHA.
- `RUNTIME-DERIVED`: CT125 uses PostgreSQL 17.11 and pgvector 0.8.6; runtime
  role `lms_app` is not superuser and has no `BYPASSRLS`; 77 of 77 RLS tables
  have FORCE RLS.
- `RUNTIME-DERIVED`: signed restore report
  `kz_restore_drill_20260820T170343Z.json` passed and its detached signature is
  valid. The offsite encrypted archive hash matches the signed report and
  sidecar, the proxy copy is immutable, and no restore database remains.
- `RUNTIME-DERIVED`: bounded disposable three-tenant security acceptance passed
  17 tests on synthetic data. Cleanup left zero pentest databases, containers,
  derived images and temporary files.

GitHub monitor issue `#3`, created by the pre-deployment SHA mismatch, was
automatically closed after scheduled production smoke `32565715719` passed on
the exact deployed SHA. The failed pre-deployment run remains preserved as
historical evidence.

## KZ document-upload release acceptance — 2026-08-24

Release verdict: **GO** for backend release
`d17a9206086d8557f797a13563353c406d0ce9f4`; the first authenticated production
document/course journey remains a separate owner-controlled synthetic rehearsal.

- `GIT-DERIVED`: GitHub CI run `32743293275` passed all jobs for the exact SHA,
  including 1,555 backend tests with two skipped, coverage above the required
  threshold, unit tests, PostgreSQL 17 + pgvector RLS gates, Alembic/Celery and
  tenant-security contracts, frontend checks, Python quality and secrets scan.
- `RUNTIME-DERIVED`: VM126 API and all three Celery workers run immutable image
  `kamilya-api:d17a9206086d`; exact public and private health identify
  `kz-production` and the full SHA. Application restart counts and bounded
  post-deploy error-pattern counts are zero.
- `RUNTIME-DERIVED`: production Alembic remains `0131 (head)`. No migration,
  tenant, database, blob, Valkey, Docling or frontend mutation was part of this
  deployment.
- `RUNTIME-DERIVED`: the public endpoint verifier passed. A no-credential,
  no-file request to `/api/v1/documents/upload` returned HTTP 401, proving the
  route is reachable without recreating the former edge HTTP 503 or creating a
  document. An authenticated production upload was deliberately not submitted.
- `RUNTIME-DERIVED`: rollback SHA
  `760eeb72cac972a9ff2b2763d770f9cfc31d15eb`, its image and release directory
  remain present. Timestamped backups of `compose.yml`, `runtime.env` and the
  watchdog configuration were retained. Transit archives were removed from the
  workstation, proxy and VM126.
- `RUNTIME-DERIVED`: VM126 had about 14 GiB available RAM and 8.8 GiB free disk
  after deployment. The watchdog expects the new release/image and reports a
  successful service with its timer enabled and active.
- `BLOCKED`: the current push-capable GitHub PAT receives HTTP 403 for Actions
  Variables, so an exact provider variable/readback and manual dispatch were not
  performed. The scheduled smoke workflow does not use that variable; the exact
  SHA was independently verified from the workstation and VM126.

# Trial-registration operator notifications - 2026-08-26

- `GIT-DERIVED`: commits `82f29284245acd0f2ab5cdb46741a3164c0fbb3d` and
  `80205985c43483d341d41c8be74bbf8640dc6e04` add best-effort operator
  notifications for successful public tenant registrations, independently fan
  out the complete stored application to every configured recipient, and use a
  recipient-specific provider idempotency key. GitHub CI run `32925288220`
  passed all unit, database, PostgreSQL 17 + pgvector/RLS, frontend, quality,
  release-security and secret-detection jobs.
- `RUNTIME-DERIVED`: VM126 API and all three application workers run immutable
  image `kamilya-api:80205985c434`; public and private health identify exact
  release `80205985c43483d341d41c8be74bbf8640dc6e04` and `kz-production`.
  All four application containers were running with zero restart count after
  deployment. No database migration, tenant mutation, Valkey, Docling, blob,
  frontend or CT125 configuration change was part of this release.
- `RUNTIME-DERIVED`: production `runtime.env` contains one
  `PUBLIC_LEAD_NOTIFICATION_EMAIL` setting with two deduplicated operator
  recipients. Recipient values remain runtime-only and are not stored in Git or
  command output. The post-deploy operational watchdog completed with
  `Result=success` and `ExecMainStatus=0`.
- `RUNTIME-DERIVED`: the first guarded deployment attempt automatically restored
  the previous image/configuration because the watchdog's separate expected
  image field had not yet been reconciled. The corrected guarded attempt updated
  both expected release and expected image, passed health/watchdog gates, removed
  its temporary release source and retained the prior image plus a root-only
  rollback backup.
- `NOT VERIFIED`: no retrospective Coffee Nation notification is claimed. A
  read-only production query found no current lead under the supplied historical
  slug or company-name match, so no contact fields were reconstructed from a
  screenshot and no backfill email was sent. Future successful public tenant
  registrations are covered by the deployed path. No synthetic registration was
  submitted for this verification.
- `GIT-DERIVED`: ops commit `f0ffc0abd9daceff68f552763eb65cc9406988a6`
  tracks the fail-closed KZ remote executor, reconciles VM126's exact runtime
  hostname, and records recurrence prevention. GitHub CI run `32926482727`
  passed all jobs.

## Team onboarding email and contextual-help release - 2026-08-26

- `GIT-DERIVED`: release `7bc11a9873cc0a3b136db46d1ac1e1732e205685`
  makes team-member passwords optional, keeps email-code login as the primary
  path, reports welcome-email delivery status, exposes an authorized resend
  endpoint, supports authenticated SMTP as well as Resend, and adds role/path
  contextual help for the main methodologist and team-management sections.
  GitHub Actions run `32935612145` passed secrets, quality, frontend, migration,
  PostgreSQL 17 + pgvector/RLS, DB-backed and release-security gates.
- `PROVIDER-CONFIRMED`: the exact release is READY in the Vercel production
  deployment associated with `app.kml.kz` and branch `master`; the public login
  route returned HTTP 200. The same exact SHA was independently verified in the
  dev Vercel and Render deployments before production promotion.
- `RUNTIME-DERIVED`: public and private API health identify exact release
  `7bc11a9873cc0a3b136db46d1ac1e1732e205685` and `kz-production`. VM126 API,
  worker-ai, worker-documents and worker-ops run image
  `kamilya-api:7bc11a9873cc`, are `running`, and have zero restarts. No migration,
  CT125, PostgreSQL, tenant content or blob mutation was part of the release.
- `RUNTIME-DERIVED`: the VM126 operational watchdog expected release/image now
  match the deployed identity and its timer remains active. Runtime email
  transport uses authenticated SMTP through the configured Kamilya mailbox;
  credentials remain runtime-only. API and worker-ops were the only services
  recreated for this transport reconciliation.
- `RUNTIME-DERIVED`: the existing Lombard Sandyq methodologist account received
  a code-first welcome (`sent`) and a login-code request was accepted. No
  duplicate correct-address account was created. One malformed account produced
  solely by a hidden-PTY test-input defect was deactivated through the standard
  user-management API; the valid account remains active and unchanged apart from
  the intended delivery verification.
- `INFERRED`: delivery-provider acceptance and SMTP envelope acceptance prove
  that the messages left Kamilya's application path, but recipient inbox display
  remains owner/client observable rather than independently read back by this
  release process.

## Document-grounded AI generation correction - 2026-08-27

- `GIT-DERIVED`: exact release `4de6358851dc22fadcb0a41320e4d52bad9c8069`
  aligns document-ingestion source revisions with the original uploaded blob SHA.
  Exact release `b4cca57bded652c1c4b825c2cdcb6fff4ddb27a5` deterministically
  deduplicates adjacent context-window overlap while preserving tenant, document,
  revision and embedding-space fail-closed checks. Both exact releases passed dev
  and master CI; the final release passed Python quality, unit, integration,
  PostgreSQL 17 + pgvector/RLS, frontend, coverage and secrets gates.
- `RUNTIME-DERIVED`: production Alembic is `0133`; the runtime role has
  `SELECT, INSERT, UPDATE` and no `DELETE` on the three embedding lifecycle tables.
  The previously failing verified-embedding SELECT completed under the runtime role.
- `RUNTIME-DERIVED`: VM126 API and all three workers run image
  `kamilya-api:b4cca57bded6`, are `running`, and have zero restarts. Public health
  reports `ok`, `kz-production` and exact release
  `b4cca57bded652c1c4b825c2cdcb6fff4ddb27a5`. No database migration was part of
  this final application release.
- `RUNTIME-DERIVED`: three existing production documents completed canonical
  reindexing. A disposable production AI smoke then completed architect, content,
  review, assessment and save stages and produced 2 modules, 5 lessons and 25
  Russian-language questions. The disposable course was deleted and zero invitations
  were sent.
- `RUNTIME-DERIVED`: the candidate-retention timer and operational watchdog remain
  active, with watchdog expected release/image reconciled to the deployed identity.
- **Verdict:** document-grounded automatic course and assessment generation is GO for
  controlled tenant use. Human methodologist review before publication remains
  mandatory; this verification does not authorize automatic publication or learner
  assignment.

## Protected release plane and persistent synthetic smoke — 2026-08-31

- `GIT-DERIVED`: commits `c930749b894708c8fcf9db964054c75278a2dd9d` and `1d876a0c8f19fa3c1a340c2a42d4ae4b768e95c7` add a protected, signed-bundle release-plane upgrader and preserve executable/systemd file types. CI runs `33394763365` and `33396134759` passed. The first protected upgrade stopped safely during validation because a systemd unit suffix had been stripped; no install occurred.
- `PROVIDER-CONFIRMED`: protected workflow run `33396493124` completed successfully for upgrade `RPLANE-20260831-KAMILYA-0002`. Bundle SHA-256 was `174a77f2c5e890bf9576a533eb3d0b685884be68401bc531ce12e16f5d860299`. Independent VM126 readback confirmed exact root-owned hashes, valid sudoers syntax, active release runner, absent locks and unchanged application runtime.
- `GIT-DERIVED`: smoke-provisioner correction `e650b76e16c75e87f81aa747789a9386200b33d7` respects the admin/methodologist role boundary. CI run `33397466187` and the no-op-safe KZ release run `33397802150` completed successfully.
- `RUNTIME-DERIVED`: public health returned HTTP 200, `production`, `kz-production` and exact application SHA `be35e60c2b1af1465f770375ba9ff15e8bed4d0b`. The ops-only changes did not replace the application release.
- `RUNTIME-DERIVED`: the persistent synthetic smoke tenant completed normal document upload/indexing, one AI generation, course review/publication, employee edit, group save, program/group assignment, personal link/PIN entry, 5/5 lessons, five lesson tests, terminal completion, training-log readback and certificate readback. No email, customer data, unrelated tenant, direct DB edit or fabricated evidence artifact was used.
- `RUNTIME-DERIVED`: contextual-help dialogs sampled across dashboard, candidates, journal, confirmation and retention fit a 1280x720 viewport with internal scrolling. The superadmin add-member dialog remained open on backdrop click and closed explicitly without saving.
- `FAIL / PRODUCT_DEFECT`: production assessment generation is not ready for unattended publication. The 25-question synthetic set included semantically incorrect/incomplete answer keys, missing negation/context, fragment answers, raw Markdown and a severe correct-answer verbosity cue. Human methodologist review remains a hard gate; deterministic per-question validation and regeneration are required before changing this verdict.
- `OPEN`: some methodologist links lose the bounded superadmin impersonation context; program/AI usage counters can disagree with persisted assignments/jobs; learner confirmation wording does not yet match the clearer certificate-versus-evidence contract in the journal.
- **Verdict:** release-plane self-upgrade is `GO`; the synthetic production operating flow is `GO WITH FOLLOW-UP`; automatically generated assessments are `NO-GO` without human review and quality gating.
