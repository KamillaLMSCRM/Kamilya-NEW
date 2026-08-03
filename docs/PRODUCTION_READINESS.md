# Kamilya LMS: готовность первого production-тенанта

**Проверено:** 2026-08-03 по исходникам, CI и production-контурам
**Технический P0 baseline:** закрыт
**Режим запуска:** dev/test и контролируемая демонстрация; подключение первого
коммерческого tenant с персональными данными остаётся за отдельным KZ
DB/storage gate и приёмкой клиента
**Назначение:** единственный актуальный реестр production-gates. История изменений
остаётся в Git; отдельные датированные отчёты не используются как источник
текущего состояния.

## Текущий production release

P1-контур выпущен в production на commit
`b7d843df27cbd6ed853d84361eb8e83bf4d3a00e`:

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

Общая dev/test Supabase обновлена до Alembic `0089`. GitHub CI, внешний smoke,
Render API, Vercel frontend и VPS Celery worker проверены на одном release SHA.
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
| Application release | PASS | `b7d843df27cbd6ed853d84361eb8e83bf4d3a00e` |
| CI | PASS | GitHub Actions `30797757218`: frontend, backend, mypy, secrets и security gates |
| External smoke | PASS | GitHub Actions `30797757189`, API и frontend |
| Frontend | PASS | Vercel production `dpl_6a9z3PGCTH5WRuJf5u5FZ4aeZXMd`, состояние `READY`, alias `app.kml.kz`, exact release SHA |
| API | PASS | Render deploy `dep-d9o59hjncjis73bab7l0`, состояние `live`, exact release SHA; health `200` |
| Worker | PASS | `/opt/kamilya-worker` на exact release SHA, `kamilya-worker.service` active, Celery ping отвечает, `users.deliver_invitation` зарегистрирована |
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

- Финальный CI на `b7d843d` passed: GitHub Actions `30797757218`; отдельный
  production smoke `30797757189` также passed.
- Перед release локально пройдены backend suites: 860 тестов суммарно по
  разбитым запускам; frontend: 237 тестов, typecheck, lint и production build.
- На общей dev/test Supabase дополнительно пройдены критические DB/RLS suites;
  direct RLS assertion выполняется под runtime-ролью `lms_app`, а фабрики
  создают fixture-данные через владельца миграций.
- Focused backend P0 suites: 26 тестов канонической структуры штата и 17
  тестов invitation/SCORM contracts passed.
- Frontend architecture tests, typecheck и production build passed.
- Tenant/release/shell security gates passed.
- Graphify code graph обновлён после изменений.

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

## Открытые P1 release gates

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
