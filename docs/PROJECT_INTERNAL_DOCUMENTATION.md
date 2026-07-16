# Kamilya LMS: внутренняя документация проекта

**Статус:** рабочая документация проекта
**Дата актуализации:** 2026-07-16
**Репозиторий:** `KamillaLMSCRM/Kamilya-NEW`

## 1. Назначение продукта

Kamilya LMS — multi-tenant LMS для корпоративного обучения. Tenant — отдельная компания со своими пользователями, курсами, документами, должностями, назначениями, сертификатами и настройками.

Главная продуктовая идея:

```text
документы компании → AI/методолог → курс и тест → назначение → обучение → сертификат → HR-контроль
```

Система рассчитана на работу HR, методолога, администратора tenant и обучающегося. Superadmin управляет платформой и tenant-ами.

## 2. Репозиторий и запуск

```text
apps/api/       FastAPI backend, SQLAlchemy, Alembic
apps/web/       Next.js 14 frontend, React, TypeScript
docs/           продуктовые, архитектурные и эксплуатационные документы
```

Локально:

```powershell
cd apps/api
python -m uvicorn app.main:app --reload --port 8000

cd apps/web
npm install
npm run dev
```

Для Windows production-проверка frontend запускается через `npx next build`. Unix-синтаксис вида `NEXT_TELEMETRY_DISABLED=1 command` в PowerShell не используется.

## 3. Архитектура

### Backend

- FastAPI routers группируют API по доменам.
- SQLAlchemy async используется для доступа к PostgreSQL.
- Alembic хранит миграции.
- `app.core.auth` отвечает за JWT, текущего пользователя, tenant context и RBAC.
- `app.core.email.EmailService` поддерживает `log` и Resend.
- AI-пайплайн генерирует структуру и содержание курсов из документов.
- Qwen используется как основной AI-провайдер в соответствующих потоках; fallback зависит от конкретного AI-модуля.

### Frontend

- Next.js App Router.
- `apps/web/src/components/layout/Sidebar.tsx` — основная навигация.
- `apps/web/src/lib/api.ts` — Axios-клиент с access token и refresh-on-401.
- `apps/web/src/store/authStore` — состояние текущей сессии.
- Локали: RU, EN, KK.

## 4. Tenant isolation и безопасность

Каждая tenant-сущность содержит `tenant_id`. Backend дополнительно проверяет tenant в запросах, а PostgreSQL использует `ENABLE/FORCE ROW LEVEL SECURITY` и `app.tenant_id`.

Новые tenant-таблицы должны обязательно иметь:

1. `tenant_id` и FK на `tenants.id`.
2. RLS policy с безопасным `NULLIF(current_setting(...), '')`.
3. `FORCE ROW LEVEL SECURITY`.
4. Проверку принадлежности входящих `course_id`, `user_id`, `position_id` текущему tenant.
5. Тест на доступ между tenant-ами.

Секреты хранятся только в локальном `.env` или в секретах Render/Vercel. В git нельзя добавлять `.env`, API keys, JWT secrets, пароли БД, root/VPS credentials или токены GitHub.

## 5. Роли

| Роль | Назначение |
|---|---|
| `superadmin` | Платформа, tenant-ы, провайдеры AI, impersonation, операционный контроль |
| `admin` | Администратор tenant: команда, настройки, доступы, отчёты |
| `org_admin` | Администратор организации с tenant-функциями |
| `methodologist` | Курсы, тесты, должности, траектории, назначения, cohorts, компетенции |
| `teacher` | Текущий alias learning-content роли методолога |
| `student` | Обучение, тесты, сертификаты, AI-помощник, surveys после завершения |

`teacher` и `methodologist` взаимно разрешены на learning-content boundary. Не следует возвращать старую модель, в которой методологу закрыты курсы или назначения.

## 6. Основные доменные потоки

### 6.1 Tenant onboarding

1. HR/владелец открывает регистрацию tenant.
2. Указывает компанию, контактное лицо, email и пароль.
3. Создаётся tenant, первый admin и trial-лимиты.
4. Вход выполняется email OTP через Resend либо Telegram-потоком, если он настроен.
5. После входа пользователь должен попасть в tenant dashboard, а не в student dashboard.

### 6.2 Подготовка персонала

Канонический экран: `/admin/staff` или `/staff`.

- импорт штатки Excel/CSV с preview и mapping;
- ручное добавление сотрудника без загрузки файла;
- отделы, должности и сотрудники;
- привязка должности к курсам;
- cohorts для группового обучения.

### 6.3 Создание курса

Канонические варианты:

- `/ai/generate`: загрузка документов, выбор аудитории, числа модулей и языка;
- `/courses`: ручной курс или SCORM 1.2 import;
- `/courses/[id]/edit`: редактирование модулей и уроков.

Курс должен пройти методологическую проверку перед публикацией. Для двуязычного продукта язык выбирается при генерации; целевая модель — русский и казахский варианты из одного источника, а не простое переключение языка интерфейса.

### 6.3.1 Курс по должностной инструкции

Канонический P0-поток реализован на `/positions`:

```text
Position
  -> current Document(category=job_instruction)
  -> AIJob(course_id=pre-created draft)
  -> Course(source_instruction_id, source_instruction_version_at)
  -> PositionCourse(required=true)
```

- `POST /v1/positions/{position_id}/instruction` сохраняет бинарный источник в настроенный storage backend, индексирует документ, привязывает его к должности и обновляет извлечённые поля.
- `GET /v1/documents/{document_id}/download` отдаёт исходник только пользователю того же tenant с learning-content ролью.
- `POST /v1/positions/{position_id}/generate-instruction-course` создаёт один native draft для текущей версии источника и запускает существующий AI pipeline в заранее созданный `course_id`.
- Повторный запрос при активной или завершённой генерации возвращает conflict и не создаёт дубль. После failed job разрешён повторный запуск того же draft без повторного списания лимита.
- Замена инструкции создаёт новый `Document`; старый курс остаётся историческим и в API помечается как устаревший относительно текущего источника.
- `TenantUsage.jd_course_generations_used` и `jd_course_generations_limit` образуют отдельный trial-счётчик. Обычный `ai_course_generations_used` для этого потока не списывается.

Текст, извлечённый из ДИ, не считается юридически проверенным. Методолог должен проверить поля должности и содержание курса перед публикацией.

### 6.4 Назначение

Поддерживаются:

- ручное назначение через `/assignments`;
- правила должности/отдела;
- learning paths (`/learning-paths`);
- cohorts (`/cohorts`), где кнопка **Apply assignments** материализует `user × course` в `enrollments` с `source=cohort`.

Материализация идемпотентна: повторное применение не создаёт дублей, существующее завершённое обучение не сбрасывается.

### 6.5 Обучение

Обучающийся использует `/student` и `/my-courses`:

- видит назначенные курсы;
- продолжает незавершённый курс;
- проходит native или SCORM 1.2 курс;
- проходит тест;
- получает сертификат;
- использует AI-помощника в native-уроке в рамках контекста курса/урока.

Kiosk — отдельный режим входа по QR/ссылке. Production QA kiosk требует валидный tenant kiosk token и отдельную проверку таймаута/приватности.

### 6.6 Контроль HR

- `/admin/training-log` — единый журнал native и SCORM;
- summary: assigned, in progress, completed;
- CSV export;
- `/admin` — trial-лимиты, users, courses, certificates, storage;
- `/competencies` — связь компетенций с должностями и курсами;
- `/announcements` — ручные уведомления через Resend/log provider;
- `/surveys` — feedback после завершения курса.

## 7. Новые продуктовые модули

### Learning paths

Таблицы: `learning_paths`, `learning_path_courses`. Миграция `0056`.

### Competencies

Таблицы: `competencies`, `position_competencies`, `competency_courses`. Миграция `0057`.

### Announcements

Таблица `announcements`, ручной delivery через Resend/log provider. Миграция `0058`.

### Surveys

Таблицы `surveys`, `survey_responses`. Опрос доступен только после `Enrollment.status=completed`; один ответ на пользователя и опрос. Миграция `0059`.

### Cohorts

Таблицы `cohorts`, `cohort_members`, `cohort_courses`. Миграция `0060`. Назначения создаются отдельным apply endpoint, а не при каждом изменении UI.

## 8. Миграции и deploy

Цепочка текущих feature-миграций:

```text
0055 role aliases
0056 learning paths
0057 competency matrix
0058 announcements
0059 surveys
0060 cohorts
0061-0062 последующие продуктовые и инфраструктурные изменения
0063 источники должностных инструкций и связь с курсами
```

Перед production deploy:

1. проверить `alembic current` и `alembic heads`;
2. применить миграции на staging;
3. проверить RLS под `lms_app`;
4. выполнить smoke API и frontend;
5. только затем раскатывать production.

Render и Vercel deploy green не заменяют проверку миграций и ручной happy path.

## 9. Проверки

Минимальный gate:

```powershell
python -m compileall -q apps/api/app
python -m pytest apps/api/tests/test_role_aliases.py apps/api/tests/test_role_boundaries.py apps/api/tests/test_kiosk_jwt.py -q
cd apps/web
npm run typecheck
npx next build
```

Известные ограничения текущей проверки:

- Docker/Postgres может отсутствовать локально;
- полный integration suite требует PostgreSQL;
- production SCORM QA требует реальные пакеты iSpring/Articulate;
- browser console warnings от расширений не являются автоматически ошибкой приложения.

## 10. Правила дальнейшей разработки

- Сначала читать `AGENTS.md`, `docs/LESSONS.md`, ADR и текущий код.
- Не добавлять legacy-дубли экранов без миграционного плана.
- Не описывать в marketing/user docs функцию, которой нет в production-коде.
- Для каждой новой tenant-фичи добавлять RLS, миграцию, API, UI и focused test.
- Коммиты и push выполнять автором `kamilla_lms_crm@proton.me`; GitHub token использовать через `http.extraheader`, не через Credential Manager.
