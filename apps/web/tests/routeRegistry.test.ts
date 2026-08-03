import { describe, expect, it } from 'vitest';
import {
  CAPABILITIES,
  ROLE_CAPABILITIES,
  ROUTES,
  canAccessRegisteredRoute,
  getNavigationRoutes,
  hasCapability,
  isPublicRoute,
} from '@/lib/routeRegistry';

describe('route and capability registry', () => {
  it('defines every product role against typed capabilities', () => {
      expect(Object.keys(ROLE_CAPABILITIES)).toEqual([
        'admin',
        'methodologist',
        'student',
      'superadmin',
    ]);
    expect(Object.values(ROLE_CAPABILITIES).flat().every((capability) => CAPABILITIES.includes(capability))).toBe(true);
  });

  it('keeps active working modes isolated instead of unioning assigned roles', () => {
    expect(hasCapability('student', 'manage_profile')).toBe(true);
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
    expect(ROUTES.some((route) => route.id === 'quiz-assignments')).toBe(false);
    expect(hrefs).not.toContain('/quizzes?section=assignments');
  });

  it('makes confirmation procedures discoverable for methodologists without giving admins access', () => {
    const methodologistSidebar = getNavigationRoutes('methodologist', 'sidebar');
    const procedureRoute = methodologistSidebar.find((route) => route.id === 'training-procedures');

    expect(procedureRoute).toMatchObject({
      href: '/training-procedures',
      section: 'workforce',
      sidebar: true,
      commandPalette: true,
      capability: 'configure_training_procedures',
    });
    expect(getNavigationRoutes('admin', 'sidebar').some((route) => route.id === 'training-procedures')).toBe(false);
    expect(canAccessRegisteredRoute('methodologist', '/training-procedures')).toBe(true);
    expect(canAccessRegisteredRoute('admin', '/training-procedures')).toBe(false);
  });

  it('keeps contextual workforce tools out of global navigation', () => {
    const routes = getNavigationRoutes('methodologist', 'sidebar');
    expect(routes[0].href).toBe('/dashboard');
    const hiddenContextualRoutes = [
      'competencies',
      'training-rules',
      'invitations',
      'course-assignments',
    ];
    expect(routes.map(({ id }) => id)).not.toEqual(expect.arrayContaining(hiddenContextualRoutes));
    expect(getNavigationRoutes('methodologist', 'commandPalette').map(({ id }) => id))
      .not.toEqual(expect.arrayContaining(hiddenContextualRoutes));
    expect(getNavigationRoutes('admin', 'sidebar').some(({ id }) => id === 'invitations')).toBe(false);
  });

  it('keeps hidden contextual routes reachable through their capabilities', () => {
    const contextualRoutes = [
      ['competencies', '/competencies'],
      ['training-rules', '/training-rules'],
      ['invitations', '/invitations'],
      ['course-assignments', '/assignments'],
    ] as const;

    for (const [, pathname] of contextualRoutes) {
      expect(canAccessRegisteredRoute('methodologist', pathname)).toBe(true);
    }
  });

  it('exposes a common profile to every authenticated working mode', () => {
    for (const role of ['admin', 'methodologist', 'student']) {
      expect(canAccessRegisteredRoute(role, '/profile')).toBe(true);
    }
    expect(canAccessRegisteredRoute('superadmin', '/profile')).toBe(true);
    expect(canAccessRegisteredRoute('admin', '/settings')).toBe(true);
    expect(canAccessRegisteredRoute('methodologist', '/settings')).toBe(false);
  });

  it('keeps unfinished communication modules routable but out of navigation', () => {
    const sidebar = getNavigationRoutes('methodologist', 'sidebar').map(({ id }) => id);
    const commands = getNavigationRoutes('methodologist', 'commandPalette').map(({ id }) => id);

    expect(sidebar).not.toContain('surveys-manage');
    expect(sidebar).not.toContain('announcements');
    expect(commands).not.toContain('surveys-manage');
    expect(commands).not.toContain('announcements');
    expect(canAccessRegisteredRoute('methodologist', '/surveys')).toBe(true);
    expect(canAccessRegisteredRoute('methodologist', '/announcements')).toBe(true);
    expect(canAccessRegisteredRoute('student', '/surveys')).toBe(true);
  });

  it('recognizes only the public certificate verification surface', () => {
    expect(isPublicRoute('/verify/certificate')).toBe(true);
    expect(isPublicRoute('/verify/certificate/KML-2026-123456')).toBe(true);
    expect(isPublicRoute('/certificates')).toBe(false);
    expect(isPublicRoute('/admin/certificates/settings')).toBe(false);
  });

  it('keeps position qualification cards on the methodologist surface', () => {
    const cardPath = '/positions/420155dd-d2e3-43f1-ab16-108d8e5e4901';

      expect(canAccessRegisteredRoute('methodologist', cardPath)).toBe(true);
      expect(canAccessRegisteredRoute('admin', cardPath)).toBe(false);
    });
});
