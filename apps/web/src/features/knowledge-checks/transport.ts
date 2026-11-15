import axios from 'axios';
import { useAuthStore } from '@/store/authStore';

// Separate transport deliberately avoids the shared interceptor's automatic 401 replay.
const client = axios.create({ baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000', withCredentials: true });
export function identity() {
  const { user, sessionEpoch, accessToken } = useAuthStore.getState();
  return JSON.stringify([!!accessToken, user?.user_id, user?.tenant_id, user?.role, user?.impersonated_by, user?.impersonated_role, sessionEpoch]);
}
export async function request<T>(path: string, options: { method?: 'GET' | 'POST' | 'PUT'; data?: unknown; params?: object; signal?: AbortSignal; scope: string }): Promise<T> {
  if (identity() !== options.scope || !useAuthStore.getState().accessToken) throw new Error('Session changed');
  const response = await client.request<T>({ url: path, method: options.method ?? 'GET', data: options.data, params: options.params, signal: options.signal, headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken}` } });
  if (identity() !== options.scope) throw new Error('Session changed');
  return response.data;
}
export const base = '/v1/knowledge-checks';
export function requestError(error: unknown, fallback: string): { text: string; uncertain: boolean } {
  const response = axios.isAxiosError(error) ? error.response : undefined;
  const raw = response?.data?.detail;
  const detail = typeof raw === 'string' ? raw : Array.isArray(raw)
    ? raw.map(item => typeof item?.msg === 'string' ? item.msg : '').filter(Boolean).join('; ') : '';
  return { text: response ? `${fallback} (${response.status})${detail ? `: ${detail}` : ''}` : fallback, uncertain: !response || response.status >= 500 || response.status === 409 };
}
