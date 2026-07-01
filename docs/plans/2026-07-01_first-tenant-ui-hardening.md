# Plan: UI hardening для запуска первого тенанта — 2026-07-01

> Источник ТЗ: `docs/2026-07-01_first-tenant-ui-hardening-agent-task.md`
> Scope: Только UI-полировка. Не трогаю auth/authz/БД/deploy/секреты.

## Главные принципы

- **Не выдумываю API** — никаких новых эндпоинтов. Использую только то, что уже дёргается.
- **Не плодю новых i18n-групп** — расширяю `superadmin.*` и `users.*` (ADR указано в ТЗ как preferred).
- **Все три языка синхронно** — если добавил ключ, добавляю во `ru.json`, `en.json`, `kk.json`. Тип `TranslationKey` берётся из `ru.json`, поэтому отсутствие в ru = TS error.
- **Никаких вложенных card внутри card** (per design constraints).
- **Никаких лишних иконок** (только если естественно помогает действию).

## Что меняется

### 1. `/admin/super` (landing)
- Заголовок "Запуск первого тенанта" → `superadmin.launch.title` (i18n).
- Все 3 bullet'а → `superadmin.launch.steps.*`.
- Кнопка "Открыть тенанты" → `superadmin.launch.openTenants`.
- Дополнительно: caption под заголовком = "Когда появится первый тенант, начните с этой последовательности."

### 2. `/admin/super/tenants` (list)
- Заголовки колонок через i18n:
  - `Контакт` → `superadmin.tenants.fields.contact`
  - `Тариф / статус` → `superadmin.tenants.fields.planStatus`
  - `Триал` → `superadmin.tenants.fields.trial`
  - `Использование AI` → `superadmin.tenants.fields.aiUsage`
  - `Активность` → `superadmin.tenants.fields.activity`
  - Кнопка `Открыть` → `superadmin.tenants.open`
- Caption под `latest_lead.intent`:
  - `заявка: ${intent}` → `superadmin.tenants.source.lead`
  - `ручной режим` → `superadmin.tenants.source.manual`
- Caption под usage: `${used}/${total} курсов` → `superadmin.tenants.publishedOfTotal`
- Error state: при `fetchTenants` ошибке помимо toast-а добавить заметный inline-блок в CardContent (а не только `…` в loading). Поле состояния: `loadFailed: boolean`.
- Empty state — уже OK, только улучшу CTA: показать кнопку "Создать первого тенанта" в пустом state.
- Responsive: `overflow-x-auto` на Table-обёртке для narrow viewports.
- Search placeholder — уже i18n, ок.

### 3. `/admin/super/tenants/[id]` (detail)
- В «Панель запуска»:
  - `Контакт регистрации` → `superadmin.tenants.launch.contact`
  - `Использование триала` → `superadmin.tenants.launch.usage`
  - `Ручные действия` → `superadmin.tenants.launch.actions`
  - `Активировать paid на 30 дней` → `superadmin.tenants.launch.activatePaid` (с `{days}` interpolation)
  - `Продлить trial на 14 дней` → `superadmin.tenants.launch.extendTrial`
  - `Приостановить` → `superadmin.tenants.launch.suspend`
  - `Обновлено:` → `superadmin.tenants.launch.updatedAt`
  - `AI курс` / `ДИ курс` → `superadmin.tenants.launch.aiCourses` / `jdCourses`
  - `Обучающиеся` → `superadmin.tenants.launch.learners`
  - `Команда` → `superadmin.tenants.launch.team`
- Header:
  - `Войти как:` → `superadmin.tenants.impersonate.label`
  - Кнопка `Войти` → `superadmin.tenants.impersonate.submit`
  - Toast `Входим как ${name} (${as_role})…` → `superadmin.tenants.impersonate.entering` (с `{name}` + `{role}`)
  - `Tenant not found` → `superadmin.tenants.notFound` (i18n, не английский)
- Lead данные:
  - `телефон не указан` → `superadmin.tenants.lead.phoneMissing`
  - `telegram не указан` → `superadmin.tenants.lead.telegramMissing`
- Role selector — уже ограничен `['admin', 'org_admin', 'teacher']`, **не трогаю**.
- **Что НЕ меняю**: API-вызовы, формы, базовый layout страницы (только i18n-обвязка).

### 4. `/admin/team`
- **УЖЕ соответствует ТЗ**:
  - `ROLE_KEYS` (тут нет, но хардкод в `<option>`) = `['teacher', 'org_admin', 'admin']` (строки 167-170, 261-264)
  - `rg -n 'value="superadmin"'` ничего не найдёт — **проверю в verification**
  - Default role `'teacher'` (строка 31, 75) — ок
  - title/copy — уже про "только админы и методисты"
- **Минимальные правки**:
  - Title "Команда тенанта" уже хорош, но добавлю пометку в subtitle "Эта страница — только для системной команды тенанта" (уже есть) — оставлю как есть.
  - Title у create-modal: "Новый участник команды" — оставлю (это и есть методист/admin).
  - Подпись "Методист" в role selector — у `users.roleTeacher` уже = "Методист", проверим что отображается.
- **Verification**: `rg -n 'value="superadmin"' apps/web/src/app/admin/team/page.tsx` → 0 совпадений.

### 5. i18n
Добавляю новые ключи в `superadmin.*` (где релевантно) и `users.*`:

**`superadmin.launch` (новая подгруппа, только на landing):**
- `superadmin.launch.title`
- `superadmin.launch.subtitle`
- `superadmin.launch.openTenants`
- `superadmin.launch.steps.1` (verifyTrial)
- `superadmin.launch.steps.2` (addMethodologist)
- `superadmin.launch.steps.3` (activatePaid)

**`superadmin.tenants` (расширение):**
- `superadmin.tenants.fields.contact`
- `superadmin.tenants.fields.planStatus`
- `superadmin.tenants.fields.trial`
- `superadmin.tenants.fields.aiUsage`
- `superadmin.tenants.fields.activity`
- `superadmin.tenants.open`
- `superadmin.tenants.source.lead` (с `{intent}`)
- `superadmin.tenants.source.manual`
- `superadmin.tenants.publishedOfTotal` (с `{published}`, `{total}`)
- `superadmin.tenants.createFirst` (для empty state)
- `superadmin.tenants.notFound`
- `superadmin.tenants.impersonate.label`
- `superadmin.tenants.impersonate.submit`
- `superadmin.tenants.impersonate.entering` (с `{name}`, `{role}`)
- `superadmin.tenants.impersonate.error` (с `{error}`)
- `superadmin.tenants.launch.contact`
- `superadmin.tenants.launch.usage`
- `superadmin.tenants.launch.actions`
- `superadmin.tenants.launch.activatePaid` (с `{days}`)
- `superadmin.tenants.launch.extendTrial` (с `{days}`)
- `superadmin.tenants.launch.suspend`
- `superadmin.tenants.launch.updatedAt` (с `{date}`)
- `superadmin.tenants.launch.aiCourses`
- `superadmin.tenants.launch.jdCourses`
- `superadmin.tenants.launch.learners`
- `superadmin.tenants.launch.team`
- `superadmin.tenants.lead.phoneMissing`
- `superadmin.tenants.lead.telegramMissing`

**Без изменений (уже есть, использую):** `superadmin.tenants.title/description/search/loadError/saveOk/saveError/cancel/save/create/createTitle/noTenants/fields.*/stats.*/subscription.*/plans.*/statuses.*/roles.*/admins.*`.

**`users.*`** — ничего не добавляю, всё нужное уже есть.

## Verification (как требует ТЗ)

```powershell
cd "D:\Камиля\lms\apps\web"
npm run typecheck --if-present
npx next build
```
```powershell
cd "D:\Камиля\lms"
rg -n 'value="superadmin"|roleSuperadmin|Launch control|Trial usage|AI usage|tenant launch' apps/web/src/app/admin/super apps/web/src/app/admin/team/page.tsx
git diff --check
```

Ожидаю:
- typecheck = 0 errors (т.к. все `TranslationKey` берутся из ru.json и я их туда добавлю)
- next build = success
- grep = пусто
- diff --check = no whitespace errors

## Что не делаю (явно)

- ❌ Не трогаю backend (`apps/api/`)
- ❌ Не трогаю auth/authz/guards
- ❌ Не добавляю новых API endpoints
- ❌ Не меняю CSS-систему / Tailwind / design tokens
- ❌ Не удаляю ни одну страницу (`/admin/enrollments` особенно)
- ❌ Не использую иконки ради украшательства
- ❌ Не push'у и не deploy'ю (reviewer делает)

## Поток работы

1. ✅ Прочитал все 7 файлов в scope
2. ✅ Проверил UI-примитивы и `useT` хук
3. ✅ Добавил новые i18n-ключи в ru.json, en.json, kk.json
4. ✅ Поправил `app/admin/super/page.tsx` (landing)
5. ✅ Поправил `app/admin/super/tenants/page.tsx` (list)
6. ✅ Поправил `app/admin/super/tenants/[id]/page.tsx` (detail)
7. ✅ Поправил `app/admin/team/page.tsx` (минимальные правки — копи и валидация)
8. ✅ Verification: typecheck, build, grep, diff --check
9. ✅ Вернул summary ревьюеру

---

## Отчёт о выполнении — 2026-07-01 15:26 UTC+5

### Что сделано (всё по плану)

**§1. `/admin/super` (landing)** — карточка "Запуск первого тенанта" переведена на i18n: заголовок, subtitle, 3 bullet'а и кнопка. Внутренняя структура bullets переписана с inline-`<div>` на `<ol><li>` для семантики.

**§2. `/admin/super/tenants` (list)**:
- Заголовки колонок `contact/planStatus/trial/aiUsage/activity` добавлены в `superadmin.tenants.fields.*` (исходные `name/slug/plan/status/users/courses/created/actions` сохранены).
- Source captions (`заявка: ${intent}` / `ручной режим`) и activity captions (`создан` / `вход`) и `до {date}` перенесены в `superadmin.tenants.{source,activity,trialUntil}`.
- Кнопка `Открыть` → `superadmin.tenants.open`.
- Колонка "Использование AI": заменил хардкод `AI` / `ДИ` на `superadmin.tenants.launch.{aiCourses,jdCourses}`.
- `n/M курсов` → `superadmin.tenants.publishedOfTotal` с `{published}` + `{total}`.
- Loading state: `…` → `t('common.loading')`.
- Empty state: добавлена CTA-кнопка "Создать первого тенанта" (`superadmin.tenants.createFirst`).
- **Error state** (новое): добавлено поле `loadFailed`, при ошибке `fetchTenants` показывается inline-блок `border-destructive/30` с кнопкой `common.retry`. Toast остался как дополнительный сигнал.
- **Responsive**: таблица обёрнута в `<div className="overflow-x-auto">` для narrow viewport.

**§3. `/admin/super/tenants/[id]` (detail)**:
- Импеrsonation в header: label/submit/toast/error → `superadmin.tenants.impersonate.{label,submit,entering,error}`. Toast теперь передаёт `{name}` + `{role}` (раньше хардкод `Impersonation failed: ...` по-английски).
- Error state при загрузке: добавлен inline-блок с retry (раньше — только toast).
- "Tenant not found" (был английский!) → `superadmin.tenants.notFound`.
- "Панель запуска": все 3 секции (`contact/usage/actions`) и 4 подписи (`aiCourses/jdCourses/learners/team`) и `updatedAt {date}` и 3 кнопки (`activatePaid {days}` / `extendTrial {days}` / `suspend`) перенесены в i18n. Кнопки передают `{days}` для интерполяции.
- Lead-фолбэки: `телефон не указан` / `telegram не указан` → `superadmin.tenants.lead.{phoneMissing,telegramMissing}`.
- Loading state: `…` → `t('common.loading')`.
- **Role selector НЕ трогал** — он уже ограничен `['admin', 'org_admin', 'teacher']`, что соответствует ТЗ.

**§4. `/admin/team`**:
- `rg -n 'value="superadmin"'` → **0 совпадений** (было уже корректно). Role selector содержит только `teacher/org_admin/admin` в обоих `<select>`.
- Минимальные правки: title/subtitle/create-modal-title/validation copy → `users.teamPage.*` (10 ключей).
- Empty state padding `p-6` → `py-8 text-center` (выровнено с другими страницами).

**§5. i18n**: новые ключи добавлены **во все три файла** синхронно.

### Verification — все 4 проверки прошли

| Проверка | Результат |
|---|---|
| `npm run typecheck` (apps/web) | ✅ 0 errors |
| `npx next build` (apps/web, 35 routes) | ✅ Compiled successfully, 35/35 static pages |
| `rg -n 'value="superadmin"|roleSuperadmin|Launch control|Trial usage|AI usage|tenant launch' apps/web/src/app/admin/super apps/web/src/app/admin/team/page.tsx` | ✅ 0 matches |
| `git diff --check` | ✅ no whitespace errors |

Build warnings — все 8 — **существующие** (accept-invite, courses, dashboard, и т.д.), мои файлы новых warnings не добавили.

### Diff stat

```
apps/web/src/app/admin/super/page.tsx              |  35 ++--
apps/web/src/app/admin/super/tenants/[id]/page.tsx |  81 ++++++---
apps/web/src/app/admin/super/tenants/page.tsx      | 183 ++++++++++++---------
apps/web/src/app/admin/team/page.tsx               |  21 ++-
apps/web/src/i18n/locales/en.json                  |  75 ++++++++-
apps/web/src/i18n/locales/kk.json                  |  77 ++++++++-
apps/web/src/i18n/locales/ru.json                  |  75 ++++++++-
7 files changed, 419 insertions(+), 128 deletions(-)
```

### Что НЕ менял (явно по ТЗ "out of scope")

- ❌ Backend (`apps/api/`) — ни строчки
- ❌ Auth/authz/guards
- ❌ Migrations, schema, RLS
- ❌ `.env`, Render, Supabase, VPS docs, secrets
- ❌ Новые API endpoints
- ❌ Никаких удалённых routes (`/admin/enrollments` на месте)

### Известный нюанс (resolved)

**Self-inflicted баг**: при первом редактировании `superadmin.tenants.fields` в i18n-файлах случайно затёр 8 исходных ключей (`name/slug/plan/status/users/courses/created/actions`). `npm run typecheck` поймал это сразу (6 ошибок TS2345) — TypeScript strict-typing на `TranslationKey` сработал как defense-in-depth. Восстановил ключи в `ru.json`, `en.json`, `kk.json` одной правкой, перезапустил typecheck — 0 errors.

### Что осталось ревьюеру

1. Проверить role boundaries не ослаблены (по ТЗ checklist)
2. Проверить UI в живом браузере (визуальная регрессия)
3. Закоммитить (см. ниже proposed message), запушить, задеплоить
4. По желанию: smoke-тест на `/admin/team` (что через UI нельзя пригласить/создать `superadmin`)

### Proposed commit message

```
feat(admin): harden first-tenant UI for v1 launch (i18n + states)

Polish the superadmin flow and tenant team page for the first manual
tenant launch per docs/2026-07-01_first-tenant-ui-hardening-agent-task.md.

Changes:
- /admin/super landing card → fully i18n (superadmin.launch.*)
- /admin/super/tenants list: column headers, source/activity captions,
  loading/empty/error states, responsive overflow, "create first"
  CTA in empty state
- /admin/super/tenants/[id] detail: "Панель запуска" + impersonation
  + lead fallbacks + error state + "not found" — all i18n; loading
  text centralized via common.loading
- /admin/team: title/subtitle/modal title/validation copy →
  users.teamPage.*; empty state padding aligned with other pages
- /admin/team role selector confirmed already restricted to
  teacher/org_admin/admin (rg value="superadmin" → 0 matches)

Out of scope (intentionally not touched):
- backend, auth/authz, migrations, deploy, secrets, billing, quotas
- no new API endpoints, no routes removed

Verification:
- npm run typecheck: 0 errors
- npx next build: success (35/35 static pages)
- rg value="superadmin"|roleSuperadmin|...: 0 matches
- git diff --check: clean

Refs: docs/2026-07-01_first-tenant-ui-hardening-agent-task.md
```

