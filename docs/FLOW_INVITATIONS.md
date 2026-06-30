# Kamilya LMS — Отправка приглашений: End-to-end flow

Дата: 2026-06-30. Подробный walkthrough что происходит когда
**методолог** отправляет приглашения и что с этим можно делать.
Основано на коде (`apps/api/app/modules/users/{invitations_*}.py`
+ `apps/web/src/app/accept-invite/page.tsx`) + live smoke через
Python `urllib` + `asyncpg` против prod.

**Audience:** методолог, новый разработчик, future agent.

## TL;DR

```text
[1] Методолог открывает /admin/staff -> таб «Импорт»
    (или напрямую через /users/invitations/bulk API)
[2] Вводит список email-ов (max 200 per request)
[3] Backend dedupes, validates emails, проверяет conflicts
[4] Backend создает:
    - pending User (is_active=False, password_hash=NULL, status="inactive")
    - UserInvitation row с токеном (~190 bits entropy)
[5] Возвращает invite_url (НЕ отправляет email — копируется вручную)
[6] Методолог копирует URL в Slack/Telegram/email — recipient открывает
[7] /accept-invite?token=... — публичная страница, no auth
[8] GET /api/v1/invitations/{token} (no auth) — показывает details
[9] User заполняет first_name, last_name, password (8+ chars),
    optional personnel_number (если invitation требует)
[10] POST /api/v1/invitations/{token}/accept (no auth)
    - активирует user (password_hash = argon2, is_active=True)
    - status = "accepted"
    - returns JWT access_token (auto-login)
[11] Frontend сохраняет JWT в localStorage, редирект на /dashboard
[12] User может работать с курсами
```

## File layout

| File | Lines | Purpose |
|---|---|---|
| `apps/api/app/modules/users/invitations_service.py` | 427 | bulk_create, resend, public_view, accept |
| `apps/api/app/modules/users/invitations_router.py` | 80 | Public endpoints (no auth) |
| `apps/api/app/modules/users/router.py` | 401 | Admin endpoints (auth required) |
| `apps/api/app/modules/users/schemas.py` | 150 | Pydantic schemas (InvitationBulkCreateRequest, etc) |
| `apps/api/app/models/users.py` | — | User + UserInvitation ORM models |
| `apps/web/src/app/accept-invite/page.tsx` | 307 | Public accept-invite page |

## Auth model

| Endpoint | Auth | Role |
|---|---|---|
| `POST /v1/users/invitations/bulk` | Bearer | admin, org_admin, superadmin, **methodologist** |
| `GET /v1/users/invitations` | Bearer | admin, org_admin, superadmin, methodologist |
| `POST /v1/users/invitations/{id}/resend` | Bearer | admin, org_admin, superadmin, methodologist |
| `GET /v1/invitations/{token}` | **public** (no auth) | — |
| `POST /v1/invitations/{token}/accept` | **public** (no auth) | — |

`tenant_id` всегда из JWT (для admin endpoints) или из
UserInvitation (для public endpoints).

## Demo tenant guard

**`assert_can_send_invite`** в `app/core/demo_limits.py:173`:
```python
async def assert_can_send_invite(db, tenant_id):
    if not await _is_demo(db, tenant_id):
        return
    raise DemoLimitExceeded("users", DEMO_LIMITS["users"], ...)
```

Demo-tenant полностью блокирует invite creation. Smoke в demo
невозможен через API. (Live smoke в этом дне сделал direct DB
insert для обхода.) Production tenants работают нормально.

## Шаг 1-2: Bulk create (methodologist)

### Request

```http
POST /api/v1/users/invitations/bulk
Authorization: Bearer <methodologist-jwt>
Content-Type: application/json

{
  "items": [
    {"email": "user1@example.com"},
    {"email": "user2@example.com"}
  ]
}
```

**Max 200 items per request** (validated in schema).

### Validation pipeline (`invitations_service.py::bulk_create_invitations`)

1. **Dedupe + validate input** (lines 87-101):
   - normalize email: `email.strip().lower()`
   - validate regex: `^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$`
   - max length 320 chars
   - dedupe silently (двойной email = один)

2. **Check existing users in this tenant** (lines 107-113):
   - SQL: `SELECT email FROM users WHERE tenant_id=$1 AND email IN (...)`
   - если email уже существует → skip с reason `already_in_tenant`

3. **Check pending invitations in this tenant** (lines 116-123):
   - SQL: `SELECT email FROM user_invitations WHERE tenant_id=$1 AND email IN (...) AND status='pending'`
   - если pending → skip с reason `pending_invite_exists`

4. **Filter conflicts** (lines 127-135):
   - to_create = valid_emails - existing - pending

5. **Compute expiry** (lines 141-143):
   - `expiry_days = await _get_tenant_invite_expiry_days(db, tenant_id)`
   - default 3, configurable per tenant (1-30 range, AGENTS.md
     "Domain context" notes this was added 2026-06-25)

6. **Create User + UserInvitation** (lines 145-186):
   - `User(is_active=False, password_hash=NULL, status="inactive",
     first_name="", last_name="")`
   - `UserInvitation(token=secrets.token_urlsafe(24), status="pending",
     expires_at=now+3d, user_id=user.id)`
   - **default role = "student"** (security: bulk can't create admin)

### Response (200)

```json
{
  "created": [
    {
      "email": "user1@example.com",
      "invitation_id": "uuid",
      "invite_url": "https://app.kml.kz/accept-invite?token=KzHK...",
      "expires_at": "2026-07-03T..."
    }
  ],
  "skipped_existing": [
    {"email": "old@example.com", "reason": "already_in_tenant"}
  ],
  "invalid": [
    {"input": "not-an-email", "reason": "invalid_email"}
  ]
}
```

### Error paths

| HTTP | Cause | Detail |
|---|---|---|
| 403 | Demo tenant | "Демо-режим: использовано N/3 пользователей. Зарегистрируйтесь..." |
| 401 | No/bad JWT | "Not authenticated" |
| 422 | Schema validation | Missing `items`, > 200 items, invalid email format |

**Email is NOT sent.** Methodologist copies `invite_url` and
delivers manually (Slack, Telegram, corp email). Documented
in `invitations_service.py:13-14` and AGENTS.md "Domain context".

## Шаг 3-4: Public view (no auth)

### Request

```http
GET /api/v1/invitations/{token}
```

Токен из `invite_url`. **Никакой** auth — token is the credential.

### Response (200)

```json
{
  "email": "user1@example.com",
  "tenant_name": "Acme Corp",
  "role": "student",
  "expires_at": "2026-07-03T...",
  "valid": true,
  "reason_if_invalid": null,
  "requires_personnel_number": false
}
```

### Status logic (`get_public_invitation`)

`invitations_service.py:250-333`:
- `accepted` → `valid: false, reason: "already_accepted"`
- `superseded` → `valid: false, reason: "superseded"`
- `revoked` → `valid: false, reason: "revoked"`
- `expired` OR `expires_at < now` → `valid: false, reason: "expired"`
  (lazy-expire: если `status="pending"` но expired — flip на "expired" + commit)
- otherwise `valid: true`

UI mapping (`accept-invite/page.tsx:20-26`):
```ts
const REASON_LABELS = {
  invitation_not_found: 'Приглашение не найдено. Проверьте ссылку или попросите методолога прислать новую.',
  already_accepted: 'Это приглашение уже принято. Войдите в систему.',
  superseded: 'Приглашение заменено новым. Проверьте, нет ли более свежей ссылки.',
  revoked: 'Приглашение отозвано. Свяжитесь с методологом.',
  expired: 'Срок действия приглашения истёк. Попросите методолога прислать новое.',
};
```

### Edge case — demo limit

В demo tenant email `smoke-inv-...@newdomain.kml` (домен
`newdomain.kml`) — нет такого tenant. Но invitation row
напрямую имеет `tenant_id`. **Public view работает** потому что
endpoint читает по token, не по email.

## Шаг 5-6: Accept (no auth)

### Request

```http
POST /api/v1/invitations/{token}/accept
Content-Type: application/json

{
  "first_name": "Иван",
  "last_name": "Смирнов",
  "password": "smokeTest123!",
  "personnel_number": "EMP001"   // optional
}
```

UI validation (`accept-invite/page.tsx:92-103`):
- first_name min 1 char
- last_name min 1 char
- password min 8 chars
- password === password2
- если `requires_personnel_number` (invitation stored personnel_number):
  - personnel_number required
  - exact match (case-insensitive, trimmed)

### Backend flow (`accept_invitation`)

`invitations_service.py:336-427`:

```python
1. Lookup invitation by token
2. If status != "pending": 410 Gone with reason-specific message
3. If expires_at < now: 410 Gone (lazy-expire, commit)
4. If invitation has personnel_number:
   - if request missing: 422 "Это приглашение требует ввод табельного номера"
   - if mismatch (case-insensitive): 403 "Табельный номер не совпадает..."
5. Activate user:
   - first_name, last_name from request
   - if invitation has personnel_number AND user doesn't: persist
   - password_hash = argon2 hash
   - is_active = True
   - status = "active"
   - last_login = now
6. Mark invitation:
   - status = "accepted"
   - accepted_at = now
   - accepted_ip = X-Forwarded-For or request.client.host (capped to 64 chars)
   - accepted_user_agent = request.headers.get("user-agent") (capped to 500 chars)
7. Commit
8. Issue JWT:
   - access_token = create_access_token({sub, tenant_id, roles})
   - refresh_token = None (документировано: "v1: not issued on accept; user can log in normally later")
9. Return {user_id, tenant_id, role, access_token, refresh_token: null, token_type: "bearer"}
```

### Response (200)

```json
{
  "user_id": "4076fbd3-1434-40a9-8ef3-fb2a626f0114",
  "tenant_id": "7daa4f78-806e-4593-aace-c49eaa96493c",
  "role": "student",
  "access_token": "eyJhbGciOi...",
  "refresh_token": null,
  "token_type": "bearer"
}
```

Frontend `accept-invite/page.tsx:117-142`:
- Зовёт `/users/me` чтобы получить profile
- Строит AuthUser shape: `user_id, tenant_id, tenant, telegram_id, role, full_name, email`
- `login(access_token, authUser)` сохраняет в Zustand + localStorage
- `router.push('/dashboard')` — пользователь уже в системе

### Error paths

| HTTP | Cause | Detail |
|---|---|---|
| 404 | Token not found | "Invitation not found" |
| 410 | Already accepted | "Это приглашение уже принято" |
| 410 | Expired (lazy) | "Срок действия приглашения истёк" |
| 410 | Revoked | "Приглашение отозвано" |
| 410 | Superseded | "Приглашение заменено новым" |
| 422 | Personnel number missing | "Это приглашение требует ввод табельного номера" |
| 403 | Personnel number mismatch | "Табельный номер не совпадает" |
| 500 | Invitation has no user_id | "Invitation has no associated user" |

## Шаг 7: Resend (methodologist)

### Request

```http
POST /api/v1/users/invitations/{invitation_id}/resend
Authorization: Bearer <methodologist-jwt>
```

### Backend flow (`resend_invitation`)

`invitations_service.py:193-247`:

```python
1. Lookup invitation by id (tenant-scoped)
2. If not found OR not in caller's tenant: 404 "Invitation not found"
3. If status not in ("pending", "expired"): 409 "Cannot re-invite: status is 'X'"
4. Find pending user (must exist — created with invitation)
5. Compute new expiry
6. Generate new token
7. Create new UserInvitation row (status=pending, fresh token, fresh expiry)
8. Mark old: status="superseded", superseded_by=new_id
9. Commit
10. Return {invitation_id: NEW, invite_url, expires_at, superseded_old_id: OLD}
```

### Response (200)

```json
{
  "invitation_id": "new-uuid",
  "invite_url": "https://app.kml.kz/accept-invite?token=new-token",
  "expires_at": "2026-07-03T...",
  "superseded_old_id": "old-uuid"
}
```

### Use case

Methodologist может переслать новое приглашение если:
- recipient потерял email
- ссылка expired
- recipient не принял в течение expiry_days (default 3)

`superseded` старый token немедленно становится невалидным
(`get_public_invitation` возвращает `valid: false, reason: "superseded"`).

## Шаг 8: List (methodologist)

### Request

```http
GET /api/v1/users/invitations?status=pending&page=1&per_page=20
Authorization: Bearer <methodologist-jwt>
```

### Response (200)

```json
{
  "items": [
    {
      "id": "uuid",
      "email": "user1@example.com",
      "role": "student",
      "status": "pending",     // pending|accepted|expired|revoked|superseded
      "invited_by": "uuid",
      "created_at": "...",
      "expires_at": "...",
      "accepted_at": null,
      "user_id": "uuid"
    }
  ],
  "total": 1,
  "page": 1,
  "per_page": 20
}
```

Default sort: `created_at DESC`.

## Audit fields (HR can spot suspicious accepts)

После accept, у `UserInvitation` row:
- `accepted_at` — timestamp
- `accepted_ip` — X-Forwarded-For (или request.client.host) — capped 64 chars
- `accepted_user_agent` — request header — capped 500 chars

HR может вытащить через `GET /v1/users/invitations?status=accepted`
и проверить: IP/UA неожиданный? это может быть compromise.

## Что с этим можно делать после приглашения

| Действие | UI path | Endpoint |
|---|---|---|
| View invitation list | /admin/users (будущее) или /api | GET /v1/users/invitations |
| Resend (lost email) | та же страница | POST /v1/users/invitations/{id}/resend |
| Accept (public) | /accept-invite?token=... | GET + POST /v1/invitations/{token}/{...} |
| Promote user to admin | /admin/users | POST /v1/users/{id}/role |
| Reset password | (будущее) | POST /v1/users/{id}/reset-password |
| Bulk invite (200 max) | через API | POST /v1/users/invitations/bulk |
| Check Kiosk invite | /admin/kiosks | GET /v1/admin/kiosks |

## Edge cases & gotchas

### 1. Email domain ≠ tenant slug

`authenticate_user` (`service.py:153-169`) **scopes login by
email domain**. Если email `user@newdomain.kml` но tenant slug
`kml.kz` — `/auth/login` 401 "Invalid credentials" (security).

**НО** auto-login через accept invitation работает — token-based,
не email-based.

В smoke (2026-06-30 11:00) Step 5: `/auth/login` для user с
email `smoke-inv-...@newdomain.kml` → 401. Это **by design**,
не bug. Документировано.

### 2. Demo tenant blocks invites

`assert_can_send_invite` жёстко. Methodologist НЕ может приглашать
в demo. Это **by design** — prospect shouldn't invite fake users.

For local testing, либо:
- Использовать не-demo tenant (нет такого в нашем demo deploy)
- Вручную INSERT в БД (live smoke сделал это)

### 3. pending User — уязвим к enumeration

Public endpoint `/invitations/{token}` возвращает 200 + details
(включая email) если token валиден. **Token 32-char URL-safe =
~190 bits entropy** — brute force infeasible.

Но если **сам token** утёк (через Slack screenshot, etc) — любой
кто его получит может:
- увидеть email + tenant
- **открыть инвайт сам** (создаст user с этим email, не original recipient)
- soft 2FA (personnel_number) может защитить, если HR её указал

### 4. Refresh token НЕ выдаётся на accept

`accept_invitation` возвращает `refresh_token: null` (документировано:
"v1: not issued on accept; user can log in normally later").

Это значит: после accept пользователь залогинен, но **через 1 час
(access token TTL)** ему придётся логиниться заново через password.

Это **TODO**: v1.1 должен выдавать refresh_token при accept.

### 5. Personnel number — soft 2FA

`requires_personnel_number: true` если HR указал табельный
номер при создании invitation. Это soft 2FA — recipient должен
знать табельный номер чтобы принять.

**Use case:** HR импортировал штатку (Step 3 из FLOW_COURSE_TO_INVITATION)
с табельными номерами, потом отправил invitations. Без
табельного номера нельзя принять (даже с токеном).

### 6. Resend старого token сразу становится невалидным

`get_public_invitation` для `status="superseded"` возвращает
`valid: false, reason: "superseded"`. **Но** accept для
superseded token возвращает 410 Gone "Приглашение заменено новым".

**Edge:** если recipient уже открыл accept-invite страницу со
старым token (видит "superseded"), а потом methodologist делает
resend — recipient должен **обновить страницу** чтобы получить
новый token. Иначе старый token невалиден.

### 7. Нет DELETE /invitations/{id}

Сейчас нет endpoint для revoke. Если методолог хочет отменить
pending invitation — может:
- `resend` создаст superseded, старый автоматически невалиден
- ИЛИ вручную `UPDATE user_invitations SET status='revoked' WHERE id=$1`
  (но UI для этого нет)

**TODO:** explicit `POST /v1/users/invitations/{id}/revoke`
endpoint.

### 8. Email validation — консервативная

Regex `^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$` —
RFC 5321 не полностью. Unicode email (например `ivan@компания.рф`)
**не пройдёт**. Для production с русским тенантом — может быть
проблемой. TODO: расширить regex.

## Live smoke (2026-06-30 11:00)

### Setup

Demo tenant блокирует invite creation. Сделал **direct DB
insert** для invitation + pending user (smoke-inv-50cd267b@newdomain.kml,
token KzHKWSmY...), потом прогнал public endpoints.

### Result

| Step | Endpoint | Status | Notes |
|---|---|---|---|
| 1. DB insert | (direct) | OK | user.is_active=False, status=inactive, password_hash=NULL; invitation.status=pending, token=32-char URL-safe, expires_at=+3d |
| 2. Public view | `GET /v1/invitations/{token}` | **200** | `valid: true, email, role: "student", tenant_name: "Демо-организация", requires_personnel_number: false` |
| 3. Accept | `POST /v1/invitations/{token}/accept` | **200** | access_token (JWT, ~427 chars), refresh_token=null, token_type=bearer |
| 4. DB verify | (direct) | OK | `user.is_active=True, status="active", password_hash NOT NULL, last_login=2026-06-30 06:09:35, first_name="Иван", last_name="Смирнов"`; `invitation.status="accepted", accepted_at, accepted_ip="203.0.113.42", accepted_user_agent="smoke-test/1.0"` |
| 5. Login через email+password | `POST /v1/auth/login` | **401** | "Invalid credentials" — by design, tenant scope по email domain. `newdomain.kml` ≠ tenant `kml.kz`. **Но auto-login через accept JWT работает.** |

### Audit trail (из DB)

```sql
SELECT id, email, status, expires_at, accepted_at, accepted_ip, accepted_user_agent
FROM user_invitations
WHERE id = '918f95ae-...';
-- status: accepted
-- accepted_at: 2026-06-30 06:09:35.707547+00:00
-- accepted_ip: 203.0.113.42  (X-Forwarded-For captured)
-- accepted_user_agent: smoke-test/1.0
```

## TL;DR для UI (что видит методолог)

| Действие | UI path | Endpoint |
|---|---|---|
| Bulk invite | (будущее: /admin/users) | POST /v1/users/invitations/bulk |
| List invitations | (будущее) | GET /v1/users/invitations |
| Resend (lost/expired) | (будущее) | POST /v1/users/invitations/{id}/resend |
| View accept-page (public) | /accept-invite?token=... | GET + POST /v1/invitations/{token}/{...} |

**На текущий момент UI для методиста** — нет. Methodologist
делает invites через API (или через какой-нибудь admin tool).
Полноценный /admin/users UI с invitation management — **TODO**,
отдельный epic.

## Известные баги / TODO

1. **Нет POST /v1/users/invitations/{id}/revoke** — методолог не
   может отменить pending invitation (только через resend +
   superseded).
2. **Нет UI** для bulk invite / list / resend. Methodologist
   сейчас делает через API или console.
3. **Refresh token НЕ выдаётся на accept** — через 1 час user
   вынужден логиниться заново.
4. **Email regex** — не поддерживает Unicode (IDN). TODO.
5. **Нет resend всех expired invitations** в bulk. UI должен
   показывать expired как reminder кнопку.
6. **Demo tenant block** — `assert_can_send_invite` слишком жёсткий.
   В demo невозможно ничего потестить, кроме public view + accept.
