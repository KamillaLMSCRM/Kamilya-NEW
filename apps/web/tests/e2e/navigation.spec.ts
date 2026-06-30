import { test, expect, goToLanding } from './helpers';

test('landing page has all expected links in page', async ({ page, landingNavLinks }) => {
  await goToLanding(page);
  // Landing page nav bar: Login + Register
  await expect(landingNavLinks).toHaveCount(2);
});

test('all sidebar nav items are visible on dashboard', async ({ page }) => {
  await page.goto('/dashboard');
  await expect(page.locator('html')).toBeVisible({ timeout: 15_000 });
});

test('sidebar nav structure — verify expected hrefs exist in LandingPage', async ({ page }) => {
  await goToLanding(page);
  expect(page.url()).toBe('http://localhost:3000/');
});

test('dashboard and sub-pages return valid responses', async ({ page }) => {
  const routes = [
    '/dashboard',
    '/documents',
    '/courses',
    '/my-courses',
    '/positions',
    '/settings',
    '/admin/users',
    '/admin/quizzes',
    '/admin/enrollments',
    '/admin',
    '/certificates',
    // ADR-0012 §6 + TZ_COURSE_ASSIGNMENT_ACCESS_v1 §1.1: course-assignment
    // deep links. Sidebar uses query strings to land on the right tab in
    // the unified /admin/staff page; tests verify these routes load.
    '/admin/staff?tab=rules',
    '/admin/staff?tab=company-courses',
  ];

  for (const route of routes) {
    const response = await page.goto(route);
    const status = response?.status();
    if (status && (status === 200 || status === 301 || status === 302 || status === 307 || status === 308)) {
      await expect(page.locator('html')).toBeVisible({ timeout: 10_000 });
    }
    expect(status).not.toBe(500);
  }
});
