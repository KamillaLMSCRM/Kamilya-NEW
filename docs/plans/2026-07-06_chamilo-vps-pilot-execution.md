# Chamilo VPS Pilot Execution

Date: 2026-07-06

## Goal

Run Chamilo 2.0.3 as a separate LMS delivery engine on the existing VPS, without changing the current Kamilya production architecture.

Target v0 flow:

1. Lead comes from landing.
2. Operator manually qualifies the tenant.
3. Operator manually creates Chamilo portal/users.
4. Kamilya generator produces course content.
5. Operator manually uploads/builds the course in Chamilo.
6. Client works in Chamilo.

## Completed

- SSH access to VPS `173.249.51.164` verified.
- Existing critical services checked:
  - `docling.service` active.
  - `wa-gateway.service` active.
  - `kamilya-worker.service` active.
  - `mariadb.service` active.
  - `apache2.service` active.
  - `caddy.service` active.
- Legacy Chamilo files moved into a timestamped backup:
  - `/root/backups/chamilo-legacy-20260706-130405/files`
- Legacy Chamilo DB dumped:
  - `/root/backups/chamilo-legacy-20260706-130405/chamilo.sql`
- Clean Chamilo 2.0.3 release deployed to:
  - `/var/www/chamilo`
- New pilot database created:
  - DB name: `chamilo_pilot`
  - DB user: `chamilo_pilot`
  - credentials stored only on VPS at `/root/chamilo-pilot-db.env`
- Apache vhost updated:
  - port `8080`
  - document root `/var/www/chamilo/public`
  - server name `lms.kml.kz`
- Caddy reverse proxy block added for:
  - `lms.kml.kz -> 127.0.0.1:8080`
- Local installer verified from VPS:
  - `http://127.0.0.1:8080/` returns `302` to installer.
  - `http://127.0.0.1:8080/main/install/index.php` returns `200`.
  - `Host: lms.kml.kz` against local Apache returns `200`.

## Current Blocker

`lms.kml.kz` currently returns `NXDOMAIN`. Because the DNS record does not exist, Caddy cannot obtain a TLS certificate and the public installer is not reachable.

Required DNS record:

```text
Type: A
Name: lms
Value: 173.249.51.164
Proxy: DNS only initially, or proxied after TLS/proxy behavior is confirmed
```

After DNS propagation:

```bash
ssh root@173.249.51.164 "systemctl reload caddy && journalctl -u caddy -n 80 --no-pager"
```

Then open:

```text
https://lms.kml.kz/main/install/index.php
```

## Installer Inputs

Use database values from:

```text
/root/chamilo-pilot-db.env
```

Do not copy these values into docs or chat.

Suggested platform URL:

```text
https://lms.kml.kz/
```

Suggested first admin:

```text
Use a Kamilya-owned admin email, not a personal temporary address.
Store the generated password in the password manager.
```

## Next Steps

1. Add DNS A-record for `lms.kml.kz`.
2. Wait for DNS propagation.
3. Reload Caddy and confirm certificate acquisition.
4. Complete Chamilo web installer.
5. Lock down file permissions after install:

```bash
ssh root@173.249.51.164 "chown -R root:www-data /var/www/chamilo/.env /var/www/chamilo/config && chmod 640 /var/www/chamilo/.env"
```

6. Create the first test tenant manually in Chamilo.
7. Create admin/teacher/learner users.
8. Generate one Kamilya course package.
9. Manually upload/build the course in Chamilo.
10. Run learner smoke: login -> course -> quiz -> certificate/report.

## Rollback

If the new install needs to be reverted:

```bash
ssh root@173.249.51.164
systemctl stop apache2
mv /var/www/chamilo /root/backups/chamilo-new-failed-$(date +%Y%m%d-%H%M%S)
mv /root/backups/chamilo-legacy-20260706-130405/files /var/www/chamilo
cp /root/backups/chamilo-legacy-20260706-130405/chamilo.conf.bak /etc/apache2/sites-available/chamilo.conf
cp /root/backups/chamilo-legacy-20260706-130405/Caddyfile.bak /etc/caddy/Caddyfile
systemctl start apache2
systemctl reload caddy
```

The legacy database was not dropped. A dump also exists in the backup directory.
