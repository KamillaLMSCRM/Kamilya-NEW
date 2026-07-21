# Kamilya LMS: handoff для нового Codex

Дата: 2026-07-21

Назначение: безопасно продолжить разработку на другом компьютере без восстановления контекста из длинной истории чата.

## 1. Первые действия нового агента

До любых изменений:

1. Открыть корень клона `Kamilya-NEW` как workspace.
2. Проверить `git status -sb`, `git branch --show-current` и `git log -5 --oneline`.
3. Убедиться, что рабочая ветка основана на актуальном `origin/master`.
4. Прочитать документы в следующем порядке:
   - `AGENTS.md`;
   - `PROJECT.md`;
   - этот файл;
   - `docs/PROJECT-CONTEXT.md`;
   - `docs/PROJECT_INTERNAL_DOCUMENTATION.md`;
   - `docs/LESSONS.md`;
   - `docs/DOCUMENTATION_INDEX.md`;
   - релевантные ADR в `docs/adr/`.
5. Сверить документацию с фактическим кодом перед архитектурными выводами.
6. Не читать и не печатать значения `.env`, если для задачи достаточно имён переменных.

Стартовый промпт для новой задачи:

```text
Работай в репозитории Kamilya-NEW. До любых изменений прочитай AGENTS.md,
PROJECT.md, docs/CODEX_HANDOFF.md, docs/PROJECT-CONTEXT.md,
docs/PROJECT_INTERNAL_DOCUMENTATION.md, docs/LESSONS.md и ADR по затронутому
домену. Затем проверь git status, последние коммиты и фактическую реализацию.
Кратко сформулируй архитектуру, роли, основные продуктовые флоу, production
состояние и риски. Не изменяй код до этой сверки. Не выводи секреты из .env.
```

## 2. Что представляет собой продукт

Kamilya LMS — multi-tenant SaaS для корпоративного обучения компаний Казахстана.

Основной цикл:

```text
документы компании
  -> методологическая подготовка
  -> AI/ручной курс и тест
  -> публикация
  -> назначение сотрудникам
  -> прохождение курса и теста
  -> сертификат
  -> журнал обучения и контроль результатов
```

Это собственный продукт, не форк Chamilo. Исторические сравнения с Chamilo используются как продуктовый reference, но не определяют архитектуру.

## 3. Канонические роли

| Роль | Ответственность |
|---|---|
| `superadmin` | Платформа, tenant CRUD, глобальные AI-провайдеры, operational oversight |
| `admin`, `org_admin` | Настройки tenant, интеграции, системные пользователи, kiosk links, инфраструктура кабинета |
| `methodologist` | Штат и должности, документы, курсы, тесты, публикация, назначения, cohorts, результаты обучения |
| `student` | Только прохождение назначенного обучения, тестов и получение сертификатов |

Роль `teacher` удалена. Не добавлять compatibility alias: реальных production-пользователей с этой ролью нет.

Один tenant-пользователь может иметь несколько ролей через `user_roles`. В JWT активна одна выбранная рабочая роль. Новый аккаунт для того же email не создаётся, plan slot повторно не расходуется.

Критические границы:

- системные пользователи и обучающиеся — разные продуктовые сущности;
- `/admin/team` не показывает студентов;
- администратор не управляет курсами, тестами, обучающимися и назначениями;
- `/assignments` принадлежит методологу;
- `/admin/enrollments` — только legacy redirect на `/assignments`;
- kiosk links принадлежат администратору, журнал и контроль обучения — методологу.

Канон: `docs/adr/0012-rbac-admin-vs-methodologist.md`.

## 4. Основные продуктовые флоу

### Регистрация и вход tenant

- Self-service trial: `/register-tenant`.
- Создаются tenant, первый `admin`, lead и trial usage.
- Основной вход: email OTP через Resend.
- Telegram code flow поддерживается при настроенном боте.
- После входа пользователь должен попасть в интерфейс своей активной роли.
- Название tenant отображается в верхней панели кабинета.

Подробности: `docs/architecture/2026-07-10_tenant-auth-email-telegram-resend.md`.

### Штат и должности

- Владелец флоу: `methodologist`.
- Excel/CSV проходит preview, выбор листа, mapping колонок и подтверждение до commit.
- Поддерживается ручное добавление сотрудника без файла.
- Отделы и должности связываются с обязательными курсами.
- Пересчёт правил создаёт недостающие enrollments идемпотентно и не сбрасывает завершённое обучение.

### Обычный AI-курс

1. Методолог загружает документы и ждёт успешной индексации.
2. Выбирает документы одного будущего курса.
3. Система анализирует тематическую совместимость.
4. При разных темах методолог выбирает одну группу либо явно объединяет группы с общей учебной целью.
5. Backend повторяет проверку до расходования trial quota и dispatch задачи.
6. Architect привязывает к каждому уроку документы из выбранного набора.
7. Writer извлекает контент только из этих источников.
8. Если релевантного материала нет, генерация останавливается; общие знания LLM не подмешиваются.
9. Методолог проверяет курс, тесты и provenance, одобряет и публикует курс.
10. Ручная правка урока устанавливает `source_validation_status=needs_review` до повторной grounded-генерации или явного одобрения.

API анализа: `POST /api/v1/ai/document-compatibility`.

Миграция: `0068_course_source_governance.py`.

Подробности: `docs/plans/done/2026-07-21_document-source-governance.md`.

### Курс по должностной инструкции

- Методолог загружает утверждённую инструкцию в карточке должности.
- Система хранит исходный файл, индексирует его и извлекает обязанности/требования.
- Генерация создаёт один редактируемый draft, связанный с версией источника.
- Повторный запуск не создаёт дубль и не списывает quota повторно после технической ошибки.
- Новая версия инструкции не меняет опубликованный курс незаметно: создаётся новая версия курса.
- После публикации новая версия становится актуальной для правила должности; завершённые результаты старой версии сохраняются.

### Публикация и назначения

- AI-курс нельзя публиковать до методологического одобрения.
- Draft нельзя назначать и он не виден обучающемуся.
- Назначения бывают `manual`, `position`, `department` и `cohort`.
- Повторное применение правил/cohort не создаёт дубли.
- Прямое удаление разрешено только для `source=manual`; rule-driven назначение меняется через правило.

### Обучающийся

- Invite link ведёт к принятию приглашения и student session.
- `/student` и `/my-courses` показывают назначенные курсы.
- Course completion требует завершения уроков и обязательных тестов.
- Пустая AI quiz-запись не должна блокировать завершение.
- Сертификат выдаётся backend идемпотентно и доступен как PDF.
- Поддерживаются native courses и SCORM 1.2.

### Контроль результатов

- `/admin/training-log` — единый журнал native и SCORM для методолога.
- CSV экспортируется в UTF-8 BOM с `sep=;` и человекочитаемыми русскими заголовками для Excel.
- Сертификаты, статусы и результаты не должны вычисляться только на frontend.

## 5. Архитектура репозитория

```text
apps/api/       FastAPI, SQLAlchemy async, Alembic, Celery
apps/web/       Next.js 14 App Router, TypeScript, Tailwind
packages/       общие Python-пакеты/типы
docs/           канонические документы, ADR, планы, отчёты
scripts/        CI и эксплуатационные утилиты
tests/          дополнительные тестовые сценарии
```

Ключевые области:

- backend auth/RBAC: `apps/api/app/core/auth.py` и auth modules;
- AI pipeline: `apps/api/app/modules/ai/`;
- source analysis: `apps/api/app/modules/ai/source_analysis.py`;
- courses/lessons/quizzes: соответствующие modules в `apps/api/app/modules/`;
- frontend navigation: `apps/web/src/components/layout/Sidebar.tsx`;
- frontend API: `apps/web/src/lib/api.ts`;
- auth state: `apps/web/src/store/authStore`;
- migrations: `apps/api/alembic/versions/`.

## 6. Production на момент handoff

| Компонент | Состояние |
|---|---|
| Frontend | Vercel, `https://app.kml.kz` |
| Backend | Render, `https://kamilya-lms-api.onrender.com` |
| PostgreSQL | Supabase + pgvector, Alembic `0068` |
| Storage | Supabase Storage, bucket `Kamilya LMS` |
| Queue/cache | Valkey на VPS `173.249.51.164`, TLS `6380`, AOF, `noeviction` |
| Worker | `kamilya-worker.service` на VPS, revision `5bc86c6` |
| Document conversion | `docling.kml.kz` |
| Email | Resend, sender `no-reply@notify.kml.kz` |
| AI | Qwen primary; DeepSeek LLM fallback; Voyage embeddings fallback |

`api.kml.kz` не является production API source of truth. Production backend находится на Render.

HostKZ `2 vCPU / 2 GiB / 50 GiB` был изолированным тестовым PostgreSQL-контуром. Production API и worker на него не переключались; Supabase остаётся production DB.

Последняя подтверждённая release-проверка source governance:

- backend: `356 passed`;
- frontend: `41 passed`;
- TypeScript и Next production build: passed;
- GitHub Actions run `29820432047`: succeeded;
- production DB: `0068`;
- worker: active/ready, зарегистрированы `ai.generate_course`, `ai.ingest_document`, `positions.apply_course_rules`.

На момент релиза в production не было успешно проиндексированных документов/chunks для semantic smoke. Кластеризация и серверная блокировка проверены integration-тестом на реальной локальной PostgreSQL/pgvector. Не выдавать это за production semantic E2E на пользовательских данных.

## 7. Секреты и доступы

Локальный `.env` находится в корне репозитория и игнорируется Git. Пользователь переносит его отдельно.

Типы необходимых секретов без значений:

- `DATABASE_URL`, `MIGRATION_DATABASE_URL`;
- Supabase URL/key/bucket;
- `REDIS_URL` и TLS settings;
- JWT/encryption secrets;
- Resend API key и sender settings;
- Render/Vercel/GitHub deployment tokens;
- AI provider keys и endpoints;
- VPS credentials/keys.

Правила:

- не печатать значения в чат, логи и документацию;
- runtime DB использует `lms_app` без `BYPASSRLS`;
- migrations используют отдельный admin URL;
- GitHub push выполнять token header с отключённым Credential Manager;
- автор Git-коммитов: `Kamilla LMS CRM <kamilla_lms_crm@proton.me>`.

## 8. Установка на новом компьютере

Требуется Python 3.12, Poetry 1.8.x, Node.js 20+ и Git.

```powershell
git clone https://github.com/KamillaLMSCRM/Kamilya-NEW.git "C:\Kamilya New\Kamilya-NEW"
cd "C:\Kamilya New\Kamilya-NEW\apps\api"
poetry install --with dev

cd "C:\Kamilya New\Kamilya-NEW\apps\web"
npm install
```

Не переносить `node_modules`, `.next`, `.venv`, Poetry/npm caches и build artifacts.

После отдельного копирования `.env`:

```powershell
cd "C:\Kamilya New\Kamilya-NEW"
git check-ignore .env
git status --short --ignored
```

`.env` должен быть ignored и не должен появляться как tracked/untracked change.

## 9. Проверки перед завершением задачи

Backend:

```powershell
cd apps\api
poetry run python -m compileall app tests
poetry run pytest tests -q
```

Frontend:

```powershell
cd apps\web
npm test
npm run typecheck
npx next build
```

DB-dependent suite требует PostgreSQL/pgvector. CI поднимает `pgvector/pgvector:pg16` и Redis service container. Нельзя объявлять DB-интеграцию проверенной, если тесты фактически упали на `ConnectionRefused`.

Для UI-изменений нужны browser screenshots и проверка desktop/mobile. Для production deploy отдельно проверяются provider revision, DB revision, worker revision и поведение, а не только HTTP health.

## 10. Незавершённые продуктовые блоки

Подтверждённые открытые вопросы:

1. Trial onboarding wizard.
2. Billing и upgrade request UI.
3. Полный superadmin commercial control: lead pipeline, activation и operational diagnostics.
4. Очистка исторических `queued/running` AI jobs от ранних smoke-запусков.
5. Production semantic E2E на реально проиндексированных документах.
6. Ручной staging/production QA SCORM 1.2 с реальными пакетами iSpring/Articulate.
7. Полная mobile QA-матрица критических ролей и флоу.
8. Мониторинг Valkey: память, rejected writes, queue length, AOF restore и TLS certificate renewal.

Не считать все файлы в `docs/plans/` актуальным backlog: часть старых планов исторически не перенесена в `done`. Перед продолжением конкретного пункта сверять его с `PROJECT.md`, кодом, production и Git history.

## 11. Правила продолжения

- Один существенный эпик — один план в `docs/plans/YYYY-MM-DD_<slug>.md`.
- После выполнения и проверки план переносится в `docs/plans/done/`.
- Не сохранять поддержку legacy-роли или endpoint без реальных данных и продуктового основания.
- Не смешивать admin и methodologist ownership ради обхода 403.
- Не ослаблять tenant filters или RLS ради прохождения теста.
- Не выполнять production/DNS/DB изменения без явного запроса пользователя.
- Не пушить через Git Credential Manager; использовать токен из локального `.env` через временный HTTP authorization header.
- Перед финальным ответом проверять newest user request, `git status`, tests и фактическое состояние deployment.

## 12. Что переносится вне Git

Пользователь отдельно переносит `.env`.

При необходимости отдельно переносятся только проверенные пользовательские настройки Codex:

- `%USERPROFILE%\.codex\AGENTS.md`;
- `%USERPROFILE%\.codex\config.toml` после проверки абсолютных путей;
- используемые personal skills.

Не переносить в проект и Git `auth.json`, `.sandbox-secrets`, SQLite state, логи, кэши и сырые session transcripts. История чата не является источником истины; этот handoff и канонические документы должны быть достаточны для новой задачи.
