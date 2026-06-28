# ADR-0010: Multi-Channel Delivery + Cross-Device Learning

**Версия:** 1.1 — финал после обсуждения с Askar 2026-06-27
**Статус:** утверждён, начинаем спринт 1

## Контекст

В KZ реальная точка контакта с сотрудником — мобильный телефон, не email.
Текущее состояние Kamilya LMS:
- Email + Telegram идентификация, нет `phone`
- Telegram-бот работает (`auth_sessions.py`)
- Email-сервиса нет (AGENTS.md)
- Курсы и тесты — web-only, JWT в браузере
- Нет PWA

## Ключевой принцип (утверждён Askar 2026-06-27)

**Kamilya — middleware / инструмент. Не провайдер.**

- SMTP-сервер предоставляет сам тенант
- Telegram-бота создаёт сам тенант через @BotFather
- WhatsApp-номер — рабочий номер тенанта (HR сканирует QR с рабочего телефона)
- Риски бана Meta, лимитов SMTP, спам-фильтров — на стороне тенанта
- Kamilya хранит credentials зашифрованными и использует только как транспорт

Это снимает с Kamilya юридическую ответственность за доставляемость и баны.

## Каналы доставки

| Канал | Кто предоставляет | Стоимость | Когда использовать |
|---|---|---|---|
| **Telegram** | Тенант создаёт бота | Бесплатно | Default, ~80% KZ-аудитории |
| **Email (SMTP)** | Тенант вводит свой SMTP | Зависит от тенанта | Office-сотрудники, ~60% KZ |
| **WhatsApp (Baileys)** | Тенант сканирует QR | Бесплатно, но риски бана | Field-сотрудники, ~85% KZ |
| **Copy-paste link** | Методолог шлёт руками | $0 | Fallback для маленьких компаний без IT |

**Нет SMS** — Askar 2026-06-27 явно отказался.

## Архитектура

### Per-tenant credentials table

```sql
CREATE TABLE tenant_integrations (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  channel TEXT NOT NULL CHECK (channel IN ('smtp', 'telegram', 'whatsapp')),
  config_encrypted BYTEA NOT NULL,  -- Fernet-encrypted JSON
  is_active BOOLEAN NOT NULL DEFAULT true,
  last_test_at TIMESTAMPTZ,
  last_test_status TEXT,  -- 'ok' | 'failed: ...'
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, channel)
);

CREATE INDEX idx_tenant_integrations_active
  ON tenant_integrations(tenant_id) WHERE is_active = true;

CREATE TABLE tenant_integrations_audit (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  channel TEXT NOT NULL,
  changed_by UUID NOT NULL REFERENCES users(id),
  change_type TEXT NOT NULL,  -- 'created' | 'updated' | 'deleted' | 'test_passed' | 'test_failed'
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### Шифрование

Fernet с `MASTER_ENCRYPTION_KEY` из env. Один мастер-ключ на все tenant credentials.
Потеря ключа = все credentials нерасшифровываемы (тенанты вводят заново).

### WhatsApp-Gateway (отдельный микросервис)

```
Хост: wa.kml.kz или внутренний VPS ($5-10/мес)
Persistent disk: /var/lib/baileys/sessions/{tenant_id}/
Процесс: Node.js с Baileys multi-session manager

Endpoints:
  POST /sessions/{tenant_id}/start    → возвращает QR-код
  GET  /sessions/{tenant_id}/status   → connected | qr_pending | disconnected | banned
  POST /sessions/{tenant_id}/logout   → отвязать номер
  POST /sessions/{tenant_id}/send     → отправить сообщение
  POST /webhooks/{tenant_id}          → события от Baileys (delivered, read)
```

Kamilya backend обращается к gateway по HTTP. Credentials (`creds.json`) НЕ покидают gateway.

### Channel router

При назначении курса/теста или приглашении:

```python
def select_channel(user, tenant) -> str:
    """Priority order: telegram > whatsapp > email > manual."""
    if user.telegram_id and tenant.integration_active('telegram'):
        return 'telegram'
    if user.phone and tenant.integration_active('whatsapp'):
        return 'whatsapp'
    if user.email and tenant.integration_active('smtp'):
        return 'email'
    return 'manual'  # copy-paste fallback
```

### `/i/{token}` magic-link (device-agnostic)

Deep-link, который работает на любом устройстве:
```
https://app.kml.kz/i/{token}
```

- Токен = signed JWT с `user_id`, `tenant_id`, `scope` (course | quiz), TTL = 30 дней
- Tap из Telegram/WhatsApp/SMS → открывается в любом браузере
- Создаёт browser-session для user (attach к существующей если есть)
- Redirect → `/courses/{id}/learn` или `/quizzes/{id}/take`

Прогресс хранится на сервере (НЕ в localStorage) — иначе кросс-девайс невозможен.

### Mobile-адаптация

- Tailwind breakpoints уже есть, проверяем `/courses/[id]/learn` и `/quizzes/[id]/take`
- Видео с `playsInline` для iOS
- Touch-targets ≥ 44px
- Горизонтальный скролл запрещён

QR-code «открыть на компьютере» — генерируется для каждого `/i/{token}`.

## Disclaimer (обязательно)

На странице `/admin/settings/integrations` и в ToS:

```
Kamilya LMS предоставляет инструменты для отправки уведомлений
через каналы, настроенные администратором вашей организации.
Kamilya не является провайдером email/WhatsApp/Telegram услуг
и не несёт ответственности за доставляемость, блокировки
номеров Meta, попадание писем в спам.

При использовании WhatsApp: номер должен быть реальным
и принадлежать вашей организации. Массовые рассылки через
unofficial-канал могут привести к бану номера со стороны Meta.
Восстановление заблокированного номера — ваша ответственность.
```

## Roadmap

| Неделя | Что | Зависимости |
|---|---|---|
| **1** | Migration + Fernet + UI `/admin/settings/integrations` (skeleton) | `MASTER_ENCRYPTION_KEY` |
| **2** | Telegram-канал (per-tenant bot) | — |
| **3** | Email/SMTP-канал + шаблоны | Mailtrap для dev |
| **4** | WhatsApp-gateway (Node.js + Baileys) | VPS с persistent disk |
| **5** | Channel-router + интеграция с assignments/invitations | — |
| **6** | Mobile-адаптация + `/i/{token}` + QR-code | — |

## Что НЕ делаем в v1 этого эпика

- ❌ Email через transactional провайдер (Brevo/Mailgun) — пусть тенант использует свой SMTP
- ❌ SMS-канал — Askar отказался
- ❌ WhatsApp Business API approved — только Baileys, риски на тенанте
- ❌ Push-уведомления в PWA — не в скоупе
- ❌ Voice ASR для quiz answers — не в скоупе
- ❌ Native mobile apps — v2 (AGENTS.md)

## Открытые вопросы для Askar

1. **VPS для WhatsApp-gateway** — есть ли существующий VPS (kml.kz) куда можно положить, или нужен новый?
2. **MASTER_ENCRYPTION_KEY** — сгенерирую и положу в Render env. Если потеряем — все credentials тенантов пропадут. Backup процедура?
3. **WhatsApp multi-tenant model** — shared gateway (1 Node-процесс, N сессий) или per-tenant VM?
4. **Mobile-адаптация scope** — «читать на мобиле» или «полноценный mobile-first»?
5. **Token TTL** — 7 / 30 / 90 дней для `/i/{token}`?
6. **Celery уже подключён?** — для bulk-отправки сообщений