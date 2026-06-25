# Employee Onboarding — design doc

**Branch:** `feature/employee-onboarding` (created from master)
**Status:** Design phase — Askar's decisions integrated, awaiting final approval to start Phase 1
**Effort estimate:** ~2 weeks (4 phases, 1-4 days each)

---

## Askar's decisions (resolved 2026-06-25)

| # | Question | Decision |
|---|---|---|
| 1 | Email sending in v1? | **No SMTP.** Methodologist copies invite URL → sends manually via any channel (Slack, Telegram, WhatsApp, corp email). Messenger-native delivery (Telegram bot / WhatsApp Business) is **deferred to Phase 5** — not in this epic. |
| 2 | CSV format support? | **No CSV in Phase 1.** Just emails (paste or one-per-line). Names collected at accept-invite time. CSV support can come later if demand exists. |
| 3 | Invite expiry? | **3 days default, configurable per tenant** via `tenant_settings.invite_expiry_days` (range 1-30). |
| 4 | Default role? | **Always `student` for bulk invites.** Can't bulk-create admins/methodologists (security — single-row path only for privileged roles). |
| 5 | Re-invite behavior? | **New token, old row → `status='superseded'`.** Clean audit trail, invalidates old link. |
| 6 | Quiz attempts? | **`attempt_limit=2` default per position_quiz (configurable).** After 2 fails → locked. **Methodologist can reset** (creates fresh attempt, old ones marked `voided`). NOT admin-only — methodologist owns their department's onboarding. |

### Messenger delivery (Askar's broader insight)

Askar noted: tenants will have their own Telegram bot or WhatsApp number, and these can deliver invite links AND let employees take courses/quizzes in the messenger UI.

**Phase 1-4 scope: web only.** Invite URLs work in any messenger naturally (methodologist copies + pastes).

**Phase 5 (separate epic, post this one):** Telegram bot MVP
- Tenant connects bot via BotFather token in tenant_settings
- Bot commands: `/start <invite_token>` (replaces web /accept-invite flow), `/courses`, `/quiz`
- Same backend endpoints, just a different UI surface
- WhatsApp later (less stable API)

This is a 3-6 week epic of its own. NOT part of this design doc.

---

## Context

**Проблема:** для тенанта с 50+ сотрудниками текущий флоу онбординга — это 100+ кликов (создать каждого вручную + назначить должность вручную). Это блокер для прода.

**Что уже есть (master):**
- `POST /users` — создать одного (email, name, role, **password**)
- `POST /positions/{id}/assign/{user_id}` — назначить одного на должность + авто-enroll в курсы
- `position_quizzes` (round 5) — квиз для должности, **но не auto-assign**
- `tenant_settings` table exists (logo_url, primary_color, default_language, quiz_pass_threshold)
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
- **Срок жизни ссылки:** 3 дня (default, настраивается per-tenant через `tenant_settings.invite_expiry_days`, 1-30)

**Что это даёт:**
- Работает **прямо сейчас** без зависимостей
- Methodologist контролирует канал (особенно в КЗ: может через Kaspi-чат или Telegram вместо email)
- Не блокирует онбординг пока нет почтового провайдера
- Invite URL — просто URL, работает в любом мессенджере без интеграции

**Что в post-MVP (Phase 5+):**
- Интеграция SendGrid / AWS SES / Mailgun
- Шаблоны писем (i18n)
- Bounce-handling
- Magic-link без пароля (только email-link → войти)
- **Telegram bot** — нативный flow `/start <invite_token>` → onboarding в чате → прохождение квизов в чате (отдельный epic, 3-6 недель)

---

## Data model

### Change to existing table: `tenant_settings`

```sql
ALTER TABLE tenant_settings
    ADD COLUMN invite_expiry_days INT NOT NULL DEFAULT 3
        CHECK (invite_expiry_days BETWEEN 1 AND 30);
```

Methodologist/admin tenant может менять в `/admin/settings`. На wire это `tenant_settings.invite_expiry_days` (default 3).

### Change to existing table: `position_quizzes` (round 5)

```sql
ALTER TABLE position_quizzes
    ALTER COLUMN pass_score SET DEFAULT 80,
    -- (no schema change to attempt_limit — was already there with default 3,
    --  just bumped default to 2 conceptually via Phase 3 logic)
```

**Attempt limit logic lives in Phase 3 code**, not in `position_quizzes.attempt_limit` (which is for lesson quizzes — different schema). For onboarding quiz, count attempts via `SELECT COUNT(*) FROM onboarding_quiz_attempts WHERE user_id=? AND position_id=? AND status NOT IN ('voided')`.

### New table: `user_invitations`

```sql
CREATE TABLE user_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    email TEXT NOT NULL,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'student',
    invited_by UUID NOT NULL,  -- FK users (admin/methodologist who invited)
    token TEXT NOT NULL UNIQUE,  -- random 32-char URL-safe
    status TEXT NOT NULL DEFAULT 'pending',
        -- pending | accepted | expired | revoked | superseded
    expires_at TIMESTAMPTZ NOT NULL,  -- created_at + tenant's invite_expiry_days
    accepted_at TIMESTAMPTZ,
    superseded_by UUID,  -- FK user_invitations (if re-invited, points to newer row)
    user_id UUID,  -- FK users (set when accepted)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Only one pending invitation per (tenant, email) at a time
    -- Partial unique index allows multiple historical rows (accepted/superseded/expired)
    CONSTRAINT uq_user_invitations_pending
        UNIQUE (tenant_id, email)
        -- Note: enforced via partial index in migration, not constraint
);
CREATE UNIQUE INDEX uq_user_invitations_pending
    ON user_invitations(tenant_id, email)
    WHERE status = 'pending';
CREATE INDEX ix_user_invitations_token ON user_invitations(token);
CREATE INDEX ix_user_invitations_tenant_status ON user_invitations(tenant_id, status);
```

**Re-invite flow (вариант A):**
- Methodologist жмёт `🔄 Перепригласить` на expired/pending user
- Old row: `status='superseded'`, `superseded_by=<new row id>`
- New row: fresh token, fresh `expires_at = now + invite_expiry_days`

### New table: `onboarding_quiz_attempts`

```sql
CREATE TABLE onboarding_quiz_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,  -- FK users
    position_id UUID NOT NULL,  -- FK positions (CASCADE if position deleted)
    tenant_id UUID NOT NULL,
    quiz_snapshot JSON NOT NULL,  -- frozen copy of questions at attempt creation
    answers JSON NOT NULL DEFAULT '{}',  -- {question_id: [choice_id, ...]}
    score INT NOT NULL DEFAULT 0,  -- 0-100 percent
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress | completed | voided
    attempt_number INT NOT NULL DEFAULT 1,  -- 1 or 2 (or up to attempt_limit per position)
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    time_spent_seconds INT,
    reset_by UUID,  -- FK users (methodologist who reset attempts)
    reset_at TIMESTAMPTZ,
    reset_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_onboarding_attempts_user ON onboarding_quiz_attempts(user_id);
CREATE INDEX ix_onboarding_attempts_position ON onboarding_quiz_attempts(position_id);
CREATE INDEX ix_onboarding_attempts_tenant_status ON onboarding_quiz_attempts(tenant_id, status);
CREATE INDEX ix_onboarding_attempts_user_position_active
    ON onboarding_quiz_attempts(user_id, position_id)
    WHERE status = 'in_progress';
```

**Multiple attempts per user:**
- `attempt_number` increments per (user_id, position_id) excluding voided
- Max = 2 by default (configurable per `position_quizzes` via new column? or hardcode?)
  - **Decision:** add `max_attempts INT NOT NULL DEFAULT 2` to `position_quizzes` table (migration 0025)
- After reaching max attempts with no pass → status=`locked`, UI shows "Попытки исчерпаны. Обратитесь к методологу"

### Model changes (summary)

**Modified tables:**
- `tenant_settings`: +`invite_expiry_days` (migration 0024)
- `position_quizzes`: +`max_attempts` (migration 0025)

**New tables (migrations 0024 + 0025):**
- `user_invitations` (0024)
- `onboarding_quiz_attempts` (0025)

---

## API contracts

### Phase 1 endpoints

```
POST /api/v1/users/invitations/bulk
  Body: { items: [{email, first_name?, last_name?, role?}, ...] }  # max 200 per request
  Note: in Phase 1, first_name/last_name NOT collected at bulk time (we don't parse CSV)
        Default role='student' (security: bulk can't create privileged roles)
  Response: {
    created: [{email, invitation_id, invite_url, expires_at}],
    skipped_existing: [{email, reason: 'already_in_tenant' | 'pending_invite_exists'}],
    invalid: [{input, reason: 'invalid_email'}],
  }
  # Creates user_invitations (status=pending) + users (status=pending, no password, is_active=false)
  # invite_url = f"{settings.PUBLIC_URL}/accept-invite?token={token}"
  # where PUBLIC_URL = kml.kz base (or preview URL in staging)

GET /api/v1/users/invitations?status=pending&page=1
  # List invitations for current tenant

GET /api/v1/invitations/{token}  # public, no auth
  # Returns: {email, tenant_name, role, expires_at, valid}
  # Public endpoint — anyone with token can view invitation details

POST /api/v1/invitations/{token}/accept  # public, no auth
  Body: {first_name, last_name, password}  # first/last names collected HERE, password min 8
  Response: {user_id, tenant_id, role, access_token}  # auto-login after accept
  # Side effects:
  #   - user.first_name/last_name updated (was empty for bulk-invited users)
  #   - user.password_hash set (argon2)
  #   - user.is_active=true, status='active'
  #   - invitation.status='accepted', accepted_at=now(), user_id set
  #   - JWT issued for auto-login (returns access_token in body)

POST /api/v1/users/invitations/{invitation_id}/resend  # auth: admin or methodologist
  Body: {}  # no body needed
  Response: {invitation_id, invite_url, expires_at}
  # Side effects:
  #   - Old invitation.status='superseded', superseded_by=<new id>
  #   - New row created: fresh token, fresh expires_at = now + tenant.invite_expiry_days
  # Methodologist copies new invite_url and resends manually
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
  # For each user:
  #   1. Assign to position (existing logic from POST /positions/{id}/assign/{user_id})
  #   2. If position has is_active quiz AND assign_onboarding_quiz=true:
  #      create OnboardingQuizAttempt (Phase 3)
```

### Phase 3 endpoints

```
GET /api/v1/onboarding/quiz-attempts/me/pending
  # Auth: any user. Returns active in-progress attempt for current user, if any.
  # If user has multiple positions with active attempts → return array (rare case)
  Response: [{
    attempt_id, position_id, position_name,
    quiz: {title, questions, time_limit, pass_score, attempt_number, max_attempts}
  }]

POST /api/v1/onboarding/quiz-attempts/{attempt_id}/submit
  Body: {answers: [{question_id, selected_choice_ids}], time_spent_seconds?}
  Response: {
    attempt_id, score, passed,
    correct_count, total_count,
    per_question: [{question_id, correct_choice_ids, explanation, your_choice_ids, is_correct}],
    can_retry: bool,  # true if passed=false AND attempt_number < max_attempts
    message_ru: str,
  }
  # Side effects:
  #   - attempt.answers, score, passed, completed_at set
  #   - snapshot questions used for scoring (NOT current quiz state)

POST /api/v1/onboarding/quiz-attempts/{attempt_id}/start
  # Explicit start (for cases where we want to defer quiz loading).
  # v1: attempts are created on assign with status=in_progress and started_at=now().
  # This endpoint exists for future "save & resume" — not used in v1.

POST /api/v1/onboarding/quiz-attempts/{user_id}/{position_id}/reset  # auth: methodologist+
  Body: {reason?: str}
  Response: {new_attempt_id, voided_attempt_ids: [uuid]}
  # Side effects:
  #   - All prior non-voided attempts for (user, position) → status='voided', reset_at=now()
  #   - New attempt created: status=in_progress, attempt_number = (prior_count + 1)
  # Visible from /admin/onboarding (Phase 4) when user has status='attempts_exhausted'
```

### Phase 4 endpoints

```
GET /api/v1/admin/onboarding/overview
  # Auth: methodologist+ (sees own department) OR admin (sees whole tenant)
  Query: ?status_filter=&position_id=&page=
  Response: {
    summary: {
      invited_pending: int,        # invitation.status=pending, not accepted yet
      onboarding_in_progress: int, # accepted invite, has position, quiz not passed OR courses incomplete
      onboarding_complete: int,    # quiz passed + all required courses done
      attempts_exhausted: int,    # quiz failed and attempts >= max_attempts
      no_position: int,           # active users without position_id
    },
    rows: [{
      user_id, full_name, email,
      position_id, position_name,
      status,  # 'invited_pending' | 'onboarding_in_progress' | 'onboarding_complete' | 'attempts_exhausted' | 'no_position'
      invited_at, accepted_at,
      quiz: {status, score, passed, attempt_number, max_attempts} | null,
      courses_completed, courses_total,
    }],
  }

GET /api/v1/admin/onboarding/users/{user_id}
  # Full timeline for one user (invitations, enrollments, quiz attempts, logins)
  Response: {
    user: {...},
    timeline: [{
      event_type, timestamp, description_ru, metadata,
    }, ...],
  }
```

---

## Edge cases

| Случай | Поведение |
|---|---|
| Email уже есть в этом тенанте | Skip с reason `already_in_tenant`, возвращаем в `skipped_existing` |
| Email есть в **другом** тенанте | Skip с reason `email_taken_other_tenant` (security: don't leak) |
| Есть pending invitation для этого email | Skip с reason `pending_invite_exists` (можно resend через `/invitations/{id}/resend`) |
| Невалидный email формат | Skip с reason `invalid_email` |
| Дубли в input | Dedupe перед обработкой |
| Invite token expired (>3 дня по дефолту) | Accept возвращает 410 Gone, UI показывает «Ссылка истекла. Попросите методолога прислать новую» |
| Re-invite expired/pending | Создаёт новую запись, старая → `superseded`. Новый token. |
| Invite accepted, user потом удалён (deactivated) | Re-invite того же email создаёт новый invitation |
| User assigned to position, then position deleted | `position_id` SET NULL (existing FK), user stays but is unassigned. Quiz attempts cascade-delete. |
| User assigned, then position_quiz deactivated (`is_active=false`) | Quiz attempts остаются, новые не создаются |
| User assigned twice to same position | Skip с reason `already_assigned` |
| User assigned to position WITHOUT onboarding quiz | Phase 3 noop — просто assign + enroll, как раньше |
| User has 2 failed attempts → tries to start new attempt | 423 Locked, UI: «Попытки исчерпаны. Обратитесь к методологу для сброса» |
| Methodologist resets attempts → user logs in → sees fresh attempt | OK. New attempt_number = old_max + 1 |
| Bulk-assign с >100 user_ids | 422 error, требуется разбить на части |
| Rate limit: >5 bulk operations в минуту от одного methodologist | 429 — UI ретраит с exponential backoff |
| Accept-invite opened twice | Second time: 410 Gone «уже принят». Login вместо этого. |
| Accept-invite с weak password (<8) | 422 с указанием правил |

---

## Что НЕ делаем (deferred)

- **Email sending (SMTP / SendGrid / SES)** — отдельный epic post-MVP. v1: methodologist копирует ссылку.
- **Telegram bot / WhatsApp delivery** — Phase 5 (отдельный epic, 3-6 недель). Invite URL работает в любом мессенджере через copy-paste.
- **CSV upload** — не в v1 (только paste emails). Может быть добавлено если спрос будет.
- **Bulk deactivation** — single-row есть, bulk не критично для v1.
- **Magic link без пароля** (только email-link → войти) — post-MVP.
- **Invite analytics** (open rate, click rate) — невозможно без email-service.
- **SSO (Google/Microsoft)** — v2.0.
- **i18n** в UI/приглашениях — пока RU; KK + EN в post-MVP.
- **Email-templates engine** — вместе с SMTP-интеграцией.

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

## Открытые вопросы для Askar (Phase 1 — что ещё нужно решить)

**Уже решено (см. Askar's decisions в начале):** 1, 2, 3, 4, 5, 6.

**Новые вопросы перед стартом кода:**

1. **Frontend URL** — invite URL строится как `https://kml.kz/accept-invite?token=...`. Ок, или для staging должен быть `https://app-staging.kml.kz`? (Конфиг `PUBLIC_URL` через env)
2. **`/accept-invite` page** — должна ли быть публичной (не требует логина)? Думаю да — это весь смысл magic-link. Но тогда нельзя редиректить если уже залогинен (вдруг сотрудник зашёл с чужого устройства). Подтверди что ок.
3. **Auto-login после accept-invite** — я заложил что endpoint возвращает `access_token` и фронт автоматом логинит. Альтернатива: показываем «Пароль установлен, войдите» → логин-форма. Как лучше?
4. **JWT expiry** — сейчас какой на access_token? Должно быть разумное время (1 час? 1 день?). Это уже реализовано, нужно только убедиться что auto-login его использует.
5. **Migration 0024** — добавит `invite_expiry_days` + новую таблицу `user_invitations`. **Migration 0025** (для Phase 3) — `onboarding_quiz_attempts` + `position_quizzes.max_attempts`. Катimigration в один файл или два?
6. **UI для `/admin/settings`** — добавить поле `invite_expiry_days` туда? Или отдельная страница? Сейчас `/admin/settings` существует — посмотрю что там.

Если не возражаешь — стартую с defaults (1=kml.kz, 2=да публичная, 3=auto-login, 4=проверю что есть, 5=два файла, 6=посмотрю и предложу).
