import {
  APP_ROLES,
  ROLE_HOMES,
  canAccessRegisteredRoute,
  isAppRole,
} from '@/lib/routeRegistry';

export { APP_ROLES, isAppRole };
export type { AppRole } from '@/lib/routeRegistry';

export interface AuthRedirectInput {
  initialized: boolean;
  accessToken: string | null;
  role: string | null | undefined;
  pathname: string;
}

export function getRoleHome(role: string | null | undefined): string {
  return isAppRole(role) ? ROLE_HOMES[role] : '/login';
}

export function getRoutePath(route: string): string {
  return new URL(route, 'http://localhost').pathname;
}

export function canAccessRoute(role: string | null | undefined, route: string): boolean {
  if (!isAppRole(role)) return false;
  const pathname = getRoutePath(route);
  return canAccessRegisteredRoute(role, pathname);
}

export function getAuthRedirect({ initialized, accessToken, role, pathname }: AuthRedirectInput): string | null {
  if (!initialized) return null;
  if (!accessToken || !isAppRole(role)) return '/login';
  return canAccessRoute(role, pathname) ? null : getRoleHome(role);
}

export function isNavigationItemActive(
  href: string,
  pathname: string,
  searchParams: Pick<URLSearchParams, 'get'>,
): boolean {
  const target = new URL(href, 'http://localhost');
  const targetPath = target.pathname;

  if (pathname !== targetPath) {
    const segmentCount = targetPath.split('/').filter(Boolean).length;
    return segmentCount > 1 && pathname.startsWith(`${targetPath}/`);
  }

  for (const [key, value] of target.searchParams) {
    if (searchParams.get(key) !== value) return false;
  }

  return true;
}
