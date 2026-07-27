# Kamilya LMS: VPS и подключённые сервисы

**Обновлено:** 2026-07-27
**Правило:** этот документ описывает только подтверждённое текущее состояние.
Значения паролей, ключей и URL с credentials не приводятся.

## Production VPS

- Host: `173.249.51.164`.
- Доступ: SSH key; резервные credentials находятся только в локальном `.env`.
- Основной checkout worker: `/opt/kamilya-worker`.
- Production API размещён на Render, не на этом VPS.
- Production PostgreSQL и Storage размещены в Supabase.

Переменные доступа в локальном `.env`:

- `VPS_URL`;
- `vps_root_password`;
- `REDIS_URL`;
- связанные TLS-параметры.

Не печатать значения переменных и не добавлять их в команды, попадающие в
логи.

## Проверенное 2026-07-27

| Компонент | Состояние | Комментарий |
|---|---|---|
| `valkey-server` / `valkey` | active | Broker, result backend, OTP/rate-limit/cache |
| `kamilya-worker.service` | active, enabled | Checkout `5165a77`; устарел относительно текущего API и требует release update |
| Disk `/` | 59% used, около 30 GB free | Нужен alert по заполнению |
| App backup timer/cron | не найден | Restore readiness не подтверждена |
| `kamilya-trial-expiry.timer` | enabled, inactive | Legacy unit, ссылается на старый checkout |

Состояние Docling, WhatsApp gateway, WireGuard и legacy API в эту проверку не
входило. Перед использованием каждого сервиса нужен отдельный health и
прикладной smoke; старый отчёт не считается доказательством.

## Быстрая read-only проверка

```bash
systemctl is-active valkey-server || systemctl is-active valkey
systemctl is-active kamilya-worker.service
systemctl is-enabled kamilya-worker.service
git -C /opt/kamilya-worker status --short
git -C /opt/kamilya-worker rev-parse HEAD
df -h /
systemctl list-timers --all
journalctl -u kamilya-worker.service -n 100 --no-pager
```

Для worker используется отдельный
[`INFRA_CELERY_WORKER.md`](INFRA_CELERY_WORKER.md).

## Service ownership

| Сервис | Владелец и назначение |
|---|---|
| Render API | FastAPI production |
| Vercel | Next.js production |
| Supabase PostgreSQL | Production data and pgvector |
| Supabase Storage | Documents and generated artifacts |
| VPS Valkey | Queue/cache/runtime coordination |
| VPS Celery | AI, ingestion and rule recomputation |
| Docling | Conversion of supported office/PDF sources when enabled |
| Resend | Transactional email |
| Telegram | Alternative auth/invitation channel |

## HostKZ

HostKZ server был заказан как недельный тестовый контур PostgreSQL в
Казахстане. Он не является production и не должен автоматически получать
актуальные production secrets или customer data.

До KZ cutover требуется отдельный план:

1. sizing;
2. hardening;
3. encrypted backup/PITR;
4. object storage localization;
5. migration rehearsal;
6. rollback;
7. договорная и правовая проверка.

## Операционные запреты

- Не использовать `git reset --hard`.
- Не делать `git pull` вслепую в production checkout.
- Не обновлять worker без выбранного release SHA и rollback SHA.
- Не менять production DB URL для тестового KZ VPS.
- Не считать active unit доказательством работоспособности business-flow.
- Не отключать Supabase во время тестового переноса.

## Перед первым tenant

Обязательные действия находятся в
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md):

- worker release parity;
- прикладной E2E smoke;
- независимый backup и restore drill;
- heartbeat/queue/disk alerts.
