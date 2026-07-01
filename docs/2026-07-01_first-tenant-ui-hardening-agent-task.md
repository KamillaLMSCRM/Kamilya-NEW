# ТЗ: UI-доработка запуска первого тенанта для младшего агента - 2026-07-01

## Контекст

Kamilya LMS готовится к запуску первого реального тенанта в полуручном режиме. В commit `7647295` уже усилены границы ролей и добавлены операционные данные для суперадмина:

- роли команды тенанта ограничены `teacher`, `admin`, `org_admin`;
- платформенный `superadmin` должен оставаться ролью без `tenant_id` и не должен создаваться из tenant UI;
- ответы superadmin tenant API теперь содержат billing contact, последнюю заявку регистрации, usage counters и stats;
- в superadmin UI уже добавлены начальные launch controls, но интерфейс ещё нужно привести в аккуратный, понятный и проверяемый вид.

Эта задача ограничена UI-полировкой, состояниями и текстами. Нельзя менять auth, authz, схему БД, billing logic, quota enforcement, deployment, секреты, Render, Supabase или VPS.

## Цель

Сделать flow оператора для первого тенанта визуально понятным и сложным для ошибочного использования:

1. Суперадмин видит список тенантов и быстро понимает: кто зарегистрировался, какой trial/status, что использовано, была ли активность и какое следующее действие.
2. Суперадмин открывает одного тенанта и видит цельную панель запуска: контакт, trial usage, plan/status, ручные действия, админы/методисты.
3. Tenant admin видит `/admin/team` как системную команду тенанта, а не как страницу обучающихся/сотрудников.
4. В UI есть понятные loading, empty и error states. Нет дублей смыслов, нет смешения русского/английского в основной русской админке, нет случайной возможности выбрать `superadmin`.

## Файлы в Scope

Основные файлы:

- `apps/web/src/app/admin/super/page.tsx`
- `apps/web/src/app/admin/super/tenants/page.tsx`
- `apps/web/src/app/admin/super/tenants/[id]/page.tsx`
- `apps/web/src/app/admin/team/page.tsx`
- `apps/web/src/i18n/locales/ru.json`
- `apps/web/src/i18n/locales/en.json`
- `apps/web/src/i18n/locales/kk.json`

Опциональная документация:

- `docs/plans/2026-07-01_first-tenant-prod-ui-blockers.md`
- этот файл, если нужно оставить статусные заметки

## Строго вне Scope

Не редактировать:

- backend auth/authz logic;
- `apps/api/app/modules/users/service.py`;
- `apps/api/app/modules/admin/superadmin/*`;
- migrations;
- `.env`, `.env.*`, Render, Supabase, VPS docs или секреты;
- tenant registration, OTP, invite acceptance, payment, quota enforcement.

Не удалять страницы и routes. В частности, не удалять `/admin/enrollments` в этой задаче.

## Что нужно сделать

### 1. Superadmin landing: `/admin/super`

Улучшить checklist card запуска так, чтобы это была операционная точка входа, а не декоративная карточка.

Требования:

- заголовок карточки на русском;
- пункты checklist короткие и конкретные;
- основное действие ведёт на `/admin/super/tenants`;
- нет сырого текста API endpoints;
- нет смешанных английских слов вроде `launch`, `tenant`, `paid` в видимой русской админке, если это не техническое поле.

Acceptance:

- страница собирается без TypeScript errors;
- новые API calls не добавлены;
- карточка за один взгляд объясняет первую последовательность действий оператора.

### 2. Tenant list: `/admin/super/tenants`

Довести читаемость таблицы и states.

Требования:

- на desktop должны остаться полезные колонки: tenant, contact, plan/status, trial, users, AI/ДИ usage, activity, action;
- длинные email/slug не ломают layout;
- loading state не выглядит как пустой результат;
- empty state объясняет, что тенантов пока нет, и показывает действие создания;
- error state видимый и не схлопывает таблицу без объяснения;
- search field имеет понятный placeholder на русском;
- plan/status labels используют i18n, если ключи уже есть;
- нет hardcoded English words в видимой русской админке.

Acceptance:

- на странице нет role control для `superadmin`;
- таблица не ломает обычную desktop ширину;
- narrow/mobile viewport остаётся usable через responsive wrapping или table overflow container;
- `npm run typecheck --if-present` проходит.

### 3. Tenant detail: `/admin/super/tenants/[id]`

Сделать detail page понятной для полуручного запуска.

Требования:

- верхняя часть страницы отвечает: кто tenant, кто зарегистрировался, какой текущий status, что уже использовано, что оператору делать дальше;
- `Панель запуска` не выглядит оторванной от остальной страницы;
- ручные кнопки имеют однозначные русские labels;
- destructive action остаётся визуально отдельным;
- отсутствующие lead/contact/usage данные отображаются аккуратно через `—` или понятный fallback;
- секция участников использует смысл `админы и методисты`, а не только `админы`;
- role selector не позволяет выбрать `superadmin`;
- если создаётся методист, copy не должно намекать, что это платформенный admin.

Acceptance:

- через эту страницу нельзя пригласить, создать или повысить пользователя до `superadmin`;
- `teacher` отображается как `Методист` в русской UI;
- loading/error states понятны;
- существующие create/edit/deactivate/impersonate flows не сломаны.

### 4. Tenant team: `/admin/team`

Сделать tenant admin team page однозначной.

Требования:

- title/copy ясно говорят, что это только системная команда тенанта;
- обучающиеся/сотрудники/штат направляются в staff/import/invitations, а не смешиваются с team;
- create modal и role selector показывают только `teacher`, `org_admin`, `admin`;
- label для `teacher` - `Методист`;
- убрать или переписать любой copy, где кажется, что `superadmin` принадлежит тенанту.

Acceptance:

- `rg -n 'value="superadmin"' apps/web/src/app/admin/team/page.tsx` ничего не находит;
- empty state таблицы понятен;
- create button и modal copy соответствуют назначению страницы.

### 5. i18n cleanup

Перенести новые видимые labels в locale files там, где это практично.

Минимум:

- русские строки основной operator UI согласованы;
- English/Kazakh files не ломают runtime/type access;
- в новых правках нет очевидного mojibake.

Предпочтительно:

- добавлять ключи в существующие группы `superadmin.*` и `users.*`, а не создавать случайные top-level группы.

## Design constraints

Следовать существующему стилю приложения. Это operational SaaS/admin tool:

- плотный, читаемый, спокойный UI;
- без marketing hero и декоративных больших визуалов;
- без nested cards;
- cards только для реальных repeated items, modals или framed tools;
- не использовать огромную типографику внутри admin panels;
- buttons компактные и явно action-oriented;
- длинный текст не должен сдвигать layout;
- использовать существующие UI primitives из `@/components/ui`;
- `lucide-react` icons использовать только если иконка естественно помогает действию; не добавлять иконки ради украшения.

## Проверки перед сдачей

Исполнитель должен запустить и приложить результаты:

```powershell
cd "C:\Kamilya New\Kamilya-NEW\apps\web"
npm run typecheck --if-present
npx next build
```

Также:

```powershell
cd "C:\Kamilya New\Kamilya-NEW"
rg -n 'value="superadmin"|roleSuperadmin|Launch control|Trial usage|AI usage|tenant launch' apps/web/src/app/admin/super apps/web/src/app/admin/team/page.tsx
git diff --check
```

Ожидаемый результат:

- typecheck проходит;
- Next build проходит;
- grep не показывает legacy English/operator labels или tenant team `superadmin` option;
- `git diff --check` без whitespace errors.

## Что вернуть на review

Младший агент должен вернуть:

1. краткое summary изменённого UI behavior;
2. список изменённых файлов;
3. точные verification commands и results;
4. screenshots, если делалась browser/UI verification;
5. явную заметку, что он намеренно не менял.

Не push и не deploy. Reviewer проверит, протестирует, закоммитит, запушит и задеплоит, если работа принята.

## Checklist ревьюера

Reviewer должен проверить:

- role boundaries не ослаблены;
- backend/security/env/deploy files не тронуты;
- UI не возвращает tenant-scoped `superadmin`;
- русский operator flow понятен;
- нет дублей и конфликтов между admin/team/staff concepts;
- первого tenant можно базово вести полуручно без прямого DB access;
- build output содержит только известные старые warnings или явно приемлемые новые warnings.
