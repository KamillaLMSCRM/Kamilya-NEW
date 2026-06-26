export interface AuthTenant {
  id: string;
  name: string;
  slug: string;
  is_demo: boolean;
  plan: string;
}

export interface AuthUser {
  user_id: string;
  tenant_id: string;
  telegram_id: string;
  role: string;
  full_name: string;
  email?: string | null;
  tenant?: AuthTenant | null;
  // Set when this session was minted by the platform superadmin via
  // /admin/super/tenants/{id}/impersonate. The frontend uses this to
  // render an "Acting as superadmin → tenant X (exit)" banner.
  impersonated_by?: string | null;
  impersonated_tenant?: string | null;
  impersonated_role?: string | null;
}

export interface AuthState {
  access_token: string;
  user: AuthUser;
}

const AUTH_KEY = 'kamilya_auth';
const TOKEN_COOKIE = 'kamilya_token';

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
  document.cookie = `${TOKEN_COOKIE}=${state.access_token}; path=/; max-age=86400; SameSite=Lax`;
}

export function clearStoredAuth(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(AUTH_KEY);
  document.cookie = `${TOKEN_COOKIE}=; path=/; max-age=0`;
}
