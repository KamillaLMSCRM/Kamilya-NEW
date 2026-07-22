import { describe, expect, it } from 'vitest';
import {
  canAccessRoute,
  getAuthRedirect,
  getRoleHome,
  isNavigationItemActive,
} from '@/lib/rolePolicy';

describe('role route policy', () => {
  it.each([
    ['admin', '/admin', true],
    ['admin', '/admin/team', true],
    ['admin', '/admin/training-log', true],
    ['admin', '/courses', false],
    ['admin', '/assignments', false],
    ['org_admin', '/admin/kiosks', true],
    ['org_admin', '/admin/training-log', true],
    ['org_admin', '/documents', false],
    ['methodologist', '/courses', true],
    ['methodologist', '/admin/staff', true],
    ['methodologist', '/assignments', true],
    ['methodologist', '/admin/training-log', true],
    ['methodologist', '/admin/team', false],
    ['student', '/student', true],
    ['student', '/my-courses', true],
    ['student', '/courses/course-1', true],
    ['student', '/courses/course-1/edit', false],
    ['student', '/courses', false],
    ['student', '/documents', false],
    ['student', '/admin/training-log', false],
    ['superadmin', '/admin/super/tenants', true],
    ['superadmin', '/admin/providers', true],
    ['superadmin', '/dashboard', false],
    ['superadmin', '/admin/training-log', false],
  ] as const)('%s access to %s is %s', (role, route, expected) => {
    expect(canAccessRoute(role, route)).toBe(expected);
  });

  it('uses role-specific home routes', () => {
    expect(getRoleHome('admin')).toBe('/admin');
    expect(getRoleHome('org_admin')).toBe('/admin');
    expect(getRoleHome('methodologist')).toBe('/dashboard');
    expect(getRoleHome('student')).toBe('/student');
    expect(getRoleHome('superadmin')).toBe('/admin/super');
  });
});

describe('auth redirect policy', () => {
  it('waits while restore is pending', () => {
    expect(getAuthRedirect({
      initialized: false,
      accessToken: null,
      role: null,
      pathname: '/courses',
    })).toBeNull();
  });

  it('redirects to login after a failed restore instead of leaving a protected layout pending', () => {
    expect(getAuthRedirect({
      initialized: true,
      accessToken: null,
      role: null,
      pathname: '/dashboard',
    })).toBe('/login');
  });

  it('redirects an authenticated user to the active-role home when the route is disallowed', () => {
    expect(getAuthRedirect({
      initialized: true,
      accessToken: 'access-token',
      role: 'admin',
      pathname: '/dashboard',
    })).toBe('/admin');
  });

  it.each([
    ['admin', null],
    ['org_admin', null],
    ['methodologist', null],
    ['student', '/student'],
    ['superadmin', '/admin/super'],
  ] as const)('uses the shared training-log policy for direct routes: %s', (role, expected) => {
    expect(getAuthRedirect({
      initialized: true,
      accessToken: 'access-token',
      role,
      pathname: '/admin/training-log',
    })).toBe(expected);
  });
});

describe('navigation active state', () => {
  it('matches the staff structure link only for its selected tab', () => {
    expect(isNavigationItemActive(
      '/staff?tab=structure',
      '/staff',
      new URLSearchParams('tab=structure'),
    )).toBe(true);
    expect(isNavigationItemActive(
      '/staff?tab=structure',
      '/staff',
      new URLSearchParams('tab=import'),
    )).toBe(false);
  });
});
