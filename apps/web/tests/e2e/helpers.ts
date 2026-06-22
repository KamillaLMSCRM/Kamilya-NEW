import { test as base, expect, Page, Locator } from '@playwright/test';

/* ─── page objects ─────────────────────────────────────────── */

export async function goToLanding(page: Page) {
  await page.goto('/');
  await expect(page).toHaveTitle(/Kamilya LMS/i);
}

export async function goToLogin(page: Page) {
  await page.goto('/login');
  await expect(page.locator('h1', { hasText: 'Kamilya LMS' })).toBeVisible();
}

export function landingNavLinks(page: Page) {
  return page.locator('nav.space-x-4 a');
}

export function loginPageElements(page: Page) {
  return {
    heading: page.locator('h2'),
    codeDigits: page.locator('[role="img"] > div'),
    copyButton: page.getByRole('button', { name: /скопировать/i }),
    telegramLink: page.locator('a[href*="t.me/"]'),
    registerLink: page.locator('a[href="/register"]'),
    refreshButton: page.getByRole('button', { name: /новый код/i }),
  };
}

/* ─── fixtures ─────────────────────────────────────────────── */

type E2EFixtures = {
  landingNavLinks: ReturnType<typeof landingNavLinks>;
  loginPageElements: ReturnType<typeof loginPageElements>;
};

export const test = base.extend<E2EFixtures>({
  landingNavLinks: async ({ page }, use) => {
    await use(landingNavLinks(page));
  },
  loginPageElements: async ({ page }, use) => {
    await use(loginPageElements(page));
  },
});

export { expect };
