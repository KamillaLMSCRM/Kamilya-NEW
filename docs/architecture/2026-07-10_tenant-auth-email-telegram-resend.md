# Авторизация тенантов: email, Telegram и Resend

**Проект:** Kamilya LMS  
**Статус:** фактическая реализация на 10.07.2026.  
**Назначение:** самостоятельная инструкция для переноса схемы в другой multi-tenant проект.

## 1. Архитектура

В системе есть четыре разных процесса:

1. регистрация компании и первого администратора;
2. вход существующего пользователя по email OTP;
3. вход существующего пользователя через Telegram-бота;
4. принятие приглашения сотрудником или обучающимся.

Resend не авторизует пользователя. Resend только доставляет email, а код создаётся, хранится и проверяется backend.

~~~mermaid
flowchart LR
    W["Web app"] --> A["FastAPI API"]
    A --> DB[("PostgreSQL")]
    A --> R[("Redis")]
    A --> E["Resend API"]
    E --> M["Email пользователя"]
    T["Telegram Bot"] -->|webhook| A
    A -->|sendMessage| T
~~~

Тенант определяется сервером через tenant_id. Пользователь имеет email и/или numeric telegram_id, роль и статус активности. Superadmin с tenant_id = NULL является отдельной платформенной идентичностью.

## 2. Регистрация тенанта через email

Текущий основной flow:

~~~text
kml.kz -> app.kml.kz/register-tenant
  -> company_name, contact_name, email, password
  -> POST /api/v1/tenants/register
  -> Tenant + User(admin) + UserRole + TenantUsage + TenantLead
  -> access JWT + refresh cookie
  -> /dashboard
~~~

Endpoint: POST /api/v1/tenants/register.

Обязательные поля:

~~~json
{
  "company_name": "ТОО Example",
  "contact_name": "Имя Фамилия",
  "email": "hr@example.kz",
  "password": "at-least-8-chars"
}
~~~

Дополнительные поля: phone, telegram_username, employee_count_range, preferred_language, intent (try|demo|buy), billing_identifier, message.

Backend:

1. Нормализует email и запрещает дубликат пользователя.
2. Создаёт уникальный slug из названия, включая транслитерацию кириллицы.
3. Создаёт tenant со статусом и планом trial.
4. Устанавливает PostgreSQL/RLS context app.tenant_id до tenant-scoped вставок.
5. Создаёт первого пользователя с ролью admin, is_active=true и Argon2-хешем пароля.
6. Создаёт UserRole, TenantUsage и TenantLead.
7. Создаёт access/refresh JWT и ставит refresh-cookie.
8. Отправляет уведомление о старте trial через EmailService.
9. Возвращает tenant, user, limits и даты trial.

Текущие лимиты trial:

| Ресурс | Значение |
|---|---:|
| Обычная AI-генерация курса | 1 |
| Курс по должностной инструкции | 1 |
| Обучающиеся | 10 |
| Системные пользователи | 3 |
| Длительность | 14 дней |

Важно: уведомление trial started не является обязательной email-верификацией. Текущая регистрация активирует tenant сразу. Verified-first onboarding потребует отдельного состояния email_pending, verification token и активации после подтверждения.

## 3. Вход по email OTP

~~~mermaid
sequenceDiagram
    participant U as User
    participant W as Web
    participant A as API
    participant R as Redis
    participant E as Resend
    U->>W: Вводит email
    W->>A: POST /auth/email/request-code
    A->>R: Сохранить OTP на 5 минут
    A->>E: Отправить письмо
    E-->>U: Шестизначный код
    U->>W: Вводит код
    W->>A: POST /auth/email/verify-code
    A->>R: Проверить и удалить OTP
    A-->>W: Access JWT + refresh cookie + user
~~~

### Запрос кода

Endpoint: POST /api/v1/auth/email/request-code.

~~~json
{ "email": "hr@example.kz" }
~~~

Backend нормализует email, выполняет login lookup активного пользователя и создаёт OTP только для найденного active User. Для неизвестного email ответ нейтральный, чтобы нельзя было перечислять зарегистрированные адреса.

### OTP storage

Основной Redis key:

~~~text
auth:email:<normalized_email>
~~~

Payload содержит email, user_id, tenant_id, роль, created_at, expires_at и код.

Параметры:

- TTL: 300 секунд;
- cooldown повторной отправки: 25 секунд;
- повторная отправка в cooldown возвращает тот же код;
- успешная проверка удаляет запись;
- неверный код не раскрывает наличие email.

Текущий process-local in-memory fallback допустим для локальной разработки. Для production с несколькими API replicas он ненадёжен: storage не общий и очищается после рестарта. В новом проекте лучше общий Redis либо fail-closed для auth.

### Проверка кода

Endpoint: POST /api/v1/auth/email/verify-code.

~~~json
{ "email": "hr@example.kz", "code": "123456" }
~~~

После успешного consume backend загружает пользователя по user_id, проверяет is_active и совпадение email, обновляет last_login, строит payload пользователя с tenant и актуальной ролью из БД, выдаёт JWT и refresh-cookie.

Ошибка неверного или просроченного кода: 401 Invalid or expired code.

## 4. Resend

Граница ответственности:

~~~text
auth router -> EmailService -> Resend REST API -> mailbox
~~~

Backend env:

~~~env
EMAIL_PROVIDER=resend
RESEND_API_KEY=<backend-only secret>
EMAIL_FROM=Product <no-reply@verified-domain>
~~~

RESEND_API_KEY нельзя публиковать в Git, frontend env, URL, telemetry или обычных логах.

При EMAIL_PROVIDER=resend backend вызывает:

~~~http
POST https://api.resend.com/emails
Authorization: Bearer <RESEND_API_KEY>
Content-Type: application/json
~~~

Логический payload:

~~~json
{
  "from": "Product <no-reply@verified-domain>",
  "to": ["hr@example.kz"],
  "subject": "Product login code",
  "text": "Your login code is 123456. It expires in 5 minutes.",
  "html": "<p>Your login code:</p><strong>123456</strong>"
}
~~~

EmailService отделяет auth от конкретного провайдера. Режим log нужен для локального тестирования, режим resend — для production.

Для домена отправителя Resend и DNS должны подтвердить DKIM, SPF, custom return-path если используется, и DMARC на правильном домене отправителя: например _dmarc.notify.example.kz, а не только _dmarc.example.kz.

После DNS-подтверждения проверить реальное письмо: From, доставляемость, SPF/DKIM/DMARC в заголовках и spam placement.

## 5. Вход через Telegram

Telegram flow не использует Resend. Код показывается в browser и передаётся пользователем общему боту.

~~~mermaid
sequenceDiagram
    participant U as User
    participant W as Web
    participant A as API
    participant R as Redis
    participant B as Telegram bot
    U->>W: Получить Telegram-код
    W->>A: POST /auth/generate-code
    A->>R: auth:code:<code>, TTL 5 минут
    A-->>W: code + expires_in
    U->>B: Отправляет 6 цифр
    B->>A: POST /telegram/webhook
    A->>A: Проверить webhook secret и telegram_id
    A->>R: verified + user_data
    loop каждые 5 секунд
      W->>A: POST /auth/check-code
    end
    A-->>W: Access JWT + refresh cookie + user
~~~

### Генерация

Endpoint: POST /api/v1/auth/generate-code.

Ответ:

~~~json
{ "code": "123456", "expires_in": 300 }
~~~

Redis keys:

~~~text
auth:code:<code>
auth:latest_code
~~~

Cooldown — 25 секунд, TTL — 5 минут. Frontend показывает таймер и опрашивает POST /api/v1/auth/check-code раз в 5 секунд.

### Webhook

Endpoint: POST /api/v1/telegram/webhook.

Telegram должен вызывать его с заголовком:

~~~text
X-Telegram-Bot-Api-Secret-Token: <TELEGRAM_WEBHOOK_SECRET>
~~~

Если secret отсутствует или не совпадает, backend отвечает 404 и не обрабатывает update. Это fail-closed защита от открытого relay.

Обработка:

- /start — инструкция отправить код;
- ровно 6 цифр — попытка подтверждения login code;
- другое сообщение — ошибка формата.

Пользователь ищется по numeric telegram_id, а не username. Username изменяем и не должен быть credential. После нахождения backend получает роль и tenant, сохраняет user_data в auth session и отправляет ботом подтверждение.

### Polling

Endpoint: POST /api/v1/auth/check-code.

До подтверждения ответ:

~~~json
{ "verified": false }
~~~

После подтверждения возвращаются verified=true, access token и user payload. После выдачи запись удаляется, поэтому код одноразовый.

Если один Telegram ID привязан к нескольким пользователям, текущая реализация предпочитает tenant-scoped активного пользователя, затем superadmin. Для нового проекта лучше запретить неоднозначные привязки или добавить явный выбор tenant.

## 6. Legacy Telegram registration

Отдельный маршрут POST /api/v1/auth/register-by-telegram и frontend /register создают tenant и первого admin по company, telegram_id, first_name, last_name без email, пароля и Resend. После этого пользователь входит обычным Telegram-кодом.

Это не тот же flow, что /register-tenant. В новом проекте следует оставить один canonical tenant-registration flow, иначе появляются дубли и разные правила лимитов. Legacy маршрут нужно удалить или явно оставить только для миграции.

## 7. Приглашения пользователей

Приглашение не создаёт компанию. Методолог/администратор создаёт pending User и UserInvitation с криптографически случайным token. Ссылка:

~~~text
https://app.example.com/accept-invite?token=<url-safe-token>
~~~

Текущий flow передаёт ссылку вручную; автоматической отправки приглашений через Resend нет.

Backend проверяет tenant, срок и статусы pending/accepted/expired/revoked/superseded, затем принимает имя, фамилию и пароль. Если приглашение связано с табельным номером, он проверяется как дополнительная сверка. После успеха User активируется, invitation отмечается accepted, выдаётся JWT и refresh-cookie.

## 8. JWT, refresh и frontend session

Access JWT содержит минимум:

~~~json
{
  "sub": "user UUID",
  "tenant_id": "tenant UUID or null",
  "roles": ["admin"],
  "aud": "project-name",
  "iss": "project-name",
  "type": "access"
}
~~~

Backend декодирует JWT с явным алгоритмом, audience и issuer, затем загружает User из БД. Роль и is_active проверяются по БД, а не только по claims.

Refresh cookie:

- имя: kamilya_refresh;
- httpOnly, Secure, SameSite=None, Partitioned;
- Path=/api/v1/auth;
- срок 30 дней.

SameSite=None нужен для cross-origin frontend app.kml.kz и API kamilya-lms-api.onrender.com; вместе с ним обязателен Secure. Partitioned помогает браузерам с политикой third-party cookies.

Frontend lifecycle:

~~~text
success -> setAuth(access, user) in memory
reload  -> POST /auth/refresh with credentials: include
401     -> one shared refresh request, then retry original request
logout  -> clear state + POST /auth/logout + clear cookie
~~~

Access и refresh нельзя хранить в localStorage. После неудачного refresh frontend очищает auth state и отправляет пользователя на /login.

## 9. Deployment checklist

~~~env
JWT_SECRET=<random, at least 32 chars>
JWT_ALGORITHM=HS256
JWT_AUDIENCE=<project-name>
JWT_ISSUER=<project-name>
REDIS_URL=<shared Redis URL>
TELEGRAM_BOT_TOKEN=<backend-only>
TELEGRAM_WEBHOOK_SECRET=<random secret>
EMAIL_PROVIDER=resend
RESEND_API_KEY=<backend-only>
EMAIL_FROM=Product <no-reply@verified-domain>
CORS_ORIGINS=["https://app.example.com"]
PUBLIC_URL=https://app.example.com
~~~

Перед production проверить:

- HTTPS на frontend, API и Telegram webhook;
- точный CORS origin и allow_credentials=true;
- credentials: include в browser requests;
- общий Redis для всех API instances;
- verified Resend domain и sender;
- одинаковый webhook secret в Telegram и backend;
- rate limits, TTL, cooldown и одноразовое потребление OTP;
- нейтральный ответ для неизвестного email;
- tenant context из JWT/серверного lookup, не из доверенного тела запроса;
- роли и активность из БД;
- отсутствие токенов и API keys в логах.

## 10. Карта файлов текущей реализации

| Файл | Ответственность |
|---|---|
| apps/api/app/modules/tenants/router.py | регистрация tenant, первый admin, trial, уведомление |
| apps/api/app/modules/tenants/schemas.py | request/response регистрации и trial limits |
| apps/api/app/modules/auth/router.py | password login, email OTP, Telegram code, refresh/logout |
| apps/api/app/modules/auth/email_otp.py | email OTP storage/consume |
| apps/api/app/modules/auth/auth_sessions.py | Telegram auth-code sessions |
| apps/api/app/modules/auth/telegram.py | Telegram webhook и user resolution |
| apps/api/app/modules/auth/telegram_register.py | legacy Telegram tenant registration |
| apps/api/app/core/email.py | EmailService, Resend/log adapters |
| apps/api/app/core/auth.py | JWT и current-user checks |
| apps/api/app/modules/users/invitations_service.py | invite token и auto-login |
| apps/web/src/app/register-tenant/page.tsx | регистрация компании |
| apps/web/src/app/login/page.tsx | email и Telegram UI |
| apps/web/src/lib/auth.ts | in-memory access, refresh, logout |
| apps/web/src/lib/api.ts | Bearer, credentials, refresh-on-401 |
| apps/web/src/app/register/page.tsx | legacy Telegram registration UI |
| apps/web/src/app/accept-invite/page.tsx | invite acceptance |

## 11. Перенос в другой проект

Переносить лучше четырьмя сервисами:

1. TenantProvisioningService — tenant, первый admin, trial, лимиты и audit в одной транзакции.
2. OtpService — генерация, cooldown, TTL и атомарный consume для email/Telegram.
3. EmailProvider — интерфейс send(template, recipient, variables) с log и resend реализациями.
4. SessionService — access JWT, refresh rotation, cookie и logout независимо от канала.

Canonical flow:

~~~text
email registration -> optional email verification -> tenant admin session
email OTP login   -> existing user session
Telegram login   -> existing user session
invite link       -> employee/student onboarding session
~~~

Нельзя:

- использовать Telegram username вместо numeric ID;
- полагаться на in-memory OTP при нескольких replicas;
- отправлять Resend key во frontend;
- раскрывать существование email;
- принимать tenant_id из тела запроса как источник доверия;
- считать username доказательством владения Telegram;
- оставлять два равноправных tenant-registration flow без общей идемпотентности.

## 12. Тестовая матрица

| Проверка | Ожидаемый результат |
|---|---|
| известный active email | OTP отправлен и verify создаёт session |
| неизвестный email | нейтральный ответ, без enumeration |
| неверный/истёкший OTP | 401, сессия не создана |
| повторное использование OTP | 401, запись уже удалена |
| повторная отправка до cooldown | новый код не создаётся |
| webhook без secret | 404, update не обрабатывается |
| Telegram correct code + user | polling получает session |
| refresh после reload | новый access, тот же tenant |
| logout после истечения access | refresh отозван и cookie очищена |
| invite accepted | правильный User/tenant и auto-login |
| Resend 4xx/5xx | key не раскрыт, ошибка наблюдаема |
| Redis недоступен | поведение соответствует production policy |

## 13. Ограничения текущей версии

- Регистрация тенанта активирует его сразу; обязательной email verification нет.
- Telegram trial использует общий бот; dedicated bot per tenant — отдельная интеграция.
- Приглашения сейчас копируются вручную, без автоматического email delivery.
- In-memory Redis fallback допустим локально, но не является надёжным production storage.
- Legacy /register сохраняет второй путь создания тенанта и требует отдельного решения по удалению или миграции.

