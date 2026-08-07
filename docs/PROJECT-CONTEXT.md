# Kamilya LMS: текущий контекст проекта

> Living document. Значения секретов здесь не хранятся.
> Обновлено: 2026-08-06.

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
| Backup и restore | [`BACKUP_RESTORE_RUNBOOK.md`](BACKUP_RESTORE_RUNBOOK.md) |
| OCR и KZ infrastructure migration | [`INFRA_KZ_OCR_MIGRATION_ANALYSIS.md`](INFRA_KZ_OCR_MIGRATION_ANALYSIS.md) |
| Правила для агентов | [`AGENTS.md`](../AGENTS.md) |

Старые планы, аудиты, отчёты веток и ТЗ не являются источниками текущего
поведения.

## Репозиторий и сервисы

| Контур | Текущее размещение |
|---|---|
| Monorepo | `KamillaLMSCRM/Kamilya-NEW`, branch `master` |
| Frontend | Next.js, Vercel, `https://app.kml.kz` |
| API | FastAPI, Render, `https://kamilya-lms-api.onrender.com` |
| PostgreSQL/pgvector | Supabase, общий dev/test и controlled-pilot контур |
| Object storage | Supabase Storage, общий dev/test и controlled-pilot контур |
| Broker/cache | Valkey TLS на VPS |
| Background jobs | Три Celery worker на VPS: AI, documents и notifications/maintenance |
| Email | Resend, домен `notify.kml.kz` |
| Telegram | Kamilya bot/auth flow |
| Document conversion | Ограниченный локальный сервис: MarkItDown для Office/PDF с текстом, Docling для сканов/OCR, LibreOffice для старого `.doc` |

Текущая Supabase используется для разработки, интеграционных тестов и
контролируемой демонстрации. Реальные данные коммерческого клиента в этот
контур не загружаются. Для первого клиента до запуска создаётся отдельный
PostgreSQL и object storage в Казахстане; параметры подключения, backup,
restore и cutover проходят отдельный release-gate.

## Текущий проверенный release

На 2026-08-06 application release
`c4a5eb8bf58989eff4f4338272dc68941bd416bd` находится в production:

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
5. AI job создаёт draft курса и тестов с трассировкой к источникам.
6. В списке курсов непроверенный AI-draft имеет статус **Требует проверки**:
   прямое действие публикации недоступно до явного одобрения методологом.
7. Методолог проверяет, редактирует, одобряет и затем публикует курс.
8. В редакторе AI-помощник может дать read-only рекомендацию аудитории по
   текущей структуре tenant. Рекомендация не создаёт назначения или правила;
   для опубликованного курса она только ведёт на контекстный экран
   `/assignments?course_id=...`.

### Должностная инструкция

1. Инструкция привязывается к должности.
2. Из неё создаётся отдельный grounded-курс с provenance/version.
3. Курс входит в профиль квалификации должности.
4. Назначения пересчитываются для сотрудников этой должности.

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

Самостоятельные пункты меню `/competencies`, `/training-rules`, `/invitations`
и `/assignments` скрыты: они остаются каноническими deep-link/API-контурами,
но открываются из должности, отдела, курса или сотрудника. Отдельное назначение
`Quiz` не используется: тест урока наследует доступ назначенного курса.

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
