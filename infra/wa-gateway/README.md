# WhatsApp Gateway (`wa-gateway`)

Multi-tenant Baileys bridge for Kamilya LMS. Each tenant connects their own
WhatsApp number; gateway manages sessions and provides REST API for the
Kamilya backend.

## Architecture

```
Kamilya backend (Render, FastAPI)
  ↓ HTTPS + JWT
wa-gateway (VPS 173.249.51.164, Node.js + Baileys)
  ↓ persistent socket
WhatsApp servers (Meta)

Per-tenant state on disk:
  /opt/whatsapp-gateway/sessions/{tenant_id}/auth/creds.json
```

One Node.js process holds all tenant sessions in memory. creds.json on
disk means sessions survive gateway restart without QR re-scan.

## Local development

```bash
cd infra/wa-gateway
npm install
cp .env.example .env
# Generate a dev secret
echo "KAMILYA_BACKEND_SECRET=$(openssl rand -hex 32)" >> .env
echo "MOCK_MODE=true" >> .env
npm start
```

In mock mode, no real WhatsApp connection. POST `/v1/sessions/foo/start`
returns `{ status: 'connected' }` immediately. POST `/send` returns a fake
message_id. Useful for testing the API surface in CI.

## Production deployment

See `docs/VPS_CONNECTION_GUIDE.md` for SSH access to the VPS. Steps:

```bash
# 1. SSH to VPS
ssh -i ~/.ssh/id_vm root@173.249.51.164

# 2. Create install dir (one-time)
mkdir -p /opt/whatsapp-gateway
cd /opt/whatsapp-gateway

# 3. Get code (from the laptop that has git push access)
# On your laptop:
scp -i ~/.ssh/id_vm -r infra/wa-gateway/* root@173.249.51.164:/opt/whatsapp-gateway/

# 4. Install deps on VPS
cd /opt/whatsapp-gateway
npm ci --omit=dev

# 5. Configure env (one-time)
cp .env.example .env
nano .env   # set KAMILYA_BACKEND_SECRET — must match Render env

# 6. Create systemd unit (one-time)
cat > /etc/systemd/system/wa-gateway.service <<'EOF'
[Unit]
Description=Kamilya WhatsApp Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/whatsapp-gateway
EnvironmentFile=/opt/whatsapp-gateway/.env
ExecStart=/usr/bin/node src/index.js
Restart=always
RestartSec=5
StandardOutput=append:/var/log/wa-gateway.log
StandardError=append:/var/log/wa-gateway.err

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now wa-gateway

# 7. Nginx proxy (wa.kml.kz -> 127.0.0.1:8700)
cat > /etc/nginx/sites-available/wa.kml.kz <<'EOF'
server {
    listen 80;
    server_name wa.kml.kz;

    client_max_body_size 1M;

    location / {
        proxy_pass http://127.0.0.1:8700;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/wa.kml.kz /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

DNS for `wa.kml.kz` is in Cloudflare — A record → 173.249.51.164, proxy ON.

## API

All `/v1/*` endpoints require:
```
Authorization: Bearer <service-jwt>
```
where the JWT is signed with `KAMILYA_BACKEND_SECRET` (HS256). Mint via:
```python
# Python (Kamilya backend)
import jwt
token = jwt.encode(
    {"sub": "kamilya-backend", "role": "service"},
    settings.KAMILYA_BACKEND_SECRET,
    algorithm="HS256",
    expires_in=300,  # 5 min
)
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe (no auth) |
| POST | `/v1/sessions/{tenant_id}/start` | Init session, return QR |
| GET | `/v1/sessions/{tenant_id}/status` | Current state + active QR |
| POST | `/v1/sessions/{tenant_id}/logout` | Destroy session |
| POST | `/v1/sessions/{tenant_id}/send` | Send `{ to, message }` |
| POST | `/v1/sessions/{tenant_id}/test` | Self-test (sends to own phone) |

### Example: tenant_admin UI flow

```javascript
// 1. Admin clicks "Connect WhatsApp"
const startRes = await fetch(`${WA_GATEWAY_URL}/v1/sessions/${tenantId}/start`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${serviceJwt}` },
});
const { status, qr } = await startRes.json();
// qr is base64 PNG; show in <img src={`data:image/png;base64,${qr}`} />

// 2. Poll status every 5s while qr_pending
const poll = setInterval(async () => {
  const statusRes = await fetch(`${WA_GATEWAY_URL}/v1/sessions/${tenantId}/status`, {
    headers: { Authorization: `Bearer ${serviceJwt}` },
  });
  const s = await statusRes.json();
  if (s.status === 'connected') {
    clearInterval(poll);
    showSuccess(s.phone_number);
  } else if (s.status === 'qr_pending' && !s.qr) {
    // QR expired — call /start again for new one
  }
}, 5000);

// 3. Send test message
const testRes = await fetch(`${WA_GATEWAY_URL}/v1/sessions/${tenantId}/test`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${serviceJwt}` },
});
```

## Security & risk

- **Unofficial WhatsApp API** — Meta may ban numbers using Baileys. We
  document this in tenant-facing UI. Recovery is the tenant's
  responsibility.
- **Session files** are unencrypted creds.json. Anyone with file access
  on VPS can hijack a session. Mitigations:
  - File permissions `chmod 600` on `/opt/whatsapp-gateway/sessions`
  - VPS access is via SSH key only (no password)
- **JWT secret** must match Render env. Loss = re-auth all tenants.
- **Rate limiting** — Kamilya backend should cap messages per tenant/day.
  Implemented in backend, not gateway.

## Troubleshooting

```bash
# Service status
systemctl status wa-gateway

# Live logs
journalctl -u wa-gateway -f

# Or via the file output
tail -f /var/log/wa-gateway.log

# Test health from VPS itself
curl http://127.0.0.1:8700/health

# Test from outside (after DNS + nginx)
curl https://wa.kml.kz/health

# Manual session cleanup (force re-scan for one tenant)
ssh ... "rm -rf /opt/whatsapp-gateway/sessions/{tenant_id}/auth"
# Tenant then calls /start again to get fresh QR

# Restart gateway (sessions persist via creds.json)
systemctl restart wa-gateway
```