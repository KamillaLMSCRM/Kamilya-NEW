# Follow-up task / ТЗ: довести P0 hardening до merge-ready production confidence

Дата: 2026-07-09

Репозиторий: `C:\Kamilya New\Kamilya-NEW`

Базовая ветка: `origin/master`

Рабочая ветка:

```bash
git fetch origin
git checkout -b p0-followup-training-log-scorm-mobile-ci origin/master
```

Не работай напрямую в `master/main`.

## Контекст

В `master` уже смержен P0 first-tenant hardening:

- SCORM 1.2 import/launch/runtime;
- kiosk admin/logs;
- learner AI assistant;
- superadmin tenant lifecycle;
- staff import mappings;
- training log;
- onboarding checklist.

Быстрые проверки после merge проходят:

```bash
cd apps/api
python -m compileall app
python -m alembic -c alembic.ini heads
python -m pytest tests/unit/test_scorm_parse.py -q

cd apps/web
npm run typecheck
```

Остаются follow-up блокеры перед спокойным production rollout.

## Scope

Сделать только этот follow-up. Не добавлять новые крупные LMS-фичи.

P0 follow-up состоит из 4 блоков:

1. Исправить честность `training-log`: статусы, прогресс, фильтры.
2. Провести ручной SCORM 1.2 QA на реальных пакетах или подготовить воспроизводимый QA harness.
3. Провести mobile/desktop QA ключевых learner/kiosk/admin flow.
4. Добавить CI/test workflow для backend unit/integration smoke.

---

## 1. Training log: честные статусы и прогресс

### Проблема

Сейчас frontend показывает фильтры:

- `assigned`;
- `in_progress`;
- `completed`;
- `overdue`.

Но backend в `apps/api/app/modules/training_log/repository.py` реально фильтрует только:

- `completed`;
- `assigned`.

Для `in_progress` и `overdue` фильтр фактически не применяется. Это опасно: HR выберет "В процессе" или "Просрочен" и увидит неверный список.

Кроме того, `progress_percent` сейчас 0 или 100, хотя для native courses в базе есть lesson progress.

### Что сделать

#### Backend

1. Определить статус строки журнала явно:
   - `completed`: enrollment completed или `completed_at IS NOT NULL`;
   - `in_progress`: не completed и есть хотя бы один completed lesson progress или SCORM attempt/commit;
   - `assigned`: не completed и нет progress;
   - `overdue`: пока дедлайна нет. Либо убрать из API/UI, либо добавить только если в модели есть реальный deadline.

2. Для native course считать `progress_percent`:
   - `completed_lessons / total_lessons * 100`;
   - если уроков нет, 0;
   - если enrollment completed, 100.

3. Для SCORM:
   - `completed/passed` -> 100;
   - если есть SCORM attempt/commit, но не completed -> `in_progress`, progress можно оставить 0 до появления нормального SCORM progress map;
   - если attempts нет -> `assigned`.

4. Фильтр `status=in_progress` должен возвращать только реально начатые, но не завершенные записи.

5. Если `overdue` не может быть честно реализован без deadline:
   - убрать `overdue` из `TrainingLogFilter`;
   - убрать из frontend select;
   - убрать из документации/отчета.

#### Frontend

1. Синхронизировать `STATUS_OPTIONS` с реальным backend.
2. В таблице показывать вычисленный статус, а не только raw `enrollment_status`.
3. Добавить текст в empty state, если фильтр ничего не нашел.

#### Tests

Добавить/обновить backend tests:

- assigned без progress;
- in_progress с native lesson progress;
- completed;
- SCORM attempt без completion -> in_progress;
- SCORM completed -> completed;
- если overdue убран, убедиться что API не принимает `status=overdue` или UI его не отправляет.

---

## 2. SCORM 1.2 real-package QA

### Цель

Подтвердить, что SCORM 1.2 работает не только на synthetic ZIP, но и на реальных экспортированных пакетах.

### Что сделать

1. Собрать минимум 2 реальных SCORM 1.2 пакета:
   - простой пакет;
   - пакет с вложенными assets, JS/CSS/images и query/hash в entrypoint.

2. Если реальных iSpring/Articulate/Captivate пакетов нет:
   - создать `docs/test-assets/scorm/README.md` с инструкцией, где взять/как экспортировать;
   - создать локальный QA harness, который генерирует максимально похожий SCORM 1.2 ZIP.

3. Проверить flow:
   - import через UI `/courses`;
   - launch iframe;
   - загрузка CSS/JS/images;
   - `LMSInitialize`;
   - `LMSSetValue`;
   - `LMSCommit`;
   - `LMSFinish`;
   - completion создает certificate;
   - learner dashboard показывает завершение.

4. Проверить отрицательные кейсы:
   - SCORM 2004 отклоняется понятной ошибкой;
   - unsafe href/path traversal отклоняется;
   - missing entrypoint дает понятную ошибку или понятный UI state.

### Security/robustness fix

В `apps/api/app/modules/scorm/router.py` HTML launch shell сейчас вставляет `package.title` и `asset_url` напрямую в HTML.

Нужно:

- HTML-экранировать title;
- безопасно формировать iframe `src`;
- добавить unit/integration тест на title с `<script>` или кавычками.

---

## 3. Mobile/desktop QA

### Цель

Подтвердить, что первый tenant сможет пройти основные flow без визуальных сломов.

### Проверить через Playwright или ручной браузер

Desktop: `1280x800`

Mobile: `390x844`

Tablet/kiosk: `768x1024`

Flow:

1. Login/email OTP.
2. Trial tenant admin dashboard.
3. Onboarding checklist.
4. Staff import page.
5. Courses list + SCORM import card.
6. Training log.
7. Learner my-courses.
8. Native course player.
9. SCORM player.
10. Quiz.
11. Certificate view.
12. Kiosk identify and course open.
13. Logout from shared device.

### Что исправлять

- горизонтальный скролл в learner/kiosk;
- перекрытие кнопок;
- текст, который не помещается;
- sidebar/topbar ломаются на tablet/mobile;
- зависание logout/loading.

### Артефакт

Создать:

`docs/reports/2026-07-09_mobile_desktop_qa_report.md`

Содержимое:

- URL;
- viewport;
- pass/fail;
- screenshot path;
- найденные дефекты;
- исправленные дефекты.

---

## 4. CI backend tests

### Цель

Чтобы следующие агенты не писали "тесты есть, но не запускались".

### Что сделать

1. Проверить существующие GitHub Actions.
2. Добавить workflow или job для:

```bash
cd apps/api
python -m compileall app
python -m pytest tests/unit -q
```

3. Для integration tests:
   - поднять Postgres service в GitHub Actions;
   - задать test `DATABASE_URL`;
   - прогнать хотя бы smoke subset:

```bash
python -m pytest tests/integration/test_superadmin_lifecycle.py tests/integration/test_training_log.py -q
```

Если полный integration suite пока нестабилен, не скрывать это. Добавить documented skip или отдельный non-blocking job только с объяснением.

---

## Required checks before handoff

Минимум:

```bash
cd apps/api
python -m compileall app
python -m alembic -c alembic.ini heads
python -m pytest tests/unit/test_scorm_parse.py -q
python -m pytest tests/unit -q
```

```bash
cd apps/web
npm run typecheck
```

Если настроен Postgres:

```bash
cd apps/api
python -m pytest tests/integration/test_training_log.py tests/integration/test_superadmin_lifecycle.py -q
```

## Final report

Создать:

`docs/reports/2026-07-09_p0_followup_report.md`

Структура:

1. Что исправлено.
2. Какие файлы изменены.
3. Какие тесты добавлены.
4. Какие проверки прошли.
5. Что осталось ручным QA.
6. Что нельзя мержить без владельца.

## Git

Коммиты делать с автором:

```bash
git config user.name "Kamilla LMS CRM"
git config user.email "kamilla_lms_crm@proton.me"
```

В конце:

```bash
git status --short
git log --oneline -5
```

Push:

```bash
git push origin p0-followup-training-log-scorm-mobile-ci
```
