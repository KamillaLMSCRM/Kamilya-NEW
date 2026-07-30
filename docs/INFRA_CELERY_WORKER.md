# Kamilya LMS Celery worker

**Обновлено:** 2026-07-29
**Назначение:** текущий runbook worker. Исторические инструкции Upstash и старых
checkout удалены.

## Production topology

- Host: основной VPS Kamilya.
- Checkout: `/opt/kamilya-worker`.
- Unit: `kamilya-worker.service`.
- Broker/result backend: Valkey по TLS.
- Database: тот же runtime `DATABASE_URL`, что у API.
- Document conversion: локальный `http://127.0.0.1:8600` с тем же
  `DOCLING_API_KEY`, что у Docling service; timeout не менее 900 секунд для
  OCR больших сканированных PDF.
- Code: совместимый commit release, а не обязательно последний docs-only
  commit.

Worker выполняет:

- `ai.generate_course`;
- `ai.regenerate_module`;
- `ai.regenerate_lesson`;
- `ai.ingest_document`;
- document cleanup/reindex jobs;
- `positions.apply_course_rules`.

## Текущий известный статус

На 2026-07-29 unit active/enabled, checkout
`f3df397c9a326964b17d4d8aa9370ecbb5995547`, production API и worker
синхронизированы. Production DB находится на `0079`; реальный Celery inspect
ping отвечает. Worker зарегистрировал обязательные задачи генерации,
перегенерации, индексации документов и применения правил. После выкладки в
журнале unit не обнаружены `ERROR`, `CRITICAL` или traceback. GitHub CI и
внешний production smoke для release прошли; полный synthetic tenant journey
на этом release отдельно не повторялся.

## Проверка без изменения сервера

```bash
systemctl is-active kamilya-worker.service
systemctl is-enabled kamilya-worker.service
git -C /opt/kamilya-worker status --short
git -C /opt/kamilya-worker rev-parse HEAD
journalctl -u kamilya-worker.service -n 100 --no-pager
```

Из virtualenv worker:

```bash
celery -A app.core.celery_app:celery_app inspect ping
celery -A app.core.celery_app:celery_app inspect registered
```

В списке registered обязательны `ai.generate_course`,
`ai.regenerate_module`, `ai.regenerate_lesson`, `ai.ingest_document` и
`positions.apply_course_rules`.

Не выводить environment unit и значения `.env`.

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
systemctl restart kamilya-worker.service
systemctl is-active kamilya-worker.service
journalctl -u kamilya-worker.service -n 100 --no-pager
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

1. Остановить worker.
2. Переключить checkout на записанный предыдущий SHA.
3. Восстановить зависимости для этого SHA.
4. Запустить unit и повторить ping/registered.
5. Не откатывать БД автоматически. Если новый worker требовал необратимую
   migration, нужен отдельный DB rollback plan.

## Monitoring

Минимальный production watchdog установлен:

- `kamilya-ops-check.timer` запускается каждые 5 минут;
- проверяет worker unit, Valkey, API/frontend, backup age, disk и Celery ping;
- alert/recovery отправляются через Resend;
- GitHub production smoke выполняется каждые 15 минут и на push в `master`.

Метрики queue depth, job age, task failure rate и memory pressure остаются P1
наблюдаемости. Один `systemctl is-active` вручную не заменяет watchdog.

## Legacy unit

Legacy `kamilya-trial-expiry.timer`, ссылавшийся на старый
`/root/Kamilya-LMS/backend`, отключён. Trial expiration проверяется backend во
время tenant-scoped операций.
