/**
 * Integrations API client — talks to Kamilya backend /v1/integrations/*.
 *
 * Three channels: WhatsApp (wa-gateway), SMTP (per-tenant SMTP relay),
 * Telegram (per-tenant bot). Tenant provides all credentials — Kamilya
 * is middleware, not provider (ADR-0010).
 */

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? '').replace(/\/$/, '');

function auth(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

// ── WhatsApp ──────────────────────────────────────────────────────────────

export interface WhatsAppStatus {
  status:
    | 'not_started'
    | 'persisted'
    | 'initializing'
    | 'qr_pending'
    | 'connected'
    | 'disconnected'
    | 'logged_out'
    | 'gateway_error';
  phone_number: string | null;
  qr: string | null;
  qr_expires_at: string | null;
}

export interface WhatsAppInitResult {
  status: 'connected' | 'qr_pending' | 'initializing';
  qr: string | null;
  phone_number: string | null;
  mock: boolean;
}

export async function initWhatsApp(token: string): Promise<WhatsAppInitResult> {
  const res = await fetch(`${BASE}/v1/integrations/whatsapp/init`, {
    method: 'POST',
    headers: auth(token),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function getWhatsAppStatus(token: string): Promise<WhatsAppStatus> {
  const res = await fetch(`${BASE}/v1/integrations/whatsapp/status`, {
    headers: auth(token),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function logoutWhatsApp(token: string): Promise<void> {
  const res = await fetch(`${BASE}/v1/integrations/whatsapp/logout`, {
    method: 'POST',
    headers: auth(token),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function testWhatsApp(token: string): Promise<{ ok: boolean; detail: string }> {
  const res = await fetch(`${BASE}/v1/integrations/whatsapp/test`, {
    method: 'POST',
    headers: auth(token),
  });
  const body = await res.json().catch(() => ({ ok: false, detail: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

// ── SMTP ─────────────────────────────────────────────────────────────────

export interface SMTPConfig {
  host: string;
  port: number;
  username: string;
  password: string;
  from_addr: string;
  from_name: string;
  use_tls: boolean;
}

export async function setSMTP(token: string, cfg: SMTPConfig): Promise<void> {
  const res = await fetch(`${BASE}/v1/integrations/smtp`, {
    method: 'PUT',
    headers: auth(token),
    body: JSON.stringify(cfg),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
}

export async function testSMTP(token: string): Promise<{ ok: boolean; detail: string }> {
  const res = await fetch(`${BASE}/v1/integrations/smtp/test`, {
    method: 'POST',
    headers: auth(token),
  });
  const body = await res.json().catch(() => ({ ok: false, detail: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

// ── Telegram ─────────────────────────────────────────────────────────────

export interface TelegramConfig {
  bot_token: string;
}

export async function setTelegram(token: string, cfg: TelegramConfig): Promise<void> {
  const res = await fetch(`${BASE}/v1/integrations/telegram`, {
    method: 'PUT',
    headers: auth(token),
    body: JSON.stringify(cfg),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
}

export async function testTelegram(token: string): Promise<{ ok: boolean; detail: string }> {
  const res = await fetch(`${BASE}/v1/integrations/telegram/test`, {
    method: 'POST',
    headers: auth(token),
  });
  const body = await res.json().catch(() => ({ ok: false, detail: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

// ── List ─────────────────────────────────────────────────────────────────

export interface IntegrationSummary {
  channel: 'smtp' | 'telegram' | 'whatsapp';
  is_active: boolean;
  last_test_at: string | null;
  last_test_status: string | null;
  has_secret: boolean;
  updated_at: string;
  extra: Record<string, unknown>;
}

export async function listIntegrations(token: string): Promise<IntegrationSummary[]> {
  const res = await fetch(`${BASE}/v1/integrations`, {
    headers: auth(token),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}