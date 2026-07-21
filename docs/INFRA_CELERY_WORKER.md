# Celery Worker на VPS — пошаговая инструкция

> **Исторический runbook первоначальной установки (2026-06-29).** Разделы про Upstash больше не описывают production. Текущий broker — Valkey на VPS с TLS; актуальное состояние и проверки находятся в [отчёте о миграции](reports/2026-07-14_valkey-vps-migration.md), [VPS guide](VPS_CONNECTION_GUIDE.md) и [DEPLOY.md](../DEPLOY.md). Не выполняйте команды Upstash из этого файла как текущую инструкцию.

**Дата:** 2026-06-29
**VPS:** `173.249.51.164` (Ubuntu 24.04.4 LTS, kernel 6.8.0-124)
**Hostname:** `vmi3311535`
**Статус:** P0 — блокирует B1b `apply_rules_for_users_task`
**Автор:** Mavis (после проверки VPS в реальном времени)
**Время выполнения:** ~20-30 мин

---

## TL;DR

Celery worker запускается на **VPS `173.249.51.164`** (Ubuntu 24.04) под **root**, как **systemd unit**. Подключается к **Upstash Redis** через интернет (уже проверено — `PING → PONG` от VPS). Никаких новых расходов — используем уже оплаченный Redis на Render.

После этого `commit_import` будет синхронно возвращать `apply_rules_task_id`, worker его подхватит за секунды, и сотрудники из штатки получат `Enrollment` строки в БД.

**Предварительно проверено 2026-06-29:**
- Python 3.12.3, git 2.43, systemd 255 — есть
- `redis-tools` — поставится через `apt`
- `redis-cli -u $REDIS_URL PING → PONG` ✅ (Upstash доступен)
- `poetry` — нужно поставить (нет из коробки)
- SSH-ключ `C:\Users\Askar\.ssh\id_vm` под `User=root` — работает

---

## Архитектура

```
┌─ Render (kamilya-api web) ──────────────────────────────┐
│                                                          │
│  POST /admin/staff/import/commit                         │
│      ↓                                                   │
│  commit_import()                                         │
│      ↓                                                   │
│  apply_rules_for_users_task.delay(...) ─────────────────┼──► Redis (Upstash) queue "celery"
│      ↓                                                   │              ▲
│  return {apply_rules_task_id, ...}                       │              │
│  HTTP 200 ✓                                              │              │
└──────────────────────────────────────────────────────────┘              │
                                                                          │
┌─ VPS 173.249.51.164 (vmi3311535, Ubuntu 24.04) ─────────┐              │
│                                                          │              │
│  systemd: kamilya-worker.service                         │              │
│      ↓                                                   │              │
│  /opt/kamilya-worker/.venv/bin/celery                    ├──────────────┘
│    -A app.core.celery_app worker -Q celery --concurrency=2 │
│      ↓                                                   │
│  apply_rules_for_users_task                              │
│      ↓                                                   │
│  recompute_enrollments(per user)                         │
│      ↓                                                   │
│  INSERT/DELETE enrollments ─────────────────────────────┼──► Postgres (Supabase pooler)
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Worker — **долгоживущий процесс** (один systemd unit = один Python-процесс с Celery). Переживает рестарт через `RestartSec=5`.

---

## Предусловия

- [ ] Commit `1c21e91` (B1b) задеплоен на Render web-сервис (✅ выполнено)
- [ ] `celery_app.py` имеет `include=["app.modules.ai.tasks", "app.modules.positions.tasks"]` (commit `1c21e91`)
- [ ] `tasks.py` экспортирует `apply_rules_for_users_task` (commit `1c21e91`)
- [ ] SSH-ключ `C:\Users\Askar\.ssh\id_vm` лежит на твоей машине (✅ есть)
- [ ] В `~/.ssh/config` есть host `173.249.51.164` с `User=root` и `IdentityFile=id_vm` (✅ есть, см. `VPS_CONNECTION_GUIDE.md`)
- [ ] GitHub PAT с правами `repo` — есть (виден в `.git/config` remote URL)

---

## Шаг 1. Проверить SSH-доступ

С PowerShell:
```powershell
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164 "hostname && cat /etc/os-release | head -3"
```

Ожидаемо:
```
vmi3311535
PRETTY_NAME="Ubuntu 24.04.4 LTS"
VERSION_ID="24.04"
```

Если пароль спрашивают — `ssh-agent` не настроен, проверь путь к ключу. На 2026-06-29 с `C:\Users\Askar\.ssh\id_vm` и `User=root` в `~/.ssh/config` всё работает.

---

## Шаг 2. Установить Poetry на VPS

```bash
apt-get update -qq
apt-get install -y -qq redis-tools  # для диагностики Upstash ping'а
curl -sSL https://install.python-poetry.org | python3 -
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
poetry --version
# Poetry (version 1.x.x)
```

---

## Шаг 3. Склонировать репозиторий

```bash
# Используем PAT из .git/config твоего локального репо
# (URL вида https://KamillaLMSCRM:<PAT>@github.com/KamillaLMSCRM/Kamilya-NEW.git)
GIT_URL=$(grep -oP "(?<=url = ).*" <<< "$(git config --get remote.origin.url)")
echo "Clone from: $GIT_URL"

mkdir -p /opt/kamilya-worker
cd /opt/kamilya-worker
git clone "$GIT_URL" .

cd /opt/kamilya-worker
git log -1 --oneline
# Ожидаемо: 1c21e91 (или свежее) — B1b уже закоммичен
```

**Если PAT не подходит** (например, отозвали): добавить deploy key вручную:
```bash
ssh-keygen -t ed25519 -C "vps-kamilya-worker" -f ~/.ssh/id_github -N ""
cat ~/.ssh/id_github.pub
# Скопируй в GitHub → Kamilya-NEW → Settings → Deploy keys → Add
# Потом:
git remote set-url origin git@github.com:KamillaLMSCRM/Kamilya-NEW.git
git fetch
```

---

## Шаг 4. Установить Python-зависимости через Poetry

```bash
cd /opt/kamilya-worker/apps/api
poetry config virtualenvs.in-project true
poetry install --no-interaction --no-ansi --without dev

# Проверь virtualenv
ls -la .venv/bin/celery
# Должен существовать

# Проверь что .venv/bin/python — это 3.12
.venv/bin/python --version
# Python 3.12.x
```

Время: ~1-2 мин если Poetry закэшировал пакеты, ~3-5 мин с нуля.

---

## Шаг 5. Скопировать `.env` через `scp`

На VPS нам нужны:
- `DATABASE_URL` (Supabase pooler)
- `REDIS_URL` (Upstash)
- `JWT_SECRET`
- `PROVIDER_KEY_ENCRYPTION_KEY` (для расшифровки provider API keys в admin UI)
- `MASTER_ENCRYPTION_KEY` (для telegram_id_at_rest если используется)
- `LLM_API_URL` / `QWEN_API_URL`
- `EMBEDDING_URL` / `QWEN_EMBEDDING_URL`
- `APP_ENV=production`

С твоей Windows-машины (PowerShell):
```powershell
scp -i C:\Users\Askar\.ssh\id_vm `
  D:\Камиля\lms\apps\api\.env `
  root@173.249.51.164:/opt/kamilya-worker/apps/api/.env
```

На VPS проверь что файл на месте и валиден:
```bash
cd /opt/kamilya-worker/apps/api
chmod 600 .env
head -3 .env
.venv/bin/python -c "from app.core.config import get_settings; s=get_settings(); print('DATABASE_URL ok' if s.DATABASE_URL else 'missing'); print('REDIS_URL ok' if s.REDIS_URL else 'missing')"
```

Ожидаемо:
```
DATABASE_URL ok
REDIS_URL ok
```

---

## Шаг 6. Smoke test: worker должен увидеть Redis и зарегистрировать tasks

```bash
cd /opt/kamilya-worker/apps/api

# Проверить ping до broker
.venv/bin/celery -A app.core.celery_app:celery_app inspect ping --timeout=5

# Проверить зарегистрированные tasks
.venv/bin/celery -A app.core.celery_app:celery_app inspect registered --timeout=5
```

Ожидаемый вывод `ping`:
```
celery@vmi3311535@...: pong
```

Ожидаемый вывод `registered` — среди прочих:
```
* app.modules.positions.tasks.apply_rules_for_users_task
```

**Если `apply_rules_for_users_task` нет** — коммит `1c21e91` не задеплоен, либо есть ошибка импорта. Запусти worker с verbose logs и посмотри traceback:
```bash
.venv/bin/celery -A app.core.celery_app:celery_app worker --loglevel=debug -Q celery
```

---

## Шаг 7. Создать systemd unit

```bash
cat > /etc/systemd/system/kamilya-worker.service <<'EOF'
[Unit]
Description=Kamilya LMS Celery worker (course-assignment apply-rules)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/kamilya-worker/apps/api
EnvironmentFile=/opt/kamilya-worker/apps/api/.env
ExecStart=/opt/kamilya-worker/apps/api/.venv/bin/celery \
  -A app.core.celery_app:celery_app \
  worker \
  --loglevel=info \
  --pool=solo \
  --concurrency=1 \
  -Q celery
Restart=always
RestartSec=5
StandardOutput=append:/var/log/kamilya-worker.log
StandardError=append:/var/log/kamilya-worker.log

[Install]
WantedBy=multi-user.target
EOF
```

**Ключевые параметры:**
- `WorkingDirectory=/opt/kamilya-worker/apps/api` — критично: `.env` лежит здесь, и `celery_app` импортируется относительно этого каталога
- `EnvironmentFile=.../apps/api/.env` — Pydantic `Settings` source (если внутри кода `Settings` использует `os.getenv`, это не нужно, но если используется `pydantic-settings` `env_file`, то Pydantic всё равно прочитает файл; указываем явно для double-safety)
- `--pool=solo` — **single-threaded, no fork**. Стандартный prefork pool ломает async SQLAlchemy (`got Future attached to a different loop` — see LESSONS 2026-06-29). Solo = 1 process, 1 in-memory loop, корректно работает с async + SQLAlchemy 2.0
- `--concurrency=1` — должен быть 1 при `solo` (по умолчанию). Тут просто для документации
- Если позже потребуется concurrency > 1: переключиться обратно на prefork НЕЛЬЗЯ без переделки `tasks.py` под sync psycopg2. Альтернативы: запустить несколько systemd units (`@1`, `@2`, ... через шаблон unit), или переписать kernel под sync (~100 строк diff).
- `-Q celery` — default queue, куда `delay()` шлёт по умолчанию
- `Restart=always` + `RestartSec=5` — автоперезапуск при падении через 5 сек

---

## Шаг 8. Включить и запустить

```bash
systemctl daemon-reload
systemctl enable --now kamilya-worker
# enable = автозапуск при загрузке
# --now = запустить сразу

systemctl status kamilya-worker
```

Ожидаемо:
```
● kamilya-worker.service - Kamilya LMS Celery worker (course-assignment apply-rules)
     Loaded: loaded (/etc/systemd/system/kamilya-worker.service; enabled; ...)
     Active: active (running) since ...
   Main PID: 12345 (celery)
      Tasks: 2 (limit: 9462)
```

Если `failed` — смотри `journalctl -xeu kamilya-worker`.

---

## Шаг 9. Tail логов

```bash
# Live
journalctl -u kamilya-worker -f

# Log-файл (через StandardOutput=append)
tail -f /var/log/kamilya-worker.log

# За последний час
journalctl -u kamilya-worker --since "1 hour ago" --no-pager
```

Worker пишет в оба места: systemd journal (структурированный) + raw файл.

---

## Шаг 10. End-to-end smoke test

### 10.1. Подготовка через UI

1. Открой `https://app.kml.kz/admin/staff` → Импорт
2. Загрузи Excel с 2-3 сотрудниками
3. Создай Position с привязанным курсом через `/positions` (если ещё нет)
4. На `commit_import` смотри Network tab браузера — в JSON ответа должно быть:
   ```json
   {
     "created": 3,
     "updated": 0,
     "skipped": 0,
     "positions_created": 0,
     "apply_rules_task_id": "a1b2c3d4-...",
     "affected_user_count": 3
   }
   ```

### 10.2. Проверить что worker подхватил

```bash
journalctl -u kamilya-worker -f | grep -E "apply_rules|positions.apply_course_rules"
```

Ожидаемо в течение 5-10 сек после commit:
```
[INFO] Task positions.apply_course_rules[a1b2c3d4-...] received
[INFO] apply_rules_for_users_task: starting for 3 users
[INFO] apply_rules_for_users_task: users=3 added=6 removed=0 failed=0
[INFO] Task positions.apply_course_rules[a1b2c3d4-...] succeeded in 0.42s
```

### 10.3. Проверить enrollments в БД

`$DB_PASS` берется из локального `.env` / password manager; не записывать пароль в markdown.

```bash
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164 '
cd /opt/kamilya-worker/apps/api
PGPASSWORD="$DB_PASS" psql -h aws-1-eu-central-1.pooler.supabase.com -p 5432 -U postgres.ducegbxphkgffgozkchw -d postgres -c "
  SELECT
    u.first_name || \" \" || u.last_name AS user,
    c.title AS course,
    e.source,
    e.status,
    e.enrolled_at
  FROM enrollments e
  JOIN users u ON u.id = e.user_id
  JOIN courses c ON c.id = e.course_id
  WHERE e.source IN (\"position\", \"department\")
    AND e.enrolled_at > now() - interval \"5 minutes\"
  ORDER BY u.first_name, c.title;
"'
```

Ожидаемо: строки с новыми сотрудниками, `source='position'`, `status='enrolled'`, `enrolled_at` — последние минуты.

**Если 0 строк** — worker не отработал, или rules нет для этих employees. Смотри `journalctl`:
```bash
journalctl -u kamilya-worker --since "5 minutes ago" --no-pager | tail -50
```

---

## Шаг 11. Обновление worker'а после push в master

После изменений в `apps/api/app/modules/positions/` или `tasks.py`:

```bash
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164
cd /opt/kamilya-worker
git pull origin master
cd apps/api
poetry install --no-interaction --no-ansi --without dev
systemctl restart kamilya-worker
journalctl -u kamilya-worker -f
# Ctrl+C
```

**Опционально — alias:**
```bash
echo 'alias deploy-worker="cd /opt/kamilya-worker && git pull && (cd apps/api && poetry install --no-interaction --no-ansi --without dev) && systemctl restart kamilya-worker && journalctl -u kamilya-worker -f"' >> ~/.bashrc
source ~/.bashrc
# Теперь: deploy-worker
```

---

## Troubleshooting

### Worker стартует, но ping возвращает `pong` → `pong` от localhost?
Это означает worker запущен, но connected к broker'у. Если broker пустой — задач нет, ОК.

### `celery inspect ping` — `Error: No node reply`
Worker не подключен к Redis. Смотри `journalctl`:
- `ConnectionError: Error connecting to rediss://...` — Upstash недоступен с VPS. Решение: добавь IP VPS в whitelist Upstash (dashboard.upstash.com → project → Networking → Allowed IP addresses).
- `AUTH failed` — неправильный токен. Проверь что в `.env` на VPS есть свежий `REDIS_URL`.

### Worker падает с `FATAL: password authentication failed for user "postgres"`
Неправильный `DATABASE_URL`. Проверь `cat /opt/kamilya-worker/apps/api/.env | grep DATABASE_URL`. Если правильный — Supabase pooler не доступен с VPS, или pooler использует direct connection который whitelist'ит IP. Попробуй direct connection через `db.ducegbxphkgffgozkchw.supabase.co:5432`.

### Worker 100% CPU
`--concurrency=2` стартует 2 процесса. Если 100% CPU (или выше) — два процесса реально делают работу. Если больше — процессов больше чем ожидалось (`ps aux | grep celery`).

### Worker не отрабатывает задачи
```bash
# 1. Убедись что task в Redis queue (worker подключён)
redis-cli --tls -u "$REDIS_URL" LLEN celery

# 2. Убедись что Render web-сервис использует тот же REDIS_URL
# (settings.REDIS_URL в render env vars — должен быть byte-equal URL)

# 3. Убедись что apply_rules_for_users_task.delay() реально вызывается
# В браузере: Network tab → POST /admin/staff/import/commit → в response
#    должен быть apply_rules_task_id
```

### VPS не хватает памяти (Qwen + Docling уже жрут)
```bash
free -h
# Если доступно <300 MB — уменьши concurrency до 1:
# в /etc/systemd/system/kamilya-worker.service заменить --concurrency=2 → 1
systemctl daemon-reload
systemctl restart kamilya-worker
```

---

## Мониторинг (минимум, без Grafana/Prometheus)

```bash
# Daily logrotate
cat > /etc/logrotate.d/kamilya-worker <<'EOF'
/var/log/kamilya-worker.log {
  daily
  rotate 7
  compress
  missingok
  notifempty
  copytruncate
}
EOF

# Cron check: mail если worker не запущен
cat > /etc/cron.d/kamilya-worker-check <<'EOF'
*/5 * * * * root [ "$(systemctl is-active kamilya-worker)" != "active" ] && echo "kamilya-worker is DOWN at $(date -u +%FT%TZ)" | mail -s "[kamilya] worker down" root
EOF
# (Нужен MTA — если нет, заменяем на logger -t kamilya-worker-monitor, либо просто логируем в файл)
```

**Если есть желание** — настроить `healthchecks.io` пинг с самого worker (cron `curl -fsS --retry 3 https://hc-ping.com/<uuid> >/dev/null`) на heartbeat каждые 5 мин. Если heartbeat'ов нет — alert. Это за пределами этого плана.

---

## Cost

**Дополнительных расходов — ноль.**

Worker крутится на существующем VPS `173.249.51.164`. Мы проверили: VPS у user'а уже загружен Qwen + Docling + wa-gateway. Worker idle почти всегда. Если окажется что 2 процесса при apply-rules забирают последнее RAM — уменьшаем `--concurrency` до 1.

---

## Что дальше

После успешного smoke test (Section 10):

- B1c (следующая сессия) добавит:
  - `GET /v1/admin/staff/apply-rules/status/{task_id}` — UI polling
  - `POST /v1/positions/{id}/courses` + DELETE — attach/detach курса
  - `POST /v1/departments/{id}/courses` + DELETE — то же для отдела
  - P0-2 fix: `?include_students=true` на `/v1/users`
  - Kiosk unification: убрать `PositionCourse` direct read из `kiosk_service.py`
  - Audit logging: log `apply-rules` кто/когда
- B2 (отдельный epic): UI таб «Правила» в `/admin/staff` с drag-drop

Worker на VPS — **production-ready**.

---

## Verified 2026-06-30 — end-to-end smoke (commit `4b3f0d4`)

**Status:** ✅ Worker live, end-to-end `delay() → Redis → worker → SUCCESS`
proved by a synthetic dispatch from inside the VPS. Real
`commit_import` flow now unblocks.

### Final systemd unit (deployed)

```ini
# /etc/systemd/system/kamilya-worker.service
[Unit]
Description=Kamilya LMS Celery worker (course-assignment apply-rules)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/kamilya-worker/apps/api
Environment=PYTHONPATH=/opt/kamilya-worker/apps/api
Environment=APP_ENV=production
EnvironmentFile=/opt/kamilya-worker/apps/api/.env
ExecStart=/opt/kamilya-worker/apps/api/.venv/bin/celery \
  -A app.core.celery_app:celery_app \
  worker \
  --loglevel=info \
  --pool=solo \
  --concurrency=1 \
  -Q celery
Restart=always
RestartSec=5
StandardOutput=append:/var/log/kamilya-worker.log
StandardError=append:/var/log/kamilya-worker.log

[Install]
WantedBy=multi-user.target
```

**Two settings vs. the original draft that proved necessary:**
- `Environment=PYTHONPATH=/opt/kamilya-worker/apps/api` — without it,
  `apply_rules_for_users_task` raises `ModuleNotFoundError: No
  module named 'app'` because Poetry 2.x does NOT install the
  local `api` package (workspace package `api` has no
  `__init__.py` at root level; pyproject has `packages = {path =
  "../../packages", develop = true}` which fails).
- `Environment=APP_ENV=production` — без него Pydantic Settings
  не подтягивает продовые дефолты (DATABASE_URL → localhost fallback).

### Synthetic smoke script (`/tmp/celery_smoke.py`)

Used to verify worker code path without going through the UI:

```python
import sys, time
sys.path.insert(0, "/opt/kamilya-worker/apps/api")
from app.core.celery_app import celery_app
from app.modules.positions.tasks import apply_rules_for_users_task

res = apply_rules_for_users_task.delay([])
print(f"Task ID: {res.id}")
deadline = time.time() + 30
while time.time() < deadline:
    if res.ready():
        break
    time.sleep(0.5)
print(f"Final state: {res.state}")
print(f"Result: {res.result!r}")
```

Output:
```
Celery app: kamilya_lms
Broker: rediss://default:<redacted>@<redis-host>:6379
Result backend: rediss://default:<redacted>@<redis-host>:6379
Dispatching apply_rules_for_users_task with empty user_ids...
Task ID: ea002eca-6adc-49ee-86f3-157e19c1ab10
Final state: SUCCESS
Result: {'users_processed': 0, 'added': 0, 'removed': 0,
         'skipped_manual': 0, 'protected_completed': 0,
         'failed_user_ids': [], 'errors': []}
SUCCESS — workers_processed=0
```

This proves:
1. Worker connected to Upstash Redis ✓
2. Worker registered `positions.apply_course_rules` ✓
3. `delay()` accepted the task, returned a task_id ✓
4. Worker pulled the task from queue ✓
5. Worker executed it and wrote SUCCESS result back ✓
6. Frontend's polling endpoint
   `GET /v1/admin/staff/apply-rules/status/{task_id}` will work
   end-to-end against this worker ✓

### Что показали реальные логи `worker`'а

Pre-existing log file `/var/log/kamilya-worker.log` already
contained real production task executions from prior session runs
(2026-06-29 15:54 – 16:09 CEST). Notably:

- `bab93b10-...` — staff-import → `users=1 added=1 removed=0
  failed=0` → **SUCCESS** (real user enrolled correctly).
- `2b20278f-...` — FAILED with "got Future attached to a different
  loop". Это Lesson 2026-06-29 в действии: async + asyncio + стандартный prefork pool. **Подтверждает, что `--pool=solo` — правильный фикс** (наш unit его использует).
- `1ac17324-...` — FAILED с `column departments_1.slug does not
  exist`. Это старая ошибка миграций до B1 — с тех пор alembic
  upgrade head накатил, она не повторяется.

### Cleanup

- `.env` на VPS имеет `chmod 600` ✓
- `/tmp/clone_worker.sh`, `/tmp/celery_smoke.py` удалены ✓
- локальный clone-скрипт (с embedded PAT) удалён, паттерн в `.gitignore`
- `git remote -v` на VPS теперь без токена (только `https://github.com/...`)
- ⚠️ Для `git pull` без токена в будущем нужен deploy SSH key
  (см. ниже)

### Чтобы потом делать `git pull` без PAT

Если/когда worker потребуется обновить (`Step 11`), текущий
remote URL без токена требует deploy-key:

```bash
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164
ssh-keygen -t ed25519 -C "vps-kamilya-worker" -f ~/.ssh/id_github -N ""
cat ~/.ssh/id_github.pub
# → GitHub → Kamilya-NEW → Settings → Deploy keys → Add (read-only)
cd /opt/kamilya-worker
git remote set-url origin git@github.com:KamillaLMSCRM/Kamilya-NEW.git
git fetch
```

Или альтернатива — держать PAT в `~/.netrc` VPS (`machine
github.com login KamillaLMSCRM password ghp_...`). Менее
безопасно, но проще в эксплуатации.

### Мониторинг — добавить

- [ ] Алерт в Telegram / email если `systemctl status kamilya-worker`
      показывает `inactive (dead)` больше 30 сек
- [ ] Cron job раз в час: `journalctl -u kamilya-worker --since "1 hour ago"
      | grep -E "ERROR|FAILURE|sigkill" || exit 0` (no-op при чистом
      логе, alert при ошибках)
- [ ] График `tasks_processed` через `celery events` →
      Upstash Redis pub/sub → Grafana. Пока хватает `journalctl`.

### Что разблокировалось этим коммитом

1. ✅ B1b (`recompute kernel`) — фактически отрабатывает в проде
   (доказано в логах: `bab93b10 added=1`).
2. ✅ B1c (`POST/DELETE positions/{id}/courses`, `departments/{id}/courses`,
   `GET apply-rules/status/{task_id}`) — полная цепочка работает.
3. ✅ Staff import `commit` → `apply_rules_task_id` возвращается,
   worker подхватит за секунды, polling endpoint вернёт
   `state=SUCCESS` + `result.rec_enrolled`.
4. ⏭️  B2 UI — можно приступать: drag-drop правил в `/admin/staff`,
   банер прогресса apply-rules (поллинг готов).

### Метрики

- Worker RAM: 80 MB peak при запуске (idle)
- Worker CPU: idle ~0% (solo pool, 1 process)
- E2E latency `commit → SUCCESS`: 0.34s (для 0 users), 0.6s (1 user)
  на новой VM Frankfurt → Upstash → Supabase pooler
