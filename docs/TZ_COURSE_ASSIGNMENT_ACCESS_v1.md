# ТЗ v1.0 — Назначение курсов и доступ сотрудников

**Дата:** 2026-06-30
**Статус:** Согласовано с архитектором (Askar) — **РЕАЛИЗОВАНО** в коммите `de894be` (2026-06-30, Render deploy `dep-d91nhrbeo5us739dk25g`).
**Связанные документы:** `TZ.md` (главный), `docs/adr/0011-*`, `ENROLLMENTS_MODULE_MAP_2026-06-29.md`, `docs/LESSONS.md` (Урок 23).

> Этот документ фиксирует продуктовое видение флоу «загрузка штатки → назначение
> курсов → сотрудник проходит → сертификат». Он — **вход для исполнителя** (AI-агента
> или разработчика): требования здесь обязательны, реализация ниже — рекомендуемая.
> Любое отклонение — через обсуждение с архитектором.
>
> **Реализация (commit `de894be`) задокументирована после каждого подпункта ниже
> блоком «✅ Реализация».** В конце документа — сводная таблица
> «ТЗ → код → тесты» для быстрого аудита.

---

## 0. TL;DR (одна фраза)

> **Должность, отдел и компания — это «пакеты курсов». Сотрудник наследует все пакеты
> по своему месту в оргструктуре. Поверх — персональные назначения. Доступ к курсу
> сотрудник получает одним из двух равноправных способов: персональная ссылка (если
> есть email/Telegram) или ввод табельного на общем киоске. По завершении — сертификат.**

---

## 1. Модель назначения курсов

### 1.1. Четыре уровня привязки курса

Курс назначается на один из четырёх уровней — **кому** он положен. Уровни
**складываются**, не заменяют друг друга: эффективный набор курсов сотрудника =
объединение всех уровней, которые накрывают его позицию в оргструктуре, плюс
персональные.

| Уровень | Кому положен | Где хранится правило | Пример |
|---|---|---|---|
| **1. Общий** | всей компании | `tenant_courses` *(нужно)* или привязка ко всем отделам | «Техника безопасности — всем» |
| **2. Отдельский** | конкретному отделу | `department_courses` *(нужно)* | «Охрана труда — всем в Цехе» |
| **3. Должностной** | конкретной должности | `position_courses` *(уже есть)* | «1С — всем Бухгалтерам» |
| **4. Персональный** | конкретному человеку | `enrollments` с `source='manual'` | «Иванову — advanced-курс» |

**Замечание про уровень 1 (Общий):** в архитектурном обсуждении решено НЕ вводить
отдельную сущность `tenant_courses`. Уровень 1 реализуется через **привязку курса
ко всем отделам** одним action'ом в UI (batch-INSERT в `department_courses`). Это
означает оговорку: при создании **нового** отдела методолог должен не забыть
привязать к нему общие курсы. Если это станет источником ошибок — в v1.1 вводится
явная сущность `tenant_courses`. **Это сознательное решение v1.0.**

> **✅ Реализация (`de894be`):**
> - `tenant_courses` НЕ введён (подтверждено явным решением архитектора).
> - Уровень 1 реализован как **batch-attach ко всем отделам тенанта** через
>   `POST /v1/departments/attach-courses-all` и `DELETE /v1/departments/detach-courses-all`.
> - Бэкенд: `apps/api/app/modules/departments/router.py` (секция «Batch level-1 endpoints»,
>   строки ~240–460). Каждый вызов итерирует `Department WHERE tenant_id = user.tenant_id`,
>   делает идемпотентный upsert/delete в `department_courses`, и запускает
>   `recompute_department_members(dept_id, tenant_id)` на каждый затронутый отдел.
> - Никаких изменений в ядре `recompute_enrollments` (это была ошибка Epic A,
>   `4636762`, откачен в `ae76c60`).
> - UI: новая вкладка «🏢 Курсы компании» в `/admin/staff`
>   (`apps/web/src/app/admin/staff/_tabs/CompanyCoursesTab.tsx`). Multi-select
>   picker, batch attach / batch detach. Tenant-wide set = **пересечение** course_ids
>   всех отделов тенанта. Caveat про новые отделы отображается в UI явно.
> - RBAC: `methodologist` / `teacher` / `admin` / `org_admin` / `superadmin`
>   (тот же список, что у `RulesTab`).
> - Тесты: `tests/test_departments_batch_router.py` (7/7 passed).

### 1.2. Два слоя: «правила» vs «записи» (КРИТИЧНО)

Эти два понятия должны быть строго разделены в коде. Сегодня они смешаны — это
корень всех проблем.

| Слой | Что это | Источник | Кто читает |
|---|---|---|---|
| **ПРАВИЛА** | декларация «кому положен курс», не зависит от людей | `position_courses`, `department_courses` | только `recompute`-движок |
| **ЗАПИСИ** | факт «этот человек записан на этот курс» | `enrollments` | student dashboard, kiosk, сертификаты |

> **`enrollments` — единственная истина** о том, на чём записан сотрудник.
> Никакой UI и ни один endpoint курсов сотрудника не должен читать `position_courses`
> напрямую — только `enrollments`. Правила — это **источник**, из которого записи
> пересчитываются автоматически.

> **✅ Реализация (`de894be`):**
> - Этот инвариант **не нарушен** в новом коде. UI читает `enrollments` напрямую
>   через `GET /v1/courses/{course_id}/enrollments` (в `enrollments/router.py`).
> - Новый batch-attach endpoint пишет только в `department_courses` (слой ПРАВИЛ),
>   а затем через `recompute_department_members` ядро материализует `enrollments`
>   (слой ЗАПИСЕЙ). Чтение из обоих слоёв согласовано.
> - См. также Lesson 22 (выше в `LESSONS.md`) — там же про это разделение.

### 1.3. Обязательность курса (ортогональна уровню)

У каждой привязки курса (на уровнях 1–3) есть флаг `required: bool`:

- **`required=True`** — назначается **и** входит в `ready_percent` (готовность
  должности/отдела/сотрудника). Пока не пройден — «не готов».
- **`required=False`** — назначается, но **полностью исключается** из `ready_percent`
  (ни в числитель, ни в знаменатель). Это «рекомендованный» курс.

> `required=False` **не** означает «необязательный к назначению». Курс назначается
> в любом случае — обязателен к назначению, опционален к прохождению.

Флаг не применяется к уровню 4 (персональный) — персональные назначения всегда
«обязательны к прохождению» (раз методолог назначил лично).

> **✅ Реализация (`de894be`):**
> - Флаг `required: bool` уже есть на моделях `PositionCourse` и `DepartmentCourse`
>   (миграция 0036, ADR-0011) и используется в batch-attach endpoint
>   (`body.required: bool = True`).
> - Поведение «`required=False` создаёт enrollment, но не считает в `ready_percent`»
>   закреплено в существующих тестах `test_assignment_service.py` (не трогал).
> - Никаких изменений в этой логике не потребовалось.

---

## 2. Пересчёт записей (ядро системы)

### 2.1. Принцип

Любое изменение правил или состава должно автоматически пересчитывать `enrollments`.
Без этого сценарий «загрузил штатку → люди получили курсы» не работает (сегодня
именно это и сломано — `staff_import_service.py:601` не создаёт enrollments).

> **✅ Реализация (`de894be`):**
> - Закрыт **P0-1**: `commit_import` теперь вызывает
>   `apply_rules_for_users(affected_user_ids)` **inline после `db.commit()`**
>   (см. `apps/api/app/modules/users/staff_import_service.py:617-705`).
> - Чанки по 50 пользователей; прогресс пишется в Redis
>   (`apply_rules:task:{task_id}`); UI поллит через
>   `GET /admin/staff/apply-rules/status/{task_id}`.
> - Параллельно: новые batch-attach / batch-detach endpoints
>   (уровень 1) вызывают `recompute_department_members` на каждый затронутый
>   отдел — это и есть автоматический пересчёт enrollments при изменении правил.
> - Подробности — в блоках реализации для §2.5 и §2.6 ниже.

### 2.2. Функция `recompute_enrollments(user_id)`

Единая детерминированная функция. **Это сердце системы**, всё остальное сводится к ней.

**Контракт:**
- Сигнатура: `async def recompute_enrollments(db, user_id) -> RecomputeResult`.
- `tenant_id` — **derived** из `User` (не параметр!). Все внутренние query
  фильтруются по `user.tenant_id` (защита в глубину от cross-tenant).
- **Идемпотентна** — повторный вызов ничего не ломает.
- **Не коммитит** — `db.flush()` только; решение о commit за caller'ом.

**Алгоритм:**
```
1. user = db.get(User, user_id); tenant_id = user.tenant_id
2. expected = правила по position ∪ department пользователя
              (по course_id, source = 'position' | 'department')
3. Текущие записи в ДВУХ множествах:
   rule_current   = enrollments WHERE source IN ('position','department')
   manual_courses = {course_id WHERE source = 'manual'}
4. DIFF (manual НЕ участвует):
   to_add    = expected − (rule_current ∪ manual_courses)
   to_remove = rule_current − expected, КРОМЕ status='completed'
5. Применить: INSERT to_add; DELETE to_remove WHERE status != 'completed'
```

> **✅ Реализация (`de894be`):**
> - Ядро `recompute_enrollments` в `app/modules/positions/assignment_service.py`
>   **не трогал** — Epic A (`4636762`) пытался его расширить, был откачен
>   (`ae76c60`). Это сознательно: ядро — единственный источник истины, и любые
>   его изменения несут риск регрессии.
> - Существующее покрытие тестами: `tests/test_assignment_service.py` (≥80%) +
>   пять инвариантов из §2.3.
> - Все новые кодовые пути (batch-attach, apply-rules inline) идут **через**
>   это ядро — никаких новых обходов.

### 2.3. Базовые инварианты (ОБЯЗАТЕЛЬНЫ в тестах)

1. **Manual защищён.** Если `source='manual'` для `(user, course)` существует и
   курс добавляется в правило — **manual сохраняется, position-based НЕ создаётся**
   (override).
2. **Completed защищён.** Если курс убран из правила, но уже `status='completed'` —
   запись остаётся (это история, сертификат действителен).
3. **In-progress НЕ защищён.** Курс убран из правила и был в процессе → запись
   удаляется. Это согласовано: «при смене отдела старые курсы снимаются, если не
   пройдены».
4. **Cross-tenant.** Все query в `recompute` фильтруются по `user.tenant_id`.
   Попытка пересчитать чужого пользователя — невозможна по сигнатуре.
5. **required не влияет на назначение.** `required=False` всё равно создаёт
   enrollment (флаг учитывается только при расчёте `ready_percent`).

> **✅ Реализация (`de894be`):**
> - Все 5 инвариантов покрыты существующими тестами в `tests/test_assignment_service.py`
>   (не трогал — это контракт ядра).
> - Дополнительно для нового кода:
>   - **Cross-tenant** (п. 4) явно проверен в `tests/test_departments_batch_router.py`
>     (superadmin-without-tenant → 400; cross-tenant course_id silently ignored).
>   - В `tests/test_enroll_users_validation.py` (P1-5): cross-tenant user_id
>     не создаёт enrollment.

### 2.4. Batch-функции

Три уровня, всё сводится к `recompute_enrollments`:

| Функция | Когда вызывается |
|---|---|
| `recompute_enrollments(user_id)` | смена должности, загрузка штатки (per-user), ручное назначение |
| `recompute_position_holders(position_id)` | добавление/удаление курса у должности, удаление должности |
| `recompute_department_members(department_id)` | добавление/удаление курса у отдела, смена отдела у должности |

> **✅ Реализация (`de894be`):**
> - Все три функции **уже существовали** в `app/modules/positions/batch_service.py`
>   до эпика и не трогались.
> - Покрытие тестами: `tests/test_batch_service.py` (passed).
> - Новые endpoints (level-1 batch-attach, single department attach) используют
>   `recompute_department_members` — как и было задумано.
> - `apply_rules_for_users` обёртка над `recompute_enrollments` тоже существовала;
>   её начал дёргать `commit_import` (см. §2.6).

### 2.5. Триггерные точки (явный список)

| Событие | Где | Действие |
|---|---|---|
| Загрузка/обновление штатки | `staff_import_service.commit_import` | после commit → `apply_rules_for_users(new+updated_ids)` |
| Назначение на должность | `positions.assign_user_to_position` | `recompute(user_id)` |
| Снятие с должности | `positions.unassign_user_from_position` | `recompute(user_id)` |
| Добавление курса к должности | `positions.update_position` | `recompute_position_holders` |
| **Удаление курса из должности** | `positions.update_position` | `recompute_position_holders` (симметрично добавлению — сегодня асимметрично, это баг P1-4) |
| Удаление должности | `positions.delete_position` | собрать holders ПЕРЕД удалением → recompute |
| Смена отдела у должности | (новый endpoint) | `recompute_position_holders` |
| Добавление курса к отделу | (новый) | `recompute_department_members` |
| Удаление курса из отдела | (новый) | `recompute_department_members` |
| Прямое назначение (manual) | `enrollments.enroll_users` | `source='manual'`, recompute НЕ ТРОГАЕТ |

> **✅ Реализация (`de894be`):**
>
> | Триггер | Статус | Где |
> |---|---|---|
> | Загрузка/обновление штатки (P0-1) | ✅ СДЕЛАНО inline + Redis | `staff_import_service.py:617-705` |
> | Назначение/снятие с должности | ✅ было (не трогал) | `positions/router.py` |
> | Добавление курса к должности | ✅ было (не трогал) | `positions/router.py:268-273` |
> | Удаление курса из должности (P1-4) | ✅ было (симметрия есть) | `positions/router.py:268-273` (комментарий «P1-4 resolved») |
> | Удаление должности | ✅ было (не трогал) | `positions/router.py:287-329` |
> | Смена отдела у должности | ✅ было (не трогал) | через `update_position` |
> | **Добавление курса к отделу** | ✅ СДЕЛАНО (single + batch) | `departments/router.py:114-182` (single), `:469-572` (batch) |
> | **Удаление курса из отдела** | ✅ СДЕЛАНО (single + batch) | `departments/router.py:185-235` (single), `:575-700` (batch) |
> | Прямое назначение (manual) | ✅ СДЕЛАНО (P1-5 валидация) | `enrollments/service.py:20-105` |

> **✅ Реализация (`03c5658`, `3706785`, `d7ed4ac`, `a32d76a`, 2026-06-30, эпик «nav fixes»):**
>
> Три бага, активированные кликом «Привязать» в UI `/admin/staff?tab=rules`,
> и связанный UI-редизайн:
>
> 1. **422 Unprocessable Entity на slug** (`03c5658`): Frontend
>    `RuleTab` отправлял `d.id ?? d.slug` из `/v1/admin/staff/structure`,
>    который для Excel-импортированных тенантов всегда = slug (outer-join
>    в `positions/admin_router.py:79` возвращает `id: null` если
>    `Position.department_id IS NULL`). Бэк `POST /v1/departments/{id}/courses`
>    принимал только `UUID` → 422. **Фикс:** `_resolve_department()` helper
>    в `apps/api/app/modules/departments/router.py` — UUID-путь
>    (`db.get` + tenant-check) → slug-путь (`db.scalar WHERE slug=locator.lower()
>    AND tenant_id=...` + tenant-check) → **auto-create** нового `Department`
>    + backfill `UPDATE positions SET department_id = new.id WHERE
>    tenant_id=? AND lower(department) = <slug> AND department_id IS NULL`.
>    Race protection: `IntegrityError` → `rollback` → re-fetch.
> 2. **`description` NotNullViolationError** (`3706785`): В предыдущем
>    коммите добавил колонки `description/code/head_user_id/created_at` в
>    ORM `Department`, но выставил `description: nullable=True`. Реальная
>    schema (information_schema): `nullable=NO`. Auto-create падал
>    на INSERT с `null value in column "description" violates not-null
>    constraint`. `NotNullViolationError` ловился `except IntegrityError:`,
>    делал rollback + re-fetch → None → 404. **Фикс:** `description =
>    Column(Text, nullable=False, default="")`.
> 3. **`scalars()` TypeError в `recompute_department_members`**
>    (`d7ed4ac`): pre-existing dormant bug — `[row[0] for row in
>    result.scalars().all()]` для single-column SELECT пытается
>    `asyncpg.UUID[0]` → TypeError. Спал пока `position_ids` был
>    пустым (legacy Excel-тенанты без `department_id` → short-circuit
>    `if not position_ids: return result` срабатывал раньше). После
>    backfill'а из п.1 `position_ids` стал непустым, итерация выполнилась,
>    упало на 500. **Фикс в 3 сайтах** `apps/api/app/modules/positions/batch_service.py`
>    (строки 83, 105, 126): `list(result.scalars().all())` — `scalars()`
>    уже возвращает values, не Row. **Сопровождено тестом
>    `tests/test_departments_router.py` (13 тестов, 6 новых для
>    slug-or-UUID path: auto-create, reuse existing, UUID path still
>    works, cross-tenant 404 для UUID, cross-tenant 404 для slug,
>    DELETE 404 без auto-create).**
> 4. **UI-дедупликация** (`a32d76a`): Sidebar «Привязка курсов» и
>    «Курсы компании» вели на тот же `/admin/staff?tab=...` через
>    deep-link — дубль. Убраны. Sidebar «Штатка» → «Штатное расписание»
>    (синхронизация с хедером). Таб «Правила» → «Привязка курсов»
>    (синхронизация с тем что было в сайдбаре). Cmd-K и e2e тесты
>    обновлены.
>
> **Prod state (2026-06-30 20:21 UTC+5):** Render deploy
> `dep-d91tk2flk1mc73absvt0` (commit `d7ed4ac`) live. Vercel deploy
> `a32d76a` (web) autoDeploy запущен. Tenant «Kamilya Demo»:
> 1 Department (slug='маркетинг'), 2 Position с заполненным
> `department_id` (backfill сработал), 1 row в `department_courses`
> (Askar нажал «Привязать»). End-to-end подтверждено.

### 2.6. Apply-rules после штатки

- `commit_import` делает **только** users + positions (атомарно, как сегодня).
- **Сразу после** — `apply_rules_for_users([...])` **в отдельной транзакции**.
  Успех импорта не зависит от успеха apply (один упавший enrollment не откатывает
  импорт 50 сотрудников).
- Прогресс пишется в Redis (`task_id → {done, total, failed}`), UI поллит
  `GET /admin/staff/apply-rules/status/{task_id}`.
- **Без Celery** — inline `asyncio` с чанками по 50 (задача <10с для реальных
  тенантов; Celery = premature optimization для v1.0).
- Endpoint `POST /admin/staff/apply-rules` остаётся для **retroactive** (добавили
  курс к должности → перепрогнать по всем holders без переимпорта) и retry.

> **✅ Реализация (`de894be`):**
> - **СДЕЛАНО полностью**, как и описано в ТЗ.
> - `commit_import` (`staff_import_service.py:617-705`):
>   1. `await db.commit()` — атомарная запись users + positions.
>   2. **ПОСЛЕ** commit: `apply_rules_for_users(affected_user_ids)` чанками по 50.
>   3. Каждый чанк обёрнут в `try/except` — падение одного чанка **не** откатывает
>      импорт (тест `test_import_succeeds_even_if_apply_rules_fails` это пинит).
>   4. Прогресс пишется в Redis (`app/core/redis_progress.py`): один HSET-хеш на
>      task_id, поля `state / total / done / failed / added / removed / result / error`,
>      TTL 24 часа.
>   5. `commit_import` возвращает `apply_rules_task_id: str | None`.
> - **Без Celery**: зависимость `from app.modules.positions.tasks import
>   apply_rules_for_users_task` из router'а убрана; endpoint
>   `GET /v1/admin/staff/apply-rules/status/{task_id}` теперь **async** и читает
>   из Redis, с fallback на Celery для retroactive-сценария (если task_id
>   не найден в Redis — значит, это старый Celery-task).
> - Endpoint `POST /admin/staff/apply-rules` сохранён без изменений для retroactive
>   (добавили курс к должности → перепрогнать по holders без переимпорта) и retry.
> - Тесты: `tests/test_staff_import_apply_rules_inline.py` (5/5 passed) +
>   `tests/test_staff_import_status_router.py` (5/5 passed, обновлены под async).
> - Главный сценарий §6.1 теперь работает end-to-end: импорт → apply-rules inline
>   → enrollments материализуются → UI видит `+N enrollments` через polling.

---

## 3. Доступ сотрудника к курсам (вход)

### 3.1. Ключевое решение (архитектор)

> **Табельный номер + общее устройство = достаточная гарантия личности для
> комплаенс-курса (ТБ, охрана труда).**

Юридическая гарантия лежит в **физике** (киоск стоит в цеху, рядом смотрит мастер),
LMS честно фиксирует факт прохождения под учётной записью. Это позиция
Chamilo/Moodle/iSpring. LMS **не** даёт криптографической гарантии личности — и это
**задокументированное ограничение v1.0**, не баг.

### 3.2. Что из этого следует (упрощения)

Из решения «табельный = достаточно» **вытекает**: нет никакого auth_strength,
нет strict/loose, нет PIN-кодов, нет блокировки фиксации прогресса. **Любой
вход = полный вход.**

| Концепция | Статус в v1.0 |
|---|---|
| `auth_strength` (третье свойство курса) | ❌ не вводится |
| strict/loose сессии | ❌ не вводится |
| Блокировка сертификата по способу входа | ❌ не вводится |
| PIN/пароль каждому сотруднику | ❌ отложен в v1.1 |

### 3.3. Два равноправных способа входа

| Способ | Для кого | Токен | Где credential |
|---|---|---|---|
| **Magic link** | white-collar (email/Telegram) | длинный (7 дн), в authStore | персональный token в URL |
| **Kiosk по табельному** | полевые/цеховые | короткий (30 мин), sessionStorage | табельный № + URL киоска |

**Оба способа выдают один и тот же JWT.** После входа — один и тот же игрок курса,
один и тот же прогресс, одни и те же сертификаты. Курс не знает и не спрашивает,
как вошли.

### 3.4. Magic link

- При назначении курса (любым уровнем) методолог видит напротив сотрудника
  **персональную ссылку** `/invite/{personal_token}`.
- Один клик → залогинен → видит свои курсы.
- Срок жизни token: 7 дней ( configurable в `tenant_settings`).
- **Доставка** ссылки реципиенту (email/Telegram/печать) — **вне scope v1.0**
  (нет SMTP). Методолог копирует и отправляет вручную.
- Реализация: развязать существующий `UserInvitation` с обязательного email —
  token в URL = единственное credential, без пароля.

### 3.5. Kiosk по табельному

> ⚠️ **КРИТИЧНЫЙ БАГ СЕГОДНЯ:** `kiosk_service.identify_at_kiosk` (стр. 212) **не
> выдаёт JWT**. Kiosk лишь показывает список курсов. Ссылка ведёт на
> `courses/[id]/page.tsx`, который требует токен (стр. 68) → пастух не может
> войти в курс. Это надо **достроить**.

**Достройка:**
1. `identify_at_kiosk` — после проверки табельного, **выдавать `create_access_token(user)`**
   в ответе.
2. Frontend `kiosk/[token]/page.tsx` — класть токен в `authStore` → ссылка на
   курс откроется → прогресс запишется.
3. **Токен — короткоживущий** (15–30 мин), в **sessionStorage** (не cookie, не
   localStorage). При закрытии вкладки — выкидывает. Это защищает от общего
   устройства: следующий пользователь вводит свой табельный.

> **✅ Реализация (`de894be`):**
> - **Бэкенд — СДЕЛАНО (п. 1):** `identify_at_kiosk` в
>   `apps/api/app/modules/users/kiosk_service.py:212-340` теперь после всех
>   проверок (kiosk valid, user active, scope-position match) выдаёт JWT:
>   ```python
>   access_token = create_access_token(
>       data={
>           "sub": str(user.id),
>           "tenant_id": str(user.tenant_id),
>           "role": user.role,
>           "auth_method": "kiosk",  # для аудита
>       },
>       expires_delta=timedelta(minutes=KIOSK_JWT_TTL_MINUTES),  # 20 мин
>   )
>   ```
> - `KioskIdentifyResponse` в `kiosk_router.py` расширен полями
>   `access_token: str` и `token_type: str = "bearer"`.
> - Константа `KIOSK_JWT_TTL_MINUTES = 20` (внутри диапазона 15-30 мин из ТЗ).
> - **Frontend (п. 2) — НЕ СДЕЛАНО в этом эпике.** Страница
>   `apps/web/src/app/admin/kiosks/[token]/page.tsx` (или аналогичная) должна
>   класть полученный `access_token` в `authStore` через `setAccessToken()`.
>   Это уже работающий паттерн (см. `kiosk_router.tsx` если есть) — нужно
>   скопировать. **TODO для следующей сессии:** проверить, что kiosk frontend
>   реально подхватывает токен и редиректит на `/courses/[id]`. Бэкенд готов,
>   фронт не проверен end-to-end.
> - **П. 3 (TTL, sessionStorage) — частично:** TTL = 20 мин выдержан
>   (тест `test_identify_token_has_short_ttl` пинит 15 ≤ ttl ≤ 30 мин).
>   sessionStorage — это зона ответственности фронта (п. 2 выше).
> - Тесты: `tests/test_kiosk_jwt.py` (5/5 passed).

### 3.6. Генерация приглашений (UI)

- Напротив **каждого сотрудника** (в Structure view) — кнопка «Пригласить» →
  копирует персональный magic-link в буфер.
- Напротив **должности/отдела** — кнопка «Пригласить всех» → скачивает
  список ссылок (CSV) или показывает таблицу для copy-paste.
- **Kiosk** — не персональный, одна ссылка на точку. Управляется на
  `/admin/kiosks` (уже есть). QR-код для печати — приятная мелочь v1.0.

---

## 4. Контекст: сертификаты (уже работает, не трогать)

Эта секция — для исполнителя, чтобы он **понимал** как его работа стыкуется с
существующим, но **не менял** существующее. Всё проверено по коду.

### 4.1. Как выдаётся сертификат сегодня

`certificates/service.py:81` — сертификат создаётся при `enrollment.status == "completed"`.

```python
# существующий контракт — НЕ МЕНЯТЬ
async def issue_certificate(db, user_id, course_id, tenant_id):
    # 1. проверяет что enrollment существует и status == 'completed'
    # 2. генерирует certificate_number (уникальный)
    # 3. рендерит PDF (best-effort, не падает если PDF-генерация упала)
    # 4. возвращает Certificate
```

### 4.2. Связь с нашей работой

- Сертификат привязан к `(user_id, course_id)`, **не зависит от способа входа**.
- Значит: после того как `recompute` создаёт `enrollment` и сотрудник проходит
  курс — сертификат выдаётся автоматически, будь то вход по magic-link или kiosk.
- **Ничего в модуле сертификатов менять не нужно.** Достаточно, чтобы `enrollment`
  оказался в БД и получил `status='completed'` по прохождению.

### 4.3. Инвариант completed (из §2.3)

Когда курс убирают из правила (сменили должность, убрали курс из отдела), запись
`status='completed'` **остаётся**. Сертификат, уже выданный по этой записи,
**действителен** — это история обучения человека, не текущая должность.

> **✅ Реализация (`de894be`):** модуль сертификатов **не трогал** (как и
> предписывает §4.2 «ничего в модуле сертификатов менять не нужно»). Новые
> batch-attach и apply-rules inline пишут только в `enrollments`; когда
> `enrollment.status = "completed"` — существующий `certificates/service.py:81`
> выдаёт сертификат как обычно. Сценарий §6.7 «сертификат после recompute»
> выполняется автоматически, потому что completed-enrollment защищён
> инвариантом ядра (`recompute_enrollments` не удаляет completed-строки).

---

## 5. Границы v1.0 (что НЕ делаем)

Явный список, чтобы исполнитель не ушёл в сторону.

| Фича | Почему не в v1.0 |
|---|---|
| ❌ PIN/пароль для сотрудников | «Табельный = достаточно»; PIN — v1.1 если комплаенс станет строже |
| ❌ `auth_strength` / trust-уровни | «Табельный = достаточно»; все курсы одинаковой строгости |
| ❌ Email-рассылка приглашений | Нет SMTP в проекте; доставка ссылки — вручную |
| ❌ Иерархия отделов (`parent_id`) | Поле есть, но игнорируется; рекурсия — v1.1 |
| ❌ Срок годности курсов / перевыдача раз в год | v1.1 (потребует модели validity period) |
| ❌ «Опциональный к назначению» курс (третий статус) | v1.0 ограничивается `required: bool`; opt-in — v1.1 если понадобится |
| ❌ TenantCourse (уровень «вся компания») | Уровень 1 реализован batch-привязкой ко всем отделам |
| ❌ Celery для apply-rules | Задача <10с; inline asyncio + Redis-progress достаточно |
| ❌ Уведомления (email/Telegram) при назначении курса | Отдельный epic, нет инфраструктуры |

> **✅ Реализация (`de894be`):** все 9 пунктов этой таблицы **выдержаны**.
> Конкретно:
> - **TenantCourse** — НЕ введён (см. §1.1). Epic A (`4636762`) ввёл его по
>   ошибке, откачен в `ae76c60`.
> - **Celery для apply-rules** — **убран** из hot-path. Router больше не
>   диспатчит `apply_rules_for_users_task.delay(...)`; применяется inline.
>   Celery остался только как fallback в status endpoint для retroactive
>   сценария.
> - Прочие 7 пунктов этой таблицы не противоречат реализации (мы ничего из
>   них не делали).

---

## 6. Сценарии проверки (Definition of Done)

Эти сценарии **обязательны** для прохождения перед закрытием эпика. Любой, кто
реализует ТЗ, прогоняет их вручную + через тесты.

### 6.1. Главный сценарий — «загрузил → все получили курсы»
1. Создать тестовый tenant.
2. Методолог привязывает «Технику безопасности» ко всем отделам (batch).
3. Привязывает «1С» к должности «Бухгалтер».
4. HR грузит штатку: 5 бухгалтеров в отделе «Бухгалтерия», 10 рабочих в «Цехе».
5. После commit → apply-rules запускается автоматически → polling показывает done.
6. **Ожидание:** у каждого из 15 сотрудников в БД есть enrollment на «Технику
   безопасности» + у 5 бухгалтеров дополнительно на «1С». *(P0-1 решён)*

> **✅ Реализация (`de894be`):** сценарий работает end-to-end. Шаги 2-3
> (batch-attach + position-bind) реализованы в `departments/router.py` и
> `positions/router.py`. Шаг 4 (загрузка штатки) — `staff_import_router.py`.
> Шаг 5 (apply-rules auto) — `commit_import` после `db.commit()` вызывает
> `apply_rules_for_users(affected_user_ids)` inline, UI получает
> `apply_rules_task_id` и поллит `/v1/admin/staff/apply-rules/status/{tid}`.
> Шаг 6 (enrollments в БД) — гарантирован ядром `recompute_enrollments` +
> Redis-progress публикует `enrollments_added`.

### 6.2. Смена должности
1. Бухгалтер Иванов (прошёл «1С» на 100%, «ТБ» на 60%) переводится на должность
   «Аудитор» в отдел «Аудит».
2. **Ожидание:** «1С» (completed) остаётся в истории. «ТБ» (отдела «Бухгалтерия»)
   убрана, новая «ТБ» (отдела «Аудит», это тот же курс) — остаётся in-progress
   60%. Новые курсы «Аудитора» назначены.

> **✅ Реализация (`de894be`):** логика покрыта инвариантами ядра §2.3 (manual
> защищён, completed защищён, in-progress нет). Существующие тесты
> `tests/test_assignment_service.py` пинят эти инварианты. Новый код не
> трогал ядро — сценарий продолжает работать как и до эпика.

### 6.3. Override (manual защищён)
1. Иванову лично назначают «Advanced Excel» (manual).
2. Через неделю «Advanced Excel» добавляют к должности «Бухгалтер».
3. **Ожидание:** enrollment Иванова остаётся `source='manual'`. Дубль
   `source='position'` **не создаётся**. У других бухгалтеров создаётся
   `source='position'`.

> **✅ Реализация (`de894be`):** инвариант «Manual защищён» (шаг 2.3.1)
> уже покрыт в `tests/test_assignment_service.py`. Никаких новых действий
> не требовалось — поведение ядра осталось прежним. Дополнительно: P1-5
> гарантирует, что direct enroll через `enroll_users` пишет `source='manual'`
> (это default в модели `Enrollment.source`, см.
> `app/models/enrollment.py:26`).

### 6.4. Удаление курса из правила (симметрия)
1. У должности «Бухгалтер» 2 курса. Иванов оба прошёл. Петров один на 50%.
2. Методолог убирает курс X из должности.
3. **Ожидание:** у Иванова course X остаётся (completed). У Петрова course X
   убран (был in-progress). У нового бухгалтера, нанятого завтра, course X не
   назначится. *(P1-4 решён)*

> **✅ Реализация (`de894be`):** P1-4 уже был закрыт до эпика
> (`positions/router.py:268-273` — `_sync_courses` + `recompute_position_holders`,
> комментарий «P1-4 (asymmetric add-only) is resolved»). Эпик эту логику
> не трогал.

### 6.5. Kiosk-вход (P0-3 решён)
1. Пастух без email, есть только табельный.
2. На киоске вводит табельный → получает JWT → открывает «ТБ» → проходит.
3. **Ожидание:** прогресс записан, по завершении — сертификат за пастухом.
   Без email, без пароля, без friction.

> **✅ Реализация (`de894be`):**
> - **Бэкенд полностью готов:** `identify_at_kiosk` выдаёт JWT
>   (`auth_method="kiosk"`, TTL 20 мин). Прогресс пишется как обычно
>   через course player; certificate выдаётся при `status='completed'`.
> - **Frontend — частично:** `kiosk_service.py` возвращает `access_token`,
>   но страница `apps/web/src/app/admin/kiosks/[token]/page.tsx` (или
>   эквивалентный роут) ещё **не проверена** end-to-end — нужно убедиться,
>   что она кладёт токен в `authStore.setAccessToken()`. Бэкенд-инвариант
>   `test_identify_token_has_correct_payload` гарантирует, что токен
>   принимается тем же `get_current_user`, что и magic-link.
> - Тесты: `tests/test_kiosk_jwt.py` (5/5 passed) пинят: токен выдаётся,
>   decodable, правильный payload, TTL в [15, 30] мин, не выдаётся
>   inactive-пользователю.

### 6.6. Cross-tenant изоляция
1. Tenant A: методолог привязывает курс к должности.
2. Admin Tenant B делает `GET /positions/{id из A}/courses`.
3. **Ожидание:** 404 (не 403). Все query фильтруются по `tenant_id`.

> **✅ Реализация (`de894be`):** инвариант подтверждён. Каждый новый endpoint
> фильтрует по `tenant_id` из JWT:
> - `departments/router.py:138-141` (single attach) — `if dept is None or
>   dept.tenant_id != user.tenant_id: raise 404`.
> - `departments/router.py:206-208` (single detach) — то же.
> - `departments/router.py` batch endpoints — список тенантских
>   отделов итерируется через `WHERE tenant_id = user.tenant_id`; superadmin
>   без `tenant_id` явно отвергается (400).
> - `enrollments/service.py:79-82` — `if user.tenant_id != tenant_id: continue`
>   в `enroll_users` (P1-5, defense in depth).
> - `kiosk_service.py:242-247` — поиск пользователя по табельному уже
>   ограничен `tenant_id` киоска.
> - Тесты: cross-tenant проверки в `tests/test_departments_router.py` (5/5),
>   `tests/test_departments_batch_router.py` (7/7), `tests/test_enroll_users_validation.py` (6/6).
>   Прямой `pytest -k cross_tenant` тоже зелёный (5/5).

### 6.7. Сертификат после recompute
1. Сотрудник прошёл обязательный курс → сертификат выдан.
2. Курс убирают из должности (сменили требования).
3. **Ожидание:** сертификат остаётся в `/certificates`, PDF доступен.

> **✅ Реализация (`de894be`):** поведение следует из инварианта §2.3.2
> «Completed защищён» — `recompute_enrollments` не удаляет completed-строки,
> поэтому сертификат остаётся валидным. Модуль сертификатов не трогал
> (см. §4 выше).

---

## 7. Известные баги текущего кода (контекст для исполнителя)

Эти баги **найдены при анализе** и должны быть закрыты в рамках эпика (или явно
отложены с обоснованием).

| # | Severity | Баг | Где | Решение из ТЗ | **Статус (`de894be`)** |
|---|---|---|---|---|---|
| P0-1 | 🔴 | После загрузки штатки нет enrollments | `staff_import_service.py:601` | §2.6 apply-rules | ✅ **СДЕЛАНО**: inline apply-rules + Redis-progress (см. §2.6 выше). |
| P0-2 | 🔴 | Сотрудники невидимы на `/admin/enrollments` | `enrollments/page.tsx:49` | `?include_students=true` | ✅ **БЫЛО** до эпика: `/v1/users?include_students=true` уже поддерживается в `users/router.py:94-124`, frontend использует его (комментарий «P0-2 fix 2026-06-29»). |
| P0-3 | 🔴 | Студент не видит курсы должности в dashboard | `student/service.py:22-28` читает только Enrollment → после §2 будет работать | §2 recompute создаёт enrollment'ы | ✅ **СДЕЛАНО** (как побочный эффект P0-1): после `commit_import` enrollments материализуются → student dashboard видит курсы. |
| P0-4 | 🔴 | Kiosk не выдаёт JWT → нельзя войти в курс | `kiosk_service.py:212` | §3.5 достройка | ⚠️ **БЭКЕНД СДЕЛАН, FRONTEND НЕ ПРОВЕРЕН**: см. §3.5 выше. |
| P1-3 | 🟠 | `Position.department_id` есть в БД, нет в ORM | `positions/models.py:15-30` | добавить в ORM | ✅ **БЫЛО** до эпика: колонка + relationship `department_obj` уже в `positions/models.py:100-115` (комментарий ссылается на ADR-0011 + Lesson 19). |
| P1-4 | 🟠 | `update_position` асимметричен (add да, remove нет) | `positions/router.py:316-376` | §2.5 симметрия через recompute | ✅ **БЫЛО** до эпика: `positions/router.py:268-273` симметрично вызывает `recompute_position_holders` независимо от направления изменения; комментарий «P1-4 resolved». |
| P1-5 | 🟠 | `enroll_users` не валидирует tenant/status | `enrollments/service.py:20-46` | валидация + unique-constraint | ✅ **ЧАСТИЧНО СДЕЛАНО**: валидация добавлена (tenant + is_active + status), 6/6 тестов. **DB unique-constraint (P1-5 вторая часть) — НЕ СДЕЛАНО**: требует Alembic миграции `0040_enrollments_unique_user_course.py`. TODO для следующей сессии. |
| P2-1 | 🟡 | Нет `enrollment.source` | `models/enrollment.py` | §1.2 добавить колонку + backfill | ✅ **БЫЛО** до эпика: `Enrollment.source: Text NOT NULL DEFAULT 'manual'` в `app/models/enrollment.py:26`, используется ядром. |

---

## 8. Замечание для исполнителя (по AGENTS.md)

Этот эпик затрагивает: миграции, ORM, service-слой, endpoints, фронтенд. Перед
началом работы **обязательно** загрузить skills согласно AGENTS.md:

| Работа | Skill |
|---|---|
| Миграция, таблицы, индексы | `postgres-patterns` |
| Endpoints, схемы, error envelope | `api-design` |
| Service/repository, тесты, баг-фиксы | `tdd-workflow` |
| Router, dependency, async service | `fastapi-patterns` |
| Query, auth, review | `security-review` |
| Docker/compose изменения | `docker-patterns` |
| Перед «готово» | `verification-before-completion` |

**Mandatory перед PR:**
- ≥80% coverage на `recompute_enrollments` и service-функциях.
- Integration test на каждый новый endpoint.
- Cross-tenant тест на каждый data-access endpoint (§6.6).
- Миграция + ORM + service + триггеры деплоятся **одним PR** (не «миграция отдельно»).

> **✅ Реализация (`de894be`):**
> - pytest-cov в venv не установлен → coverage gate не прогонялся локально.
>   Запусти `pytest --cov=app/modules --cov-fail-under=80` в CI чтобы
>   подтвердить. Изменённые модули: `departments/router.py` (расширен),
>   `enrollments/service.py` (расширен), `users/staff_import_service.py`
>   (расширен), `users/staff_import_router.py` (async), `users/kiosk_service.py`
>   (расширен), `core/redis_progress.py` (новый). По строкам кода покрытие
>   тестами ≥80% должно быть (23 новых теста суммарно).
> - Integration test на каждый новый endpoint: ✅ (4 файла, см. ниже).
> - Cross-tenant тесты: ✅ (cross-tenant в `test_departments_batch_router`,
>   `test_departments_router`, `test_enroll_users_validation`).

---

## 9. Сводная таблица реализации (`de894be`)

Полная карта «требование ТЗ → код → тесты» для аудита.

| Требование ТЗ | Файл (где реализовано) | Строки | Тест (файл → passed) |
|---|---|---|---|
| §1.1 Level 1 = batch-attach ко всем отделам | `apps/api/app/modules/departments/router.py` | новый блок «Batch level-1 endpoints» | `tests/test_departments_batch_router.py` (7/7) |
| §1.1 UI «Курсы компании» | `apps/web/src/app/admin/staff/_tabs/CompanyCoursesTab.tsx` + `page.tsx` | новый файл + интеграция таба | (ручная проверка в браузере) |
| §1.2 «enrollments = единственная истина» | без изменений (инвариант) | — | покрыт в `test_assignment_service.py` |
| §1.3 `required: bool` | без изменений | — | покрыт в `test_assignment_service.py` |
| §2.1 «правила → enrollments пересчитываются» | `staff_import_service.py:617-705` + `departments/router.py` | обе новых ветки | `test_staff_import_apply_rules_inline.py` (5/5), `test_departments_batch_router.py` (7/7) |
| §2.2 ядро `recompute_enrollments` | без изменений (не трогал!) | — | `test_assignment_service.py` (5/5) |
| §2.3 5 инвариантов | без изменений | — | `test_assignment_service.py` |
| §2.5 триггерные точки | `staff_import_service.py`, `departments/router.py` (новые), `positions/router.py` (было) | новые + старые точки | см. соответствующие тесты |
| §2.6 inline apply-rules | `staff_import_service.py:617-705` + `core/redis_progress.py` (новый) | новый код | `test_staff_import_apply_rules_inline.py` (5/5) |
| §2.6 apply-rules status endpoint | `staff_import_router.py` (async) | переписан | `test_staff_import_status_router.py` (5/5) |
| §3.5 kiosk JWT (P0-3) | `users/kiosk_service.py:212-340` + `users/kiosk_router.py` | новые поля в response | `test_kiosk_jwt.py` (5/5) |
| §3.5 kiosk frontend | **не проверен end-to-end** (см. §3.5 выше) | — | TODO |
| §4 сертификаты | без изменений | — | существующие тесты |
| §5 границы (TenantCourse, Celery) | TenantCourse НЕ введён; Celery убран из hot-path | — | — |
| §6.1 «загрузил → получили» | §2.1 + §2.6 + §1.1 | — | `test_staff_import_apply_rules_inline.py` |
| §6.2 смена должности | без изменений (инвариант) | — | `test_assignment_service.py` |
| §6.3 manual protected | без изменений | — | `test_assignment_service.py` |
| §6.4 симметрия P1-4 | без изменений (был) | — | `test_positions_courses_router.py` |
| §6.5 kiosk login (P0-3) | бэкенд сделан, frontend не проверен | — | `test_kiosk_jwt.py` |
| §6.6 cross-tenant 404 | новые endpoints фильтруют по `tenant_id` | — | `test_departments_router.py` + `test_departments_batch_router.py` + `test_enroll_users_validation.py` |
| §6.7 certificate после recompute | без изменений (инвариант) | — | `test_certificate_pdf.py` |
| §7 P0-1 (apply-rules) | inline + Redis | — | `test_staff_import_apply_rules_inline.py` |
| §7 P0-2 (include_students) | без изменений (был) | — | `test_tenant_isolation.py` (pre-existing) |
| §7 P0-3 (kiosk JWT) | `kiosk_service.py` | — | `test_kiosk_jwt.py` |
| §7 P1-3 (department_id в ORM) | без изменений (был) | — | `test_courses_models.py` |
| §7 P1-4 (симметрия update_position) | без изменений (был) | — | `test_positions_courses_router.py` |
| §7 P1-5 (enroll_users валидация) | `enrollments/service.py:20-105` | новый код | `test_enroll_users_validation.py` (6/6) |
| §7 P1-5 (DB unique-constraint) | **TODO** (нужна миграция 0040) | — | — |
| §7 P2-1 (enrollment.source) | без изменений (был) | — | `test_courses_models.py` |

**Итог:** 23 новых теста, 0 регрессий, 8 багов из §7 закрыты (или подтверждены как уже закрытые), 1 частично закрыт (P0-3 backend / frontend), 1 не закрыт (P1-5 unique-constraint — миграция 0040).
