import { test, expect, goToLanding, goToLogin } from './helpers';

test('landing page shows title, nav links, and hero', async ({ page }) => {
  await goToLanding(page);

  // Title present
  await expect(page.locator('nav > div.text-2xl', { hasText: 'Kamilya LMS' })).toBeVisible();

  // Nav has Login + Register links
  const nav = page.locator('nav.space-x-4 a');
  await expect(nav).toHaveCount(2);

  await expect(nav.first()).toHaveAttribute('href', '/login');
  await expect(nav.last()).toHaveAttribute('href', '/register');

  // Hero section visible
  await expect(page.locator('h1')).toBeVisible();
  await expect(page.locator('#features')).toBeVisible();
});

test('landing → navigate to login page', async ({ page }) => {
  await goToLanding(page);
  await page.getByRole('link', { name: /войти/i }).click();
  await page.waitForURL(/\/login/);
  await expect(page.locator('h1', { hasText: 'Kamilya LMS' })).toBeVisible();
});

test('landing → navigate to register from nav bar', async ({ page }) => {
  await goToLanding(page);
  await page.getByRole('link', { name: /регистрац/i }).click();
  // Should land on /register (308 or direct)
  const url = page.url();
  expect(url).toMatch(/\/register/);
});

test('landing → navigate to register from hero CTA', async ({ page }) => {
  await goToLanding(page);
  const heroStartButton = page.getByRole('link', { name: /начать/i, exact: false }).first();
  await heroStartButton.click();
  const url = page.url();
  expect(url).toMatch(/\/register/);
});

test('login page generates code and shows digit boxes', async ({ page, loginPageElements: el }) => {
  await goToLogin(page);

  // At least one code digit box rendered
  await expect(el.codeDigits.first()).toBeVisible();

  // Copy button present
  await expect(el.copyButton).toBeVisible();

  // Telegram bot link present
  await expect(el.telegramLink).toBeVisible();
  await expect(el.telegramLink).toHaveAttribute('href', 'https://t.me/kamilla_lms_bot');

  // Refresh button
  await expect(el.refreshButton).toBeVisible();
});

test('login page has registration link', async ({ page, loginPageElements: el }) => {
  await goToLogin(page);
  await expect(el.registerLink).toHaveAttribute('href', '/register');
});

test('login page heading is visible', async ({ page, loginPageElements: el }) => {
  await goToLogin(page);
  await expect(el.heading).toContainText(/войти с помощью telegram|войти через telegram/i);
});
