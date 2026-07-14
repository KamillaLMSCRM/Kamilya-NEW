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
- Установлен публичный Let’s Encrypt IP-сертификат с SAN для IP VPS.
- Сертификат короткоживущий; настроен systemd timer для автоматического обновления.
- Worker `/opt/kamilya-worker` переключён на новый endpoint и перезапущен.
- Render service `kamilya-lms-api` получил новый `REDIS_URL` и `REDIS_TLS_VERIFY=true`, после чего был выполнен deploy.
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

## Состояние безопасности

Используется публичный Let’s Encrypt IP-сертификат с проверкой цепочки доверия. В `REDIS_URL` удалён параметр `ssl_cert_reqs=none`, а `REDIS_TLS_VERIFY=true` установлен и на Render, и на VPS worker.

IP-сертификаты Let’s Encrypt короткоживущие, поэтому на VPS добавлен `valkey-certbot-renew.timer`, который дважды в сутки проверяет необходимость обновления, временно освобождает порт 80 для ACME HTTP-01 и после выпуска копирует сертификат в Valkey с перезапуском сервиса.

## Откат

Для временного отката нужно вернуть прежний `REDIS_URL` в:

- Render environment service `kamilya-lms-api`;
- `/opt/kamilya-worker/apps/api/.env` на VPS;
- локальный `.env`.

После этого перезапустить `kamilya-worker` и выполнить новый Render deploy. Старый Upstash endpoint не удалялся.

## Следующие действия

- добавить отдельные namespaces для `celery`, `auth`, `rate_limit` и `progress`;
- настроить мониторинг памяти, rejected writes, длины очереди и перезапусков worker;
- добавить регулярную проверку восстановления AOF/RDB;
- после стабилизации удалить временный smoke-ключи с TTL автоматически.
