# P0 first-tenant hardening — детальный план работ

Дата: 2026-07-09
Ветка: `p0-first-tenant-hardening` (от `origin/foundation-scorm-kiosk-assistant-2026-07-09`)
Базовый коммит: `95a9370` (foundation: SCORM 1.2 + kiosk + learner-assistant + 3 документа)
Текущий HEAD: `0481f57` (P0.0: fix SCORM 2004 namespace detection — закоммичен)

Основа: `docs/agent-tasks/2026-07-09_p0_hardening_external_agent_prompt.md`,
`docs/plans/2026-07-09_p0_p1_product_hardening_plan.md`,
`docs/plans/2026-07-09_scorm-kiosk-ai-chamilo-roadmap.md`.

## Контекст (что уже в репо)

По разведке кода на 2026-07-09:

| Блок | Что уже реализовано | Что нужно доделать |
|---|---|---|
| P0.1 SCORM 1.2 | Import ZIP, manifest parser, runtime bridge (LMSInitialize/Get/Set/Commit/Finish + error helpers), asset proxy (token-path), completion+certificate, lessons_status hook | QA на 2-3 реальных пакетах, edge cases (entrypoint с query/hash), logging, Playwright smoke |
| P0.2 Superadmin | GET/POST/PATCH/DELETE tenants, первые admin'ы, duplicate slug auto-resolve, slug normalize, delete (guarded) | UI polish: ошибки в форме (409/422), confirm-by-slug для delete, tenant detail (users/courses counts) |
| P0.3 Training-log | Ничего — отдельной страницы/эндпоинта нет | Backend `GET /api/v1/admin/training-log` (фильтры+export CSV), frontend `/admin/training-log`, натив+SCORM в одном журнале |
| P0.4 Staff import | preview/commit endpoints, multi-sheet selector, suggested_mapping, sample_rows, errors, missing_required_columns | save mapping per tenant (новая таблица), manual staff create (есть endpoint, проверить UI), UX-полировка |
| P0.5 Mobile/desktop | /admin/kiosks + /kiosk/[token] есть, learner pages есть | Playwright screenshots на critical paths, фикс очевидных layout issues если найду |
| P0.6 Onboarding checklist | Ничего — admin dashboard не имеет виджета | Widget «Подготовить компанию» с 7 шагами, статусы из реальных данных, trial limits |

**P0.0 уже сделан** (коммит `0481f57`): fix SCORM 2004 namespace detection.

---

## P0.1. SCORM 1.2 end-to-end QA

**Цель:** подтвердить, что SCORM 1.2 пакеты реально импортируются, запускаются, сохраняют прогресс, выдают сертификат. Найти edge cases и зафиксить их.

**Что сделать:**

1. **Edge-case: entrypoint с query/hash в href**
   - Сейчас в `scorm/router.py:131-136` если `entrypoint not in names` ставится `entrypoint_exists=False`, но не блокирует. Некоторые SCORM-пакеты (iSpring) кладут `index.html?param=value` в href. Это нужно:
     - либо нормализовать href на этапе парсинга (отрезать query/hash до проверки);
     - либо при запуске отдавать `entrypoint` как есть и решать на runtime.
   - **Файлы:** `apps/api/app/modules/scorm/router.py:131`
   - **Проверка:** написать unit-тест на `_parse_manifest` с манифестом где href = `index.html?loadcss=1`.
   - **Статус:** ⬜

2. **Edge-case: SCORM 1.2 без `imscp:schemaversion` и без namespace 2004**
   - Сейчас если нет ни того ни другого, по умолчанию `scorm_1_2`. Это правильно, но хочется unit-тест, чтобы зафиксировать поведение.
   - **Файлы:** `apps/api/tests/test_scorm_parse.py` (создать)
   - **Статус:** ⬜

3. **Edge-case: asset path с query в `_asset_bytes`**
   - Уже обрабатывается через `asset_path.split("?", 1)[0]` (строка 222). Добавить unit-тест.
   - **Файлы:** `apps/api/tests/test_scorm_assets.py` (создать)
   - **Статус:** ⬜

4. **Logging runtime errors**
   - Runtime bridge пишет в `console.error` (браузер). Добавить structured log на бэкенде при `commit_scorm_attempt` с status code != 0.
   - **Файлы:** `apps/api/app/modules/scorm/router.py:505+`
   - **Статус:** ⬜

5. **QA-отчёт** — даже без реальных пакетов iSpring/Articulate/Captivate можно прогнать 2 синтетических минимальных SCORM 1.2 ZIP-пакета (создать в `apps/api/tests/fixtures/scorm12_minimal.zip`):
   - минимальный: `imsmanifest.xml` + `index.html` который сразу `LMSSetValue("cmi.core.lesson_status", "completed") + LMSCommit + LMSFinish`;
   - с assets: тот же + подключённый CSS/JS.
   - Прогнать через API: `POST /api/v1/scorm/packages/import`, потом `GET /api/v1/scorm/courses/{id}/launch`, потом `POST /api/v1/scorm/attempts/{id}/commit`. Проверить что:
     - импорт OK;
     - launch отдаёт HTML с iframe;
     - asset proxy отдаёт CSS/JS;
     - commit с `lesson_status=completed` переводит enrollment в `completed` и создаёт certificate.
   - **Файлы:** `apps/api/tests/integration/test_scorm_e2e.py` (создать), `docs/reports/2026-07-09_scorm_12_qa_report.md` (создать)
   - **Статус:** ⬜

6. **Playwright smoke** — happy path: admin загружает SCORM ZIP → открывает launch → iframe загружается → commit → видит "Курс завершён". Пока без реальных iSpring — проверяю iframe shell + asset proxy.
   - **Файлы:** `apps/web/e2e/scorm-launch.spec.ts` (создать)
   - **Статус:** ⬜

**Commit-границы:** `p0.1-scorm-12-edge-cases`, `p0.1-scorm-12-tests`, `p0.1-scorm-12-playwright-smoke`, `p0.1-scorm-12-qa-report`.

**DoD:**
- [ ] 3 unit-теста на edge cases (entrypoint, schemaversion, asset query)
- [ ] integration test: minimal SCORM 1.2 ZIP → import → launch → commit → certificate
- [ ] Playwright smoke на iframe shell
- [ ] QA-отчёт в `docs/reports/2026-07-09_scorm_12_qa_report.md` с результатами
- [ ] SCORM 2004 пакет отклоняется (smoke test на manifest с `adlcp_v1p3`)

---

## P0.2. Superadmin / tenant lifecycle hardening

**Цель:** суперадмин может создать/исправить/удалить tenant через UI без 500, ошибки показываются в форме, prod tenant защищён.

**Что сделать:**

1. **Tenant create wizard — отображение ошибок в форме**
   - Текущий код: `apps/api/app/modules/admin/superadmin/router.py:73` POST `/tenants`. Если duplicate slug/email — обычно 409. Фронт должен показать ошибку у поля.
   - Прочитать `apps/web/src/app/admin/super/tenants/page.tsx` и `apps/web/src/app/admin/super/tenants/[id]/page.tsx`, проверить обработку ошибок.
   - Если 409 → toast + пометить поле `slug`/`email`.
   - Если 422 → per-field errors.
   - **Файлы:** `apps/web/src/app/admin/super/tenants/page.tsx`, `apps/api/app/modules/admin/superadmin/schemas.py`
   - **Статус:** ⬜

2. **Delete tenant — confirm by slug/name**
   - Сейчас DELETE `/tenants/{tenant_id}` есть (router.py:157). Проверить:
     - Есть ли в UI confirm dialog?
     - Защищён ли prod tenant (slug `kamilya` или is_protected flag)?
   - Если нет — добавить confirm dialog с вводом slug, плюс backend-проверку `is_protected` или `slug != 'kamilya'`.
   - **Файлы:** `apps/web/src/app/admin/super/tenants/[id]/page.tsx`, `apps/api/app/modules/admin/superadmin/router.py:157`
   - **Статус:** ⬜

3. **Tenant detail page** — добавить users count, courses count, status, trial end, plan, limits.
   - Сейчас `tenants/[id]/page.tsx` есть. Проверить что показывает.
   - Добавить backend endpoint если нужен (например `GET /tenants/{id}/stats`) или расширить существующий.
   - **Файлы:** `apps/web/src/app/admin/super/tenants/[id]/page.tsx`, при необходимости backend
   - **Статус:** ⬜

**Commit-границы:** `p0.2-superadmin-errors`, `p0.2-superadmin-delete-confirm`, `p0.2-superadmin-detail`.

**DoD:**
- [ ] Duplicate slug → 409 показывается в форме, не только в консоли
- [ ] Validation errors → per-field
- [ ] Delete tenant требует confirm по slug
- [ ] Tenant detail показывает usage stats
- [ ] Playwright/manual QA: создать тестовый tenant → удалить → 0 500

---

## P0.3. Единый журнал обучения

**Цель:** HR/admin видит кто обучен / не обучен / получил сертификат, фильтрует по course/department/position/status/date, экспортирует CSV. Native + SCORM в одном журнале.

**Это основной блок — здесь больше всего нового кода.**

**Что сделать:**

### Backend

1. **Миграция** — не нужна новая таблица. Используем существующие:
   - `enrollments` (user, course, status, source, completed_at)
   - `courses` (id, title, delivery_type='native'|'scorm')
   - `users` (id, first_name, last_name, email, personnel_number, department_id, position_id)
   - `departments` / `positions` (названия)
   - `quiz_attempts` (user, course, score, passed) — для `best_score`
   - `certificates` (user, course, certificate_number)
   - `kiosk_access_logs` — `kiosk_last_seen_at` для пользователя

2. **Endpoint** `GET /api/v1/admin/training-log`
   - **Auth:** `admin`, `org_admin`, `methodologist`, `superadmin`
   - **Query params:**
     - `course_id: UUID | None`
     - `department_id: UUID | None`
     - `position_id: UUID | None`
     - `status: Literal['assigned','in_progress','completed','overdue'] | None`
     - `delivery_type: Literal['native','scorm'] | None`
     - `date_from: datetime | None`
     - `date_to: datetime | None`
     - `search: str | None` (поиск по имени/email/табельному)
     - `limit: int = 100, offset: int = 0`
   - **Response:** список объектов с полями:
     ```
     user_id, full_name, email, personnel_number,
     department_id, department_name,
     position_id, position_name,
     course_id, course_title, delivery_type,
     enrollment_status, progress_percent,
     best_score, quiz_attempts_count,
     enrolled_at, completed_at,
     certificate_id, certificate_number,
     assignment_source,
     kiosk_last_seen_at
     ```
   - **Реализация:** single SQL с JOIN'ами + агрегаты (quiz_attempts count+max score). Избегать N+1.
   - **Tenant scope:** обязательно `WHERE users.tenant_id = :tenant_id` из JWT.
   - **Файлы:** `apps/api/app/modules/training_log/router.py`, `service.py`, `repository.py`, `schemas.py` (новый модуль), регистрация в `apps/api/app/main.py`
   - **Статус:** ⬜

3. **Export CSV**
   - Тот же endpoint с `?format=csv` — отдаёт CSV с BOM (Excel-friendly).
   - Альтернатива: `GET /api/v1/admin/training-log/export.csv`
   - **Файлы:** в том же модуле
   - **Статус:** ⬜

4. **Tests** — unit на service/repository (фильтры, tenant scope), integration на endpoint с реальной БД.
   - **Файлы:** `apps/api/tests/integration/test_training_log.py`
   - **Статус:** ⬜

### Frontend

5. **Page** `/admin/training-log`
   - **Файлы:** `apps/web/src/app/admin/training-log/page.tsx` (создать)
   - **Layout:** фильтры сверху (collapsible), таблица, export-кнопка.
   - **Фильтры:** course (Select), department (Select), position (Select), status (Select), delivery_type (Select), date range, search input.
   - **Таблица:** виртуализированная (TanStack Table), колонки согласно backend response.
   - **Export:** кнопка "CSV" → download через `?format=csv`.
   - **Empty state:** «Нет данных для фильтра».
   - **Loading:** skeleton.
   - **Error:** toast + retry.
   - **Статус:** ⬜

6. **Sidebar entry** — добавить "Журнал обучения" в sidebar для admin/org_admin/methodologist/superadmin.
   - **Файлы:** `apps/web/src/components/layout/Sidebar.tsx`, i18n `ru/kk/en.json`
   - **Статус:** ⬜

7. **Tests** — Playwright smoke: открыть страницу, применить фильтр, проверить таблицу.
   - **Файлы:** `apps/web/e2e/training-log.spec.ts`
   - **Статус:** ⬜

**Commit-границы:**
- `p0.3-training-log-backend` (модуль + endpoint + tests)
- `p0.3-training-log-csv-export`
- `p0.3-training-log-frontend`
- `p0.3-training-log-sidebar`

**DoD:**
- [ ] Endpoint отдаёт JSON с фильтрами, tenant-scoped
- [ ] CSV export работает
- [ ] Страница `/admin/training-log` рендерит таблицу
- [ ] Фильтры работают (course/department/position/status/date/search)
- [ ] Native + SCORM в одном журнале
- [ ] Нет N+1 (один запрос или batched)
- [ ] Sidebar entry есть
- [ ] Integration test проходит

---

## P0.4. Staff import wizard 2.0

**Цель:** реальные много-листовые Excel загружаются без переименования колонок, mapping сохраняется per tenant, ошибки понятные.

**Что уже есть:** preview/commit, multi-sheet selector, suggested_mapping, sample_rows, missing_required_columns. UI в `apps/web/src/app/admin/staff/page.tsx` работает.

**Что доделать:**

1. **Save column mapping per tenant**
   - Новая таблица `staff_import_mappings`:
     ```sql
     id, tenant_id, name, mapping_json, is_default, created_at
     ```
   - **Файлы:** `apps/api/alembic/versions/0053_add_staff_import_mappings.py` (новая)
   - Endpoints:
     - `GET /api/v1/admin/staff/import/mappings` — список сохранённых mapping'ов tenant'а
     - `POST /api/v1/admin/staff/import/mappings` — создать (name, mapping_json, is_default?)
     - `DELETE /api/v1/admin/staff/import/mappings/{id}`
   - На preview: если выбран сохранённый mapping — применить, не предлагать suggested.
   - **Файлы:** `apps/api/app/modules/users/staff_import_router.py` (дополнить), `apps/api/app/modules/users/staff_import_service.py`, новая миграция
   - **Статус:** ⬜

2. **UX: загрузка существующего mapping**
   - На странице `/admin/staff` (Import tab) добавить dropdown "Применить сохранённый mapping" над Upload.
   - **Файлы:** `apps/web/src/app/admin/staff/page.tsx`
   - **Статус:** ⬜

3. **Manual staff create UI**
   - Endpoint есть (`create_manual_staff_member` в service.py). Проверить есть ли UI кнопка. Если нет — добавить.
   - **Файлы:** `apps/web/src/app/admin/staff/page.tsx` (проверить), возможно создать модалку
   - **Статус:** ⬜

4. **Tests** — unit на mapping service, integration на новый endpoint.
   - **Файлы:** `apps/api/tests/integration/test_staff_import_mapping.py`
   - **Статус:** ⬜

**Commit-границы:**
- `p0.4-staff-import-mapping-migration` (0053)
- `p0.4-staff-import-mapping-endpoints`
- `p0.4-staff-import-mapping-ui`
- `p0.4-staff-import-manual-ui`

**DoD:**
- [ ] Mapping сохраняется per tenant и применяется при следующем upload
- [ ] Список сохранённых mapping'ов виден
- [ ] Manual staff create работает из UI
- [ ] Integration test проходит

---

## P0.5. Mobile/desktop QA ключевых flow

**Цель:** learner и kiosk работают на телефоне/планшете без горизонтального скролла, без перекрытий.

**Что сделать:**

1. **Playwright screenshots** на critical paths:
   - `/login` (email OTP) — desktop + mobile
   - `/courses` — desktop + mobile
   - `/courses/[id]` (native player) — desktop + mobile
   - `/courses/[id]/scorm` (SCORM player iframe) — desktop + mobile
   - `/kiosk/[token]` — desktop + mobile (это планшет-сценарий)
   - `/admin/kiosks` — desktop only (admin-heavy)
   - `/admin/training-log` (новый из P0.3) — desktop only

   **Файлы:** `apps/web/e2e/mobile-qa.spec.ts` (создать), скриншоты в `docs/reports/mobile-qa-2026-07-09/`
   **Статус:** ⬜

2. **Layout fixes** — если найду горизонтальный скролл, перекрытие кнопок, мелкие tap targets — фикшу.
   - **Файлы:** CSS в соответствующих pages
   - **Статус:** ⬜ (зависит от того что найду)

3. **Logout с shared device (kiosk)**
   - Проверить что после закрытия kiosk-таба JWT протухает (TTL 20 мин уже есть). Проверить что нет persistent cookies на kiosk-странице.
   - **Файлы:** `apps/web/src/app/kiosk/[token]/page.tsx`
   - **Статус:** ⬜

**Commit-границы:** `p0.5-mobile-qa-screenshots`, `p0.5-mobile-qa-fixes` (если будут).

**DoD:**
- [ ] Скриншоты learner/kiosk на mobile (375x812) и desktop (1280x800)
- [ ] Нет критичных layout bugs (нет горизонтального скролла, нет перекрытий)
- [ ] Отчёт `docs/reports/2026-07-09_mobile_qa_report.md` со списком screens + issues

---

## P0.6. Onboarding checklist для tenant admin

**Цель:** новый tenant видит «что делать дальше» — 7 шагов с реальными статусами.

**Что сделать:**

1. **Backend endpoint** `GET /api/v1/admin/onboarding-status`
   - Возвращает статус каждого шага:
     - `profile_complete: bool` (есть tenant.name, tenant_settings.logo_url и primary_color)
     - `staff_imported: bool` (users.count > 0)
     - `documents_uploaded: bool` (documents.count > 0)
     - `first_course_generated: bool` (courses.count > 0)
     - `first_course_assigned: bool` (enrollments.count > 0)
     - `kiosk_or_invite: bool` (kiosks.count > 0 OR pending_invites.count > 0)
     - `training_log_viewed: bool` — пропустить, или считать «всегда false, но и не блокер»
   - **Файлы:** `apps/api/app/modules/admin/onboarding/router.py` (новый), `service.py`, `schemas.py`
   - **Статус:** ⬜

2. **Frontend widget** на admin dashboard (`/admin` или `/admin/dashboard`)
   - Если файл существует — добавить. Если нет — создать `/admin/page.tsx`.
   - Компонент `<OnboardingChecklist tenant={...} status={...} />`
   - 7 шагов с иконками ✓/○, ссылками на разделы.
   - Trial limits рядом с действиями.
   - **Файлы:** `apps/web/src/app/admin/page.tsx` (создать или дополнить), `apps/web/src/components/admin/OnboardingChecklist.tsx`
   - **Статус:** ⬜

3. **i18n** — строки для виджета (ru, kk, en)
   - **Файлы:** `apps/web/src/i18n/locales/{ru,kk,en}.json`
   - **Статус:** ⬜

4. **Tests** — unit на сервисе (правильные статусы), Playwright на виджет (рендерится, шаги кликабельны).
   - **Файлы:** `apps/api/tests/integration/test_onboarding.py`, `apps/web/e2e/onboarding.spec.ts`
   - **Статус:** ⬜

**Commit-границы:**
- `p0.6-onboarding-backend`
- `p0.6-onboarding-widget`
- `p0.6-onboarding-i18n`
- `p0.6-onboarding-tests`

**DoD:**
- [ ] Новый tenant видит 7 шагов, статусы из реальных данных
- [ ] Trial limits видны
- [ ] Клики ведут в правильные разделы
- [ ] i18n ru/kk/en

---

## Общий трек работы

**Последовательность (по приоритету реального блокера для первого tenant):**

1. **P0.3 training-log** — главный недостающий блок для HR. ~3-4 часа.
2. **P0.6 onboarding checklist** — помогает первому tenant не потеряться. ~1.5-2 часа.
3. **P0.4 staff-import mapping-save** — UX-доделка, важна для штатки. ~1-1.5 часа.
4. **P0.1 SCORM QA** — критично для SCORM-клиента, но без реальных пакетов = mock-tests. ~1.5-2 часа.
5. **P0.2 superadmin polish** — мелкие правки. ~1 час.
6. **P0.5 mobile QA** — screenshots + возможно мелкие CSS fixes. ~1-1.5 часа.

**Общий бюджет:** ~9-12 часов кодинга. Реалистично в один проход — да, если не уходить в perfectionism.

**Финальный отчёт:** `docs/reports/2026-07-09_p0_hardening_report.md` после всех блоков.

---

## Проверки перед каждым коммитом

Минимум:
```bash
cd apps/api && python -m compileall app          # синтаксис
cd apps/api && python -m alembic -c alembic.ini heads  # одна head
cd apps/web && npm run typecheck                  # TS strict
```

Если менялся UI — Playwright smoke по соответствующему flow.

---

## Что НЕ делается в этом эпике

- SCORM 2004 (явно вне scope, отклоняем)
- xAPI / cmi5 / LTI
- Форумы / wiki / CMS / e-commerce
- Полный plugin system
- Большие дизайн-рефакторинги вне P0
- P1+ (surveys, reminders, skill matrix, certificate QR, 2FA, CRM API) — отдельный эпик

---

## Текущий статус

- ✅ P0.0 fix SCORM 2004 namespace detection (commit `0481f57`)
- ⬜ P0.1 SCORM QA
- ⬜ P0.2 Superadmin hardening
- ⬜ P0.3 Training-log (ГЛАВНЫЙ)
- ⬜ P0.4 Staff import mapping
- ⬜ P0.5 Mobile QA
- ⬜ P0.6 Onboarding checklist
- ⬜ Финальный отчёт