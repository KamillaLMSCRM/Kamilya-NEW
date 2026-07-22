export const APP_ROLES = ['admin', 'org_admin', 'methodologist', 'student', 'superadmin'] as const;

export type AppRole = (typeof APP_ROLES)[number];

type RouteMatcher = (pathname: string) => boolean;

export interface AuthRedirectInput {
  initialized: boolean;
  accessToken: string | null;
  role: string | null | undefined;
  pathname: string;
}

function exact(path: string): RouteMatcher {
  return (pathname) => pathname === path;
}

function prefix(path: string): RouteMatcher {
  return (pathname) => pathname === path || pathname.startsWith(`${path}/`);
}

function learnerCourseRoute(pathname: string): boolean {
  return pathname.startsWith('/courses/') && !pathname.includes('/edit');
}

const ROLE_POLICY: Record<AppRole, { home: string; routes: readonly RouteMatcher[] }> = {
  admin: {
    home: '/admin',
    routes: [
      exact('/admin'),
      prefix('/admin/team'),
      prefix('/admin/users'),
      prefix('/admin/kiosks'),
      prefix('/admin/settings/integrations'),
      prefix('/admin/certificates/settings'),
      prefix('/admin/training-log'),
      exact('/settings'),
    ],
  },
  org_admin: {
    home: '/admin',
    routes: [
      exact('/admin'),
      prefix('/admin/team'),
      prefix('/admin/users'),
      prefix('/admin/kiosks'),
      prefix('/admin/settings/integrations'),
      prefix('/admin/certificates/settings'),
      prefix('/admin/training-log'),
      exact('/settings'),
    ],
  },
  methodologist: {
    home: '/dashboard',
    routes: [
      exact('/dashboard'),
      prefix('/ai'),
      exact('/learning-paths'),
      exact('/cohorts'),
      exact('/competencies'),
      exact('/surveys'),
      exact('/announcements'),
      prefix('/courses'),
      prefix('/quizzes'),
      prefix('/documents'),
      exact('/staff'),
      prefix('/positions'),
      prefix('/assignments'),
      prefix('/admin/staff'),
      prefix('/admin/quizzes'),
      prefix('/admin/invitations'),
      prefix('/admin/training-log'),
      prefix('/admin/enrollments'),
    ],
  },
  student: {
    home: '/student',
    routes: [
      exact('/student'),
      exact('/my-courses'),
      exact('/my-quizzes'),
      prefix('/certificates'),
      exact('/learning-paths'),
      exact('/surveys'),
      learnerCourseRoute,
    ],
  },
  superadmin: {
    home: '/admin/super',
    routes: [prefix('/admin/super'), prefix('/admin/providers')],
  },
};

export function isAppRole(role: string | null | undefined): role is AppRole {
  return typeof role === 'string' && (APP_ROLES as readonly string[]).includes(role);
}

export function getRoleHome(role: string | null | undefined): string {
  return isAppRole(role) ? ROLE_POLICY[role].home : '/login';
}

export function getRoutePath(route: string): string {
  return new URL(route, 'http://localhost').pathname;
}

export function canAccessRoute(role: string | null | undefined, route: string): boolean {
  if (!isAppRole(role)) return false;
  const pathname = getRoutePath(route);
  return ROLE_POLICY[role].routes.some((matches) => matches(pathname));
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
