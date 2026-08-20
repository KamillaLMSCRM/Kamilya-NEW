# KZ production identity monitoring

Дата: 2026-08-20

## Граница

Авторитетный production API Kamilya — `https://api.kml.kz/api`. Render и
Supabase сохранены как development/demo/rollback-контур и не могут удовлетворять
production smoke, даже если возвращают HTTP 200.

`GET /api/v1/health` возвращает только несекретную идентичность:

- `status` и `app`;
- `app_environment` — режим приложения;
- `deployment_environment` — точный контур (`kz-production` для VM126);
- `release_sha` — полный 40-символьный Git SHA.

Ответ имеет `Cache-Control: no-store`. KZ compose требует
`KAMILYA_RELEASE_SHA` и передаёт его API/worker как `RELEASE_SHA`; отсутствие
точного значения останавливает materialization compose до запуска runtime.
Render явно помечен `render-development`.

## Enforcement

- `.github/workflows/production-smoke.yml` проверяет KZ API и `app.kml.kz`, не
  следует redirects и сверяет `release_sha` с repository variable
  `KZ_PRODUCTION_RELEASE_SHA`. Переменная обновляется только после успешного
  deploy/readback exact release; она не приравнивается автоматически к HEAD
  `master`. Допускается ограниченное окно ожидания, затем открывается incident.
- `scripts/ops/healthcheck.sh` использует тот же verifier, требует ожидаемый
  release SHA, проверяет фактические Compose services API/Valkey/workers,
  Celery ping, disk и обязательный явно настроенный источник свежести KZ backup.
  Старые systemd worker/Valkey и каталог Supabase backup не входят в success path.
- `scripts/ops/verify_production_endpoint.py` не принимает короткий SHA,
  неправильный deployment, не-production app mode, redirect или не-JSON ответ.

## Release gate

Локальная реализация не меняет работающий production. Перед rollout необходимо:

1. собрать и выбрать exact release SHA;
2. установить этот SHA как `KAMILYA_RELEASE_SHA` в root-only deployment env;
3. развернуть API/worker одним и тем же immutable release;
4. установить тот же SHA как `EXPECTED_RELEASE_SHA` для host watchdog и как
   GitHub repository variable `KZ_PRODUCTION_RELEASE_SHA`;
5. проверить внешний verifier, затем fault-injection на контролируемом staging:
   неправильный deployment/SHA и redirect обязаны сделать check красным;
6. настроить `BACKUP_FRESHNESS_PATH` на read-only evidence фактического KZ
   database/blob backup; пустое/старое evidence обязано сделать check красным;
7. только после readback включить обновлённый scheduled monitor.

Fault injection на production не выполняется.
