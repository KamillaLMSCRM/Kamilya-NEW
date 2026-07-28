# Kamilya LMS: текущий контекст проекта

> Living document. Значения секретов здесь не хранятся.
> Обновлено: 2026-07-28.

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
| Правила для агентов | [`AGENTS.md`](../AGENTS.md) |

Старые планы, аудиты, отчёты веток и ТЗ не являются источниками текущего
поведения.

## Репозиторий и сервисы

| Контур | Текущее размещение |
|---|---|
| Monorepo | `KamillaLMSCRM/Kamilya-NEW`, branch `master` |
| Frontend | Next.js, Vercel, `https://app.kml.kz` |
| API | FastAPI, Render, `https://kamilya-lms-api.onrender.com` |
| PostgreSQL/pgvector | Supabase production |
| Object storage | Supabase Storage |
| Broker/cache | Valkey TLS на VPS |
| Background jobs | Celery worker на VPS |
| Email | Resend, домен `notify.kml.kz` |
| Telegram | Kamilya bot/auth flow |
| Document conversion | Docling на VPS |

Production БД пока не перенесена в Казахстан. HostKZ использовался как
изолированный тестовый контур и не является текущим production.

## Проверенная release-картина

На 2026-07-28:

- проверенный application HEAD:
  `fe6ff6c2e914ed05cd7c05bbe1b29e5b2d4cc2e7`;
- GitHub CI `30352487058`: success, backend `625 passed`;
- GitHub production smoke `30352486895`: success;
- Vercel production deployment `2tZoCGURNydq1q46BFKb8DsUwQ8Z`,
  commit `fe6ff6c`;
- Render API deployment `dep-d9k8kv61egvs7381jo80`: live,
  commit `fe6ff6c`;
- production Alembic: `0078`, repository head: `0078`;
- Celery worker active/enabled на `a10786c`, реальный Celery ping passed;
- ежедневный encrypted backup и пятиминутный watchdog активны;
- реальный backup/portable restore drill PostgreSQL 17 + pgvector passed;
- полный production synthetic tenant journey от регистрации до сертификата и
  журнала обучения passed; synthetic tenant и storage objects удалены.
- AI-рекомендация аудитории курса прошла read-only production smoke:
  агрегаты совпали со структурой, запрос не создал назначений или правил.

Технический и прикладной P0 закрыты для контролируемого первого pilot.
Отдельные условные gates сохраняются для SCORM, kiosk, KZ data residency и
заявленной массовой нагрузки. Полный список находится в
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
2. Создаются tenant, первый `admin` и trial limits.
3. Вход выполняется по email OTP через Resend или настроенному Telegram-flow.
4. Администратор создаёт системного пользователя с ролью `methodologist`.
5. Admin onboarding завершается после формирования системной команды; учебные
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
6. Методолог проверяет, редактирует и публикует курс.
7. В редакторе AI-помощник может дать read-only рекомендацию аудитории по
   текущей структуре tenant. Рекомендация не создаёт назначения или правила;
   для опубликованного курса она только ведёт на `/assignments`.

### Должностная инструкция

1. Инструкция привязывается к должности.
2. Из неё создаётся отдельный grounded-курс с provenance/version.
3. Курс входит в профиль квалификации должности.
4. Назначения пересчитываются для сотрудников этой должности.

### Доставка и подтверждение

1. Отдельный курс назначается вручную или автоматическим правилом.
2. Программа назначается человеку, группе, отделу или должности; cohort хранит
   только состав аудитории.
3. Методолог создаёт invitation link и передаёт его сотруднику через рабочий
   канал. Автоматическая отправка через Resend пока не реализована.
4. Обучающийся принимает приглашение.
5. Проходит уроки и обязательные тесты.
6. Backend сохраняет прогресс и завершает курс идемпотентно.
7. При выполнении условий выдаётся сертификат.
8. Журнал обучения показывает назначение, его источник, прогресс, результат и
   доказательство.

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
