export interface AuthUser {
  user_id: string;
  tenant_id: string;
  telegram_id: string;
  role: string;
  full_name: string;
}

export interface AuthState {
  access_token: string;
  user: AuthUser;
}

const AUTH_KEY = 'kamilya_auth';

export function getStoredAuth(): AuthState | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(AUTH_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function getAccessToken(): string | null {
  const state = getStoredAuth();
  return state?.access_token ?? null;
}

export function setStoredAuth(state: AuthState): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(AUTH_KEY, JSON.stringify(state));
}

export function clearStoredAuth(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(AUTH_KEY);
}
