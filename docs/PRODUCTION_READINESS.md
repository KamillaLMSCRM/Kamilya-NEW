# Kamilya LMS: готовность первого production-тенанта

**Проверено:** 2026-08-08 по исходникам, CI и production-контурам
**Технический P0 baseline:** закрыт
**Режим запуска:** dev/test и контролируемая демонстрация; подключение первого
коммерческого tenant с персональными данными остаётся за отдельным KZ
DB/storage gate и приёмкой клиента
**Назначение:** единственный актуальный реестр production-gates. История изменений
остаётся в Git; отдельные датированные отчёты не используются как источник
текущего состояния.

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

До подключения коммерческого клиента остаётся обязательным отдельный gate:
подтвердить размещение основной БД, файлов, резервных копий и журналов с
персональными данными в Казахстане и заполнить фактический реестр внешних
обработчиков. Публичные тексты описывают это как условие запуска, а не как уже
подтверждённое состояние текущей пилотной инфраструктуры.

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
