# Kamilya LMS Celery worker

## Повторное обучение

Задачи `learning_cycles.materialize` и `learning_cycles.recover_due` направляются в
очередь `maintenance`. Установите и включите
`kamilya-learning-cycle-recovery.timer`: oneshot-сервис каждую минуту вызывает
`python -m app.modules.learning_cycles.recovery`. Он выбирает не более 100
просроченных правил за запуск; уникальность occurrence и блокировка правила делают
повторные тики идемпотентными. Уведомление о новом назначении фиксируется в outbox
в той же транзакции, отправляется только после commit и восстанавливается отдельным
assignment-notification timer при недоступности брокера.

**Обновлено:** 2026-08-04
**Назначение:** текущий runbook worker. Исторические инструкции Upstash и старых
checkout удалены.

## Production topology

- Host: основной VPS Kamilya.
- Checkout: `/opt/kamilya-worker`.
- Units:
  - `kamilya-worker.service`: `notifications`, `maintenance` and legacy
    `celery`, concurrency 1;
  - `kamilya-worker-documents.service`: `documents`, concurrency 1;
  - `kamilya-worker-ai.service`: `ai`, prefork concurrency 2 and
    `max-tasks-per-child=20`.
- Broker/result backend: Valkey по TLS.
- Database: тот же runtime `DATABASE_URL`, что у API.
- Document conversion: локальный `http://127.0.0.1:8600` с тем же
  `DOCLING_API_KEY`, что у Docling service; timeout не менее 900 секунд для
  OCR больших сканированных PDF.
- Code: совместимый commit release, а не обязательно последний docs-only
  commit.

Маршрутизация задач:

- `ai`: генерация курса, модуля, урока и оценочных материалов;
- `documents`: первичная индексация и переиндексация документов;
- `notifications`: доставка приглашений и подписанных CRM lead events;
- `maintenance`: очистка документов, backfill хешей и применение правил
  обучения;
- `celery`: временно сохраняется только для безопасного дренирования старых
  сообщений.

## DEV topology (актуализировано 2026-11-04)

DEV использует единственный изолированный контейнер `kamilya-dev-worker` на
VM126, узел Celery `kamilya-dev-worker@vm126`, очереди
`ai,documents,maintenance`, concurrency=1. Production broker, база и consumers
не используются. DEV broker: прежний TLS Redis, logical database `/1`;
DEV application database — канонический Supabase DEV, runtime `lms_app`.
Контейнер ограничен 1 CPU/1 GiB, read-only root, без published ports и mounts,
cap-drop ALL, no-new-privileges. Старый Render Free worker
`srv-dar2dvbncjis73bsda3g` остаётся suspended/autoDeploy=no. Не будить его:
это создаст второй consumer. Публичный health старого Render worker не является
проверкой нынешнего DEV worker.

Релизная проверка: `scripts/deploy/dev_release_controller.py` с точным VM packet,
`scripts/ops/vm126_dev_worker_verify.sh` и совпадением SHA API/worker/frontend.
Probe проверяет pinned image, environment digest, непривилегированный процесс,
изоляцию и реальные Celery ping/queues. Новый env устанавливается исключительно
immutable receiver-скриптом, секреты идут в памяти через SSH stdin и не печатаются.
Перед обновлением — idle/queue proof, warm drain, сохранение предыдущего контейнера
и env для отката. Текущие runtime SHA и доказательства — `CODEX_HANDOFF.md` и
`PRODUCTION_READINESS.md`; Git push сам по себе не доказывает deploy.

### Временная ASUS DeepSeek через компьютер владельца

Владелец 2026-11-04 разрешил этот путь только для DEV. Прямой API
`http://10.66.66.20:8888/v1` доступен с Windows, но из VM/worker тайм-аут.
`scripts/dev/run_dev_asus_bridge.py` использует канонические credentials/known
hosts и тот же nested SSH transport, что проверенный Docling helper. Он создаёт
loopback `127.0.0.1:18890` внутри ТОЧНО указанного DEV контейнера; единственный
upstream — ASUS `10.66.66.20:8888`. Публичного listener, нового сервиса или платного
ресурса нет. Требуются полные container ID, image digest, release SHA; сначала
network-free plan, затем `--execute --expected-sha256` с точным digest.
`--probe-only --inference-probe --receipt-path <новый файл>` выполняет один
синтетический inference с exclusive intent без повторов. Проверено из настоящего
DEV worker: точная модель `DeepSeek-V4.1-Flash-1017`, 2.158s/96input122output,
правильная коррекция ключа и отсутствие listener после закрытия.

Для обычной генерации подготовлен default-off
`AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED`: только новые policy25 курсы постоянного
синтетического QA tenant; все четыре Luna QA flags должны быть false. Это
worker-wide выбор для свежих QA курсов, не one-job fence. Клиент без коммерческого
ключа/fallback/retries, reasoning включён, thinking_budget4096/max_tokens16384,
whole-invocation timeout300s. Установленный TensorFold не поддерживает native
response_format; `prompt_json` передаёт ту же JSON schema в trusted instructions,
а локальная строгая проверка контракта сохраняется. Код профиля входит в DEV
f7bfe272, но флаг выключен и bridge закрыт. Локальный полный source-first прогон
остановился после двух полученных ответов: checker вернул JSON внутри Markdown
ограды, строгий адаптер его отклонил. Офлайн снятие ограды не является приёмкой.
По последнему поручению владельца дальнейшие DEV проверки идут по прежнему
managed Luna6/HIGH маршруту, reasoning включён. Transport smoke не равен приёмке
полного курса; не включать ASUS профиль автоматически после перезапуска.

Максимальная жизнь bridge7200s. Отключение компьютера, VPN, SSH или перезапуск
worker прекращает доступ. Тайм-аут/неизвестный исход модельного запроса нельзя
автоматически повторять; использовать штатный checkpoint/unknown-state workflow.
При новом worker нужно заново проверить/pin его identity и запустить bridge.
Production routing, reserve connector, права и тарифы этим путём не меняются.

## Исторический статус 2026-08-04 (не runtime truth)

На 2026-08-04 три unit active/enabled, checkout находится на application release
`fe0f3c97`. Общая dev/test Supabase находится на Alembic `0089`; Celery inspect
показывает три узла `fast`, `documents` и `ai` с ожидаемыми очередями. Production
API Render live на `fe0f3c97`, frontend Vercel READY, GitHub CI и внешний smoke
прошли. Полный клиентский journey остаётся отдельной согласованной приёмкой.

## Проверка без изменения сервера

```bash
systemctl is-active kamilya-worker.service \
  kamilya-worker-documents.service kamilya-worker-ai.service
systemctl is-enabled kamilya-worker.service \
  kamilya-worker-documents.service kamilya-worker-ai.service
git -C /opt/kamilya-worker status --short
git -C /opt/kamilya-worker rev-parse HEAD
journalctl -u kamilya-worker.service \
  -u kamilya-worker-documents.service -u kamilya-worker-ai.service \
  -n 100 --no-pager
```

Из virtualenv worker:

```bash
celery -A app.core.celery_app:celery_app inspect ping
celery -A app.core.celery_app:celery_app inspect registered
celery -A app.core.celery_app:celery_app inspect active_queues
celery -A app.core.celery_app:celery_app inspect stats
```

В списке registered обязательны `ai.generate_course`,
`ai.regenerate_module`, `ai.regenerate_lesson`, `ai.ingest_document` и
`positions.apply_course_rules`, `users.deliver_invitation`,
`crm.deliver_lead_outbox`, `crm.recover_lead_outbox`,
`enrollments.deliver_assignment_notification` и
`enrollments.recover_assignment_notifications`.

### CRM lead outbox recovery

После release с миграцией `0094` установить checked-in units
`infra/systemd/kamilya-crm-outbox-recovery.service` и `.timer` в
`/etc/systemd/system/`, затем выполнить `systemctl daemon-reload` и включить
timer. Он раз в минуту запускает bounded Python recovery напрямую, без Celery,
поэтому недоступный broker не накапливает по сообщению на каждую минуту простоя.
Один запуск обрабатывает не более 20 due rows.

В `.env` worker/API должны быть одинаковые `CRM_WEBHOOK_URL` и
`CRM_WEBHOOK_SECRET`; значение secret совпадает с `LMS_WEBHOOK_SECRET` CRM и
в production содержит не менее 32 случайных символов.
Значения не выводить в логи или команды проверки. До настройки события остаются
в deferred retry, а приём публичной заявки продолжает работать.

Проверка:

```bash
systemctl is-active kamilya-crm-outbox-recovery.timer
systemctl is-enabled kamilya-crm-outbox-recovery.timer
```

### Course-assignment email recovery

Course-assignment email has an independent durable outbox. Install and enable
`kamilya-assignment-notification-recovery.service` and `.timer`; the timer runs
the bounded database recovery entry point every minute and does not depend on
the Celery broker. Release verification must confirm the timer is active and
enabled, task `enrollments.deliver_assignment_notification` is registered on
the notifications worker, and a duplicate recovery run sends no duplicate
message. Assignment sends pass `course-assignment/<outbox_id>` as Resend's
stable `Idempotency-Key`; recovery must run within the provider's documented
24-hour deduplication window. The timer requires
`ASSIGNMENT_RECOVERY_DATABASE_URL` for the dedicated `lms_recovery`
`NOSUPERUSER NOBYPASSRLS` role. The shared API role `lms_app` must not have
execute permission on the cross-tenant due-inventory function.

```bash
systemctl is-active kamilya-assignment-notification-recovery.timer
systemctl is-enabled kamilya-assignment-notification-recovery.timer
celery -A app.core.celery_app:celery_app inspect registered
```

Не выводить environment unit и значения `.env`.

### Candidate-assessment retention

Before applying Alembic revision 0102, provision the login with an admin
connection (Supabase SQL editor or the migration connection). Keep its password
in the production secret store; do not place it in SQL history or repository
files:

```sql
CREATE ROLE lms_candidate_retention LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
-- Set the login password through the provider secret-management workflow.
```

Revision 0102 fails closed if this role is absent or has `SUPERUSER` or
`BYPASSRLS`. The migration itself revokes table/function defaults and grants
only `USAGE` on `public` plus `EXECUTE` on the bounded retention function.
Configure `CANDIDATE_RETENTION_DATABASE_URL` only after the migration succeeds.

Install and enable `kamilya-candidate-retention.service` and `.timer`. The
broker-independent timer runs hourly, with a bounded batch of at most 100
candidates, through `CANDIDATE_RETENTION_DATABASE_URL`. That URL must use the
dedicated `lms_candidate_retention` role. The role has no table access and may
execute only `enforce_expired_candidate_retention(integer)`; `lms_app` must not
execute that cross-tenant function.

For each expired candidate, the transaction revokes credentials, removes
attempt answer/snapshot evidence, redacts name/contact/consent, and retains only
campaign-level counts (`candidates_redacted`, submitted/passed attempts, and
the score sum). It retains no candidate identifier in the aggregate. Repeated
runs skip `status='deleted'` rows and therefore do not double-count.

```bash
systemctl daemon-reload
systemctl enable --now kamilya-candidate-retention.timer
systemctl is-active kamilya-candidate-retention.timer
systemctl is-enabled kamilya-candidate-retention.timer
```

Do not log candidate rows or database URLs. A failed run is retried by the
persistent timer. A manual smoke may run the oneshot service twice; the second
run must report zero after the test candidate has been handled. Never call the
function with a limit above 100 and never expose the recovery URL to the API.

## Обновление worker

1. Записать текущий SHA и убедиться, что checkout чистый.
2. Выбрать SHA, совместимый с live API и применённой Alembic revision.
3. Получить commit из origin без merge локальных изменений.
4. Обновить Python dependencies штатным способом проекта.
5. Выполнить import/compile smoke.
6. Перезапустить unit.
7. Проверить active, ping, registered tasks и последние logs.
8. Выполнить прикладной smoke, а не только ping.

Пример последовательности после выбора `<release_sha>`:

```bash
cd /opt/kamilya-worker
git fetch origin master
git checkout --detach <release_sha>
/opt/kamilya-worker/apps/api/.venv/bin/pip install \
  -r /opt/kamilya-worker/apps/api/requirements.txt
cd /opt/kamilya-worker/apps/api
.venv/bin/python -m compileall -q app
systemctl restart kamilya-worker.service \
  kamilya-worker-documents.service kamilya-worker-ai.service
systemctl is-active kamilya-worker.service \
  kamilya-worker-documents.service kamilya-worker-ai.service
journalctl -u kamilya-worker.service \
  -u kamilya-worker-documents.service -u kamilya-worker-ai.service \
  -n 100 --no-pager
```

Не использовать `git reset --hard`. Если checkout грязный, остановиться и
разобраться с происхождением изменений.

## Обязательный smoke после обновления

На удаляемом test tenant:

1. загрузить небольшой документ, убедиться, что HTTP upload завершается сразу,
   и дождаться terminal ingestion status фоновой задачи;
2. запустить одну AI generation и дождаться terminal status;
3. создать organization training rule;
4. добавить или импортировать сотрудника;
5. дождаться `positions.apply_course_rules`;
6. проверить одно назначение с правильным source;
7. повторить recompute и подтвердить отсутствие дубля;
8. удалить rule и убедиться, что completed/manual grants защищены.

## Rollback

1. Остановить все три worker unit.
2. Переключить checkout на записанный предыдущий SHA.
3. Восстановить зависимости для этого SHA.
4. Запустить все unit и повторить ping/registered/active_queues.
5. Не откатывать БД автоматически. Если новый worker требовал необратимую
   migration, нужен отдельный DB rollback plan.

## Monitoring

Минимальный production watchdog установлен:

- `kamilya-ops-check.timer` запускается каждые 5 минут;
- проверяет все три worker unit, Valkey, API/frontend, backup age, disk, Celery
  ping и глубину очередей;
- alert/recovery отправляются через Resend;
- GitHub production smoke выполняется каждые 15 минут и на push в `master`.

Queue depth проверяется для `ai`, `documents`, `notifications`, `maintenance` и
legacy `celery`; порог предупреждения по умолчанию равен 50 сообщениям. Метрики
возраста старейшей задачи, task failure rate, provider throttling и memory
pressure остаются P1 наблюдаемости. Один `systemctl is-active` вручную не
заменяет watchdog.

## Проверенная пропускная способность и пределы

- VPS: 4 vCPU, 7.8 GiB RAM, swap отсутствует. После запуска трёх worker и
  converter доступно около 5.3 GiB; Docling остаётся самым тяжёлым процессом.
- Converter: `CONVERTER_MAX_CONCURRENCY=1`, ожидание слота 30 секунд, upload не
  более 50 MiB. На синтетической серии 50 одновременных digital PDF все 50
  запросов завершились HTTP 200 за 2.219 секунды; p50 1.175 секунды, p95 2.060
  секунды. Это проверка лёгкого text-layer маршрута, не 50 OCR-сканов.
- Реальные smoke: DOCX и XLSX прошли через MarkItDown; digital PDF через
  MarkItDown; два image-only/low-text PDF через Docling OCR. OCR остаётся
  последовательным и масштабируется прежде всего с количеством и сложностью
  страниц.
- Document worker обрабатывает один документ одновременно. Поэтому burst 10-50
  документов увеличивает время ожидания, но не создаёт 10-50 копий Docling в
  памяти.
- AI worker обрабатывает максимум две генерации одновременно. Внутренние этапы
  одной генерации выполняются последовательно, что ограничивает одновременное
  давление на LLM-провайдера.
- API допускает не более двух `pending/running` задач генерации на tenant.
  Admission сериализуется в PostgreSQL до списания trial/LLM-бюджета. Третий
  параллельный запрос получает `429` и `Retry-After`; документная очередь этим
  лимитом не затрагивается. Позиция и ETA в UI относятся только к очереди
  текущей компании, а не к недоступной глобальной позиции Celery.
- Историческая выборка dev/test из 29 завершённых генераций: среднее 509.5 с,
  медиана 504.1 с, p90 836.1 с, максимум 1290.2 с. При двух AI слотах и пустой
  очереди ориентир для 10 задач составляет около 42 минут по среднему или 70
  минут по p90; для 50 задач — около 3.5 или 5.8 часа соответственно. Это
  оценка пропускной способности по тестовым данным, а не SLA.

Увеличивать AI concurrency выше 2 на текущем VPS без измерения provider 429,
CPU/RAM и DB pool нельзя. Следующий этап capacity acceptance должен использовать
реальные многостраничные сканы и согласованный платный запуск 10 генераций.

## Legacy unit

Legacy `kamilya-trial-expiry.timer`, ссылавшийся на старый
`/root/Kamilya-LMS/backend`, отключён. Trial expiration проверяется backend во
время tenant-scoped операций.
