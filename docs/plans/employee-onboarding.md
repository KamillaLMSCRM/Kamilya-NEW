# Employee Onboarding — design doc

**Branch:** `feature/employee-onboarding` (created from master)
**Status:** Design phase — no code yet, awaiting Askar's approval
**Effort estimate:** ~2 weeks (4 phases, 1-4 days each)

---

## Context

**Проблема:** для тенанта с 50+ сотрудниками текущий флоу онбординга — это 100+ кликов (создать каждого вручную + назначить должность вручную). Это блокер для прода.

**Что уже есть (master):**
- `POST /users` — создать одного (email, name, role, **password**)
- `POST /positions/{id}/assign/{user_id}` — назначить одного на должность + авто-enroll в курсы
- `position_quizzes` (round 5) — квиз для должности, **но не auto-assign**
- User model: `password_hash` is nullable → можно создать без пароля
- **Нет email-сервиса** — SMTP/SendGrid/mailgun не подключены
- **Нет magic-link / accept-invite** — пользователь не может сам задать пароль

**Что строим:** единый epic из 4 фаз, чтобы методолог мог за день принять 50 сотрудников и видеть, как они проходят онбординг.

---

## UX flow (as methodologist sees it)

### Phase 1 — Приглашение сотрудников

**Entry:** `/admin/users` → кнопка `📋 Массовое приглашение` рядом с `+ Создать пользователя`.

**Modal 1: input**
- Title: «Пригласить сотрудников»
- Big textarea (10 rows): placeholder `email1@company.kz\nemail2@company.kz\n...` или CSV-формат `email,first_name,last_name` (опционально)
- Кнопка `📁 Загрузить CSV` (file picker → парсим)
- Live-счётчик под textarea: `Распознано: 47 email-ов · 2 некорректных · 3 уже в команде`
- Кнопки: `Отмена` / `Пригласить 44 человека`

**Parsing rules:**
- Один email на строку ИЛИ email-ы через запятую/пробел
- CSV с заголовком: `email,first_name,last_name,role` (опционально)
- Trim whitespace, lowercase email
- Email regex: `^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`
- Дубли в input — dedupe

**Modal 2: results**
- «Приглашено 44, пропущено 3 (уже в команде), 2 ошибки формата»
- Список созданных с кнопкой `📋 Скопировать ссылку` для каждого (методолог шлёт ссылку в Slack/Telegram/email вручную — **v1 без автоматической отправки писем**, см. раздел Email Strategy)
- Кнопка `Готово`

### Phase 2 — Массовое назначение на должность

**Entry:** `/admin/users` → добавить чекбоксы в таблицу + toolbar с действиями.

**Selection model:**
- Чекбокс в каждой строке + чекбокс «выбрать все» в шапке
- После выбора: панель сверху `Выбрано: 12` + actions `[Назначить должность ▾] [Снять с должности] [Деактивировать]`

**Modal: assign position**
- Dropdown должностей (только текущего тенанта)
- Чекбокс `Также назначить онбординг-тест (если есть)` — auto-checked если у position есть `is_active=true` quiz, можно снять
- Кнопка `Назначить`

**Backend behavior:** тот же что у `POST /positions/{id}/assign/{user_id}`, но batch:
- Для каждого юзера: assign + auto-enroll в position courses + **Phase 3 auto-quiz** (если quiz активен)
- Возвращает per-user статус: `success | already_assigned | failed`

**Modal: results**
- «Назначено 11, уже были на этой должности 1»
- Список с per-row статусом

### Phase 3 — Auto-assign онбординг-тест (server-side)

**Trigger:** внутри `POST /positions/{id}/assign/{user_id}` (и в bulk-варианте из Phase 2):
- Если у position есть `is_active=true` onboarding quiz — создаём `OnboardingQuizAttempt` для юзера
- Snapshot квиза (frozen copy questions) на момент создания attempt → правки квиза не ломают in-progress attempts
- Кнопка/ссылка сотруднику «Пройти тест» появится в `/student` (Phase 4)

### Phase 4 — Onboarding dashboard

**Entry:** `/admin/onboarding` (новая страница) + ссылка из sidebar.

**Summary cards:**
- 👋 Приглашено, не приняли: N
- 📚 В процессе онбординга: M (приняли invite, есть активные enrollments, не прошли тест)
- ✅ Прошли онбординг полностью: K (тест passed + все required courses completed)
- ⏸ Без должности: L

**Table:**
- Фото/имя, Email, Должность, Статус (приглашение/онбординг/завершён/застрял), Дата приглашения, Дата принятия, Тест (не начат / в процессе / passed N% / failed), Действия

**Filters:** по должности, по статусу, по дате.

**Bulk actions на строке:** Resend invite, View quiz attempt, Reassign position, Deactivate.

---

## Email Strategy (важно)

**В v1.0 НЕТ автоматической отправки писем.** SMTP-сервис не подключен, и добавлять его сейчас — отдельный epic (SMTP-конфиг, шаблоны, bounce-handling, DKIM/SPF для доставляемости).

**Что делаем в v1:**
- Приглашение создаёт пользователя (status=pending, без пароля) + invite token в `user_invitations`
- Methodologist копирует ссылку `/accept-invite?token=...` и шлёт сотруднику **вручную** через любой канал (Slack, Telegram, корпоративная почта)
- Сотрудник переходит → создаёт пароль → логинится

**Что это даёт:**
- Работает **прямо сейчас** без зависимостей
- Methodologist контролирует канал (особенно в КЗ: может через Kaspi-чат вместо email)
- Не блокирует онбординг пока нет почтового провайдера

**Что в post-MVP:**
- Интеграция SendGrid / AWS SES / Mailgun
- Шаблоны писем (i18n)
- Bounce-handling
- Magic-link без пароля (только email-link → войти)

---

## Data model

### New table: `user_invitations`

```sql
CREATE TABLE user_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    email TEXT NOT NULL,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'student',
    invited_by UUID NOT NULL,  -- FK users (admin who invited)
    token TEXT NOT NULL UNIQUE,  -- random 32-char URL-safe
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | expired | revoked
    expires_at TIMESTAMPTZ NOT NULL,  -- created + 14 days
    accepted_at TIMESTAMPTZ,
    user_id UUID,  -- FK users (set when accepted)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- index for tenant lookup + email uniqueness within tenant
    UNIQUE (tenant_id, email, status) WHERE status = 'pending'
);
CREATE INDEX ix_user_invitations_token ON user_invitations(token);
CREATE INDEX ix_user_invitations_tenant_status ON user_invitations(tenant_id, status);
```

### New table: `onboarding_quiz_attempts`

```sql
CREATE TABLE onboarding_quiz_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,  -- FK users
    position_id UUID NOT NULL,  -- FK positions (for cleanup if position deleted)
    tenant_id UUID NOT NULL,
    quiz_snapshot JSON NOT NULL,  -- frozen copy of questions at attempt time
    answers JSON NOT NULL DEFAULT '{}',  -- {question_id: [choice_id, ...]}
    score INT NOT NULL DEFAULT 0,  -- 0-100 percent
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    time_spent_seconds INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, position_id)  -- one attempt per user per position (for v1; future: allow multiple)
);
CREATE INDEX ix_onboarding_attempts_user ON onboarding_quiz_attempts(user_id);
CREATE INDEX ix_onboarding_attempts_position ON onboarding_quiz_attempts(position_id);
CREATE INDEX ix_onboarding_attempts_tenant_status ON onboarding_quiz_attempts(tenant_id, passed);
```

### Model changes (minimal, backward-compatible)

**User model:**
- No new columns. Existing `password_hash` is nullable + `is_active` works.

**Position model:**
- No changes.

**No schema changes to existing tables.** All new state lives in two new tables.

---

## API contracts

### Phase 1 endpoints

```
POST /api/v1/users/invitations/bulk
  Body: { items: [{email, first_name?, last_name?, role?}, ...] }  # max 200 per request
  Response: {
    created: [{email, invitation_id, invite_url, first_name, last_name}],
    skipped_existing: [{email, reason}],
    invalid: [{input, reason}],
  }
  # Creates user_invitations + users (status=pending, no password)

GET /api/v1/users/invitations?status=pending&page=1
  # List invitations for current tenant

GET /api/v1/invitations/{token}  # public, no auth
  # Returns: {email, first_name, tenant_name, role, expires_at, valid}
  # Public endpoint — anyone with token can view

POST /api/v1/invitations/{token}/accept  # public, no auth
  Body: {password}  # min 8 chars
  Response: {user_id, tenant_id, role, access_token}  # auto-login after accept
  # Side effects: user.password_hash set, user.status='active', invitation.accepted_at set

POST /api/v1/users/invitations/{invitation_id}/resend  # auth required
  # Returns the invite_url again (for re-copying)
  # Doesn't send email — just regenerates URL with same token (or new token if expired)
```

### Phase 2 endpoints

```
POST /api/v1/positions/{position_id}/assign-bulk
  Body: {user_ids: [uuid, ...], assign_onboarding_quiz?: bool}  # max 100 per request
  Response: {
    succeeded: [{user_id, full_name, newly_enrolled_courses, quiz_attempt_id?}],
    skipped: [{user_id, full_name, reason}],
    failed: [{user_id, reason}],
  }
```

### Phase 3 endpoints (additions to existing)

```
GET /api/v1/onboarding/quiz-attempts/me/pending
  # Auth required (student/employee). Returns active attempt for current user, if any.
  Response: {attempt_id, position_id, position_name, quiz: {title, questions, time_limit, pass_score}}

POST /api/v1/onboarding/quiz-attempts/{attempt_id}/submit
  Body: {answers: [{question_id, selected_choice_ids}], time_spent_seconds?}
  Response: {attempt_id, score, passed, correct_count, total_count, per_question: [{...}]}
  # Side effects: attempt.completed_at set, score calculated from snapshot
```

### Phase 4 endpoints

```
GET /api/v1/admin/onboarding/overview
  # Auth required (admin only). Returns summary cards + table data.
  Response: {
    summary: {
      invited_pending: int,  # invitation status=pending, not accepted
      onboarding_in_progress: int,  # accepted invite, has position, quiz not passed OR courses not done
      onboarding_complete: int,  # quiz passed + all required courses done
      no_position: int,  # active users without position_id
    },
    rows: [{user_id, full_name, email, position_name, status, invited_at, accepted_at, quiz_status, courses_completed, courses_total}],
  }

GET /api/v1/admin/onboarding/users/{user_id}
  # Drill-down: full timeline for one user (invited, accepted, enrollments, quiz attempts)
```

---

## Edge cases

| Случай | Поведение |
|---|---|
| Email уже есть в этом тенанте | Skip с reason `already_in_tenant`, возвращаем в `skipped_existing` |
| Email есть в **другом** тенанте | Skip с reason `email_taken_other_tenant` (security: don't leak) |
| Невалидный email формат | Skip с reason `invalid_email` |
| Дубли в input | Dedupe перед обработкой |
| Invite token expired (>14 дней) | Resend создаёт новый token, старый остаётся в истории со status=`superseded` |
| Invite accepted, user потом удалён (deactivated) | Re-invite того же email создаёт новый invitation |
| User assigned to position, then position deleted | `position_id` SET NULL (existing FK), user stays but is unassigned |
| User assigned, then position_quiz deactivated (`is_active=false`) | Quiz attempts остаются, новые не создаются |
| User assigned twice to same position | Skip с reason `already_assigned` |
| User assigned to position WITHOUT onboarding quiz | Phase 3 noop — просто assign + enroll, как раньше |
| Bulk-assign с >100 user_ids | 422 error, требуется разбить на части |
| Rate limit: >5 bulk operations в минуту от одного админа | 429 — UI ретраит с exponential backoff |
| CSV с неизвестным role | Fail всего запроса с указанием строки (v1 не partial — проще для UX) |
| Magic link открыт дважды (replay) | Second accept: 410 Gone с message «уже принят» |

---

## Что НЕ делаем (deferred)

- **Email sending (SMTP)** — отдельный epic post-MVP. См. Email Strategy.
- **Bulk deactivation** — single-row есть, bulk не критично для v1.
- **Resend invite с новым письмом** — UI генерит ссылку, methodologist копирует.
- **Magic link без пароля** (только email-link → вход) — post-MVP.
- **Multiple quiz attempts** — v1 = 1 попытка на user+position. Если провалил → manual reset от admin.
- **Invite analytics** (open rate, click rate) — невозможно без email-service.
- **SSO (Google/Microsoft)** — v2.0.
- **i18n** в письмах/страницах — пока RU, KK + EN в post-MVP.

---

## Implementation order

| Phase | Длительность | Что | Зависит от |
|---|---|---|---|
| **1** | 3-4 дня | Bulk invitations + accept-invite flow | — |
| **2** | 2-3 дня | Bulk-assign на должность | Phase 1 (нужны user_ids) |
| **3** | 1-2 дня | Auto-quiz on assign + student quiz UI | Phase 2 + round 5 (position_quizzes) |
| **4** | 2-3 дня | Onboarding dashboard | Phase 1+2+3 (всё готово) |

**Рекомендация:** идти по порядку, не пытаться всё за один PR. Каждая фаза = отдельный commit с возможностью отката. Phase 1 → merge → Phase 2 → merge → ...

---

## Открытые вопросы для Askar (до старта Phase 1)

1. **Email sending** — ок с тем что v1 без SMTP (methodologist копирует ссылку)? Или подключаем SendGrid/Mailgun прямо сейчас?
2. **CSV format** — поддерживаем `email,first_name,last_name,role` или только emails (проще для v1)?
3. **Invite expiry** — 14 дней ок? Можно дольше/короче?
4. **Роль по умолчанию** для приглашённых — всегда `student`? Или dropdown в modal?
5. **Re-invite** — если человек не принял за 14 дней, методолог может resend? Или автоматически шлём напоминание через 7 дней (но это требует email)?
6. **Single attempt per quiz** — ок что 1 попытка? Или сразу даём attempt_limit=3?
