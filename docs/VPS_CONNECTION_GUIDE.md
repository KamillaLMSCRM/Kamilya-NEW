# Kamilya LMS: VPS и подключённые сервисы

**Документация сверена:** 2026-09-05; runtime заново не проверялся.
**Правило:** топология и процедуры ниже отделены от датированного evidence.
Старые PASS, SHA и ревизии не подтверждают состояние нового release.
Значения паролей, ключей и URL с credentials не приводятся.

## Выбор контура и проверочной процедуры

- [Карта окружений и доступов](PROJECT-CONTEXT.md#карта-окружений-и-доступов)
  определяет production/dev, источники credentials и запрет смешения данных.
- [KZ deployment procedure](../.codex/skills/kamilya-production-deploy/SKILL.md)
  определяет проверку exact API/worker identity на VM126. Наличие SSH-доступа
  не разрешает release, rollback или миграцию CT125.
- [Backup/restore runbook](BACKUP_RESTORE_RUNBOOK.md) определяет fail-closed
  проверку, одноразовую target DB и signed drill report. Наличие архивов не
  является restore proof; secret env/pgpass/key-файлы не выводить.

Прежний VPS/systemd-профиль до KZ cutover не применяется к production.
Для его отдельного dev/demo использования нужен точный owner-approved target
и свежая проверка; старые адреса и имена credentials не являются fallback.

## Казахстанский production-контур 2026-08-17

После отдельного release gate production frontend `app.kml.kz` направлен на
этот контур через `https://api.kml.kz/api`. Render и Supabase сохранены для
dev/demo и rollback, но production customer traffic к ним не направляется.

| Компонент | Evidence на дату cutover (не новый release readback) |
|---|---|
| VM126, приложение | API и три Celery worker из exact release `e9fc8f3`; API привязан только к WireGuard `10.77.77.2:8000` |
| VM126, broker | Valkey 8.1 с обязательным паролем, AOF и `noeviction`; наружу порт не опубликован |
| VM126, файлы | общий bind-mount `/opt/kamilya-runtime/blob-storage` для API и worker, корень `0700 root:root` |
| VM126, backup файлов | `kamilya-blob-backup.timer`; key-only SSH в CT125, шифрование и проверка архива на отдельном узле |
| CT125, база | native PostgreSQL 17 + pgvector, ревизия на дату cutover `0111`; runtime-роль `lms_app` без SUPERUSER/BYPASSRLS. Текущую ревизию проверять заново |
| CT125, backup | `kamilya-pg-backup.timer` active/enabled; encrypted backup, SHA-256 verification и restore drill проверены |

17.08.2026 исправлена проверка freshly encrypted PostgreSQL dump: дешифрованный
временный файл теперь передаётся `postgres` с корректным владельцем и затем
проверяется `pg_restore --list`. Контрольный запуск завершился с `Result=success`,
созданный `.dump.gpg` прошёл `sha256sum -c`, имеет mode `0600`; timer остался
`active` и `enabled`. Root-only копии прежних вариантов скрипта сохранены на
CT125 для точечного rollback.

### Proxy ingress: свежая проверка 2026-08-17

- Канонический reachable target берётся из `PROXY_VPS_HOST`; текущий IP
  `92.38.49.167`. Историческое provider-имя `vds36463.vpsza500.kz` возвращает
  NXDOMAIN и не используется.
- SSH authentication с проверкой сохранённого ED25519 host key прошла через
  `PROXY_VPS_*` из `C:\Kamilya New\.env`; значения не выводились.
- Ubuntu 24.04, Nginx и `wg-quick@wg0` active. WireGuard peer VM126
  `10.77.77.2/32` имеет свежий handshake; proxy-запрос к
  `http://10.77.77.2:8000/health` вернул HTTP 200.
- UFW active: разрешены SSH, HTTP, HTTPS и WireGuard. После выпуска сертификата
  listeners включают SSH `22`, HTTP `80`, HTTPS `443` и WireGuard UDP `51820`.
- Создан отдельный Nginx virtual host `api.kml.kz` с upstream
  `10.77.77.2:8000`, лимитом request body 50 MiB и bounded proxy timeouts.
  Existing default site не изменён; до изменения создан root-only архив
  Nginx-конфигурации. `nginx -t`, reload, local и внешний Host-header
  `/health` smoke прошли с HTTP 200.
- Authoritative DNS `kml.kz` находится в Cloudflare. 17.08.2026 через
  подтверждённую браузерную сессию создан A-record
  `api.kml.kz -> 92.38.49.167` в режиме DNS only; обе authoritative NS и
  Google Public DNS вернули заданный адрес.
- На proxy установлен Certbot, выпущен сертификат Let's Encrypt для
  `api.kml.kz`, включён автоматический `certbot.timer` и HTTP перенаправляется
  на HTTPS. Внешний HTTPS `/health` с проверкой имени сертификата вернул 200.
  `certbot renew --dry-run` завершился успешно. На этом ingress-этапе Vercel
  production env ещё не менялся; переключение выполнено позднее отдельным gate.
- Proxy root filesystem: 4.9 GiB, занято 82%, свободно около 858 MiB. До
  production обязательны disk alert/cleanup policy; не устанавливать пакеты
  вслепую и не считать этот объём запасом для application data/backups.

DNS/TLS ingress gate закрыт. Dev Vercel environment переключён на
`NEXT_PUBLIC_API_URL=https://api.kml.kz/api`; deployment exact SHA собран и
защищённая `/login` проверена через Vercel protection bypass. На proxy временно
добавлен точный CORS allowlist известных Kamilya origins; посторонний origin
по-прежнему отклоняется. Production Vercel environment 17.08.2026 переключён
на тот же API после tenant/business smoke и создания rollback-снимка env.

Проверено прикладным smoke: авторизованный login и `/users/me`, courses,
documents, training log, tenant RLS, staff structure, Celery control plane и
совместное файловое хранилище API/worker. В CT125 загружен tenant
`too-lombard-sandyk` с 12 сотрудниками, структурой двух подразделений, двумя
курсами и назначениями; старые попытки/сертификаты/evidence не переносились.

18.08.2026 закрыт routine admin path к VM126. Host-specific private key создан
на proxy и не копируется на рабочую станцию; public key установлен пользователю
`kamilya-admin`. Вход через `10.77.77.2` с обязательной проверкой host key,
`sudo -n`, список runtime-контейнеров и API health подтверждены. Root SSH login
остаётся выключенным, временный root authorized key удалён. Для обычной работы
используется только цепочка workstation -> proxy -> VM126 по WireGuard/SSH;
Proxmox QGA и console — только bootstrap/recovery.

Для штатного администрирования PostgreSQL на CT125 используется продолжение той
же цепочки, а не Proxmox API: workstation -> public proxy SSH -> WireGuard ->
`kamilya-admin@10.77.77.2` (VM126) -> `root@192.168.1.225` (CT125). На proxy
используется host-specific key `/root/.ssh/kamilya-vm126-admin`; переход с VM126
на CT125 выполняется только ключом `/root/.ssh/kamilya_ct125_ed25519` и с
отдельным known-hosts файлом `/root/.ssh/known_hosts.ct125`. Ключи не копируются
на рабочую станцию и их содержимое не выводится. Proxmox API, QGA и console для
CT125 являются только recovery/bootstrap путями; ошибка этого запасного пути не
доказывает отсутствие штатного SSH-доступа.

При потоковой передаче проверенного скрипта вложенные SSH-вызовы, которые не
должны читать общий stdin, запускаются с `ssh -n`; только конечный вызов,
получающий скрипт, использует `ssh -T`. Команды `docker compose exec` внутри
такого скрипта получают `</dev/null`. Для cleanup временных restore-артефактов
используется `trap cleanup EXIT`: `trap ... ERR` запрещён, если функции вызываются
в command substitution, потому что Bash может выполнить cleanup в subshell.

В тот же день production `runtime.env` дополнен одобренной Resend-конфигурацией
без вывода значений секретов. Перед изменением создана root-only резервная
копия; пересозданы только `api` и `worker-ops`, после чего API health прошёл.
Приглашение пользователю tenant `too-lombard-sandyk` было доставлено штатным
email-каналом; одноразовый token не выводился.

После проверки реального email-login миграция `0111` исправила bounded
`lookup_login_user_by_email()` под FORCE RLS: policy выдана только фактическому
владельцу SECURITY DEFINER-функции, а `lms_app` сохраняет только EXECUTE.
Production lookup, создание purpose-bound OTP в Valkey и TTL были проверены от
реальной runtime-роли.

Воспроизводимый compose хранится в
`infra/compose/kamilya-app-worker.yml`. После cutover обязательны штатный
SSH/WireGuard admin path к guest, внешний health/backup-age alert и проверка
следующего автоматического запуска backup timer.

## Операционные запреты

- Не использовать `git reset --hard`.
- Не делать `git pull` вслепую в production checkout.
- Не обновлять worker без выбранного release SHA и rollback SHA.
- Не менять production DB URL для тестового KZ VPS.
- Не считать active unit доказательством работоспособности business-flow.
- Не отключать Supabase во время тестового переноса.

## Перед подключением нового production-тенанта

Обязательные действия находятся в
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md):

- worker release parity;
- прикладной E2E smoke;
- независимый backup и restore drill;
- heartbeat/queue/disk alerts.
