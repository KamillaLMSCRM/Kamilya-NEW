/**
 * WhatsApp Gateway — main entry point.
 *
 * Multi-tenant Baileys bridge for Kamilya LMS. Each tenant gets its own
 * WhatsApp session (creds.json) on disk. The Kamilya backend (Render)
 * talks to this gateway over HTTP with a JWT signed by KAMILYA_BACKEND_SECRET.
 *
 * Endpoints:
 *   GET  /health                                  — liveness (no auth)
 *   POST /v1/sessions/:tenant_id/start            — init session, returns QR
 *   GET  /v1/sessions/:tenant_id/status           — { status, phone, qr? }
 *   POST /v1/sessions/:tenant_id/logout           — destroy session
 *   POST /v1/sessions/:tenant_id/send             — { to, message }
 *   POST /v1/sessions/:tenant_id/test             — self-test, sends to admin
 *
 * All /v1/* endpoints require Authorization: Bearer <service-jwt>.
 *
 * Lifecycle of a session:
 *   1. tenant_admin POSTs /start → wa-gateway spawns Baileys socket
 *   2. Waits for QR event → stores PNG in sessions/{tid}/qr.png + returns base64
 *   3. Admin scans QR → Baileys emits 'connection.update' with 'open'
 *   4. creds.json written, session moves to 'connected' state
 *   5. Persistent — survives gateway restart (Baileys reuses creds.json)
 *
 * NOTE on terminology:
 *   - "session" here = one WhatsApp login on one phone = one tenant's bot
 *   - NOT to be confused with browser sessions / cookies
 */

'use strict';

// Load .env file if present (no-op if dotenv not installed; we parse manually)
const fs = require('fs');
const path = require('path');
try {
  const envPath = path.join(__dirname, '..', '.env');
  const envText = fs.readFileSync(envPath, 'utf8');
  for (const line of envText.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq < 0) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim();
    if (!(key in process.env)) process.env[key] = value;
  }
} catch {
  // .env not found — assume env vars are set by systemd / docker / etc.
}

const express = require('express');
const jwt = require('jsonwebtoken');
const pino = require('pino');

const { SessionManager } = require('./session-manager');
const { authMiddleware } = require('./auth');

// ── Config ────────────────────────────────────────────────────────────────

const PORT = parseInt(process.env.PORT || '8700', 10);
const HOST = process.env.HOST || '127.0.0.1';
const SECRET = process.env.KAMILYA_BACKEND_SECRET;
const SESSIONS_DIR = process.env.SESSIONS_DIR || './sessions';
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';
const MOCK_MODE = process.env.MOCK_MODE === 'true';

if (!SECRET) {
  // Fail fast — better to crash on boot than run an unauthenticated gateway.
  console.error('FATAL: KAMILYA_BACKEND_SECRET is not set. Refusing to start.');
  process.exit(1);
}

// ── Logger ────────────────────────────────────────────────────────────────

const logger = pino({
  level: LOG_LEVEL,
  transport: {
    target: 'pino-pretty',
    options: { colorize: true, translateTime: 'SYS:HH:MM:ss.l' },
  },
});

// ── Session manager ───────────────────────────────────────────────────────

const sessions = new SessionManager({
  sessionsDir: SESSIONS_DIR,
  logger,
  mockMode: MOCK_MODE,
});

// Restore any sessions that were connected before gateway restart.
// Without this, every restart would force tenants to re-scan QR.
sessions.restoreFromDisk().catch((err) => {
  logger.error({ err }, 'failed to restore sessions from disk');
});

// ── Express app ───────────────────────────────────────────────────────────

const app = express();
app.use(express.json({ limit: '1mb' }));

// Health endpoint — no auth, used by systemd / monitoring.
app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    uptime: process.uptime(),
    sessions: sessions.count(),
    mock: MOCK_MODE,
  });
});

// All /v1/* endpoints require valid service JWT from Kamilya backend.
app.use('/v1', authMiddleware(SECRET, logger));

// ── Session lifecycle ─────────────────────────────────────────────────────

app.post('/v1/sessions/:tenant_id/start', async (req, res) => {
  const { tenant_id } = req.params;
  // Validate tenant_id format to prevent path traversal in SESSIONS_DIR.
  if (!/^[a-zA-Z0-9-]{1,64}$/.test(tenant_id)) {
    return res.status(400).json({ detail: 'invalid tenant_id' });
  }

  try {
    const result = await sessions.start(tenant_id);
    // 202 Accepted — session is initializing, QR may take a few seconds.
    res.status(202).json(result);
  } catch (err) {
    logger.error({ err, tenant_id }, 'start session failed');
    res.status(500).json({ detail: err.message });
  }
});

app.get('/v1/sessions/:tenant_id/status', async (req, res) => {
  const { tenant_id } = req.params;
  try {
    const status = await sessions.status(tenant_id);
    res.json(status);
  } catch (err) {
    res.status(500).json({ detail: err.message });
  }
});

app.post('/v1/sessions/:tenant_id/logout', async (req, res) => {
  const { tenant_id } = req.params;
  try {
    await sessions.logout(tenant_id);
    res.json({ status: 'logged_out' });
  } catch (err) {
    res.status(500).json({ detail: err.message });
  }
});

// ── Send ──────────────────────────────────────────────────────────────────

app.post('/v1/sessions/:tenant_id/send', async (req, res) => {
  const { tenant_id } = req.params;
  const { to, message } = req.body || {};

  if (!to || typeof to !== 'string') {
    return res.status(400).json({ detail: '`to` (phone E.164) is required' });
  }
  if (!message || typeof message !== 'string') {
    return res.status(400).json({ detail: '`message` is required' });
  }
  if (message.length > 4096) {
    return res.status(400).json({ detail: 'message too long (max 4096 chars)' });
  }

  try {
    const result = await sessions.send(tenant_id, to, message);
    res.json(result);
  } catch (err) {
    logger.error({ err, tenant_id, to }, 'send failed');
    res.status(500).json({ detail: err.message });
  }
});

// ── Self-test: send a test message to the tenant's own phone ─────────────

app.post('/v1/sessions/:tenant_id/test', async (req, res) => {
  const { tenant_id } = req.params;
  try {
    const status = await sessions.status(tenant_id);
    if (status.status !== 'connected') {
      return res.status(409).json({ detail: 'session not connected', status });
    }
    const result = await sessions.send(
      tenant_id,
      status.phone_number,  // send to self
      '✅ Kamilya LMS: интеграция с WhatsApp работает. Это тестовое сообщение.'
    );
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({ detail: err.message });
  }
});

// ── Global error handler ──────────────────────────────────────────────────

// eslint-disable-next-line no-unused-vars
app.use((err, _req, res, _next) => {
  logger.error({ err }, 'unhandled error');
  res.status(500).json({ detail: 'internal error' });
});

// ── Start server ──────────────────────────────────────────────────────────

const server = app.listen(PORT, HOST, () => {
  logger.info({ host: HOST, port: PORT, sessionsDir: SESSIONS_DIR, mock: MOCK_MODE },
    'wa-gateway listening');
});

// Graceful shutdown — close all sessions cleanly so creds.json stays valid.
async function shutdown(signal) {
  logger.info({ signal }, 'shutting down');
  server.close(() => logger.info('http server closed'));
  try {
    await sessions.shutdownAll();
  } catch (err) {
    logger.error({ err }, 'error during session shutdown');
  }
  process.exit(0);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

process.on('uncaughtException', (err) => {
  logger.fatal({ err }, 'uncaughtException');
  shutdown('uncaughtException');
});
process.on('unhandledRejection', (err) => {
  logger.fatal({ err }, 'unhandledRejection');
});

module.exports = { app, sessions };