# Prompt / ТЗ для внешнего агента: P0 hardening Kamilya LMS

Дата: 2026-07-09

## Роль агента

Ты внешний инженерный агент, который дорабатывает P0-блок Kamilya LMS для запуска первого платного tenant.

Работай в репозитории:

`C:\Kamilya New\Kamilya-NEW`

GitHub:

`KamillaLMSCRM/Kamilya-NEW`

## Обязательное правило ветки

Не работай в `master/main` напрямую.

P0-работу нужно начинать не от `master`, а от базовой ветки с foundational-изменениями:

`origin/foundation-scorm-kiosk-assistant-2026-07-09`

Перед началом выполни:

```bash
git fetch origin
git checkout -b p0-first-tenant-hardening origin/foundation-scorm-kiosk-assistant-2026-07-09
```

Если ветка уже существует:

```bash
git checkout p0-first-tenant-hardening
git pull --rebase origin foundation-scorm-kiosk-assistant-2026-07-09
```

Все изменения делай только в этой ветке. В конце подготовь commit или набор commit'ов, но не делай merge в master/main.

Если `origin/foundation-scorm-kiosk-assistant-2026-07-09` недоступна, остановись и сообщи владельцу проекта. Не начинай P0 от `master`, потому что в `master` может не быть SCORM/kiosk/learner-assistant основы.

## Контекст продукта

Kamilya LMS - HR-first LMS для корпоративных tenant:

- tenant registration / trial;
- штатка, отделы, должности;
- импорт сотрудников из Excel/CSV;
- генерация курсов AI из документов и должностных инструкций;
- назначение курсов по должности/отделу;
- прохождение курсов и тестов;
- сертификаты;
- kiosk flow для цехов/общих устройств;
- superadmin для управления tenant.

Не превращай Kamilya в копию Chamilo. Chamilo используется только как ориентир по зрелости LMS. Главная линия продукта:

`штатка -> должность -> документы/ДИ -> AI-курс -> назначение -> прохождение/киоск -> тест -> сертификат -> журнал/отчет`

## Документы, которые нужно прочитать перед работой

1. `docs/analysis/2026-07-09_chamilo2_vs_kamilya_lms_feature_comparison.html`
2. `docs/plans/2026-07-09_p0_p1_product_hardening_plan.md`
3. `docs/plans/2026-07-09_scorm-kiosk-ai-chamilo-roadmap.md`
4. `AGENTS.md`
5. `docs/LESSONS.md`, если есть.

## Текущий важный статус

На момент постановки задачи уже реализовано:

- SCORM 1.2 import/launch/runtime bridge:
  - миграция `0050_add_scorm_import_tables.py`;
  - module `apps/api/app/modules/scorm`;
  - курс `delivery_type=scorm`;
  - SCORM 2004 не поддерживать, отклонять.
- Kiosk:
  - `/admin/kiosks`;
  - `/kiosk/[token]`;
  - QR/печать;
  - `kiosk_access_logs`, миграция `0051`.
- Learner AI assistant:
  - `/api/v1/learner/assistant/chat`;
  - `learner_assistant_messages`, миграция `0052`.

Не ломай эти изменения. Если видишь, что их нет в твоей ветке, сначала проверь актуальность ветки.

## P0 Scope

Нужно выполнить P0 hardening. Не уходи в P1/P2 без отдельного разрешения.

P0 состоит из шести блоков:

1. SCORM 1.2 end-to-end QA.
2. Superadmin / tenant lifecycle hardening.
3. Единый журнал обучения.
4. Staff import wizard 2.0.
5. Mobile/desktop QA ключевых flow.
6. Onboarding checklist для tenant admin.

Если объем слишком большой для одного прохода, выполняй в указанном порядке и явно отмечай, где остановился.

---

# P0.1. SCORM 1.2 end-to-end QA

## Цель

Проверить, что готовые SCORM 1.2 пакеты реально импортируются, запускаются, сохраняют прогресс и закрывают курс с выдачей сертификата.

## Что сделать

- Найти/создать 2-3 тестовых SCORM 1.2 ZIP-пакета:
  - простой минимальный пакет;
  - пакет с CSS/JS/assets;
  - по возможности экспорт из iSpring/Articulate/Captivate/Moodle/Chamilo.
- Проверить импорт через UI `/courses` и API `/api/v1/scorm/packages/import`.
- Проверить, что SCORM 2004 отклоняется понятной ошибкой.
- Проверить iframe launch.
- Проверить asset proxy:
  - CSS;
  - JS;
  - картинки;
  - относительные пути.
- Проверить runtime bridge:
  - `LMSInitialize`;
  - `LMSGetValue`;
  - `LMSSetValue`;
  - `LMSCommit`;
  - `LMSFinish`;
  - `LMSGetLastError`;
  - `LMSGetErrorString`;
  - `LMSGetDiagnostic`.
- Проверить completion:
  - `cmi.core.lesson_status = completed`;
  - `cmi.core.lesson_status = passed`;
  - enrollment становится `completed`;
  - появляется certificate;
  - learner dashboard показывает 100%.

## Что можно доработать

- Ошибки import/runtime, если они обнаружены.
- Logging runtime errors.
- Edge cases asset path/token.
- Ясные сообщения в UI.

## DoD

- Есть документ `docs/reports/2026-07-XX_scorm_12_qa_report.md` с пакетами, результатами и найденными/исправленными проблемами.
- SCORM 1.2 проходит end-to-end хотя бы на 2 пакетах.
- Тест/скрипт или Playwright smoke покрывает happy path.

---

# P0.2. Superadmin / tenant lifecycle hardening

## Цель

Суперадмин должен создавать, исправлять и удалять tenant через UI без ручного DB вмешательства.

## Что проверить и доработать

### Tenant create wizard

- Компания:
  - name;
  - slug auto-generation;
  - validation slug;
  - duplicate slug check.
- Trial/plan:
  - plan;
  - trial end;
  - limits.
- Первый админ:
  - email;
  - first_name;
  - last_name;
  - role;
  - invite link/email OTP.

### Ошибки

- 409 duplicate slug/email должен показываться в форме.
- 422 validation должен показываться у поля.
- 500 не должен быть нормальным сценарием.

### Delete tenant

- Добавить/проверить удаление test tenant из UI.
- Защитить production tenant от случайного удаления:
  - confirm by slug/name;
  - ideally soft delete или guarded hard delete.

### Tenant detail

Проверить, что tenant detail показывает:

- статус;
- plan/trial;
- limits;
- users count;
- courses count;
- first admins;
- invite status.

## DoD

- Новый tenant создается из superadmin UI.
- Первый admin входит по email OTP/invite.
- Ошибочный tenant можно удалить из UI.
- Нет 500 в happy path.
- Есть Playwright/manual QA report.

---

# P0.3. Единый журнал обучения

## Цель

HR/admin должен видеть, кто обучен, кто не обучен, кто получил сертификат, и выгрузить отчет.

## Backend

Создать endpoint:

`GET /api/v1/admin/training-log`

Фильтры:

- course_id;
- department_id или department name;
- position_id;
- status: assigned / in_progress / completed / overdue;
- delivery_type: native / scorm;
- date_from/date_to;
- search by name/email/personnel_number.

Поля ответа:

- user_id;
- full_name;
- email;
- personnel_number;
- department;
- position;
- course_id;
- course_title;
- delivery_type;
- enrollment_status;
- progress_percent;
- best_score;
- quiz_attempts_count;
- completed_at;
- certificate_id;
- certificate_number;
- assignment_source;
- kiosk_last_seen_at, если доступно.

Export:

- CSV минимум;
- XLSX желательно, если в проекте уже есть библиотека/паттерн.

## Frontend

Страница:

`/admin/training-log`

или логичный tab в staff/admin, но лучше отдельный раздел, если sidebar не перегружается.

UI:

- фильтры сверху;
- таблица;
- export;
- пустые состояния;
- loading/error states.

## DoD

- HR может ответить: “кто не прошел обязательный курс”.
- Native и SCORM курсы в одном журнале.
- Export работает.
- Запросы без N+1.

---

# P0.4. Staff import wizard 2.0

## Цель

Реальные Excel штатки должны загружаться без ручного редактирования колонок.

## Backend

Проверить текущие endpoints:

- `/api/v1/admin/staff/import/preview`;
- `/api/v1/admin/staff/import/commit`;
- manual staff create.

Доработать:

- выбор листа Excel;
- auto-detect подходящего листа;
- column mapping;
- ФИО одной колонкой;
- сохранение mapping per tenant;
- понятные ошибки;
- summary: created/updated/skipped/new positions/departments.

## Frontend

Flow:

1. Upload file.
2. Select sheet или auto-selected sheet.
3. Column mapping screen.
4. Preview rows and errors.
5. Commit.
6. Result + apply rules/enrollments status.

## DoD

- Много-листовой Excel можно загрузить.
- Пользователь не обязан переименовывать колонки в файле.
- Ошибка говорит, что именно исправить.
- После commit создаются users/departments/positions/enrollments.

---

# P0.5. Mobile/desktop QA ключевых flow

## Цель

Learner и kiosk должны работать на телефоне/планшете. Admin-heavy экраны могут быть desktop-first.

## Проверить

Desktop и mobile viewport:

- login/email OTP;
- accept invite;
- my courses;
- native course player;
- SCORM player;
- quiz;
- certificate view/download;
- kiosk identify;
- kiosk course open;
- logout from shared device.

## Что исправлять

- горизонтальный скролл;
- перекрытие кнопок;
- слишком мелкие tap targets;
- layout overflow;
- logout/loading stuck.

## DoD

- Playwright screenshots/report.
- Нет критичных layout bugs в learner/kiosk.

---

# P0.6. Onboarding checklist для tenant admin

## Цель

Новый tenant после регистрации понимает, что делать дальше.

## UI

В admin dashboard добавить checklist:

1. Заполнить профиль компании.
2. Импортировать штат.
3. Загрузить документы.
4. Сгенерировать первый курс.
5. Назначить курс.
6. Создать kiosk или отправить приглашения.
7. Проверить журнал обучения.

Статусы шагов должны считаться из реальных данных.

## DoD

- Новый tenant видит next steps.
- Trial limits видны рядом.
- Кнопки ведут в правильные разделы.

---

# Общие технические требования

## Не ломать роли

Сохраняй текущую логику:

- tenant admin / org_admin: инфраструктура tenant, команда, настройки;
- methodologist / teacher: курсы, тесты, назначения, штатка;
- student: прохождение;
- superadmin: platform admin.

Если видишь конфликт ролей, сначала зафиксируй в отчете и предложи минимальное изменение.

## Не трогать лишнее

Не делай:

- SCORM 2004;
- xAPI/cmi5/LTI;
- forum/wiki/CMS/e-commerce;
- full plugin system;
- большие дизайн-рефакторинги вне P0.

## Миграции

- Новые Alembic миграции должны идти после текущего head.
- Проверить:

```bash
cd apps/api
python -m alembic -c alembic.ini heads
```

Не создавать две head-ветки.

## Проверки

Минимум перед сдачей:

```bash
cd apps/api
python -m compileall app
python -m alembic -c alembic.ini heads
```

```bash
cd apps/web
npm run typecheck
```

Если есть тесты по затронутому модулю - запустить их.

Если меняется UI learner/kiosk/admin - сделать Playwright/manual screenshots и приложить путь к отчету.

## Работа с secrets

Не коммить `.env`, ключи, токены, пароли.

Если нужен доступ к внешним сервисам, использовать существующий локальный `.env`, но не выводить секреты в лог/отчет.

## Git

Коммиты делать с автором:

```bash
git config user.name "Kamilla LMS CRM"
git config user.email "kamilla_lms_crm@proton.me"
```

В конце показать:

```bash
git status --short
git log --oneline -5
```

Не пушить в master/main. Если пушишь ветку:

```bash
git push origin p0-first-tenant-hardening
```

## Финальный отчет агента

В конце создать файл:

`docs/reports/2026-07-XX_p0_hardening_report.md`

Структура:

1. Что сделано.
2. Какие файлы изменены.
3. Какие миграции добавлены.
4. Какие проверки запускались.
5. Что не успел / какие риски.
6. Какие ручные шаги нужны владельцу.
7. Ссылки на screenshots/reports.

В ответе пользователю кратко указать:

- branch;
- commit hash(es);
- report path;
- tests status.
