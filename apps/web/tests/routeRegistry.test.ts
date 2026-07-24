import { describe, expect, it } from 'vitest';
import {
  CAPABILITIES,
  ROLE_CAPABILITIES,
  ROUTES,
  getNavigationRoutes,
  hasCapability,
} from '@/lib/routeRegistry';

describe('route and capability registry', () => {
  it('defines every product role against typed capabilities', () => {
    expect(Object.keys(ROLE_CAPABILITIES)).toEqual([
      'admin',
      'org_admin',
      'methodologist',
      'student',
      'superadmin',
    ]);
    expect(Object.values(ROLE_CAPABILITIES).flat().every((capability) => CAPABILITIES.includes(capability))).toBe(true);
  });

  it('keeps active working modes isolated instead of unioning assigned roles', () => {
    expect(hasCapability('admin', 'manage_content')).toBe(false);
    expect(hasCapability('admin', 'manage_learners')).toBe(false);
    expect(hasCapability('admin', 'view_training_log')).toBe(false);
    expect(hasCapability('methodologist', 'manage_content')).toBe(true);
    expect(hasCapability('methodologist', 'manage_learners')).toBe(true);
    expect(hasCapability('methodologist', 'view_training_log')).toBe(true);
    expect(hasCapability('methodologist', 'configure_tenant')).toBe(false);
  });

  it('uses the same ordered registry for sidebar and command palette', () => {
    for (const role of Object.keys(ROLE_CAPABILITIES)) {
      const sidebar = getNavigationRoutes(role, 'sidebar').map(({ id }) => id);
      const commands = getNavigationRoutes(role, 'commandPalette').map(({ id }) => id);
      expect(commands).toEqual(sidebar);
    }
  });

  it('exposes only canonical navigation hrefs', () => {
    const hrefs = ROUTES.filter((route) => route.sidebar || route.commandPalette).map((route) => route.href);
    expect(hrefs).not.toContain('/admin/staff');
    expect(hrefs).not.toContain('/admin/invitations');
    expect(hrefs).not.toContain('/admin/training-log');
    expect(hrefs).not.toContain('/admin/quizzes/assign');
    expect(hrefs).toContain('/quizzes?section=assignments');
  });

  it('puts the methodologist dashboard first and learner invitations in workforce', () => {
    const routes = getNavigationRoutes('methodologist', 'sidebar');
    expect(routes[0].href).toBe('/dashboard');
    expect(routes.find(({ id }) => id === 'invitations')).toMatchObject({
      href: '/invitations',
      section: 'workforce',
    });
    expect(getNavigationRoutes('admin', 'sidebar').some(({ id }) => id === 'invitations')).toBe(false);
  });
});
