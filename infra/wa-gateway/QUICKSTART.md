# wa-gateway

Node.js multi-tenant WhatsApp bridge for Kamilya LMS.

## Local quick-start (mock mode)

```bash
npm install
echo "KAMILYA_BACKEND_SECRET=$(openssl rand -hex 32)" > .env
echo "MOCK_MODE=true" >> .env
npm start
```

Then in another terminal:
```bash
TOKEN=$(node -e "console.log(require('jsonwebtoken').sign({sub:'kamilya-backend',role:'service'}, process.env.KAMILYA_BACKEND_SECRET, {algorithm:'HS256',expiresIn:'5m'}))")
# Override:
TOKEN=$(node -e "const jwt=require('jsonwebtoken'); require('dotenv').config(); console.log(jwt.sign({sub:'kamilya-backend',role:'service'}, process.env.KAMILYA_BACKEND_SECRET, {algorithm:'HS256',expiresIn:'5m'}))" --experimental-vm-modules)

curl -X POST http://127.0.0.1:8700/v1/sessions/test-tenant/start \
  -H "Authorization: Bearer $TOKEN"
# → { "status": "connected", "phone_number": "+77000000000 (mock)", "mock": true }

curl -X POST http://127.0.0.1:8700/v1/sessions/test-tenant/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to": "+77001234567", "message": "hello"}'
# → { "message_id": "mock_xxx", "status": "sent", "mock": true }
```

## Production

See [README.md](./README.md) for VPS deployment steps.

## Structure

```
src/
├── index.js            # Express server + routes
├── session-manager.js  # Baileys multi-session lifecycle
└── auth.js             # JWT middleware (HS256, service role)

sessions/{tenant_id}/auth/creds.json   # per-tenant WhatsApp session
.env                                    # KAMILYA_BACKEND_SECRET, PORT, MOCK_MODE
```

## Adding a new endpoint

1. Add handler in `src/index.js`
2. If it's a session-level operation, add method to `SessionManager` in `session-manager.js`
3. Update README API table
4. Test in mock mode locally first

## Known limitations

- **Text only** — images/docs/stickers not yet supported (Baileys supports
  them, just not exposed in API yet)
- **No group messaging** — only 1-to-1 DMs
- **No message queuing** — if gateway is down, send fails immediately.
  Kamilya backend queues via Celery before calling gateway.
- **No webhook signing** — webhook deliveries are trusted by source IP.
  When wa-gateway is behind nginx on same VPS, this is OK; if exposed
  directly, add HMAC signing.