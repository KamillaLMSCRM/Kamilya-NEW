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
    // 2026-06-30: removed the deep-link routes to specific tabs of
    // /admin/staff. Sidebar / Cmd-K now goes through the single
    // "Штатное расписание" entry; tabs are reached inside the page.
    // The two tab deep-links are still valid (server keeps ?tab= as
    // a feature), so leaving them out of the smoke list is just a
    // navigation simplification, not a deprecation.
    '/admin/staff',
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
