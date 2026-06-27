# VPS Connection Guide for Agents

> **Дата:** 24 июня 2026
> **VPS:** 173.249.51.164
> **Purpose:** How to connect, what's running, how to deploy

---

## Quick Connect

```bash
# SSH
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164

# Password: Aa12345678!
```

**⚠️ Key-based auth preferred.** Key file: `C:\Users\Askar\.ssh\id_vm`

---

## What's Running on VPS

| Service | Port | URL | Status |
|---------|------|-----|--------|
| Qwen LLM (chat) | 8555 | `qwen.kml.kz` | ✅ Running |
| Qwen Embeddings | 8001 | `qwen-embed.kml.kz` | ✅ Running |
| Docling (PDF→MD) | 8600 | `docling.kml.kz` | ✅ Running |
| Nginx | 80/443 | Reverse proxy | ✅ Running |
| WireGuard | 22677 | Tunnel to Windows | ✅ Active |

---

## Services Management

### Docling
```bash
# Status
systemctl status docling

# Restart
systemctl restart docling

# Logs
journalctl -u docling -f

# Test health
curl http://localhost:8600/health

# Test convert
curl -X POST http://localhost:8600/convert -F "file=@/path/to/file.pdf"
```

### Qwen (vLLM)
```bash
# Check if running
curl http://localhost:8555/v1/models
curl http://localhost:8001/v1/models

# If down — check vLLM process
ps aux | grep vllm
```

### Nginx
```bash
# Test config
nginx -t

# Reload
systemctl reload nginx

# Config files
cat /etc/nginx/sites-available/qwen.kml.kz
cat /etc/nginx/sites-available/docling.kml.kz
```

---

## Deploy New Service

1. Create directory: `mkdir -p /opt/{service-name}`
2. Create venv: `cd /opt/{service-name} && python3 -m venv .venv`
3. Upload files via `scp`:
   ```bash
   scp -i C:\Users\Askar\.ssh\id_vm main.py root@173.249.51.164:/opt/{service-name}/
   scp -i C:\Users\Askar\.ssh\id_vm requirements.txt root@173.249.51.164:/opt/{service-name}/
   ```
4. Install deps: `.venv/bin/pip install -r requirements.txt`
5. Create systemd unit at `/etc/systemd/system/{service-name}.service`:
   ```ini
   [Unit]
   Description={Service Name}
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/{service-name}
   ExecStart=/opt/{service-name}/.venv/bin/python main.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
6. Enable: `systemctl daemon-reload && systemctl enable --now {service-name}`
7. Add Nginx proxy if needed (sites-available → sites-enabled symlink → reload)

---

## DNS (Cloudflare)

All DNS is managed via Cloudflare dashboard: `dash.cloudflare.com` → `kml.kz`

| Record | Type | Value | Proxy |
|--------|------|-------|-------|
| `qwen.kml.kz` | A | 173.249.51.164 | ✅ |
| `qwen-embed.kml.kz` | A | 173.249.51.164 | ✅ |
| `docling.kml.kz` | A | 173.249.51.164 | ✅ |

To add new subdomain: A record → 173.249.51.164 → Proxy on.

---

## Credentials

| What | Value |
|------|-------|
| SSH user | `root` |
| SSH key | `C:\Users\Askar\.ssh\id_vm` |
| SSH password | `Aa12345678!` |
| DB password | `ParolSupabase!1` |
| DB user | `postgres.ducegbxphkgffgozkchw` |
| DB host | `aws-1-eu-central-1.pooler.supabase.com` |
| DB port | `5432` |
| DB name | `postgres` |

**⚠️ Never commit these to git.**

---

## Common Tasks

### Run SQL on Supabase (via VPS)
```bash
# 1. Upload SQL file
scp -i C:\Users\Askar\.ssh\id_vm file.sql root@173.249.51.164:/tmp/file.sql

# 2. Execute
ssh -i C:\Users\Askar\.ssh\id_vm root@173.249.51.164 \
  "PGPASSWORD='ParolSupabase!1' psql -h aws-1-eu-central-1.pooler.supabase.com -p 5432 -U postgres.ducegbxphkgffgozkchw -d postgres -f /tmp/file.sql"
```

**⚠️ Do NOT run SQL via PowerShell — parentheses break parsing. Always use scp + psql.**

### Check Disk Usage
```bash
df -h
du -sh /opt/*
```

### Check Memory
```bash
free -h
```

### Check Running Processes
```bash
ps aux | grep -E "python|uvicorn|vllm|nginx" | grep -v grep
```

---

## Nginx Config Template

```nginx
server {
    listen 80;
    server_name {subdomain}.kml.kz;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
```

Save to `/etc/nginx/sites-available/{subdomain}.kml.kz`, then:
```bash
ln -sf /etc/nginx/sites-available/{subdomain}.kml.kz /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection refused | Check firewall: `ufw status` or `iptables -L` |
| 502 Bad Gateway | Service not running: `systemctl status {service}` |
| DNS not resolving | Check Cloudflare, wait 5 min propagation |
| SSH key rejected | Ensure key is at `C:\Users\Askar\.ssh\id_vm` |
| OOM killed | Check `dmesg | grep -i oom`, increase swap |
| Port already in use | `lsof -i :{port}` to find process |
