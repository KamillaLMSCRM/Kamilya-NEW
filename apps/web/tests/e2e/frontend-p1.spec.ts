import { expect, type Page } from '@playwright/test';
import type { AxeResults } from 'axe-core';
import { appOrigin, course, ids, test } from './learning-workspace-ux-fixtures';

test.use({ baseURL: appOrigin, serviceWorkers: 'block' });

async function accessibilitySmoke(page: Page) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const serious = await page.evaluate(async () => {
    const axe = (window as typeof window & { axe: { run: () => Promise<AxeResults> } }).axe;
    return (await axe.run()).violations.filter((item) => item.impact === 'serious' || item.impact === 'critical').map((item) => item.id);
  });
  expect(serious).toEqual([]);
}

const courses = Array.from({ length: 101 }, (_, index) => ({
  ...course, id: `72000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  title: `Course ${index + 1}`, status: 'draft', ai_generated: false,
}));

for (const width of [390, 915, 1024, 1440]) {
  test(`catalogue pagination, mobile return and skip link at ${width}`, async ({ page, workspace }, info) => {
    await page.setViewportSize({ width, height: 900 });
    workspace.role = 'methodologist';
    workspace.get('/v1/course-blueprints', []);
    workspace.onGet('/v1/courses', ({ url }) => {
      const pageNumber = Number(url.searchParams.get('page') ?? 1);
      const matching = courses.filter((item) => (!url.searchParams.get('status') || item.status === url.searchParams.get('status'))
        && (!url.searchParams.get('q') || item.title.includes(url.searchParams.get('q')!)));
      return { json: matching.slice((pageNumber - 1) * 100, pageNumber * 100) };
    });
    await page.goto('/courses');
    const rows = page.locator('[data-methodologist-records] > ul');
    await expect(rows.getByRole('button')).toHaveCount(100);
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('main#main-content')).toBeFocused();
    await expect(page.locator('#main-content')).toHaveCount(1);

    if (width < 1024) {
      for (const number of [1, 50, 100]) {
        const row = rows.getByRole('button', { name: new RegExp(`^Course ${number} Learning course`) });
        await row.scrollIntoViewIfNeeded();
        const priorScroll = await page.evaluate(() => window.scrollY);
        await row.click();
        await expect(rows).toBeHidden();
        const details = page.getByRole('region', { name: 'Open course' });
        await expect(details).toBeFocused();
        await expect(details.getByRole('heading', { name: `Course ${number}`, exact: true })).toBeVisible();
        if (number === 50) await page.screenshot({ path: info.outputPath('mobile-details.png') });
        await details.getByRole('button', { name: 'Back to course list' }).click();
        await expect(row).toBeFocused();
        await expect.poll(async () => Math.abs((await page.evaluate(() => window.scrollY)) - priorScroll)).toBeLessThan(3);
      }
    } else {
      await expect(page.getByRole('region', { name: 'Open course' })).toBeVisible();
      await expect(rows).toBeVisible();
      await expect(page.getByRole('button', { name: 'Back to course list' })).toBeHidden();
    }
    await page.getByRole('button', { name: 'Next page', exact: true }).click();
    await expect(page).toHaveURL(/page=2/);
    await expect(rows.getByRole('button')).toHaveCount(1);
    await expect(rows.getByRole('button', { name: /^Course 101 / })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();
    await page.reload();
    await expect(rows.getByRole('button', { name: /^Course 101 / })).toBeVisible();
    await page.screenshot({ path: info.outputPath('catalogue-page-2.png') });
    await page.getByRole('button', { name: 'Previous page', exact: true }).click();
    await expect(page).toHaveURL(`${appOrigin}/courses`);
    await expect(rows.getByRole('button')).toHaveCount(100);
    await page.goBack();
    await expect(rows.getByRole('button')).toHaveCount(1);
    await page.goForward();
    await expect(rows.getByRole('button')).toHaveCount(100);
    await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('draft');
    await expect(page).toHaveURL(/status=draft/);
    await expect(page).not.toHaveURL(/page=/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: info.outputPath('catalogue-list.png') });
    await accessibilitySmoke(page);
  });

  test(`creation HTTP failure preserves input at ${width}`, async ({ page, workspace }, info) => {
    await page.setViewportSize({ width, height: 900 });
    workspace.author();
    await page.goto(`/courses/${ids.course}/edit`);
    const moduleInput = page.getByRole('textbox', { name: 'Add Module', exact: true });
    const creationError = page.getByRole('alert').filter({ hasText: 'The title is retained' });
    await moduleInput.fill('Retained module');
    workspace.command('POST', `/v1/courses/${ids.course}/modules`, () => ({ status: 503, json: {} }));
    await moduleInput.press('Enter');
    await expect(creationError).toBeVisible();
    await expect(moduleInput).toHaveValue('Retained module');
    await expect(moduleInput).toBeEnabled();
    await creationError.scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath('module-creation-error.png') });
    workspace.command('POST', `/v1/courses/${ids.course}/modules`, () => ({ json: { id: '73000000-0000-4000-8000-000000000001', title: 'Retained module', order_index: 1 } }));
    await moduleInput.press('Enter');
    await expect(moduleInput).toHaveValue('');
    await expect(page.getByRole('heading', { name: 'Retained module' })).toBeVisible();
    await page.getByRole('button', { name: '+ Add Lesson' }).first().click();
    const lessonInput = page.getByRole('textbox', { name: 'Add Lesson', exact: true });
    await lessonInput.fill('Retained lesson');
    workspace.command('POST', `/v1/modules/${ids.module}/lessons`, () => ({ status: 503, json: {} }));
    await lessonInput.press('Enter');
    await expect(creationError).toBeVisible();
    await expect(lessonInput).toHaveValue('Retained lesson');
    await creationError.scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath('lesson-creation-error.png') });
    await accessibilitySmoke(page);
  });
}
