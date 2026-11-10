import { forceRefreshAndStoreSession } from '@/lib/auth';
import { useAuthStore } from '@/store/authStore';
import { currentAuthorSession, sameAuthorSession, type AuthorSessionScope } from './authorSession';

/** Read only. Impersonated sessions return 401 without using the platform cookie.
 * A failed refresh returns its 401 if the original session survives; an expired
 * or replaced session throws AbortError. Never retries mutations. */
export async function authorRead(url: string, scope: AuthorSessionScope): Promise<Response> {
  const requireScope = () => {
    if (!sameAuthorSession(scope, currentAuthorSession(useAuthStore.getState()))) {
      throw new DOMException('Author session changed', 'AbortError');
    }
  };
  const read = () => {
    requireScope();
    const token = useAuthStore.getState().accessToken;
    if (!token) throw new DOMException('Author session unavailable', 'AbortError');
    return { token, pending: fetch(url, { method: 'GET', headers: { Authorization: `Bearer ${token}` } }) };
  };

  const first = read();
  let response = await first.pending;
  requireScope();
  if (response.status !== 401) return response;
  requireScope();
  if (scope.impersonatedBy !== null || scope.impersonatedRole !== null) return response;
  if (useAuthStore.getState().accessToken === first.token) {
    const refreshed = await forceRefreshAndStoreSession();
    requireScope();
    if (!refreshed) return response;
  }
  response = await read().pending;
  requireScope();
  return response;
}
