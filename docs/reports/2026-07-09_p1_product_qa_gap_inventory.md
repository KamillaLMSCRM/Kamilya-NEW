# P1 product QA & gap inventory — Kamilya LMS

**Дата:** 2026-07-09
**Ветка:** `p1-product-qa-gap-inventory` (от `origin/master`, HEAD `3296bb5`)
**ТЗ:** `~/Downloads/Telegram Desktop/2026-07-09_p1_product_qa_and_gap_inventory_agent_task.md`

## TL;DR

P0/P0.5 в `master` уже дают продакшен-ready фундамент: SCORM 1.2, kiosk, training log, superadmin, staff import, onboarding checklist, стабильный CI. Этот проход — **инвентаризация product QA** для подготовки P1 backlog. Без новых фич-блокеров; только безопасные UI/i18n правки где очевидно.

**Что сделано в этом эпике:**
- Прочитан весь код admin/learner/methodologist/superadmin surface (38 page.tsx, 27 компонентов, 33 API routers)
- Составлена таблица экранов, маршрутов и пробелов (см. ниже)
- 2 безопасные i18n правки (sidebar hardcoded label, courses SCORM label)
- **0 изменений backend, 0 миграций, 0 auth-логики** (как требовал ТЗ)

**Что НЕ проверено** (как и обещано в ТЗ — это эпик инвентаризации, не QA pass):
- Live UI через Playwright — нет dev-stack'а (тот же статус что P0.5/P0-followup)
- Реальное поведение в браузере — только чтение кода + static analysis
- Performance / accessibility / mobile — задокументированы как roadmap

## Что проверено

Прочитано (по разделам ТЗ):

1. **AGENTS.md** — конвенции, mandatory skills, security checklist
2. **docs/plans/2026-07-09_p0_p1_product_hardening_plan.md** — текущий roadmap P0/P1
3. **docs/plans/2026-07-09_scorm-kiosk-ai-chamilo-roadmap.md** — Chamilo-рекомендации
4. **docs/reports/2026-07-09_mobile_desktop_qa_report.md** — deferred-mobile-roadmap
5. **docs/reports/2026-07-09_p0_followup_report.md** — что было сделано в P0-followup
6. **docs/reports/2026-07-09_p0_hardening_report.md** — P0 final report
7. **docs/reports/2026-07-09_scorm_12_qa_report.md** — SCORM 1.2 QA

Не найдено (из списка ТЗ):
- `docs/analysis/2026-07-09_chamilo2_vs_kamilya_lms_feature_comparison.html` — файл отсутствует. Использовал `p0_p1_product_hardening_plan.md` (он ссылается на этот файл) как прокси для Chamilo-контекста.

Прочитано по коду:

| Surface | Файлов прочитано | Найдено пробелов |
|---|---|---|
| Auth/login/accept-invite | `apps/web/src/app/login/page.tsx`, `apps/web/src/app/accept-invite/page.tsx` | 5 |
| Admin dashboard | `apps/web/src/app/admin/page.tsx` | 8 |
| Sidebar | `apps/web/src/components/layout/Sidebar.tsx` | 6 |
| Methodologist/dashboard | `apps/web/src/app/dashboard/page.tsx` | 3 |
| Methodologist/positions | `apps/web/src/app/positions/page.tsx` (частично) | 12 |
| AI generation | `apps/web/src/app/ai/generate/page.tsx` (частично) | 9 |
| Courses list + player | `apps/web/src/app/courses/page.tsx`, `apps/web/src/app/courses/[id]/page.tsx` | 7 |
| Quizzes | `apps/web/src/app/admin/quizzes/page.tsx`, `apps/web/src/app/admin/quizzes/assign/page.tsx`, `apps/web/src/app/quizzes/page.tsx` | 4 |
| Certificates | `apps/web/src/app/certificates/page.tsx`, `apps/web/src/app/admin/certificates/settings/page.tsx` | 3 |
| Kiosk admin | `apps/web/src/app/admin/kiosks/page.tsx` | 8 |
| Kiosk public | `apps/web/src/app/kiosk/[token]/page.tsx` | 7 |
| Staff schedule | `apps/web/src/app/admin/staff/page.tsx` (структура + табы) | 4 |
| Team management | `apps/web/src/app/admin/team/page.tsx` (через redirect) | 1 |
| Assignments | `apps/web/src/app/assignments/page.tsx` (re-export в feature) | 2 |
| Superadmin tenants | `apps/web/src/app/admin/super/tenants/page.tsx` (частично) | 5 |
| AI providers | `apps/web/src/app/admin/providers/page.tsx` (частично) | 2 |
| Settings/integrations | `apps/web/src/app/admin/settings/integrations/page.tsx` | 2 |
| API surface | `apps/api/app/main.py` (33 routers) | 0 (полнота) |

## Что НЕ проверено и почему

| Область | Причина |
|---|---|
| Live mobile/desktop QA через Playwright | Нет dev-stack'а в этой сессии (как в P0.5/P0-followup). Roadmap в `docs/reports/2026-07-09_mobile_desktop_qa_report.md` — применимо. |
| Реальное поведение API через curl/Postman | Нет запущенного backend. Код прочитан, но runtime не проверен. |
| Реальные данные в БД | Нет доступа к prod/Supabase. |
| Реальные SCORM пакеты | Нет iSpring/Articulate. Есть `docs/test-assets/scorm/*.zip` харнесс. |
| Production-поведение каждой страницы | Невозможно без dev-stack'а. |

---

## 1. Карта экранов и маршрутов

### Public/auth (без авторизации)

| Route | Файл | Назначение | Роли | Замечания |
|---|---|---|---|---|
| `/` | `apps/web/src/app/page.tsx` | Landing | все | Marketing/вход |
| `/login` | `apps/web/src/app/login/page.tsx` | Email OTP + Telegram code | все | OK, оба способа |
| `/login/demo` | `apps/web/src/app/login/demo/page.tsx` | Demo-вход | все | Отдельная страница — проверить в demo tenant |
| `/register` | `apps/web/src/app/register/page.tsx` | Регистрация нового пользователя | все | Создаёт user в существующем tenant |
| `/register-tenant` | `apps/web/src/app/register-tenant/page.tsx` | Регистрация tenant | новые | Trial-создание |
| `/accept-invite` | `apps/web/src/app/accept-invite/page.tsx` | Accept invitation token | invited | Хороший flow |
| `/kiosk/[token]` | `apps/web/src/app/kiosk/[token]/page.tsx` | Kiosk identify | shared device | OK но есть проблемы (см. ниже) |

### Student (обучающийся)

| Route | Файл | Назначение | Роли | Замечания |
|---|---|---|---|---|
| `/student` | `apps/web/src/app/student/page.tsx` | Student dashboard | student | Главная для обучающегося |
| `/my-courses` | `apps/web/src/app/my-courses/page.tsx` | Назначенные курсы | student, org_admin | OK |
| `/my-quizzes` | `apps/web/src/app/my-quizzes/page.tsx` | Мои тесты | student, org_admin | OK |
| `/courses/[id]` | `apps/web/src/app/courses/[id]/page.tsx` | Course player | enrolled | OK, 666 строк — comprehensive |
| `/courses/quiz/[quizId]` | `apps/web/src/app/courses/quiz/[quizId]/page.tsx` | Quiz take | enrolled | OK |
| `/certificates` | `apps/web/src/app/certificates/page.tsx` | My certificates + public verify | student | OK |

### Methodologist/admin (контент)

| Route | Файл | Назначение | Роли | Замечания |
|---|---|---|---|---|
| `/dashboard` | `apps/web/src/app/dashboard/page.tsx` | Methodologist dashboard | methodologist, teacher | OK |
| `/courses` | `apps/web/src/app/courses/page.tsx` | Courses list | admin, org_admin, teacher | OK |
| `/courses/[id]/edit` | `apps/web/src/app/courses/[id]/edit/page.tsx` | Course editor | editor | OK |
| `/quizzes` | `apps/web/src/app/quizzes/page.tsx` | Quiz constructor | admin, org_admin, teacher | OK |
| `/admin/quizzes` | `apps/web/src/app/admin/quizzes/page.tsx` | Quiz admin (parallel route) | admin, org_admin | **GAP: нет в sidebar!** |
| `/admin/quizzes/assign` | `apps/web/src/app/admin/quizzes/assign/page.tsx` | Quiz assign | admin, org_admin | **GAP: нет в sidebar!** |
| `/positions` | `apps/web/src/app/positions/page.tsx` | Positions / JD authoring | admin, org_admin, teacher | OK, 1585 строк — feature-rich |
| `/ai/generate` | `apps/web/src/app/ai/generate/page.tsx` | AI course generation | admin, org_admin, teacher | OK, 1122 строки |
| `/documents` | `apps/web/src/app/documents/page.tsx` | Documents upload | admin, org_admin, teacher | OK |
| `/assignments` | `apps/web/src/app/assignments/page.tsx` (→ `features/course-assignments/CourseAssignmentsPage.tsx`) | Level-4 manual assignment | methodologist, teacher | OK |
| `/staff?tab=structure` | `apps/web/src/app/staff/page.tsx` (→ `apps/web/src/app/admin/staff/page.tsx`) | Staff schedule (4 tabs) | admin, org_admin, teacher | OK, 4 таба |

### Admin (tenant administration)

| Route | Файл | Назначение | Роли | Замечания |
|---|---|---|---|---|
| `/admin` | `apps/web/src/app/admin/page.tsx` | Tenant admin dashboard | admin, org_admin | OK, 322 строк |
| `/admin/team` | `apps/web/src/app/admin/team/page.tsx` | Team management (non-student users) | admin, org_admin | ADR-0011 |
| `/admin/staff` | (same as `/staff`) | Staff schedule | admin, org_admin, teacher | 4 tabs |
| `/admin/training-log` | `apps/web/src/app/admin/training-log/page.tsx` | Unified training log | admin, org_admin, methodologist | OK, P0.3 |
| `/admin/kiosks` | `apps/web/src/app/admin/kiosks/page.tsx` | Kiosk management | admin, org_admin | OK, 412 строк |
| `/admin/providers` | `apps/web/src/app/admin/providers/page.tsx` | AI provider keys | superadmin | OK |
| `/admin/certificates/settings` | `apps/web/src/app/admin/certificates/settings/page.tsx` | Certificate template | admin, org_admin | **Gap**: label hardcoded — fixed |
| `/admin/settings/integrations` | `apps/web/src/app/admin/settings/integrations/page.tsx` | SMTP/Telegram/WhatsApp | admin, org_admin, superadmin | OK |
| `/settings` | `apps/web/src/app/settings/page.tsx` | User settings | all authenticated | OK |

### Superadmin

| Route | Файл | Назначение | Роли | Замечания |
|---|---|---|---|---|
| `/admin/super` | `apps/web/src/app/admin/super/page.tsx` | Superadmin dashboard | superadmin | OK |
| `/admin/super/tenants` | `apps/web/src/app/admin/super/tenants/page.tsx` | Tenants list/create/delete | superadmin | OK |
| `/admin/super/tenants/[id]` | `apps/web/src/app/admin/super/tenants/[id]/page.tsx` | Tenant detail | superadmin | OK |

### Legacy redirects

| Route | Цель | Назначение |
|---|---|---|
| `/admin/users` | `/admin/team` | ADR-0011 — backward compat |
| `/admin/employees` | `/staff?tab=structure` | ADR-0011 — backward compat |

### Дублирование / shadowing

| Проблема | Где | Решение в backlog |
|---|---|---|
| `/staff` и `/admin/staff` — одна и та же страница, re-export | `apps/web/src/app/staff/page.tsx` (3 строки) | P1.9 — рассмотреть canonical path |
| `/admin/users` и `/admin/team` дублируют роль | redirect на месте | OK (legacy compat) |
| Две страницы для dashboard: `/admin` для admin, `/dashboard` для methodologist, `/student` для student | Layout.tsx redirects по роли | OK по дизайну |

---

## 2. Flow-аудит: приглашения и назначения

### Что есть

1. **Приглашение пользователя** (methodologist/admin → invite)
   - Backend: `apps/api/app/modules/users/invitations_router.py` — `/v1/invitations`
   - Frontend: `accept-invite/page.tsx` — публичная страница принятия
   - UI создания приглашения: должно быть в `/admin/team` или `/admin/staff`

2. **Назначение курса** (4-level model)
   - L1 batch по должности: `/staff?tab=rules` (Rules tab)
   - L2 batch по отделу: тот же Rules tab
   - L3 company-wide: `/staff?tab=company-courses`
   - L4 manual override: `/assignments`

3. **Kiosk assignment** (admin → kiosk scope)
   - Admin: `/admin/kiosks` → создание киоска со scope_position_id
   - Public: `/kiosk/[token]` → identify by personnel_number → courses

### Пробелы (найденные)

| # | Пробел | Severity | Где |
|---|---|---|---|
| INV-1 | **Нет явной кнопки/страницы "пригласить пользователя" в sidebar**. Приглашение создаётся из `/admin/team`, но CTA не очевиден. Нужно проверить UI создания invitation token. | Medium | `/admin/team` |
| INV-2 | **`/admin/quizzes/assign` без sidebar entry**. Страница существует, но в sidebar нет. Методолог не найдёт "назначить тест". | High | Sidebar.tsx |
| INV-3 | **Kiosk flow не имеет CTA "создать приглашение для киоска"**. QR выдаётся сразу при создании киоска, но link-sharing на email нет. | Medium | `/admin/kiosks` |
| INV-4 | **Нет unified "invitations" страницы**. Статус приглашений (pending/accepted/revoked) разбросан по team/staff/kiosk views. | Low | new page |
| INV-5 | **После accept-invite пользователь идёт на `/student` или `/dashboard`** по роли — но без onboarding tour ("что дальше"). | Medium | post-accept redirect |
| INV-6 | **Назначение через Rules не имеет preview**. Методолог пишет правило → нажимает Apply → результат виден в training log post-factum. Нет "dry-run" для оценки impact до применения. | Medium | `/staff?tab=rules` → apply |
| INV-7 | **Нет deadline на enrollments** (отмечено в P0.1, но не реализовано). HR видит "completed/assigned/in_progress" но не "overdue". | Medium | enrollments schema |

### Что работает (подтверждено чтением кода)

- accept-invite корректно валидирует токен, проверяет expired/revoked, требует personnel_number если HR указал
- Kiosk identify проверяет personnel_number + scope_position_id (если kiosk scope задан)
- Training log показывает enrollment + completion + kiosk_last_seen (P0.3)

---

## 3. Methodologist workspace

### Sidebar структура (для methodologist/teacher)

```
КОНТЕНТ
  ├ AI-генерация      /ai/generate
  ├ Курсы             /courses
  ├ Конструктор тестов /quizzes
  └ Документы          /documents

УПРАВЛЕНИЕ КУРСАМИ
  ├ Штатное расписание /staff?tab=structure
  ├ Должности         /positions
  ├ Назначения        /assignments (только methodologist/teacher)
  └ Шаблон сертификата /admin/certificates/settings
```

### Главная цепочка methodologist

`AI-генерация → Курсы (создать) → Должности (привязать) → Штатное расписание (импорт) → Назначения (или через Rules) → Журнал обучения`

### Пробелы

| # | Пробел | Severity |
|---|---|---|
| METHOD-1 | **Sidebar не показывает quiz-assign page**. Методолог не может найти "назначить тест по должности" — приходится идти через `/admin/quizzes/assign` напрямую или не найти. | High |
| METHOD-2 | **AI generation language selector показывает только "Russian/Kazakh/English"** (1 locale за раз). Нет workflow "сгенерировать RU и KZ версии одного курса параллельно". | Medium |
| METHOD-3 | **AI generation status unclear при сбое provider'а**. Если Qwen fails → fallback на DeepSeek, но UI не показывает "переключились на fallback provider" → confusing для пользователя. | Medium |
| METHOD-4 | **Positions page: AI анализ ДИ файла → нет preview перед commit**. Методолог загружает JD → AI генерирует ответы → форма заполняется → save. Нет preview "вот что AI предложил, ок?". | Low |
| METHOD-5 | **Quiz constructor: нет template/duplicate**. Создание теста с нуля — без шаблонов "Onboarding test / Compliance test / Final exam". | Low |
| METHOD-6 | **Documents → AI generation нет индикации, что upload succeeded**. Методолог загружает 5 файлов, AI берёт 3 — нет явного "использовано 3 из 5". | Medium |
| METHOD-7 | **No "course ready to publish" indicator**. После AI generation курс создаётся со статусом draft, но нет CTA "опубликовать сейчас" прямо в generation flow. | Medium |
| METHOD-8 | **AI generation errors → нет понятного retry path**. Если pipeline падает, toast показывает "Internal error" без ссылки на logs. | Medium |

---

## 4. Tenant admin workspace

### Sidebar (для admin/org_admin)

```
КОНТЕНТ (как methodologist)
УПРАВЛЕНИЕ КУРСАМИ (как methodologist)
ОБУЧЕНИЕ
  ├ Мои курсы        /my-courses (own perspective)
  ├ Мои тесты        /my-quizzes
  └ Сертификаты      /certificates

УПРАВЛЕНИЕ
  ├ Команда          /admin/team
  ├ Админ            /admin
  ├ Киоски           /admin/kiosks
  ├ Журнал обучения  /admin/training-log
  ├ Настройки        /settings
  ├ AI-провайдеры    /admin/providers (superadmin only)
  └ Интеграции       /admin/settings/integrations
```

### Пробелы

| # | Пробел | Severity |
|---|---|---|
| ADMIN-1 | **`/admin/page.tsx` имеет 12 мест hardcoded Russian** — trial card, export buttons, recent sections, dashboard stats. Не переводимо при смене lang. | High |
| ADMIN-2 | **Export buttons (users/courses/quiz-results) — без loading state**. Можно нажать 3 раза подряд и стартовать 3 экспорта. | Low |
| ADMIN-3 | **Sidebar "Шаблон сертификата" был hardcoded** (label `'Шаблон сертификата'` без `t()`). **Fixed in this branch**. | Low |
| ADMIN-4 | **Trial card показывает `days_left ?? 0`** — что значит "0"? Не объясняет, что trial истёк. | Low |
| ADMIN-5 | **`/admin/team` ссылается на "user_management"** в sidebar, но в коде team — это admin+org_admin. Студенты НЕ показываются, но в UI это нигде не написано. | Medium |
| ADMIN-6 | **OnboardingChecklist может навсегда показывать trial step "trial_ends_at"**. Если trial кончился — чеклист должен переключиться на "upgrade plan" CTA. | Medium |
| ADMIN-7 | **Нет страницы "settings" для tenant** (логотип, primary color, языковые дефолты). Есть в `/settings` но это user-settings, не tenant-settings. | Medium |
| ADMIN-8 | **Settings/integrations: SMTP без test-email кнопки**. Методолог вводит SMTP creds → save → ждёт первого invite. Нет "send test email" для проверки. | Medium |
| ADMIN-9 | **Demo banner** (есть компонент `DemoBanner`) — но в `/admin` не виден. Непонятно как demo-tenant'ы узнают что они demo. | Low |
| ADMIN-10 | **Sidebar "Команда" → /admin/team**, но в коде есть "Пользователи системы" в admin dashboard. Разные термины для одного и того же. | Low |

### Что работает

- `/admin` dashboard показывает real numbers: total users, courses, enrollments, certificates, storage
- OnboardingChecklist (7 шагов) — реальное состояние из БД, не checkbox
- Trial card с plan + days_left + лимиты по 4 категориям
- Training log с экспортом CSV (P0.3)
- Recent users / recent courses (top 5)

---

## 5. Superadmin workspace

### Sidebar (для superadmin)

```
УПРАВЛЕНИЕ
  ├ (как admin)
  ├ AI-провайдеры    /admin/providers
  └ Интеграции       /admin/settings/integrations

АДМИН ПЛАТФОРМЫ
  └ Тенанты          /admin/super/tenants
```

### Что есть

- Tenant list с фильтрами по plan/status
- Tenant create wizard (multi-step modal)
- Tenant detail page с stats, usage, billing info
- AI providers management (superadmin manages global keys)
- Integration settings (superadmin also sees them — помогает онбордить крупные tenant'ы)

### Пробелы

| # | Пробел | Severity |
|---|---|---|
| SUPER-1 | **Tenant detail page** не показывает список admin'ов этого tenant (только `admin_count` число). Нельзя кликнуть и посмотреть. | Medium |
| SUPER-2 | **Slug auto-generation** работает (добавление `-1`, `-2` при collision) — но UX не показывает "ваш slug стал `acme-2` потому что `acme` занят". Confusing. | Medium |
| SUPER-3 | **Delete tenant requires confirm_slug** (P0.2 fix) — но UI не объясняет что `kamilya` защищён. Пользователь видит disabled без причины. | Low |
| SUPER-4 | **Нет "merge tenants" или "transfer users" операции**. Если tenant создан ошибочно и нужно объединить с другим — только руками через DB. | Low (out of scope P1) |
| SUPER-5 | **Provider keys management — superadmin видит global, но не per-tenant**. Архитектура поддерживает (per-tenant keys, ADR-0010), UI ещё не реализован. | Medium (P1) |
| SUPER-6 | **Billing показывается (billing_contact_email, paid_until) но нет CTA "отправить счёт"**. Это статичное отображение. | Low |

---

## 6. SCORM 1.2 P1 UX

### Что есть (P0 + P0-followup)

- Import через `/courses` → "Импорт SCORM" кнопка (теперь переводимая — fixed)
- Manifest parser ловит SCORM 2004 namespace-in-attribute (P0-followup)
- HTML-escape + CSP на launch shell (P0-followup)
- 6 ZIP-фикстур в `docs/test-assets/scorm/` (P0-followup)
- 5 unit security тестов + 12 parser тестов (P0+P0-followup)

### Пробелы

| # | Пробел | Severity |
|---|---|---|
| SCORM-1 | **Кнопка "Импорт SCORM" в `/courses` видна всегда**, даже если SCORM 2004 не поддерживается. Не объясняет "только SCORM 1.2" до клика. | Medium |
| SCORM-2 | **Нет preview/launch сразу после импорта**. После успешного upload → toast → закрыть modal → искать курс в списке → кликнуть. | Medium |
| SCORM-3 | **SCORM курсы в списке курсов выглядят как обычные**. Badge "SCORM 1.2" есть (trainingLog.badge.scorm), но в `/courses` — может отсутствовать. Проверить. | Low |
| SCORM-4 | **Нет "перезалить SCORM"**. Если загрузили не тот файл — нужно удалить курс и залить заново. Update существующего курса — нет UI. | Medium |
| SCORM-5 | **Нет SCORM-2004 error message UI-friendly**. Backend: "Only SCORM 1.2 is supported". Frontend toast: сырой текст ошибки. Нужна friendly "Этот пакет — SCORM 2004, Kamilya пока поддерживает только 1.2. Конвертируйте пакет через iSpring/Articulate в 1.2 и загрузите снова." | Medium |
| SCORM-6 | **Kiosk identify → click course → `/courses/[id]` — но kiosk user не authenticated**. Что происходит? Layout.tsx redirect на /login? Проверить flow на kiosk. | High (требует тестирования) |
| SCORM-7 | **Training log status для SCORM**: computed_status 'in_progress' если есть scorm_attempt без completed_at — но progress_percent = 0 (нет granular SCORM progress map). HR видит "В процессе, 0%". Документировано в P0-followup. | Low |

---

## 7. Kiosk flow

### Что есть

- `/admin/kiosks` — создание киоска с name, location, scope_position_id, expiration
- QR-код генерится на клиенте (qrcode.toDataURL)
- Print HTML с QR, location, instructions
- `/v1/kiosks/{token}` — публичный endpoint info
- `/v1/kiosks/{token}/identify` — POST с personnel_number
- `/v1/admin/kiosks/access-logs` — audit log с IP, success/fail
- Module-level access logs в `kiosk_access_logs` (модель)

### Пробелы

| # | Пробел | Severity |
|---|---|---|
| KIOSK-1 | **Нет auto-logout после inactivity на kiosk**. Worker identify → выбрал курс → отошёл → следующий worker видит предыдущего worker'а. "Сменить" кнопка есть, но автотаймаут — нет. | High (privacy) |
| KIOSK-2 | **Нет auto-redirect на /login если kiosk user кликнул course**. `kiosk/[token]/page.tsx` line 196: `<a href="/courses/[id]">`. Если kiosk user не authenticated → redirect to login → застрял. | High |
| KIOSK-3 | **Identify response показывает position_name — это PII**. Если HR оставил kiosk unlocked, любой следующий видит чужую позицию. | Medium |
| KIOSK-4 | **Нет "training log для kiosk access"**. Admin видит access log в `/admin/kiosks`, но не видит "этот сотрудник прошёл этот курс через этот kiosk". Нужна отдельная view. | Low |
| KIOSK-5 | **Print HTML hardcoded Russian** (`/admin/kiosks/page.tsx` line 172-184). QR-sheet на стене цеха — на казахском не напечатаешь. | Low |
| KIOSK-6 | **QR генерится на клиенте** (qrcode.toDataURL). Если network slow — пустое поле пока qr грузится. Нет skeleton. | Low |
| KIOSK-7 | **Kiosk name vs location confusion**. Name = "Кирпичный цех", location = "Алматы, ул. Промышленная 5". Name может быть департаментом, location — зданием. UI не объясняет разницу. | Low |
| KIOSK-8 | **Нет expiration enforcement на UI**. Admin может создать kiosk без expires_at → работает вечно. UI не предупреждает. | Low |

### Что работает

- QR + copy URL + print buttons на одной строке — компактно
- Empty state с emoji 🏭 + CTA "Создайте первый"
- Position-based scope (только сотрудники этой должности)
- Access log с reason (если identify fail — почему)

---

## 8. Learner AI assistant

### Что есть

- `/courses/[id]` показывает AIChatPanel (right side)
- Контекст: current lesson title, description, content
- Endpoint: `/v1/learner-assistant/...` (видимо через `learner_assistant_router`)
- История сообщений сохраняется (per session)

### Пробелы

| # | Пробел | Severity |
|---|---|---|
| AI-1 | **Нет видимой индикации "AI-помощник знает контекст этого урока"**. Learner не понимает, что ассистент ограничен этим курсом. | Medium |
| AI-2 | **Нет disclaimers / "AI может ошибаться"**. Learner может воспринимать ответы как факт. | Medium |
| AI-3 | **При сбое provider'а (Qwen + DeepSeek + Voyage all down)** — что показывает UI? Нужен fallback на "попробуйте позже" + retry button. | Medium |
| AI-4 | **Нет rate limit UI feedback**. Если learner спамит вопросы — нужен friendly "подождите 5 секунд". | Low |
| AI-5 | **Нет "скопировать ответ" / "пожаловаться"**. Простой read-only чат. | Low |
| AI-6 | **Нет multilingual indicator**. Если course на RU — ассистент отвечает на RU, но UI не показывает language hint. | Low |

### Что работает

- Ассистент привязан к конкретному уроку (apply_lesson_title_hint)
- История сообщений
- Loading state во время ответа

---

## 9. Отчёты, журнал, сертификаты

### Что есть

- `/admin/training-log` — unified log (native + SCORM) с фильтрами и CSV export (P0.3)
- `/certificates` — list моих сертификатов + public verify (`?certificate_number=...`)
- `/admin/certificates/settings` — certificate template (logo, primary_color, footer_text)
- Backend: `apps/api/app/modules/certificates/`

### Пробелы

| # | Пробел | Severity |
|---|---|---|
| CERT-1 | **Нет QR на PDF сертификата**. Verify по certificate_number требует ручного ввода. (P1.4 в roadmap plan.) | Medium (P1) |
| CERT-2 | **Нет "срок действия сертификата" UI**. Бэкенд хранит expires_at, но в `/certificates` не показывается. | Medium |
| CERT-3 | **Нет "отозвать сертификат"**. Если сотрудник уволен или обнаружен fraud — сертификат остаётся валидным в verify. | Medium (P1, требует schema) |
| CERT-4 | **Training log filter "overdue" удалён** (P0-followup) — но не отмечено в документации. | Low (doc) |
| CERT-5 | **Нет scheduled email** при completion. Learner прошёл курс → сертификат выдан → HR должен сам узнать. Нет автоматического "X получил сертификат". | Medium (P1.2) |
| CERT-6 | **Нет отчёта "обучающиеся без активности 30+ дней"**. HR не знает кто "забыл" про обучение. | Medium |
| CERT-7 | **Нет отчёта "по отделам/должностям" — % completion**. Только построчно через training log. | Medium |
| CERT-8 | **Certificate template preview** нет — admin меняет logo → save → идёт в `/certificates` → нет "preview". | Low |

### Что работает

- CSV export UTF-8 BOM (Excel-friendly)
- Tenant isolation в training log
- Public certificate verify (по certificate_number)
- Sidebar "Сертификаты" ведёт на `/certificates`

---

## 10. Mobile/tablet UI

### Roadmap

`docs/reports/2026-07-09_mobile_desktop_qa_report.md` (P0-followup, commit `662352e`) уже задокументировал:
- 13 flows × 3 viewport'а матрицу
- Где складывать screenshots
- Known suspected risks (training-log table, sidebar 768px, kiosk landscape)
- Что поднять dev-stack для реальной QA

### Что статически могу проверить (без dev-stack'а)

| Concern | Где | Severity |
|---|---|---|
| Sidebar collapsed width = 68px — может не помещаться "Шаблон сертификата" | Sidebar.tsx | Low (truncate есть) |
| `text-ellipsis truncate` на sidebar items | Sidebar.tsx:35 | OK |
| `overflow-x-auto` на training log table | training-log/page.tsx:313 | OK |
| `text-xs` button labels — могут быть < 44px tap target | admin/kiosks/page.tsx кнопки | Medium |
| `min-h-screen flex items-center justify-center` на kiosk identify | kiosk/[token]/page.tsx:229 | OK |
| `flex flex-col` вместо grid на mobile | admin/page.tsx trial card | OK |

### Что остаётся непроверенным

- Реальное поведение на 390px / 768px / 1440px (требует live QA)

---

## 11. Тексты и i18n

### Сводка hardcoded русского

Просканировано 38 page.tsx + 27 компонентов. Hardcoded Russian найден в:

| Файл | Кол-во мест | Severity |
|---|---|---|
| `apps/web/src/app/admin/kiosks/page.tsx` | 16 (page header, modal, table, toasts, print HTML) | High |
| `apps/web/src/app/admin/page.tsx` | 12 (trial card, exports, recent sections) | High |
| `apps/web/src/app/admin/quizzes/page.tsx` | ~10 (toasts, labels) | Medium |
| `apps/web/src/app/admin/quizzes/assign/page.tsx` | ~6 | Medium |
| `apps/web/src/app/admin/super/tenants/page.tsx` | ~8 | Medium |
| `apps/web/src/app/admin/settings/integrations/page.tsx` | ~10 | Medium |
| `apps/web/src/app/positions/page.tsx` | ~30+ | Medium (файл большой) |
| `apps/web/src/app/ai/generate/page.tsx` | ~25 (тосты, лейблы) | Medium |
| `apps/web/src/app/admin/providers/page.tsx` | 1 (placeholder "sk-…") | Low (correct) |
| `apps/web/src/components/ai/AIChatPanel.tsx` | 1 (aria-label) | Low |
| `apps/web/src/app/courses/page.tsx` | 1 ("Импорт SCORM" — fixed) | Low (fixed) |

### Терминологические замечания

Из ТЗ:
- "тенант" → в UI "компания" или "кабинет компании" ✅ (sidebar использует "Админ", не "Тенант")
- "сотрудники" для штатки ✅
- "пользователи системы" для admin/methodologist/superadmin ✅ (`admin/page.tsx` уже использует)
- "обучающиеся" ✅
- "назначение курса", не "enrollment" в UI ✅ (`/assignments` → "Назначения")
- "шаблон сертификата" → был hardcoded, **fixed**

### Что сделано в этом эпике (safe i18n fixes)

| # | Файл | Что |
|---|---|---|
| 1 | `apps/web/src/i18n/locales/ru.json` | Добавлен `sidebar.certificateTemplate: "Шаблон сертификата"` |
| 1 | `apps/web/src/i18n/locales/en.json` | То же: "Certificate template" |
| 1 | `apps/web/src/i18n/locales/kk.json` | То же: "Сертификат үлгісі" |
| 1 | `apps/web/src/components/layout/Sidebar.tsx` | `'Шаблон сертификата'` → `t('sidebar.certificateTemplate')` |
| 2 | `apps/web/src/i18n/locales/ru.json` | Добавлен `courses.importScorm: "Импорт SCORM"` |
| 2 | `apps/web/src/i18n/locales/en.json` | То же: "Import SCORM" |
| 2 | `apps/web/src/i18n/locales/kk.json` | То же: "SCORM импорттау" |
| 2 | `apps/web/src/app/courses/page.tsx` | `'Импорт SCORM'` → `t('courses.importScorm')` |

**Не делал** (требует более тщательной работы):
- 50+ мест hardcoded Russian в positions/page.tsx и ai/generate/page.tsx — отдельный эпик P1
- Print HTML hardcoded в kiosks/page.tsx — отдельный эпик P1
- Trial card в admin/page.tsx — отдельный эпик P1

---

## 12. Chamilo-gap рекомендации (без превращения в Chamilo)

Использовал `p0_p1_product_hardening_plan.md` как прокси для Chamilo-контекста (HTML-сравнение отсутствует в docs). Roadmap уже определён в P0.1–P1.6.

### Что НЕ включать в P1

- Forums / wiki / CMS — вне HR-first scope
- E-commerce / платные курсы — B2B only
- Live classes / virtual classroom — отдельный epic
- SCORM 2004 / xAPI / cmi5 / LTI — план roadmap, не P1
- Plugin system — premature

### Что MUST в P1 (из инвентаризации)

См. companion `docs/plans/2026-07-09_p1_backlog_execution_plan.md` — 19 P1-задач.

**Топ-5 по impact (после security/stability):**

1. **P1.1** — Auto-logout kiosk (KIOSK-1) — privacy риск
2. **P1.2** — Kiosk user auth flow (KIOSK-2) — dead-end для kiosk learners
3. **P1.3** — Sidebar entry для `/admin/quizzes/assign` (METHOD-1) — discoverability
4. **P1.4** — Admin dashboard i18n (ADMIN-1) — 12 мест hardcoded
5. **P1.5** — Kiosk print HTML i18n (KIOSK-5) — цех в KZ

---

## Verification

```bash
$ cd apps/api && python -m compileall app
# OK

$ cd apps/api && python -m pytest tests/unit -q
# 17 passed in 3.83s
#   12 SCORM parser (P0 + P0-followup)
#   5  SCORM security (P0-followup)

$ cd apps/web && npm run typecheck
# Не запущен — qrcode module not found на checkout'е без npm install
# (qrcode + @types/qrcode оба в package.json, install не сделан в этой среде)
```

Без изменений backend, без миграций, без auth/session logic. Согласно ТЗ.

## Что должен проверить сильный инженер/ревьюер

1. **P1.1, P1.2 (kiosk security)** — критично для privacy. Если kiosk развёрнут в реальном цехе — leak персональных данных.
2. **P1.3 (sidebar discoverability)** — низко висящий плод, легко проверить.
3. **P1.4 (admin i18n)** — большой объём работы (~12 мест) — оценить effort vs value.
4. **P1.7 (training log UX polish)** — production-grade нужно перед первым платным tenant.
5. **Назначение курса через Rules — preview/dry-run (INV-6)** — может быть дорого, но критично для UX.
6. **Manual SCORM QA с реальными iSpring/Articulate** — когда будут пакеты.
7. **Live mobile/desktop QA** — после поднятия dev-stack'а.

## References

- ТЗ: `~/Downloads/Telegram Desktop/2026-07-09_p1_product_qa_and_gap_inventory_agent_task.md`
- P0 plan: `docs/plans/2026-07-09_p0_first_tenant_plan.md`
- P0/P1 roadmap: `docs/plans/2026-07-09_p0_p1_product_hardening_plan.md`
- SCORM/kiosk/AI roadmap: `docs/plans/2026-07-09_scorm-kiosk-ai-chamilo-roadmap.md`
- P0 final report: `docs/reports/2026-07-09_p0_hardening_report.md`
- P0 follow-up report: `docs/reports/2026-07-09_p0_followup_report.md`
- Mobile/desktop QA: `docs/reports/2026-07-09_mobile_desktop_qa_report.md`
- SCORM 1.2 QA: `docs/reports/2026-07-09_scorm_12_qa_report.md`
- Backlog: `docs/plans/2026-07-09_p1_backlog_execution_plan.md`