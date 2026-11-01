import { useAuthStore } from '@/store/authStore';

type AuthIdentity = {
  accessToken: string | null;
  sessionEpoch?: number;
  user: { user_id: string; tenant_id: string | null; role: string; impersonated_by?: string; impersonated_role?: string } | null;
};

export type AuthorSessionScope = {
  sessionPresent: boolean; userId: string | null; tenantId: string | null; role: string | null; sessionEpoch: number; impersonatedBy: string | null; impersonatedRole: string | null; generation: number;
};

// Credentials are transport-only. This clock remembers identities/presence, not
// tokens, and distinguishes logout/login even when the same actor returns.
let current: AuthorSessionScope | null = null;
export function authorSessionScope(auth: AuthIdentity): AuthorSessionScope {
  const identity = { sessionPresent: Boolean(auth.accessToken), userId: auth.user?.user_id ?? null, tenantId: auth.user?.tenant_id ?? null, role: auth.user?.role ?? null, sessionEpoch: auth.sessionEpoch ?? 0, impersonatedBy: auth.user?.impersonated_by ?? null, impersonatedRole: auth.user?.impersonated_role ?? null };
  if (!current || current.sessionPresent !== identity.sessionPresent || current.userId !== identity.userId
    || current.tenantId !== identity.tenantId || current.role !== identity.role || current.sessionEpoch !== identity.sessionEpoch
    || current.impersonatedBy !== identity.impersonatedBy || current.impersonatedRole !== identity.impersonatedRole) {
    current = { ...identity, generation: (current?.generation ?? 0) + 1 };
  }
  return current;
}

// Observe session boundaries while the author page is unmounted, so its volatile
// recovery buffer cannot reappear after logout. A token-only refresh is a no-op.
if (typeof useAuthStore.subscribe === 'function') {
  useAuthStore.subscribe((auth) => { authorSessionScope(auth); });
}

export function currentAuthorSession(fallback: AuthIdentity): AuthorSessionScope {
  return authorSessionScope(typeof useAuthStore.getState === 'function' ? useAuthStore.getState() : fallback);
}

export function sameAuthorSession(left: AuthorSessionScope, right: AuthorSessionScope) {
  return left.generation === right.generation && left.sessionPresent === right.sessionPresent
    && left.userId === right.userId && left.tenantId === right.tenantId && left.role === right.role
    && left.sessionEpoch === right.sessionEpoch && left.impersonatedBy === right.impersonatedBy && left.impersonatedRole === right.impersonatedRole;
}
