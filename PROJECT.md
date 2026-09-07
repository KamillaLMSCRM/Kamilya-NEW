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
- AI generation в выделенной Celery queue с двумя параллельными worker slots;
- не более двух `pending/running` генераций на tenant, с атомарным admission,
  tenant-relative позицией, ориентировочным ожиданием и отменой queued job;
- provenance уроков и проверка grounding;
- отдельный flow курса по должностной инструкции.

Несвязанные документы не смешиваются автоматически. Методолог выбирает один
смысловой кластер либо явно задаёт общую цель объединения.

### Курсы и тесты

- draft, review и publish;
- версионированные отраслевые заготовки: первый RU/KK курс по информационной
  безопасности для финансовых организаций создаётся как обычный draft, а его
  публикация блокируется до заполнения восьми пунктов адаптации tenant;
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
- invitation links и история их состояния; bulk-создание ставит доставку
  ссылки в Celery и сохраняет `pending/sent/failed`, provider message id,
  время/число попыток и безопасную причину ошибки;
- copyable activation link остаётся manual fallback при недоступном email
  provider или broker, но не является единственным способом доставки;
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

Tenant methodologist также управляет versioned процедурами `acknowledgement`,
`internal_attestation` и `admission_decision`. Draft можно редактировать и
удалять; activation требует approval/basis/retention metadata, а для
аттестации и допуска — правил комиссии или уполномоченного решения. Эта
конфигурация не создаёт само решение.

Готовый evidence package можно материализовать в неизменяемые PDF/ZIP bytes и
передать по restricted link с SHA-256, expiry не более 31 дня, лимитом
скачиваний, revoke, Redis rate limit и access log без публичного PII.

Retention-контур содержит tenant policies, legal hold и bounded dry-run/manual
purge. Persistent cursor не даёт старым заблокированным цепочкам навсегда
скрывать более новые кандидаты. Scheduled purge и backup retention остаются
backlog.

Kamilya фиксирует технические доказательства внутреннего обучения. OTP не является ЭЦП, а обычный тест, completion или generic correction не создают
`training`, `knowledge_check`, аттестацию либо допуск. Аттестация и допуск
остаются fail-closed до отдельного фактического workflow комиссии или
уполномоченного решения по утверждённой форме клиента.

## Техническая архитектура

| Слой | Реализация |
|---|---|
| Frontend | Next.js 15.5.23, React, TypeScript |
| Backend | FastAPI, SQLAlchemy async, Alembic |
| Database | PostgreSQL + pgvector |
| Shared dev/test DB and storage | Supabase; не production |
| Production DB | Native PostgreSQL 17 + pgvector на CT125 в Казахстане, private-only path |
| Queue/cache | Valkey на VM126 в Казахстане |
| Background jobs | Изолированные Celery workers `ai`, `documents`, `operations/notifications` на VM126 |
| API hosting | VM126 через KZ proxy/WireGuard; Render используется для dev/demo или явно выбранного rollback |
| Web hosting | CT137 `webkml`, native Next.js/OpenRC/Nginx без Docker; Vercel project `web` сохранён как rollback, `kamilya-lms-dev` — dev |
| Public marketing landing | `kml.kz`/`www.kml.kz` остаются отдельным Vercel-контуром и не являются LMS application runtime |
| Email | Resend |
| Document conversion | Local bounded hybrid service: MarkItDown for Office/text-layer PDF, Docling for scans/OCR, LibreOffice for legacy `.doc` |

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

Регистрация с публичного лендинга принимает `utm_source`, `utm_medium`,
`utm_campaign`, `utm_content`, `utm_term` и `referrer`. Атрибуция сохраняется в
`tenant.settings.registration.attribution`, сообщении `TenantLead` и audit event
`tenant.trial.started`; значения ограничиваются backend-схемой по длине.

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

На 2026-09-07 production frontend `app.kml.kz` работает на CT137 в KZ-контуре,
production API и workers — на VM126, PostgreSQL/pgvector — на CT125. Frontend
размещён на Proxmox node `pve3`, запускается как native Next.js/OpenRC/Nginx без
Docker и обращается к `https://api.kml.kz/api`. Vercel project `web` сохранён
как rollback artifact; `kamilya-lms-dev` и Render остаются dev/demo-контуром.
Точные SHA, migration revision и release evidence всегда читаются из текущих
источников правды выше, а не переносятся из датированных исторических записей.

## Документация

- [Индекс](docs/DOCUMENTATION_INDEX.md)
- [Контекст проекта](docs/PROJECT-CONTEXT.md)
- [Production readiness](docs/PRODUCTION_READINESS.md)
- [Production frontend: выпуск и rollback](docs/PRODUCTION_FRONTEND_RUNBOOK.md)
- [Product backlog](docs/PRODUCT_BACKLOG.md)
- [Журнал ошибок и предотвращения повторов](ERRORS.md)
- [Внутренняя документация](docs/PROJECT_INTERNAL_DOCUMENTATION.md)
- [Руководство пользователя](docs/USER_DOCUMENTATION_RU.md)
- [ADR](docs/adr/)

Исторические отчёты и ТЗ доступны в Git history и не хранятся рядом с
действующей документацией.
