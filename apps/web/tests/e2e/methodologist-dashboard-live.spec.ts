import { expect, test } from '@playwright/test';

const baseUrl = process.env.LIVE_DASHBOARD_BASE_URL;
const email = process.env.DEV_QA_METHODOLOGIST_EMAIL;
const password = process.env.DEV_QA_METHODOLOGIST_PASSWORD;

test.describe('live methodologist dashboard', () => {
  test.skip(!baseUrl || !email || !password, 'Live dashboard credentials and base URL are required');

  test('shows an actionable dashboard without horizontal overflow', async ({ page }, testInfo) => {
    const failedApiResponses: string[] = [];
    page.on('response', (response) => {
      if (response.url().includes('/api/v1/') && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${new URL(response.url()).pathname}`);
      }
    });

    await page.setViewportSize({ width: 1440, height: 960 });
    await page.goto(`${baseUrl}/login`);
    await page.getByRole('tab', { name: /Пароль|Password|Құпия сөз/i }).click();
    await page.getByRole('textbox', { name: /Email/i }).fill(email!);
    await page.getByRole('textbox', { name: /Пароль|Password|Құпия сөз/i }).fill(password!);
    await page.getByRole('button', { name: /Войти|Sign in|Кіру/i }).click();

    await expect(page).toHaveURL(/\/dashboard(?:$|[?#])/);
    await expect(page.getByRole('heading', { name: /Обзор обучения|Learning overview|Оқу шолуы/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Требует внимания|Needs attention|Назар аудару қажет/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Состояние обучения|Training health|Оқу жағдайы/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Контент в работе|Content in progress|Жұмыстағы контент/i })).toBeVisible();
    await expect(page.getByText(/Сводка обучения временно недоступна|learning summary is temporarily unavailable|Оқу қорытындысы уақытша қолжетімсіз/i)).toHaveCount(0);

    await page.screenshot({ path: testInfo.outputPath('dashboard-desktop.png'), fullPage: true });
    for (const viewport of [{ width: 1024, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(400); // Let the sidebar margin transition settle after crossing the mobile breakpoint.
      await expect(page.getByRole('heading', { name: /Обзор обучения|Learning overview|Оқу шолуы/i })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 1) {
        const offenders = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>('body *')]
          .map((element) => ({
            tag: element.tagName,
            className: element.className,
            left: Math.round(element.getBoundingClientRect().left),
            right: Math.round(element.getBoundingClientRect().right),
            width: Math.round(element.getBoundingClientRect().width),
          }))
          .filter((item) => item.right > document.documentElement.clientWidth + 1)
          .sort((a, b) => b.right - a.right)
          .slice(0, 12));
        console.log('dashboard-overflow', viewport.width, offenders);
      }
      expect(overflow, `horizontal overflow at ${viewport.width}px`).toBeLessThanOrEqual(1);
    }
    await page.screenshot({ path: testInfo.outputPath('dashboard-mobile.png'), fullPage: true });

    expect(failedApiResponses).toEqual([]);
  });
});
