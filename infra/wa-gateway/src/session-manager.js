/**
 * SessionManager — owns all WhatsApp sessions across all tenants.
 *
 * Each session = one Baileys socket + creds.json on disk. Sessions are
 * isolated per tenant_id so a tenant disconnect / ban can't affect others.
 *
 * Threading model:
 *   - Single Node.js process
 *   - All sessions live in this map
 *   - Baileys is event-driven, no extra threads needed
 *   - Disk I/O for creds.json is async (fs.promises)
 *
 * Recovery:
 *   - On gateway restart, restoreFromDisk() re-uses creds.json for any
 *     tenant that was previously connected. No QR re-scan needed.
 *   - If creds.json is invalid (e.g. Meta revoked session), tenant must
 *     re-scan QR via POST /start.
 *
 * Mock mode:
 *   - When MOCK_MODE=true, no socket is opened. Status reports 'connected'
 *     after /start. /send returns a fake message_id. Useful for local dev
 *     and CI — never set in production.
 */

'use strict';

const fs = require('fs').promises;
const path = require('path');
const QRCode = require('qrcode');
const pino = require('pino');

class SessionManager {
  /**
   * @param {object} opts
   * @param {string} opts.sessionsDir — where per-tenant creds.json live
   * @param {object} opts.logger — pino logger
   * @param {boolean} opts.mockMode — disable real WhatsApp connection
   */
  constructor({ sessionsDir, logger, mockMode = false }) {
    this.sessionsDir = sessionsDir;
    this.logger = logger;
    this.mockMode = mockMode;

    /** @type {Map<string, SessionEntry>} */
    this.sessions = new Map();
  }

  count() {
    return this.sessions.size;
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────

  /**
   * Initialize a session for tenant_id.
   * Returns the QR code as base64 PNG (or null if already connected).
   * Idempotent — calling twice returns existing state.
   *
   * @param {string} tenantId
   * @returns {Promise<{status: string, qr?: string}>}
   */
  async start(tenantId) {
    const existing = this.sessions.get(tenantId);
    if (existing && existing.status === 'connected') {
      return { status: 'connected', phone_number: existing.phoneNumber };
    }
    if (existing && existing.status === 'qr_pending') {
      return { status: 'qr_pending', qr: existing.qrPngBase64 };
    }

    const sessionDir = this._sessionDir(tenantId);
    await fs.mkdir(sessionDir, { recursive: true });

    if (this.mockMode) {
      // Mock — instantly report connected, no QR.
      const entry = {
        tenantId,
        status: 'connected',
        phoneNumber: '+77000000000 (mock)',
        socket: null,
        qrPngBase64: null,
        qrExpiresAt: null,
        startedAt: new Date(),
      };
      this.sessions.set(tenantId, entry);
      this.logger.info({ tenantId }, 'mock session started');
      return { status: 'connected', phone_number: entry.phoneNumber, mock: true };
    }

    // Real mode — load Baileys dynamically. We import inside the method
    // so MOCK_MODE startup doesn't load the heavy dependency.
    const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } =
      await import('@whiskeysockets/baileys');

    const authDir = path.join(sessionDir, 'auth');
    await fs.mkdir(authDir, { recursive: true });
    const { state, saveCreds } = await useMultiFileAuthState(authDir);

    const sock = makeWASocket({
      auth: state,
      printQRInTerminal: false,  // we render QR ourselves
      logger: pino({ level: 'silent' }),  // silence Baileys' internal logger
      browser: ['Kamilya LMS', 'Chrome', '120.0'],
    });

    const entry = {
      tenantId,
      status: 'initializing',
      phoneNumber: null,
      socket: sock,
      qrPngBase64: null,
      qrExpiresAt: null,
      startedAt: new Date(),
    };
    this.sessions.set(tenantId, entry);

    // ── Event handlers ──────────────────────────────────────────────

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // New QR — render as PNG base64, store with TTL.
        try {
          const png = await QRCode.toDataURL(qr, { width: 256, margin: 1 });
          // data URL: "data:image/png;base64,XXX..." — strip prefix for API.
          const base64 = png.replace(/^data:image\/png;base64,/, '');
          entry.qrPngBase64 = base64;
          entry.status = 'qr_pending';
          // QR expires after ~60s on WhatsApp's side, we set 50s to be safe.
          entry.qrExpiresAt = new Date(Date.now() + 50_000);
          this.logger.info({ tenantId }, 'QR generated, waiting for scan');
        } catch (err) {
          this.logger.error({ err, tenantId }, 'failed to render QR');
        }
      }

      if (connection === 'open') {
        entry.status = 'connected';
        entry.qrPngBase64 = null;
        entry.qrExpiresAt = null;
        // sock.user.id looks like "77001234567:67@s.whatsapp.net"
        entry.phoneNumber = sock.user?.id?.split(':')[0] || null;
        this.logger.info({ tenantId, phoneNumber: entry.phoneNumber },
          'session connected');
      }

      if (connection === 'close') {
        const reason = lastDisconnect?.error?.output?.statusCode;
        const shouldReconnect = reason !== DisconnectReason.loggedOut;
        entry.status = shouldReconnect ? 'disconnected' : 'logged_out';

        if (shouldReconnect) {
          this.logger.warn({ tenantId, reason }, 'session disconnected, will auto-reconnect');
          // Re-init — Baileys uses the saved creds.json automatically.
          setTimeout(() => this.start(tenantId).catch((err) => {
            this.logger.error({ err, tenantId }, 'auto-reconnect failed');
          }), 5_000);
        } else {
          this.logger.warn({ tenantId, reason }, 'session logged out — tenant must re-scan QR');
          this.sessions.delete(tenantId);
        }
      }
    });

    sock.ev.on('creds.update', saveCreds);

    // Webhook callbacks — Kamilya backend subscribes to these via separate
    // webhook URL passed in tenant_integrations table. We POST to that URL.
    sock.ev.on('messages.update', async (updates) => {
      // updates = [{ key: { remoteJid, fromMe, id }, update: { status } }]
      // status: 1=SENT, 2=DELIVERED, 3=READ, 4=PLAYED (in groups)
      for (const u of updates) {
        if (u.update?.status >= 1) {
          await this._emitDeliveryWebhook(tenantId, u);
        }
      }
    });

    return {
      status: 'qr_pending',
      qr: entry.qrPngBase64,
      note: 'QR valid for ~50s. Scan from WhatsApp > Linked Devices.',
    };
  }

  /**
   * Current status of a tenant's session.
   * @param {string} tenantId
   * @returns {Promise<object>}
   */
  async status(tenantId) {
    const entry = this.sessions.get(tenantId);
    if (!entry) {
      // Maybe creds.json exists on disk but session wasn't started in this
      // gateway run — check and report accordingly.
      const authDir = path.join(this._sessionDir(tenantId), 'auth');
      const credsExist = await fs.access(path.join(authDir, 'creds.json'))
        .then(() => true)
        .catch(() => false);

      return {
        status: credsExist ? 'persisted' : 'not_started',
        phone_number: null,
        qr: null,
      };
    }

    return {
      status: entry.status,
      phone_number: entry.phoneNumber,
      qr: entry.qrExpiresAt && entry.qrExpiresAt > new Date()
        ? entry.qrPngBase64
        : null,
      qr_expires_at: entry.qrExpiresAt?.toISOString() || null,
      started_at: entry.startedAt.toISOString(),
    };
  }

  /**
   * Force logout + clear session files. Tenant will need to re-scan QR.
   * @param {string} tenantId
   */
  async logout(tenantId) {
    const entry = this.sessions.get(tenantId);
    if (entry?.socket) {
      try {
        await entry.socket.logout();
      } catch (err) {
        this.logger.warn({ err, tenantId }, 'socket.logout threw, continuing');
      }
    }
    this.sessions.delete(tenantId);
    // Delete auth files so /start produces a fresh QR.
    const authDir = path.join(this._sessionDir(tenantId), 'auth');
    await fs.rm(authDir, { recursive: true, force: true });
    this.logger.info({ tenantId }, 'session logged out and cleared');
  }

  /**
   * Send a WhatsApp text message.
   * @param {string} tenantId
   * @param {string} to — E.164 phone, e.g. "+77001234567"
   * @param {string} message — text body (max 4096 chars)
   * @returns {Promise<{message_id: string, status: string}>}
   */
  async send(tenantId, to, message) {
    const entry = this.sessions.get(tenantId);
    if (!entry) {
      throw new Error(`no session for tenant ${tenantId}`);
    }
    if (entry.status !== 'connected') {
      throw new Error(`session not connected (status: ${entry.status})`);
    }

    if (this.mockMode) {
      return {
        message_id: `mock_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        status: 'sent',
        mock: true,
      };
    }

    // Normalize phone: strip +, spaces, dashes. Baileys wants JID format.
    const phone = to.replace(/[^\d]/g, '');
    if (phone.length < 8 || phone.length > 15) {
      throw new Error('invalid phone number');
    }
    const jid = `${phone}@s.whatsapp.net`;

    const result = await entry.socket.sendMessage(jid, { text: message });
    return {
      message_id: result.key.id,
      status: 'sent',
      to_jid: jid,
    };
  }

  // ── Recovery ─────────────────────────────────────────────────────────

  /**
   * On gateway startup, try to reconnect every tenant that has a creds.json.
   * We don't await all — if one fails, others should still come up.
   */
  async restoreFromDisk() {
    let entries;
    try {
      entries = await fs.readdir(this.sessionsDir, { withFileTypes: true });
    } catch (err) {
      if (err.code === 'ENOENT') {
        this.logger.info('no sessions dir yet, starting fresh');
        return;
      }
      throw err;
    }

    for (const e of entries) {
      if (!e.isDirectory()) continue;
      const tenantId = e.name;
      const authDir = path.join(this.sessionsDir, tenantId, 'auth');
      const credsExist = await fs.access(path.join(authDir, 'creds.json'))
        .then(() => true)
        .catch(() => false);
      if (!credsExist) continue;

      this.logger.info({ tenantId }, 'restoring session from creds.json');
      try {
        await this.start(tenantId);
      } catch (err) {
        this.logger.error({ err, tenantId }, 'restore failed');
      }
    }
  }

  /**
   * Clean shutdown — close all sockets so creds.json stays valid.
   */
  async shutdownAll() {
    const entries = Array.from(this.sessions.values());
    await Promise.all(entries.map(async (entry) => {
      if (entry.socket) {
        try {
          entry.socket.end();
        } catch (err) {
          this.logger.warn({ err, tenantId: entry.tenantId }, 'socket.end threw');
        }
      }
    }));
    this.logger.info({ count: entries.length }, 'all sessions closed');
  }

  // ── Internals ────────────────────────────────────────────────────────

  _sessionDir(tenantId) {
    return path.join(this.sessionsDir, tenantId);
  }

  /**
   * POST delivery/read events to Kamilya backend so they can be persisted
   * in invitation_deliveries for HR analytics ("who saw the invite").
   *
   * Webhook URL is read from a file the backend writes — wa-gateway doesn't
   * know about DB. The backend writes /opt/whatsapp-gateway/webhooks/{tid}.json
   * whenever the tenant configures a webhook URL.
   */
  async _emitDeliveryWebhook(tenantId, update) {
    const statusMap = { 1: 'sent', 2: 'delivered', 3: 'read' };
    const status = statusMap[update.update.status];
    if (!status) return;

    const configPath = path.join(this.sessionsDir, tenantId, 'webhook.json');
    let webhookUrl;
    try {
      const cfg = JSON.parse(await fs.readFile(configPath, 'utf8'));
      webhookUrl = cfg.url;
    } catch {
      return; // no webhook configured
    }

    try {
      await fetch(webhookUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Wa-Gateway-Signature': 'internal',  // backend trusts gateway IPs
        },
        body: JSON.stringify({
          tenant_id: tenantId,
          message_id: update.key.id,
          to_jid: update.key.remoteJid,
          status,
          timestamp: new Date().toISOString(),
        }),
      });
    } catch (err) {
      this.logger.warn({ err, tenantId }, 'webhook delivery failed');
    }
  }
}

module.exports = { SessionManager };