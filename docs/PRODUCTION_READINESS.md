# Kamilya LMS: готовность первого production-тенанта

**Проверено:** 2026-07-27
**Технический P0:** закрыт
**Режим запуска:** контролируемый первый пилот
**Назначение:** единственный актуальный реестр production-gates. История изменений
остаётся в Git; отдельные датированные отчёты не используются как источник
текущего состояния.

## Release manifest

| Контур | Состояние | Подтверждение |
|---|---|---|
| Application baseline | PASS | Проверенный runtime-код: `a5edcc264ade3acf4b40a6dcbcd9ffca2f9f4944`; последующие docs-only commits не меняют эту baseline |
| CI | PASS | GitHub Actions `30248028415`, полный pipeline |
| External smoke | PASS | GitHub Actions `30248028427`, API и frontend |
| Frontend | PASS | Vercel production `READY`, application baseline `a5edcc2` |
| API | PASS | Render deploy `dep-d9jh01n41pts73clnefg`, `live`, commit `a5edcc2` |
| Worker | PASS | `/opt/kamilya-worker` на `a5edcc2`, unit active, Celery ping отвечает |
| Database | PASS | production PostgreSQL 17.6, Alembic `0078` |

## Закрытые P0

### Public auth и rate limiting

- OTP и Telegram-коды не выводятся в application logs.
- Ошибки провайдера не возвращаются клиенту.
- Все public auth routes fail closed при недоступности Valkey.
- После краткого сбоя limiter повторно подключается через 5 секунд, поэтому
  login не остаётся заблокированным до рестарта API.
- Login/register/OTP всегда ограничиваются по IP; неподписанный JWT не может
  подменить bucket.
- Реально применяются burst, minute и hour windows.
- Production probe: четвёртый запрос в burst получил `429` и
  `Retry-After: 10`; после cooldown endpoint снова отвечал.

### Trial concurrency

- Проверка и резервирование AI/JD generation выполняются атомарно.
- Лимиты курсов, обучающихся и системных пользователей защищены tenant row lock.
- Первый `TenantUsage` создаётся под тем же lock.
- PostgreSQL concurrency tests покрывают AI, course, learner и staff import.

### Backup и восстановление

- На VPS установлен только PostgreSQL client 17.10; production DB остаётся в
  Supabase.
- `kamilya-backup.timer` active/enabled, ежедневный запуск около 02:15.
- Backup хранится локально только в AES-256-CBC + PBKDF2 виде.
- Passphrase, pgpass и service env имеют режим `0600`; backup directory `0700`.
- Реальный архив `kamilya_20260727T072839Z.dump.enc`: 6 402 000 bytes,
  режим `0600`, внутренний TOC проверен `pg_restore`.
- Plaintext dump после backup не остаётся.
- Реальный restore drill выполнен в одноразовый PostgreSQL 17 + pgvector:
  Alembic `0078`, 56 public tables, агрегаты тестовых данных восстановлены.
- Portable Supabase restore явно исключает platform-owned
  `supabase_vault`/`vault` data и создаёт отсутствующую schema dependency
  `lms_app` как `NOLOGIN`. Runtime password/LOGIN на новом кластере задаётся
  отдельным provisioning-шагом.
- После drill одноразовый контейнер и локальная копия архива удалены.

### Наблюдаемость

- `kamilya-ops-check.timer` active/enabled, запуск каждые 5 минут.
- Проверяются worker unit, Valkey unit, API, frontend, возраст backup,
  заполнение диска и реальный Celery inspect ping.
- Alert/recovery отправляются через Resend; неуспешная отправка не включает
  cooldown и будет повторена.
- Тестовое monitoring-письмо принято Resend.
- GitHub production smoke работает каждые 15 минут и на каждый push в `master`;
  при сбое открывает или обновляет incident issue, при восстановлении закрывает.
- Legacy `kamilya-trial-expiry.timer` отключён.

## Проверки кода

- Backend suite: 575 tests passed до финальных rate-limit изменений.
- Финальные rate-limit tests: 18 passed; Ruff и mypy passed.
- Финальный полный CI на `a5edcc2` passed.
- Frontend: 146 tests passed, typecheck passed, production build passed.
- Tenant/release/shell security gates passed.
- Graphify code graph обновлён после изменений.

## Обязательный smoke первого пилота

Технический P0 не заменяет прикладную приёмку. Перед выдачей доступа конкретному
клиенту на отдельном тестовом tenant нужно пройти:

1. регистрацию компании, email OTP, повторный вход и logout;
2. создание methodologist как второй роли/пользователя;
3. загрузку и индексацию двух небольших документов;
4. одну обычную AI-генерацию и одну генерацию по должностной инструкции;
5. review, публикацию курса и теста;
6. ручное добавление сотрудника и один XLSX import;
7. автоматическое правило и ручное назначение без дублей;
8. приглашение, прохождение уроков/теста, завершение и сертификат;
9. запись в журнале обучения и человекочитаемый CSV/XLSX export;
10. проверку backend-enforcement trial-лимитов.

Результат фиксируется в этом документе как дата и итог, без создания нового
«финального отчёта».

## Условные launch-gates

| Условие продажи | Что требуется |
|---|---|
| Клиент требует хранение персональных данных в Казахстане | Завершить KZ DB/storage cutover или письменно согласовать текущую географию Supabase |
| В пилот продаётся SCORM 1.2 | Пройти реальный пакет iSpring/Articulate: import, launch, resume, commit, completion, журнал |
| В пилот продаётся kiosk | Пройти privacy/auto-logout QA на реальном устройстве |
| Обещается 500 одновременных пользователей | Провести отдельный capacity test с p95, 5xx, DB connections, queue wait, CPU/RAM/disk |
| Нужен автоматический billing | До реализации использовать явно описанную ручную активацию superadmin |

Не заявлять ЭЦП, юридическое соответствие, SCORM, kiosk или локализацию данных как
закрытые свойства без прохождения соответствующего gate.

## Открытый P1

Продуктовые улучшения ведутся только в
[`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md). Они не смешиваются с закрытыми
операционными P0 выше.
