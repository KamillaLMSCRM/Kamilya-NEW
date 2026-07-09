# P1 backlog execution plan — Kamilya LMS

**Дата:** 2026-07-09
**Основа:** `docs/reports/2026-07-09_p1_product_qa_gap_inventory.md`
**Roadmap:** `docs/plans/2026-07-09_p0_p1_product_hardening_plan.md` (P1.1–P1.6 стратегические блоки)

## TL;DR

**19 P1-задач** готовы к взятию в работу. Оценено по S/M/L (где S = 1-2 дня, M = 3-5 дней, L = 1-2 недели).

| Категория | Кол-во | Severity |
|---|---|---|
| Privacy / security | 4 | High |
| Discoverability / navigation | 3 | High |
| UI polish | 8 | Medium |
| New features (P1 roadmap) | 4 | Medium-Low |

**Рекомендуемая последовательность** — см. раздел «Порядок» ниже. Не пытаться делать всё параллельно: kiosk-блокер (P1.1) → sidebar (P1.3) → training log UX (P1.7) → i18n (P1.4) → всё остальное.

---

## P1.1 — Kiosk auto-logout по inactivity [privacy]

**Severity:** High (privacy)
**Размер:** M
**Проблема (KIOSK-1):** Worker identify → выбрал курс → отошёл → следующий worker видит данные предыдущего.
**Решение:**
- Frontend: idle timer (5 минут бездействия → автоматический `setResult(null)` + clear personnel_number)
- Track activity: mouse, touch, keypress, focus events
- Visual countdown за 60 секунд до logout ("Сеанс истекает через 60 секунд — нажмите чтобы продолжить")
- Backend: `/v1/kiosks/{token}/identify` принимает опциональный `session_token`, валидирует TTL 5 минут; identify с новым personnel_number сбрасывает предыдущий session
**Файлы:**
- `apps/web/src/app/kiosk/[token]/page.tsx` — добавить idle timer
- `apps/api/app/modules/users/kiosk_router.py` — session_token logic
- `docs/api/kiosk.md` — задокументировать контракт
**Тесты:**
- Unit: idle timeout срабатывает через N секунд
- Integration: новый identify инвалидирует предыдущий session
**Критерии приёмки:**
- После 5 мин idle — UI показывает "Сеанс истёк" + кнопка "Войти снова"
- Если новый worker вводит свой personnel_number — старые данные не видны
- Audit log фиксирует оба события

---

## P1.2 — Kiosk user auth flow для course player [blocker]

**Severity:** High
**Размер:** M
**Проблема (KIOSK-2):** Kiosk identify → click course → `<a href="/courses/[id]">`. Если kiosk user не authenticated → redirect to /login → застрял (нужен обычный логин).
**Решение:**
- Опция A: kiosk-issued short-lived token (5 мин TTL), прикрепляется к URL `/courses/[id]?kiosk_token=...`
- Опция B: выдавать kiosk-issued JWT при identify, использовать для `/courses/[id]`-style requests
- Опция C (минимальная): перенести course player в iframe внутри `/kiosk/[token]/play/[courseId]` — без редиректа
- **Рекомендую Опция A** — не ломает существующий course player, чисто добавляет kiosk-режим
**Файлы:**
- `apps/api/app/modules/users/kiosk_router.py` — `POST /identify` выдаёт kiosk_token (TTL 5 мин)
- `apps/web/src/app/courses/[id]/page.tsx` — если `?kiosk_token=` → auth через kiosk endpoint, не redirect на /login
- `apps/web/src/app/kiosk/[token]/page.tsx` — обновить links на курсы с kiosk_token
**Тесты:**
- Integration: kiosk_token валиден 5 мин, после — 401
- E2E (Playwright): kiosk → identify → course → commit — без /login
**Критерии приёмки:**
- Kiosk worker может пройти курс от identify до completion без /login
- При попытке использовать kiosk_token после TTL — понятная ошибка

---

## P1.3 — Sidebar entry для `/admin/quizzes/assign` [discoverability]

**Severity:** High
**Размер:** S
**Проблема (METHOD-1, INV-2):** Страница `/admin/quizzes/assign` существует, но в sidebar нет entry. Методолог не найдёт "назначить тест по должности".
**Решение:**
- Добавить в Sidebar.tsx в раздел "Управление курсами" entry:
  ```
  {
    label: t('quiz.assignQuiz'),
    href: '/admin/quizzes/assign',
    icon: <icon>,
    roles: ['admin', 'org_admin', 'methodologist'],
  }
  ```
- Добавить `quiz.assignQuiz` в i18n locales
- Альтернативно: под existing entry "Назначения" (`/assignments`) добавить sub-tabs "Курсы / Тесты"
**Файлы:**
- `apps/web/src/components/layout/Sidebar.tsx`
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Тесты:**
- Manual: sidebar показывает entry для methodologist
- Manual: страница `/admin/quizzes/assign` открывается в 1 клик
**Критерии приёмки:**
- Methodologist видит "Назначить тест" в sidebar
- Link работает на /admin/quizzes/assign
- Роли ограничены правильно

---

## P1.4 — Admin dashboard hardcoded Russian → i18n

**Severity:** Medium
**Размер:** M
**Проблема (ADMIN-1):** `/admin/page.tsx` имеет ~12 мест hardcoded Russian: trial card labels, export buttons, recent sections, dashboard stats. При смене lang на en/kk — UI остаётся русским.
**Решение:**
- Извлечь все hardcoded строки в `t('admin.dashboard.*')` / `t('admin.trial.*')` / `t('admin.export.*')`
- Примеры: "Trial и лимиты" → `t('admin.trial.title')`; "Обучающиеся" → `t('admin.trial.learners')`; "Осталось дней: X" → `t('admin.trial.daysLeft', { count })`
- Аналогично для kpi cards: totalUsers, totalCourses, enrollments, certificates
- Аналогично для "Скачать CSV" → `t('admin.export.users')` и т.п.
- Не забудь про "Перенаправляю в Штатное расписание → Структура" в `/admin/employees` (если используется)
**Файлы:**
- `apps/web/src/app/admin/page.tsx`
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Тесты:**
- Manual: при переключении lang → все тексты переводятся
- Manual: trial.daysLeft = 0 показывает "Дата окончания trial не задана" или "Trial истёк"
**Критерии приёмки:**
- 0 hardcoded Russian в `/admin/page.tsx`
- 3 locale файла обновлены
- Visual test: en и kk версии рендерятся корректно

---

## P1.5 — Kiosk print HTML i18n + RU/KK версии

**Severity:** Medium (цех в KZ)
**Размер:** S
**Проблема (KIOSK-5):** Print HTML в `/admin/kiosks/page.tsx` lines 172-184 — hardcoded Russian ("Отсканируйте QR-код и введите табельный номер", "После завершения обучения закройте вкладку"). Цех в Казахстане не напечатает на казахском.
**Решение:**
- Создать отдельный компонент `PrintKioskSheet` с props (kiosk, qr, lang)
- Использовать `t('kiosk.printSheet.*')` для всех строк
- 3 языка в i18n
**Файлы:**
- `apps/web/src/app/admin/kiosks/page.tsx` — извлечь print HTML в компонент
- `apps/web/src/components/admin/KioskPrintSheet.tsx` (new)
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Тесты:**
- Manual: print preview на ru, en, kk — все три версии читаемы
**Критерии приёмки:**
- QR sheet на казахском печатается без mojibake
- "Печать" кнопка генерирует правильную локализацию

---

## P1.6 — `/admin/quizzes` + `/admin/quizzes/assign` sidebar entry + удалить дубликаты

**Severity:** Medium
**Размер:** S
**Проблема:** Есть два routes для quiz management: `/admin/quizzes` и `/quizzes` (последний — sidebar entry). Методолог заходит на `/quizzes` — это конструктор. А `/admin/quizzes` — что?
**Решение:**
- Прочитать `/admin/quizzes/page.tsx` — понять назначение
- Если это admin-only list всех тестов tenant — оставить, добавить sidebar entry
- Если дублирует `/quizzes` — удалить `/admin/quizzes`
- Аналогично для `/admin/quizzes/assign` (см. P1.3)
**Файлы:**
- `apps/web/src/app/admin/quizzes/page.tsx` (read first, decide)
- `apps/web/src/components/layout/Sidebar.tsx`
**Критерии приёмки:**
- Один canonical route для quiz list, другой для quiz assign
- Sidebar показывает оба явно

---

## P1.7 — Training log: пустые фильтры → empty state с подсказкой

**Severity:** Medium
**Размер:** S
**Проблема:** Training log показывает "Нет записей для выбранных фильтров" если фильтр ничего не нашёл. Но не объясняет почему и что делать (попробовать другие фильтры? все курсы? убрать status?).
**Решение:**
- Empty state: "По выбранным фильтрам ничего не найдено. Попробуйте: убрать фильтр статуса, расширить диапазон дат, выбрать другой курс"
- Buttons: "Сбросить фильтры", "Показать все"
- Динамически: если фильтр `status=completed` пустой → "Нет завершённых. Проверьте, что курс опубликован и есть назначения."
**Файлы:**
- `apps/web/src/app/admin/training-log/page.tsx`
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Критерии приёмки:**
- Empty state даёт actionable подсказки
- Кнопки сброса работают

---

## P1.8 — Training log: default сортировка + видимые индикаторы прогресса

**Severity:** Low
**Размер:** S
**Проблема:** Training log сортирует по `enrolled_at DESC` — последние назначения сверху. Но HR обычно хочет "in_progress → completed → assigned" чтобы видеть проблемы первыми.
**Решение:**
- Опциональная сортировка по `progress_percent` ASC (incomplete сверху)
- Toggle: "Сначала проблемные" / "Сначала новые"
- Сохранять preference в localStorage
**Файлы:**
- `apps/web/src/app/admin/training-log/page.tsx`
- `apps/api/app/modules/training_log/repository.py` (опционально — поддержать server-side sort)
**Критерии приёмки:**
- Toggle работает, preference сохраняется
- HR быстрее находит проблемных сотрудников

---

## P1.9 — `/staff` vs `/admin/staff` consolidation

**Severity:** Low
**Размер:** S
**Проблема:** `/staff` (3 строки) — re-export `/admin/staff`. Sidebar и admin dashboard ссылаются на оба. Конфликт URL.
**Решение:**
- Решить: `/staff` canonical (user-friendly) или `/admin/staff` (consistent)
- Обновить все внутренние ссылки
- Удалить redundant файл
**Файлы:**
- `apps/web/src/app/staff/page.tsx` (delete or canonicalize)
- `apps/web/src/components/layout/Sidebar.tsx`
- `apps/web/src/app/admin/page.tsx` (links)
**Критерии приёмки:**
- Один URL для staff schedule
- Все ссылки обновлены

---

## P1.10 — Invitations UI: discoverable CTA + status page

**Severity:** Medium
**Размер:** M
**Проблема (INV-1, INV-4):** Нет явной кнопки "Пригласить сотрудника" в sidebar. Статус приглашений (pending/accepted/expired/revoked) разбросан.
**Решение:**
- Добавить CTA "Пригласить сотрудника" в `/admin/team` (form: email, role, position)
- Новая страница `/admin/invitations` — список pending/recently accepted с фильтрами
- Resend CTA в строке pending invitation
- Backend уже есть (`apps/api/app/modules/users/invitations_router.py`)
**Файлы:**
- `apps/web/src/app/admin/team/page.tsx` — добавить invite form
- `apps/web/src/app/admin/invitations/page.tsx` (new)
- `apps/web/src/components/layout/Sidebar.tsx` — entry
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Тесты:**
- Integration: invite form → email → accept-invite → user created
- E2E: invite создаётся, status page показывает pending
**Критерии приёмки:**
- HR может пригласить сотрудника в 2 клика
- Status page показывает все outstanding invitations

---

## P1.11 — Certificate template preview + expiration UI

**Severity:** Medium
**Размер:** S
**Проблема (CERT-2, CERT-8):** Admin меняет logo в certificate template → save → нет preview "как это будет выглядеть". `expires_at` хранится в БД но не показывается в `/certificates`.
**Решение:**
- `/admin/certificates/settings` — добавить preview pane (рядом с form: "Вот как будет выглядеть сертификат")
- `/certificates` — показывать `expires_at` если есть, с warning "Срок действия истекает через X дней"
**Файлы:**
- `apps/web/src/app/admin/certificates/settings/page.tsx`
- `apps/web/src/app/certificates/page.tsx`
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Критерии приёмки:**
- Preview обновляется live при изменении logo/text
- Expiration дата видна на `/certificates`

---

## P1.12 — Certificate QR verification (P1.4 из roadmap)

**Severity:** Medium
**Размер:** M (требует schema для public verification)
**Проблема (CERT-1):** Verify сертификата требует ручного ввода certificate_number. Нет QR.
**Решение:**
- QR на PDF содержит signed URL `/verify/{certificate_number}` (public, no auth)
- Public endpoint `/api/v1/public/certificates/{id}/verify` (no auth required)
- Показывает: name, course, tenant, issued_at, expires_at, status (valid/revoked)
- **Важно**: PII hygiene — не показывать email/phone
**Файлы:**
- `apps/api/app/modules/certificates/router.py` (новый public endpoint)
- `apps/api/app/modules/certificates/service.py` (qr generation)
- `apps/web/src/app/verify/[id]/page.tsx` (new)
- `apps/web/src/components/admin/CertificatePdfPreview.tsx` (qrcode generation)
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Тесты:**
- Integration: public endpoint без auth, не показывает PII
- E2E: PDF имеет QR, скан открывает verify page
**Критерии приёмки:**
- QR скан → публичная страница с валидацией
- Revoked сертификат показывает "Отозван" (требует revoke endpoint — связано с P1.13)

---

## P1.13 — Revoke certificate (audit + UI)

**Severity:** Medium
**Размер:** M (требует schema + audit log)
**Проблема (CERT-3):** Нет способа отозвать сертификат. Если сотрудник уволен / обнаружен fraud — сертификат остаётся валидным.
**Решение:**
- Schema: добавить `revoked_at`, `revoked_by`, `revoked_reason` в `certificates` table (migration)
- Backend: `POST /v1/certificates/{id}/revoke` (admin only)
- Public verify page показывает "Отозван" + reason (если public)
- UI: кнопка "Отозвать" в `/certificates` (admin) или `/admin/certificates/issued`
- Audit log через `audit/service.py`
**Файлы:**
- `apps/api/alembic/versions/005X_add_certificate_revocation.py` (new)
- `apps/api/app/modules/certificates/router.py`
- `apps/api/app/modules/certificates/models.py`
- `apps/web/src/app/admin/certificates/issued/page.tsx` (или раздел в `/admin/certificates/settings`)
**Тесты:**
- Migration applies cleanly
- Integration: revoke → public verify показывает "Отозван"
**Критерии приёмки:**
- Admin может отозвать сертификат с reason
- Public verify отображает revoked status
- Audit log фиксирует кто и когда

---

## P1.14 — AI generation: parallel RU+KZ generation

**Severity:** Medium
**Размер:** L (требует async pipeline)
**Проблема (METHOD-2):** AI generation language selector — 1 язык за раз. Нет workflow "сгенерировать RU и KZ параллельно".
**Решение:**
- Multi-select в UI: [RU, KZ, EN]
- Backend: parallel async tasks (Celery)
- Каждый язык → отдельный course row с тем же `source_group_id` (FK на первый)
- Связь: "Этот курс — RU версия KZ курса #X"
- После обоих: выбрать "primary" версию для дефолтного отображения
**Файлы:**
- `apps/api/app/modules/ai/router.py` (multi-language param)
- `apps/api/app/modules/ai/service.py` (parallel generation)
- `apps/api/app/modules/courses/models.py` (source_group_id)
- `apps/api/alembic/versions/005X_add_course_source_group.py` (new)
- `apps/web/src/app/ai/generate/page.tsx` (multi-language UI)
- `apps/web/src/components/courses/CourseLanguageTabs.tsx` (new)
**Тесты:**
- Integration: 2 языка создают 2 курса с одним group_id
- E2E: переключение между языками на /courses/{id}
**Критерии приёмки:**
- HR выбирает RU+KZ, получает 2 курса за один workflow
- UI явно показывает что есть "связанные" версии

---

## P1.15 — Assign course via Rules: dry-run preview

**Severity:** Medium
**Размер:** M
**Проблема (INV-6):** Методолог пишет rule (по должности / отделу) → Apply → результат в training log post-factum. Нет preview "вот эти X человек получат этот курс".
**Решение:**
- Backend: `POST /v1/admin/staff/rules/preview` возвращает список `(user_id, full_name, position, department)` без записи
- Frontend: кнопка "Предпросмотр" перед Apply, modal со списком
- Только после подтверждения → Apply
**Файлы:**
- `apps/api/app/modules/users/staff_import_router.py` или новый module `staff_rules/router.py`
- `apps/web/src/app/admin/staff/page.tsx` (Rules tab — добавить Preview CTA)
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Тесты:**
- Integration: rule matches → preview returns expected list, no enrollment created
- Apply после preview → enrollments created для previewed users
**Критерии приёмки:**
- Методолог видит список ДО применения
- Может отменить Apply

---

## P1.16 — Kiosk access log drill-down

**Severity:** Low
**Размер:** S
**Проблема (KIOSK-4):** Admin видит access log в `/admin/kiosks` (таблица). Но не видит "этот сотрудник прошёл этот курс через этот kiosk".
**Решение:**
- Связать `kiosk_access_logs` с `kiosk_last_seen_at` в training log
- Click на строку access log → drill-down: показать employee, courses opened, completion status
- Или добавить column "последний курс" в access log
**Файлы:**
- `apps/web/src/app/admin/kiosks/page.tsx` (drill-down modal)
- `apps/api/app/modules/users/kiosk_router.py` (новый endpoint для drill-down)
**Критерии приёмки:**
- Admin может кликнуть access log → увидеть employee + course state

---

## P1.17 — Trial expiry CTA в admin dashboard

**Severity:** Medium
**Размер:** S
**Проблема (ADMIN-4, ADMIN-6):** Trial card показывает `days_left ?? 0` без чёткого "trial кончился". OnboardingChecklist trial step показывает всегда.
**Решение:**
- Trial card: если `days_left <= 7` → красный badge "Осталось мало дней"
- Если `days_left <= 0` → CTA "Обновить тариф" (placeholder route `/admin/billing`)
- Если `trial_ends_at` отсутствует → "Trial не активирован" + CTA
- OnboardingChecklist: скрыть trial step если trial истёк
**Файлы:**
- `apps/web/src/app/admin/page.tsx`
- `apps/web/src/components/admin/OnboardingChecklist.tsx`
- `apps/web/src/i18n/locales/{ru,en,kk}.json`
**Критерии приёмки:**
- Trial status ясно показан
- CTA "Обновить тариф" placeholder работает

---

## P1.18 — Position-based course recommendations UI

**Severity:** Low (зависит от AI)
**Размер:** M
**Проблема:** `positions_recommendations_router` существует в API, но не уверен что есть UI.
**Решение:**
- На `/positions` — для каждой должности показывать "Рекомендованные курсы" (по AI)
- С click-through: посмотреть курс → attach к должности
- Если рекомендации нет — placeholder "AI анализирует..."
**Файлы:**
- `apps/web/src/app/positions/page.tsx` (добавить секцию)
- (проверить есть ли уже endpoint)
**Критерии приёмки:**
- Методолог видит рекомендации на странице должности

---

## P1.19 — Accessibility: skip-to-content + screen reader audit

**Severity:** Medium
**Размер:** M
**Проблема:** `SkipLink` и `SkipToContent` компоненты есть, но не факт что на всех страницах. Не аудитирован full WCAG AA pass.
**Решение:**
- Аудит: на каждой page.tsx проверить наличие `<SkipLink />` или aria-label
- Lighthouse CI run в pipeline
- axe-core integration test
- Manual: NVDA / VoiceOver test на key flows
**Файлы:**
- Multiple page.tsx (если SkipLink пропущен)
- `apps/web/src/a11y/` (new directory для тестов)
- `.github/workflows/lighthouse.yml` (new)
**Критерии приёмки:**
- Lighthouse accessibility ≥ 90
- axe-core: 0 critical issues
- Manual screen reader test на /courses, /admin/training-log, kiosk/[token]

---

## Порядок выполнения

```
Phase 1 — Privacy & block-критикалы (1-2 недели)
  P1.1 (kiosk auto-logout)
  P1.2 (kiosk auth flow)
  P1.3 (sidebar quiz-assign)

Phase 2 — UX polish (2-3 недели)
  P1.7 (training log empty state)
  P1.8 (training log sort)
  P1.9 (URL consolidation)
  P1.10 (invitations UI)
  P1.11 (certificate template preview)
  P1.17 (trial expiry CTA)

Phase 3 — i18n pass (1-2 недели)
  P1.4 (admin i18n)
  P1.5 (kiosk print i18n)
  P1.18 (position recommendations i18n)

Phase 4 — Features (по готовности)
  P1.12 (certificate QR)
  P1.13 (revoke certificate)
  P1.14 (parallel AI generation)
  P1.15 (rule dry-run)
  P1.16 (kiosk drill-down)
  P1.6 (quiz route cleanup)
  P1.19 (accessibility audit)
```

## Что НЕ включать в P1

Согласно ТЗ и `p0_p1_product_hardening_plan.md`:
- Forums / wiki / CMS
- E-commerce / paid courses
- Live classes / virtual classroom
- SCORM 2004 / xAPI / cmi5 / LTI
- Plugin system
- Skill matrix (P1.3 в roadmap — отдельный epic)
- 2FA для superadmin (P1.5 в roadmap — отдельный epic, требует auth changes)

## Что должен сделать сильный инженер перед взятием P1.1 / P1.2

Оба требуют понимания kiosk auth flow. Рекомендую:
1. Прочитать `apps/api/app/modules/users/kiosk_router.py` целиком
2. Понять `/v1/kiosks/{token}/identify` response shape (`KioskIdentifyResponse`)
3. Проверить текущий redirect на /courses/[id] через Layout.tsx (есть ли обход)
4. Решить: kiosk_token JWT или opaque session_id

## References

- QA inventory: `docs/reports/2026-07-09_p1_product_qa_gap_inventory.md`
- Roadmap plan: `docs/plans/2026-07-09_p0_p1_product_hardening_plan.md` (P1.1-P1.6 стратегические)
- AGENTS.md — coding conventions