### Live QA: используй production credentials вместо docker (2026-07-10)
Type: workflow
**Симптом:** Потратил 40 минут на поднятие локального docker stack (Postgres + Redis +
MinIO + alembic migrations) для QA. Застрял на сломанных миграциях. Результат:
0 production-данных, только frustration.

**Root cause:** Инерция "поднять dev stack и проверить". Не проверил что уже
есть `DATABASE_URL` (Supabase) и `RENDER_API_KEY` в `apps/api/.env` —
можно делать QA напрямую против production.

**Fix:** Всегда начинай QA с чеклиста:
1. `Get-Content apps/api/.env | Select-String '^(DATABASE_URL|RENDER_API_KEY|.*_TOKEN)'` — что доступно?
2. Production health: `curl https://<api-url>/health` — отвечает?
3. OpenAPI: `curl <api-url>/api/v1/openapi.json` — какие endpoints?
4. DB: `python + psycopg2 + DATABASE_URL` — реальные counts.

Если production отвечает — работай там. Локальный docker нужен только для
разработки новых фич, не для QA существующего продукта.

**Detection rule:** Перед `docker compose up` спроси себя — "у меня уже есть
прямой доступ к prod? Если да — зачем docker?" Если ответ "ну я не подумал"
— стоп, иди в production.

**Экономия:** 40 минут → 5 минут. Плюс — реальные данные, не synthetic.

### RLS policy `tenant_isolation` блокирует INSERT новых users в production (2026-07-10)
Type: bug-pattern
**Симптом:** `/auth/register` и `/auth/demo-login` падают с 500 в production:
```
sqlalchemy.exc.ProgrammingError: InsufficientPrivilegeError:
new row violates row-level security policy for table "users"
```

**Root cause:** RLS policy на `users`:
```sql
USING:  users.tenant_id = current_setting('app.tenant_id', true)
CHECK:  users.tenant_id = current_setting('app.tenant_id', true)
```
При INSERT нового user, `app.tenant_id` ещё не установлен в DB-сессии
(новый tenant только что создан). `current_setting(..., true)` возвращает
NULL → сравнение `tenant_id = NULL` = UNKNOWN → RLS deny.

**Fix (правильный):** В service layer перед INSERT нового user вызывать:
```python
await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"),
                  {"tid": str(tenant.id)})
```
`true` = local setting, не persistent. Это безопасно для connection pool
(PgBouncer transaction mode), потому что setting живёт только в транзакции.

**Альтернативный fix:** Добавить INSERT-policy которая bypass для случая
когда `app.tenant_id IS NULL` AND `tenant_id` NOT NULL в новой строке,
но это опасно — может привести к cross-tenant leaks.

**Detection rule:** Любой INSERT в таблицу с RLS `tenant_isolation` — проверь
что `app.tenant_id` уже установлен. Если нет — установи через `set_config`.

### Live data: 0 certificates + 0 methodologist users в production (2026-07-10)
Type: fact
Live snapshot 2026-07-10 06:01 UTC:
- `certificates=0` при 230 enrollments и 19 courses → certificate issue flow сломан
- `methodologist=0` users при том что в DEMO_USERS есть methodologist demo
- `tenant_settings=0` для всех 7 tenants → customization сломана
- `provider_keys=0` → все ключи только из env (нет DB redundancy)

Нужно расследовать каждое из этих в следующих ходах.

### SQLAlchemy 2.0: `Select.crossjoin()` удалён (2026-07-10)
Type: bug-pattern
**Симптом:** `/admin/dashboard` падает с 500:
```
AttributeError: 'Select' object has no attribute 'crossjoin'
File "apps/api/app/modules/admin/service.py", line 288, in get_activity_summary
```

**Root cause:** SQLAlchemy 2.0 удалил `Select.crossjoin()` метод. Регрессия
после upgrade SQLAlchemy — старый код не переписали.

**Fix:** Заменить `.crossjoin(table)` на:
```python
stmt = select(...).join(other_table, isouter=True, full=True)
# или
stmt = stmt.select_from(...).join(...)
```

**Detection rule:** При upgrade SQLAlchemy 1.x → 2.0 — grep по `\.crossjoin\(` в коде.
Также любой unhandled exception в runtime logs = приоритет P1 для QA.

### Upstash Redis исчерпал 500K бесплатных requests (2026-07-10)
Type: production-incident
**Симптом:** В runtime logs WARNING:
```
Redis not available (max requests limit exceeded. Limit: 500000, Usage: 500000)
- rate limiting DISABLED (fail-closed)
- auth sessions using in-memory fallback
```

**Root cause:** Upstash free tier = 500K requests/месяц. После исчерпания
Redis API возвращает errors, код переходит на fallback.

**Impact:**
- Rate limiting выключен — login endpoints не защищены от brute force
- Auth sessions in-memory — работает пока Render instance один
- Другие Redis-зависимые фичи молча деградируют

**Fix:**
1. Upgrade Upstash tier (~$10/month за 10M requests)
2. Или переключиться на Render Redis / self-hosted
3. Или мониторинг quota и алерт до исчерпания

**Detection rule:** Добавить Sentry alert / healthcheck на Redis quota.
Если Redis возвращает max-requests error → алерт в Slack.

### CSV exports без UTF-8 BOM (2026-07-10)
Type: bug
**Симптом:** `GET /admin/export/users` возвращает CSV с кириллицей,
которая нечитаема в PowerShell / Excel / Notepad (отображается как
`ID,Email,���,�������`).

**Root cause:** FastAPI `StreamingResponse(..., media_type="text/csv")`
без `charset=utf-8`. Без BOM Excel интерпретирует как cp1251.

**Fix:**
```python
return StreamingResponse(
    iter([b'\xef\xbb\xbf' + csv_content.encode('utf-8')]),
    media_type="text/csv; charset=utf-8",
    headers={"Content-Disposition": "attachment; filename=users.csv"}
)
```

**Detection rule:** Любой endpoint возвращающий CSV с non-ASCII — проверить
наличие BOM + charset в Content-Type.

### Superadmin password reset через прямой SQL (2026-07-10)
Type: workflow
**Контекст:** Для QA admin endpoints нужен superadmin token. Askar дал
разрешение "сам поменяй или сбрось".

**Алгоритм:**
1. Argon2-cffi установлен: `pip install argon2-cffi` (уже был)
2. `ph = PasswordHasher(); ph.hash("new-password")` → argon2id hash
3. `UPDATE users SET password_hash = '<hash>' WHERE email = 'admin@kamilya.kz' AND tenant_id IS NULL`
4. Verify через `/auth/superadmin-login` с новым паролем → 200

**Argon2 format:** `$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>`

**Где живёт platform superadmin:** таблица `users` где `tenant_id IS NULL`
(для платформенного operator-level суперадмина, отличается от tenant-level).

**Важно:** Сообщи Askar'у новый пароль чтобы он мог зайти или сменил обратно.