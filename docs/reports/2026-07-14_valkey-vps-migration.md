# Отчёт о переносе Redis/Upstash на Valkey VPS

**Дата:** 14 июля 2026 года  
**Статус:** выполнено, production smoke-test пройден

## Что изменено

- На VPS `173.249.51.164` установлен `valkey-server` из Ubuntu 24.04.
- Старый plaintext-порт `6379` отключён.
- Valkey слушает TLS-порт `6380`.
- Включены AOF persistence и `appendfsync everysec`.
- Для очереди настроена политика `maxmemory-policy noeviction`.
- Доступ защищён отдельным случайным 64-символьным паролем.
- Сертификат сейчас self-signed с SAN для IP VPS.
- Worker `/opt/kamilya-worker` переключён на новый endpoint и перезапущен.
- Render service `kamilya-lms-api` получил новый `REDIS_URL` и `REDIS_TLS_VERIFY=false`, после чего был выполнен deploy.
- Локальный `.env` обновлён тем же endpoint; секреты остаются только в `.env` и не добавлены в Git.

## Проверки

Пройдены:

1. Valkey local TLS `PING` на VPS.
2. Внешний TLS `PING` с рабочей машины.
3. Внешняя запись ключа с TTL.
4. `celery inspect ping` с VPS.
5. Реальная Celery smoke-задача `positions.apply_course_rules` с пустым списком пользователей:
   - задача отправлена через новый broker;
   - worker принял задачу;
   - result backend вернул `SUCCESS`;
   - результат содержит нулевые изменения.
6. Render deploy завершён в статусе `live`.
7. Production API health возвращает `ok`.

## Важное ограничение безопасности

Сейчас используется TLS-шифрование с self-signed сертификатом, поэтому в URL присутствует `ssl_cert_reqs=none`, а в окружении установлен `REDIS_TLS_VERIFY=false`. Трафик шифруется, но клиент не проверяет цепочку доверия сертификата.

Это переходный режим. Следующий инфраструктурный шаг до масштабирования — выпустить публичный CA-сертификат для отдельного hostname, например `redis.kml.kz`, перевести URL на этот hostname и вернуть `REDIS_TLS_VERIFY=true`.

## Откат

Для временного отката нужно вернуть прежний `REDIS_URL` в:

- Render environment service `kamilya-lms-api`;
- `/opt/kamilya-worker/apps/api/.env` на VPS;
- локальный `.env`.

После этого перезапустить `kamilya-worker` и выполнить новый Render deploy. Старый Upstash endpoint не удалялся.

## Следующие действия

- выпустить публичный TLS-сертификат и убрать `REDIS_TLS_VERIFY=false`;
- добавить отдельные namespaces для `celery`, `auth`, `rate_limit` и `progress`;
- настроить мониторинг памяти, rejected writes, длины очереди и перезапусков worker;
- добавить регулярную проверку восстановления AOF/RDB;
- после стабилизации удалить временный smoke-ключи с TTL автоматически.

