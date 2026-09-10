export type AiPurpose = 'generation' | 'embedding';
export type TenantAiProvider = 'deepseek' | 'openrouter' | 'voyage' | 'cohere';
export interface TenantAiSetting {
  purpose: AiPurpose;
  provider: TenantAiProvider;
  model: string;
  enabled: boolean;
  free_only: boolean;
  has_key: boolean;
  output_dimensions: number | null;
}
export interface TenantAiUpdate {
  provider: TenantAiProvider;
  model: string;
  api_key?: string;
  enabled: boolean;
  free_only: boolean;
  output_dimensions: number | null;
}

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? '').replace(/\/$/, '');

async function request(token: string, path: string, method: string, signal: AbortSignal, body?: TenantAiUpdate) {
  const response = await fetch(`${BASE}/v1/admin/ai-providers${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
    signal,
    cache: 'no-store',
  });
  // Never propagate backend validation input or provider error bodies: they may contain a key.
  if (!response.ok) throw new Error(`tenant_ai_request_${response.status}`);
  return response.status === 204 ? null : response.json();
}

export async function getTenantAiSettings(token: string, signal: AbortSignal): Promise<TenantAiSetting[]> {
  const data = await request(token, '', 'GET', signal);
  if (!data || !Array.isArray(data.providers)) throw new Error('tenant_ai_invalid_response');
  return data.providers;
}

export async function saveTenantAiSetting(token: string, purpose: AiPurpose, body: TenantAiUpdate, signal: AbortSignal): Promise<void> {
  await request(token, `/${purpose}`, 'PUT', signal, body);
}

export async function removeTenantAiSetting(token: string, purpose: AiPurpose, signal: AbortSignal): Promise<void> {
  await request(token, `/${purpose}`, 'DELETE', signal);
}
