# VPS Infrastructure Guide — `173.249.51.164`

> **Дата обновления:** 2026-07-21
> **Назначение:** какие сервисы развёрнуты на VPS, как они используются **именно для Kamilya LMS**, и как подключаться.
>
> **Старый документ `VPS_CONNECTION_GUIDE.md` имел ошибки:**
> - `qwen.kml.kz` и `qwen-embed.kml.kz` помечены как "running on VPS" — **нет**, физически они на DGX за WireGuard (`10.66.66.7:8555` / `10.66.66.7:8001`), VPS тут только держит DNS A-record через Cloudflare.
> - `kamilya-worker` отсутствовал — **сейчас добавлен** (запущен 2026-06-30, commit worker `4b3f0d4`).
> - Не было разделения: **prod vs dev-only vs legacy** — добавил.

---

## Что вообще где живёт (распределение инфраструктуры Kamilya LMS)

Чтобы не путать VPS с Render / Supabase / DGX — полная картина:

| Компонент | Где физически | Как попадает в прод |
|---|---|---|
| **Frontend (Next.js)** | Vercel Frankfurt, проект `prj_hJMzgp9QNFCwUMrsDEBZINpJJzBp` | auto-deploy на push в `master` |
| **Backend API (FastAPI prod)** | Render Frankfurt, сервис `kamilya-lms-api`, ID `srv-d8rp8ej7uimc73fglid0` | auto-deploy через `render.yaml` |
| **DB (Postgres)** | Supabase `aws-1-eu-central-1.pooler.supabase.com`, ref `ducegbxphkgffgozkchw` | pooler, прямое подключение |
| **Cache / Celery broker** | **VPS** `173.249.51.164`, Valkey TLS `6380` | один `REDIS_URL` в Render и worker env |
| **Storage (S3-compatible)** | Supabase Storage, bucket `Kamilya LMS` | прямой upload с Render |
| **LLM (Qwen chat)** | DGX-сервер `10.66.66.7:8555` за WireGuard-туннелем | Render env `LLM_API_URL` через туннель |
| **Embeddings (Qwen3-Embed)** | DGX-сервер `10.66.66.7:8001` за тем же WireGuard | Render env `EMBEDDINGS_API_URL` |
| **Docling (PDF→MD)** | **VPS** `173.249.51.164`, systemd `docling.service`, порт 8600 | домен `docling.kml.kz` → nginx → 127.0.0.1:8600 |
| **WhatsApp gateway** | **VPS** `173.249.51.164`, systemd `wa-gateway.service`, порт 8700 | домен `wa.kml.kz` → nginx → 127.0.0.1:8700 |
| **Celery worker** | **VPS** `173.249.51.164`, systemd `kamilya-worker.service` | AI generation, document ingestion и apply-rules через очередь `celery` |
| **Tunnel WireGuard** | **VPS** `173.249.51.164`, интерфейс `wg0`, UDP-порт 22677 | соединяет VPS ↔ DGX ↔ Windows-машина Askar'а |
| **Legacy Chamilo** | **VPS** `173.249.51.164`, процесс на :8080, домен `lms.kml.kz` | legacy DNS до полного cutover на LMS |

**То есть на этом VPS живут 5 prod-критичных компонентов:** `valkey-server`, `docling`, `wa-gateway`, `kamilya-worker` и WireGuard-туннель к DGX.

---

## Сервисы на VPS — подтверждённое состояние на 2026-07-21

Проверено через `systemctl list-units` и `curl localhost` с VPS.

| Сервис (systemd) | Порт | Домен | Назначение для Kamilya LMS | Статус |
|---|---|---|---|---|
| `valkey-server.service` | 6380 TLS | IP endpoint | Celery broker/result backend, OTP, auth sessions, rate limits и progress. AOF, `appendfsync everysec`, `noeviction`; сертификат обновляет `valkey-certbot-renew.timer`. | ✅ production smoke пройден 2026-07-14 |
| `docling.service` | 8600 | `docling.kml.kz` | Конвертация загруженных PDF/DOCX в markdown для RAG-ингеста документов (`/admin/documents` flow). Используется **только** если файл — не plain-text/markdown. | ✅ running, health 200 |
| `wa-gateway.service` | 8700 | `wa.kml.kz` | Отправка invite-ссылок сотрудникам через WhatsApp (альтернативный канал доставки приглашений, помимо copy-paste). Также приём кода для админ-логина через Telegram-style flow. Node.js + Baileys. Per-tenant `creds.json`. | ✅ running, health 200 |
| `kamilya-worker.service` | — | — | **Celery worker** для `ai.generate_course`, `ai.ingest_document` и `positions.apply_course_rules`. Очередь: Valkey, queue `celery`; clone `/opt/kamilya-worker`. | ✅ active/ready на revision `5bc86c6` |
| `kamilya-lms.service` | 8000 | `api.kml.kz` (origin) | ⚠️ **DEV-ONLY** запущенная uvicorn-инстанция из `/root/Kamilya-LMS/backend/`. Поднята давно для локальных экспериментов, **НЕ используется продом**. Прод = Render. На VPS держится чтобы можно было дебажить API локально когда Render лежит. Можно безопасно `systemctl stop kamilya-lms` если мешает. | ⚠️ running but unused для prod |
| nginx | 80/443 | `docling.kml.kz`, `wa.kml.kz`, `api.kml.kz`, `lms.kml.kz` | Reverse proxy + TLS termination (Cloudflare Origin Cert). | ✅ running |
| WireGuard (`wg0`) | UDP 22677 | — | Туннель к DGX-серверу `10.66.66.7` где физически живут Qwen chat (8555) и Qwen-embed (8001). **Без WG-туннеля LLM недоступен** — API упадёт на 502/503. | ✅ active |

### Что **не** запущено на этом VPS (распространённое заблуждение)

- ❌ **Qwen LLM (chat)** — НЕ на VPS. Это DGX-сервер за WireGuard. На VPS процесс `vllm` не висит. Внешний `https://qwen.kml.kz/v1/models` отвечает 200 через Cloudflare → DNS A-record → но фактически проксируется **на DGX**, не на 127.0.0.1:8555 этого VPS (тут этого порта вообще нет).
- ❌ **Qwen Embeddings** — то же самое, живёт на DGX за WG.
- ❌ **Postgres** — НЕ на этом production VPS. Production DB остаётся в Supabase; HostKZ был изолированным тестовым контуром.
- ✅ **Valkey / Celery broker** — находится на этом VPS и доступен Render/worker по TLS `6380`. Секретный URL хранится только в env.

---

## Как каждый сервис используется в проде Kamilya LMS

### 1. `docling.kml.kz` — PDF/DOCX → Markdown (RAG ingest pipeline)

**Где вызывается:** `apps/api/app/modules/documents/router.py` (endpoint `POST /v1/documents/ingest`).

**Когда:**
- Пользователь загружает PDF/DOCX в `/admin/documents`.
- Backend проверяет MIME (magic bytes, не по расширению).
- Если не plain-text — проксирует файл на `https://docling.kml.kz/convert`.
- Docling возвращает markdown, дальше markdown chunker → embeddings.

**Без этого сервиса:** только TXT/MD можно грузить в RAG. PDF-документы (Job Descriptions, политики) — слепые для AI.

**Restart/redeploy:** `systemctl restart docling`. См. `INFRA_CELERY_WORKER.md` § "Troubleshooting" — там есть типичные сценарии (OOM, model cache).

---

### 2. `wa.kml.kz` — WhatsApp invite delivery (multi-channel delivery)

**Где вызывается:** `apps/api/app/modules/notifications/` (по ADR-0006 multi-channel delivery).

**Когда:**
- Методолог нажимает "отправить приглашение через WhatsApp" в `/admin/staff`.
- Backend подписывает service-JWT (HMAC с `KAMILYA_BACKEND_SECRET`) и шлёт на `POST https://wa.kml.kz/v1/send`.
- wa-gateway через Baileys открывает persistent socket к WhatsApp Business API (Meta) и отправляет сообщение с invite-ссылкой.

**Без этого сервиса:** invite-канал работает только через copy-paste ссылки (методолог копирует URL из UI → шлёт в Slack/Telegram руками). Это **дефолтный** flow по `TZ.md` — wa-gateway это **opt-in enhancement** для тех компаний, где WhatsApp — основной канал.

**Auth model:** backend ↔ wa-gateway общаются через `KAMILYA_BACKEND_SECRET` (общий HMAC). На VPS в env wa-gateway и в Render env должны быть **одинаковые** значения. Потеря = переавторизация всех тенантов (re-scan QR).

---

### 3. `kamilya-worker.service` — Celery apply-rules

**Где вызывается:** `apps/api/app/modules/positions/tasks.py::apply_rules_for_users_task`.

**Когда:**
- Методолог делает `commit` в `/admin/staff` → backend идемпотентно пишет пользователей + `Position`/`Department`, потом `apply_rules_for_users_task.delay(user_ids, tenant_id)`.
- Задача попадает в Valkey queue `celery`.
- Worker (на этом VPS, systemd) подхватывает за секунды и:
  1. Загружает `Position` каждого user'а с eager-load `Department`.
  2. Достаёт `PositionCourseBinding` для каждой позиции (или департамента — иерархия).
  3. Создаёт/удаляет `Enrollment` строки в `enrollments` таблице.
  4. Возвращает `{created, deleted, skipped}`.
- Бэкенд хранит `apply_rules_task_id` на стороне `staff_import_commit` ответа → фронт делает polling `GET /v1/admin/staff/import/{task_id}` чтобы показать прогресс методологу.

**Без этого сервиса:** apply-rules либо (а) падает на 504 timeout (если делать синхронно), либо (б) вообще не вызывается и сотрудники не получают курсы.

**Почему на VPS, а не на Render:** Render free/starter не держит long-running workers (засыпают через 15 мин idle). VPS + systemd = надёжно. Подробности — `INFRA_CELERY_WORKER.md`.

**Deploy worker:** `cd /opt/kamilya-worker && git pull && systemctl restart kamilya-worker`. Подробный runbook — там же.

---

### 4. WireGuard-туннель к DGX (`wg0`)

**Зачем:** LLM и embeddings **физически** живут на DGX Askar'а в офисе. Этот DGX за корпоративным NAT, наружу не торчит. Чтобы Render (Frankfurt) мог до него достучаться — туннель поднят через этот VPS (который имеет публичный IP) с обратным WG-пиром на DGX.

**Без WG:** `http://10.66.66.7:8555/v1/chat/completions` с Render-сервиса вернёт connection refused (10.66.66.7 — приватный адрес в office-сети). Упадёт **весь** AI-flow: генерация курсов, embeddings для RAG, ревьюер.

**Проверка туннеля:**
```bash
ssh root@173.249.51.164 "wg show"
# ожидаем peer с endpoint = (Askar office IP) и allowed-ips = 10.66.66.0/24
```

**Если туннель упал:** AI на проде начинает 502/503 на Qwen-запросах. Failover в `ResilientLLMClient` переключится на `DeepSeek`/`Voyage` cloud (см. ADR-0007) — но это $$$.

---

### 5. Nginx reverse proxy

Четыре server blocks в `/etc/nginx/sites-enabled/`:

| Server name | Бэкенд | Что это |
|---|---|---|
| `docling.kml.kz` | `127.0.0.1:8600` | Docling (см. § 1) |
| `wa.kml.kz` | `127.0.0.1:8700` | WhatsApp gateway (см. § 2) |
| `api.kml.kz` | `127.0.0.1:8000` | ⚠️ dev-инстанция LMS API. В проде через этот nginx ничего не идёт — Render отдаёт напрямую через `kamilya-lms-api.onrender.com`. Домен `api.kml.kz` оставлен для обратной совместимости / дебага. |
| `lms.kml.kz` | `127.0.0.1:8080` | Legacy Chamilo 2.0. **Не часть Kamilya LMS** — это предыдущая LMS, которую мы заменяем. Если ты видишь `lms.kml.kz` в браузере — это **старая** система. |

**Cloudflare Origin Cert** в `/etc/ssl/cloudflare/cert.pem` — TLS termination на nginx, Cloudflare проксирует HTTPS через свой edge.

---

## Как подключиться к VPS

```bash
# С Windows (PowerShell):
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164

# Проверить что работает — должно вернуть Linux hostname "vmi3311535":
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164 "hostname; uptime; free -h"

# В ~/.ssh/config Askar'а уже есть host alias "173.249.51.164"
```

**Альтернатива (если ключ не подхватывается):** пароль (хранится в `apps/api/.env` → `VPS_SSH_PASSWORD`, НЕ коммить в git). Использовать только для экстренного входа.

> **Безопасность:** в `VPS_CONNECTION_GUIDE.md` пароль раньше был в plaintext в коммите — теперь удалён. Если нужен — спросить у Askar'а или поднять из password manager.

---

## Команды для диагностики (cheat-sheet)

```bash
# Какие сервисы запущены
ssh root@173.249.51.164 "systemctl list-units --type=service --state=running --no-pager"

# Health-check'и (локально с VPS)
ssh root@173.249.51.164 "curl -s -o /dev/null -w 'docling:%{http_code}\n' http://localhost:8600/health"
ssh root@173.249.51.164 "curl -s -o /dev/null -w 'wa:%{http_code}\n' http://localhost:8700/health"

# Health-check'и (извне, через Cloudflare)
curl -s -o /dev/null -w 'docling:%{http_code}\n' https://docling.kml.kz/health
curl -s -o /dev/null -w 'wa:%{http_code}\n' https://wa.kml.kz/health
curl -s -o /dev/null -w 'qwen:%{http_code}\n' https://qwen.kml.kz/v1/models  # через VPN к DGX

# Celery worker
ssh root@173.249.51.164 "systemctl status kamilya-worker"
ssh root@173.249.51.164 "journalctl -u kamilya-worker -f"

# WireGuard
ssh root@173.249.51.164 "wg show"
ssh root@173.249.51.164 "ping -c 1 10.66.66.7"  # проверить доступ к DGX

# Дебаг AI-цепочки (с VPS — есть доступ к DGX напрямую):
ssh root@173.249.51.164 "curl -s http://10.66.66.7:8555/v1/models | head -c 500"

# Перезапуск сервиса (без перезапуска всей VM)
ssh root@173.249.51.164 "systemctl restart docling"       # редко нужен
ssh root@173.249.51.164 "systemctl restart wa-gateway"    # при смене кода/секрета
ssh root@173.249.51.164 "systemctl restart kamilya-worker" # при deploy нового worker

# Обновить код воркера (ВАЖНО: pull на main, restart):
ssh root@173.249.51.164 "cd /opt/kamilya-worker && git pull && systemctl restart kamilya-worker"

# Update wa-gateway:
cd infra/wa-gateway && scp -r * root@173.249.51.164:/opt/whatsapp-gateway/
ssh root@173.249.51.164 "cd /opt/whatsapp-gateway && npm ci --omit=dev && systemctl restart wa-gateway"

# Ресурсы
ssh root@173.249.51.164 "free -h && df -h /opt && uptime"
```

> **Примечание по PowerShell:** одиночные кавычки в примерах выше используются только в bash (`ssh root@... "..."`). Из PowerShell адаптируй: `ssh root@... "command"` где внутренние кавычки экранируются через `"` или используется heredoc — **скобки внутри `"..."` ломают PowerShell parser**. Безопасный способ: `ssh root@... 'command-with-no-quotes'` или пиши `.sh` скрипт и вызывай его.

---

## Ресурсы VPS

- **CPU:** посмотри `nproc`
- **RAM:** 7.8 GiB (4 сервиса потребляют ~1.3 GiB обычно, есть запас)
- **Disk:** 72 GB SSD, ~37 GB свободно. Qwen/Embed на DGX, не здесь.
- **OS:** Ubuntu 24.04.4 LTS, kernel 6.8.0-124
- **Hostname:** `vmi3311535`
- **Uptime:** 24+ дня на момент обновления (стабильно)

Если место кончается — проверь `/var/log/` (`journalctl --vacuum-size=500M`) и `/opt/whatsapp-gateway/sessions/{tenant_id}/` (там могут копиться старые creds.json от deleted tenants — удалять через `rm -rf`).

---

## DNS через Cloudflare

| Record | Type | Value | Proxy |
|---|---|---|---|
| `qwen.kml.kz` | A | `173.249.51.164` | ✅ Proxied — Cloudflare edge → WG-туннель к DGX (не напрямую на этот VPS) |
| `qwen-embed.kml.kz` | A | `173.249.51.164` | ✅ Proxied — то же самое |
| `docling.kml.kz` | A | `173.249.51.164` | ✅ Proxied — nginx → :8600 |
| `wa.kml.kz` | A | `173.249.51.164` | ✅ Proxied — nginx → :8700 |
| `api.kml.kz` | A | `173.249.51.164` | ✅ Proxied — nginx → :8000 (dev-LMS) |
| `lms.kml.kz` | A | `173.249.51.164` | ✅ Proxied — nginx → :8080 (legacy Chamilo) |
| `app.kml.kz` | CNAME | `cname.vercel-dns.com` | ✅ Vercel, не наш VPS |
| `www.kml.kz` | CNAME | `cname.vercel-dns.com` | ✅ Vercel, landing site |

> **Важно:** хотя A-record `qwen.kml.kz` указывает на IP этого VPS, nginx-блока для этого домена тут нет. Cloudflare flexible/proxied через DNS-резолв пробрасывает трафик на DGX через WG-туннель — это настроено в конфигурации WG-маршрутизации на стороне Cloudflare Magic Transit или через split-tunnel. Если у тебя нет WG-маршрута на DGX — записи qwen.kml.kz **не работают** для внешних клиентов.

---

## Credentials (НЕ коммитить в git)

| Что | Где хранится | Где взять |
|---|---|---|
| SSH private key | `C:\Users\Askar\.ssh\id_vm` | Askar |
| SSH password (fallback) | `apps/api/.env` → `VPS_SSH_PASSWORD` | `Get-Content apps/api/.env | Select-String "VPS_SSH"` |
| `KAMILYA_BACKEND_SECRET` (HMAC для wa-gateway) | Render env + `/opt/whatsapp-gateway/.env` (на VPS) | `ssh root@... "cat /opt/whatsapp-gateway/.env | grep BACKEND_SECRET"` |
| Cloudflare API token | Askar's password manager | Askar |
| Postgres password | `apps/api/.env` → `DATABASE_URL` | `apps/api/.env` |

---

## Типичные задачи

### Запустить SQL на проде (Supabase) через VPS

PowerShell скрипт ломается на скобках внутри `psql` команды. Поэтому через VPS:

```bash
# 1. Положить SQL-файл
scp -i C:\Users\Askar\.ssh\id_vm query.sql root@173.249.51.164:/tmp/query.sql

# 2. Запустить (с VPS — pooler доступен, Supabase OK из EU)
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164 \
  "PGPASSWORD='$DB_PASS' psql -h aws-1-eu-central-1.pooler.supabase.com -p 5432 -U postgres.ducegbxphkgffgozkchw -d postgres -f /tmp/query.sql"
```

Где `$DB_PASS` берется из локального `.env` / password manager. **НЕ пиши пароль в git.**

### Проверить логи Celery worker (после apply-rules)

```bash
ssh root@173.249.51.164 "journalctl -u kamilya-worker --since '1 hour ago' -n 100"
```

Если видишь `ConnectionError: Error connecting to rediss://...`, проверь `valkey-server`, срок TLS-сертификата, `valkey-certbot-renew.timer` и совпадение `REDIS_URL` в Render и `/opt/kamilya-worker/apps/api/.env`.

### Деплой нового кода в worker

```bash
ssh root@173.249.51.164 "cd /opt/kamilya-worker && git pull origin master && systemctl restart kamilya-worker"
```

Если менялся `tasks.py` или `core/celery_app.py` — обязательно restart, иначе worker продолжит работать со старым bytecode.

### Деплой wa-gateway

```bash
cd infra/wa-gateway
scp -r * root@173.249.51.164:/opt/whatsapp-gateway/
ssh root@173.249.51.164 "cd /opt/whatsapp-gateway && npm ci --omit=dev && systemctl restart wa-gateway"
```

> ⚠️ ВАЖНО: `systemctl restart wa-gateway` рвёт persistent socket к Meta. Если ты restart'нул — **все тенанты которые были онлайн в WhatsApp получат disconnect** (но creds.json сохранится, при следующем запросе re-auth прозрачно). Делай это в низкий трафик (ночь/выходные).

### Перезапуск Docling

```bash
ssh root@173.249.51.164 "systemctl restart docling"
```

Docling держит model в памяти (~500 MB). После restart первый запрос будет медленным (cold load ~10 сек). Это OK.

---

## Troubleshooting table

| Симптом | Причина | Решение |
|---|---|---|
| `qwen.kml.kz/v1/models` → 502/503 | DGX упал или WG-туннель мёртв | `wg show` на VPS, проверь `ping 10.66.66.7`. Failover на DeepSeek сработает автоматически (см. ADR-0007). |
| Celery task висит `pending` | Worker или Valkey недоступен | `systemctl status kamilya-worker valkey-server`, TLS `PING`, затем проверить одинаковый `REDIS_URL`. |
| `docling.kml.kz/health` → 502 | OOM killed или упал процесс | `journalctl -u docling -n 50`. Проверь `free -h`. Если OOM — уменьши `MAX_WORKERS` в `/opt/docling-service/.env`. |
| `wa.kml.kz/health` → 200, но сообщения не уходят | Тенант залогинен в WhatsApp, но socket disconnected | Проверь логи: `journalctl -u wa-gateway`. Если "connection closed" — бэкенд автоматически reconnect (Baileys), обычно за 30 сек. Если persists — может быть ban от Meta. |
| SSH key rejected при подключении | Ключ не подхватывается | Проверь `~/.ssh/config`, у Askar'a есть ready alias "173.249.51.164". Или используй `-i C:\Users\Askar\.ssh\id_vm` явно. |
| Chamilo-страница открывается вместо LMS | user зашёл на `lms.kml.kz` — это legacy домен | Правильный домен: **`app.kml.kz`** (Vercel). Если видишь Chamilo = зашёл по старой закладке. |
| `api.kml.kz/docs` → connection timeout извне | Домен `api.kml.kz` смотрит на dev-инстанцию на VPS, не на Render prod | Используй `https://kamilya-lms-api.onrender.com` для prod API. `api.kml.kz` — только для локального дебага через VPN. |

---

## Связанные документы

- `INFRA_CELERY_WORKER.md` — детальный runbook deploy'а worker'а (создание systemd unit, env, Redis setup, apply-rules).
- `PROJECT-CONTEXT.md` — общая карта инфраструктуры (Vercel, Render, Supabase, DGX, VPS).
- `docs/adr/0007-ai-pipeline-failover.md` — как LLM-failover работает (Qwen → DeepSeek → cloud).
- `docs/adr/0006-multi-channel-delivery.md` — почему wa-gateway часть архитектуры.
- `docs/LESSONS.md` — там уроки про wa-gateway auth (session, tenant_id JSON serialization gotcha).

---

## История изменений

- **2026-07-01 (Mavis):** Полная перезапись старого `VPS_CONNECTION_GUIDE.md`. Исправлены ошибки (`qwen` не на этом VPS, добавлен `kamilya-worker`, разделение prod/dev/legacy, удалён SSH-пароль из git).
- **2026-06-24 (Askar):** Оригинальный `VPS_CONNECTION_GUIDE.md` создан. Базовое описание сервисов.
- **2026-06-30 (Mavis):** `kamilya-worker` запущен (commit `4b3f0d4`) — не отражён в старом документе.
</content>
</invoke>
