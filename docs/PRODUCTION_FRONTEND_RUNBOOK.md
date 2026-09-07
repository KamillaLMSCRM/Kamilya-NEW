# Kamilya LMS: production frontend on CT137

**Назначение:** внутренний runbook размещения и выпуска production-фронтенда.
**Состояние проверено:** 2026-09-07.

Документ не содержит паролей, private keys, токенов или значений `.env`.
Публичные клиентские приложения и договорные приложения не должны копировать
отсюда внутренние имена узлов и private-адреса.

## Текущий контур

```text
app.kml.kz
  -> Cloudflare DNS-only A 92.38.49.167
  -> public KZ proxy: Nginx + TLS
  -> WireGuard 10.77.77.1 -> 10.77.77.3
  -> CT137 webkml: Nginx
  -> Next.js on 127.0.0.1:3000
  -> https://api.kml.kz/api
```

- CT137 работает на Alpine Linux и не содержит Docker runtime для приложения.
- На 2026-09-07 CT137 размещён на Proxmox node `pve3`. Привязка public ingress
  выполнена к сохранённым адресам и WireGuard identity контейнера, а не к имени
  Proxmox node.
- Next.js запускается отдельным непривилегированным пользователем
  `kamilya-web` через OpenRC service `kamilya-web`.
- Nginx на CT137 принимает только внутренний HTTP-трафик; публичный TLS
  завершается на KZ proxy.
- WireGuard использует узкие peer routes `/32`. PostgreSQL и внутренние
  application ports не публикуются в Internet.
- Production API, workers, Valkey, файловый runtime и CT125 PostgreSQL не были
  перенесены в рамках frontend cutover и остаются отдельным release boundary.
- Vercel project `web` сохранён как rollback artifact, но больше не обслуживает
  `app.kml.kz`. Dev project `kamilya-lms-dev` и лендинг `kml.kz`/`www.kml.kz`
  остаются отдельными контурами.
- `kml.kz`/`www.kml.kz` пока обслуживаются Vercel как отдельный маркетинговый
  лендинг. Геопроверка корневого домена поэтому не является evidence размещения
  LMS application; перенос лендинга требует отдельного release/DNS gate.

## Проверенный baseline 2026-09-07

| Объект | Подтверждённое состояние |
|---|---|
| Frontend source | Git SHA `e463527cd8f5e67e987c44d8d769f337714bd25f` |
| Proxmox placement | CT137 на node `pve3`; guest IPv4 `192.168.1.237` сохранён после migration |
| Runtime | Next.js `15.5.23`, native Node.js, без Docker |
| Release directory | `/opt/kamilya-web/releases/<exact-full-sha>` |
| Active release | `/opt/kamilya-web/current` — symlink на exact release |
| Release identity | `/etc/kamilya-web-release` и HTTP header `X-Kamilya-Release` |
| Services | `wg-quick.wg0`, `kamilya-web`, `nginx` — started и enabled |
| DNS | `app.kml.kz` — DNS-only A `92.38.49.167` |
| TLS | Let's Encrypt; renewal authenticator `webroot`; `certbot.timer` enabled/active |
| Recovery | Proxmox snapshot `pre-kml-web-e463527c`; Vercel CNAME rollback сохранён |

## Existing-path-first preflight

Перед Git, Proxmox, proxy, CT137, DNS или release-действием:

1. Прочитать `AGENTS.md`, `docs/PROJECT-CONTEXT.md`, этот runbook и релевантную
   запись `ERRORS.md`.
2. Подтвердить `origin/master`, exact candidate SHA и чистоту отдельного
   release-worktree. Не собирать из dirty checkout.
3. Проверить фактическую Cloudflare-запись `app.kml.kz`, действующий сертификат,
   public `/healthz` и API `/health` до изменения.
4. Проверить identity CT137, active release, состояние трёх сервисов и свободное
   место. HTTP 200 без exact release identity недостаточен.
5. Зафиксировать rollback: предыдущую DNS-запись, текущий release symlink,
   proxy Nginx config/backup и Proxmox snapshot либо иной проверенный recoverable
   checkpoint.
6. Не менять API, базу, worker, Cloudflare proxy mode, provider plan или billing
   в составе frontend-only release.

## Сборка release

Сборка выполняется из отдельного чистого worktree точного Git SHA. Обязательная
build-time переменная:

```text
NEXT_PUBLIC_API_URL=https://api.kml.kz/api
```

Минимальный локальный gate в `apps/web`:

```powershell
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test -- --maxWorkers=2
pnpm build
```

Release directory всегда называется полным Git SHA. Нельзя перезаписывать
предыдущую release directory или выдавать dirty-файлы за committed candidate.
После доставки production dependencies сокращаются штатным package-manager
процессом; глобальные пакеты и ambient checkout не являются частью артефакта.

## Переключение приложения

1. Доставить новый immutable release в
   `/opt/kamilya-web/releases/<exact-full-sha>`.
2. Проверить владельца `kamilya-web`, отсутствие секретов и корректность
   build-time API URL.
3. Переключить `/opt/kamilya-web/current` атомарным symlink update.
4. Записать exact SHA в `/etc/kamilya-web-release`.
5. Перезапустить только `kamilya-web`; Nginx и WireGuard не перезапускать без
   отдельной причины.
6. Проверить локальные `/healthz` и `/login`, затем proxy-to-CT137 health.

Выпуск 2026-09-07 был выполнен через явно разрешённую Proxmox console как
bootstrap. Console не становится routine deploy path. До следующего release
нужно отдельно подтвердить или создать host-specific key-only admin path к
CT137 через существующий proxy/WireGuard; запрещено подбирать credentials или
ослаблять SSH вместо этого.

## Public release gate

После переключения обязательно подтвердить:

1. authoritative Cloudflare и минимум два публичных resolver возвращают
   `app.kml.kz -> 92.38.49.167`;
2. TLS hostname verification проходит;
3. `/healthz` возвращает HTTP 200, полный expected SHA в теле и
   `X-Kamilya-Release`;
4. `/login` возвращает HTTP 200;
5. синтетический production-методист входит и открывает `/dashboard` без
   page errors и failed requests к `app.kml.kz`/`api.kml.kz`;
6. `https://api.kml.kz/health` остаётся успешным;
7. `kml.kz` и `www.kml.kz` не изменились;
8. restart/reboot readback подтверждает автозапуск WireGuard, приложения и
   Nginx.

## Перенос CT137 между Proxmox nodes

Сам перенос CT137 между nodes не требует изменения Cloudflare, публичного
proxy или TLS, если контейнер сохранил guest IPv4, WireGuard private identity и
конфигурацию сервисов. После каждой migration обязательно проверить:

1. CT137 имеет ожидаемый guest IPv4 и WireGuard peer address `10.77.77.3/32`;
2. `wg-quick.wg0`, `kamilya-web` и `nginx` запущены;
3. public `/healthz` возвращает expected exact SHA в теле и header;
4. `/login`, API health и лендинг отвечают успешно;
5. при плановой production migration выполняется краткий browser business smoke.

Если эти проверки проходят, DNS и proxy не перенастраивать. Имя Proxmox node
обновляется только во внутренней operational documentation и evidence.

## TLS renewal

Nginx на proxy публикует HTTP challenge из `/var/www/letsencrypt`. Renewal
configuration для `app.kml.kz` должна содержать:

```text
authenticator = webroot
app.kml.kz = /var/www/letsencrypt
```

`certbot.timer` должен быть `enabled` и `active`. После изменения Nginx,
Cloudflare или renewal config выполняется отдельная staging/dry-run проверка.
Временные DNS challenge records после успешного перехода на webroot удаляются.

## Rollback

### Быстрый публичный rollback на Vercel

Вернуть в Cloudflare только запись `app.kml.kz`:

```text
Type: CNAME
Name: app
Target: 3a49261800d3bbae.vercel-dns-017.com
Proxy: DNS only
TTL: Auto
```

После изменения повторить DNS, TLS, login и business smoke. `kml.kz`,
`www.kml.kz` и `api.kml.kz` при этом не менять.

### Runtime rollback на CT137

Если предыдущая release directory сохранена и проверена, вернуть
`/opt/kamilya-web/current` на неё, обновить `/etc/kamilya-web-release`,
перезапустить `kamilya-web` и повторить exact-SHA gate. Если корректного
предыдущего release нет, использовать только заранее проверенный Proxmox
snapshot/recovery plan; не восстанавливать snapshot вслепую после изменения
данных или сети.

## Секреты и границы

- Production smoke credentials читаются только process-locally из
  `Kamilya-NEW/.env`; значения не выводятся и не сохраняются в evidence.
- WireGuard private keys остаются root-only на своих узлах.
- Cloudflare, Vercel и GitHub credentials не копируются между проектами.
- Frontend release не даёт разрешения менять production API, PostgreSQL,
  provider plan, billing, DNS других имён или customer data.
