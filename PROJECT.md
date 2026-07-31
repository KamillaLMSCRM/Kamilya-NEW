# Kamilya LMS

Kamilya LMS — multi-tenant платформа корпоративного обучения:

```text
документы компании
  -> курс и тест
  -> назначение
  -> обучение
  -> проверка знаний
  -> сертификат
  -> журнал обучения
```

Продукт рассчитан на tenant-компании, где администратор управляет организацией
и доступами, методолог управляет обучением, а сотрудник проходит назначенные
курсы.

## Роли

| Роль | Ответственность |
|---|---|
| `superadmin` | Платформа, tenants, providers и операционные действия |
| `admin` | Системная команда tenant, интеграции, организационные настройки |
| `methodologist` | Документы, курсы, тесты, сотрудники, правила, назначения и результаты |
| `student` | Курсы, тесты, программы и сертификаты |

`teacher` и `org_admin` удалены. Tenant admin не управляет курсами, тестами,
обучающимися или назначениями.

Пользователь может иметь несколько назначенных ролей, но в сессии выбирает
одну active role. UI и API не объединяют полномочия всех ролей.

## Основные модули

### Источники и AI

- библиотека документов tenant;
- извлечение текста, chunking и embeddings;
- проверка совместимости выбранных источников;
- AI generation в Celery;
- provenance уроков и проверка grounding;
- отдельный flow курса по должностной инструкции.

Несвязанные документы не смешиваются автоматически. Методолог выбирает один
смысловой кластер либо явно задаёт общую цель объединения.

### Курсы и тесты

- draft, review и publish;
- уроки и материалы;
- конструктор тестов;
- порог прохождения и попытки;
- SCORM 1.2 import/launch как дополнительный flow.

SCORM 2004 не поддерживается и не должен заявляться.

### Сотрудники и квалификации

- ручное добавление сотрудника;
- Excel/CSV preview, mapping и import;
- каноническая структура `Department -> Position -> User`;
- должностная инструкция;
- профиль квалификации и компетенции.

### Доставка обучения

- ручное назначение;
- reusable audiences/groups;
- последовательные learning programs;
- автоматические правила организации, отдела и должности;
- invitation links и история их состояния; передача ссылки сотруднику пока
  выполняется методологом вручную;
- активация ссылки через одноразовый код на кадровый email без повторного ввода
  ФИО, табельного номера и пароля.

При пересечении правил создаётся одно enrollment. Завершённые, ручные,
group/program grants не удаляются автоматическим recompute.

### Обучающийся и доказательства

- assigned courses and programs;
- уроки и сохранение прогресса;
- обязательные тесты;
- backend-owned completion;
- неизменяемый снимок опубликованной версии курса;
- привязка назначения и тестовой попытки к конкретной версии курса;
- полный снимок вопросов, ответов и результата попытки с SHA-256;
- append-only событие завершения курса и проверки знаний с отдельными
  исправлениями, отзывом и legal hold;
- подтверждение результата сотрудником через purpose-bound email OTP с
  фиксацией точного текста и версии объекта;
- idempotent certificate issue;
- журнал обучения, индивидуальный акт и групповой evidence package в PDF/ZIP.

Kamilya фиксирует технические доказательства внутреннего обучения, но не
называет обычный тест государственной аттестацией, допуском к работе или
документом, подписанным ЭЦП. Для процедур со специальной формой применяются
утверждённые клиентом локальные акты и требования профильного НПА.

## Техническая архитектура

| Слой | Реализация |
|---|---|
| Frontend | Next.js 14, React, TypeScript |
| Backend | FastAPI, SQLAlchemy async, Alembic |
| Database | PostgreSQL + pgvector |
| Shared dev/pilot DB and storage | Supabase |
| Commercial tenant DB | Отдельный PostgreSQL на VPS в Казахстане, до запуска не создан |
| Queue/cache | Valkey TLS на VPS |
| Background jobs | Celery worker на VPS |
| API hosting | Render |
| Web hosting | Vercel |
| Email | Resend |
| Document conversion | Docling |

Monorepo:

```text
apps/api/       FastAPI backend
apps/web/       Next.js frontend
packages/       shared Python package
infra/          local/infra helpers
docs/           current product, architecture and operations docs
```

## Tenant isolation

Для каждой tenant-scoped сущности обязательны:

1. `tenant_id`;
2. backend ownership validation;
3. PostgreSQL RLS policy;
4. FORCE RLS;
5. runtime DB role без `BYPASSRLS`;
6. cross-tenant integration test.

`DATABASE_URL` используется приложением. `MIGRATION_DATABASE_URL` используется
только для Alembic и административных операций.

## Trial

Self-service registration создаёт tenant и первого `admin`. Вход поддерживает
email OTP через Resend и Telegram flow.

Текущий trial:

- 14 дней;
- 1 обычный AI-курс;
- 1 курс по должностной инструкции;
- до 10 обучающихся;
- до 3 системных пользователей.

Лимиты и окончание периода должны проверяться backend, а не только UI.
В кабинете показывается единое состояние trial: срок, использование каждого
ресурса и конкретный исчерпанный лимит. Исчерпание одного ресурса ограничивает
только соответствующую операцию; окончание trial переводит кабинет в режим
обращения в поддержку.
Полноценный автоматический billing не является обязательным для первого
контролируемого пилота; активация может выполняться superadmin вручную.

После первого входа admin видит только governance-onboarding системной команды,
а methodologist — подготовку сотрудников, источников, курса, назначения,
    invitation link, OTP-активацию и журнал обучения.

## Production

Текущие commit, deploy, DB revision и release blockers не дублируются здесь.
Источник правды:

- [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md);
- [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

На 2026-07-27 технический P0 закрыт: API/frontend/worker синхронизированы,
encrypted backup/restore drill и минимальная наблюдаемость работают. Перед
выдачей доступа конкретному первому tenant обязателен прикладной synthetic
tenant journey из production-readiness.

## Документация

- [Индекс](docs/DOCUMENTATION_INDEX.md)
- [Контекст проекта](docs/PROJECT-CONTEXT.md)
- [Production readiness](docs/PRODUCTION_READINESS.md)
- [Product backlog](docs/PRODUCT_BACKLOG.md)
- [Внутренняя документация](docs/PROJECT_INTERNAL_DOCUMENTATION.md)
- [Руководство пользователя](docs/USER_DOCUMENTATION_RU.md)
- [ADR](docs/adr/)

Исторические отчёты и ТЗ доступны в Git history и не хранятся рядом с
действующей документацией.
