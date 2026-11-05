import { expect, test } from '@playwright/test';
import { appOrigin, ids, SyntheticWorkspace } from './learning-workspace-ux-fixtures';

if (appOrigin !== 'http://127.0.0.1:3027') throw new Error('isolated_sidebar_fixture_required');

async function geometry(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const main = document.querySelector('main.app-shell-main') as HTMLElement;
    const rail = document.querySelector('[data-workspace-rail]') as HTMLElement;
    const box = main.getBoundingClientRect();
    const side = rail.getBoundingClientRect();
    return { viewport: innerWidth, client: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth, mainLeft: box.left, mainWidth: box.width,
      margin: getComputedStyle(main).marginLeft, railRight: side.right,
      railVisibility: getComputedStyle(rail).visibility };
  });
}

for (const mode of ['fresh-mobile', 'resize-from-desktop'] as const) {
  test(mode + ': mobile shell gives content the viewport without a persistent rail', async ({ page, context }, info) => {
    const workspace = new SyntheticWorkspace(context, 'ru');
    await workspace.install();
    workspace.author();
    const revision = 'a'.repeat(64);
    workspace.get(`/v1/courses/${ids.course}/source-uncertainty`, {
      course_id: ids.course, has_active_hold: true, content_snapshot_hash: 'b'.repeat(64),
      available_revisions: [revision], source_documents: [{ document_id: ids.document,
        title: 'Synthetic source review document', filename: 'source.md', authoritative_revision: revision }],
      active_defects: [{ defect_id: 'finding-1', description: 'Проверьте условие и источник.',
        target_title: 'src-5833ddabbd3ff6586ec3', evidence: { observation: 'Исходное условие требует проверки.' } }],
      resolutions_history: [], draft_review: { version: 'p30-editorial-draft-v1', generation_status: 'draft_prepared',
        self_review_status: 'needs_attention', human_review_required: true, issues: [], observations: [] },
    });
    await page.setViewportSize(mode === 'fresh-mobile' ? { width: 390, height: 844 } : { width: 1440, height: 1050 });
    await page.goto(`/courses/${ids.course}/edit`);
    await expect(page.getByRole('heading', { name: 'Редактировать курс', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Открыть замечания и источники', exact: true }).click();
    await expect(page.getByText('Проверьте условие и источник.', { exact: true })).toBeVisible();
    if (mode === 'resize-from-desktop') await page.setViewportSize({ width: 390, height: 844 });
    const immediate = await geometry(page);
    console.log(mode, 'immediate', JSON.stringify(immediate));
    await page.screenshot({ path: info.outputPath(mode + '-immediate.png') });
    await page.waitForTimeout(600);
    const settled = await geometry(page);
    console.log(mode, 'settled', JSON.stringify(settled));
    await page.screenshot({ path: info.outputPath(mode + '.png'), fullPage: true });
    expect(immediate.viewport).toBe(390);
    expect(immediate.mainLeft).toBeLessThanOrEqual(1);
    expect(immediate.mainWidth).toBeGreaterThanOrEqual(389);
    expect(immediate.scroll - immediate.client).toBeLessThanOrEqual(1);
    expect(settled.railVisibility === 'hidden' || settled.railRight <= 0).toBe(true);
    await page.getByRole('button', { name: 'Открыть меню', exact: true }).click();
    await expect(page.locator('[data-workspace-rail]')).toBeVisible();
    expect((await geometry(page)).mainLeft).toBeLessThanOrEqual(1);
    await page.getByRole('button', { name: 'Закрыть меню', exact: true }).last().click({ position: { x: 350, y: 400 } });
    await expect(page.locator('[data-workspace-rail]')).toBeHidden();
    workspace.assertIsolated();
  });
}

test('desktop sidebar still collapses and restores its content margin', async ({ page, context }) => {
  const workspace = new SyntheticWorkspace(context, 'ru');
  await workspace.install();
  workspace.author();
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto(`/courses/${ids.course}/edit`);
  const main = page.locator('main.app-shell-main');
  const rail = page.locator('[data-workspace-rail]');
  await expect(rail).toHaveCSS('width', '240px');
  await expect(main).toHaveCSS('margin-left', '240px');
  await page.getByRole('button', { name: 'Свернуть сайдбар (Ctrl+B)', exact: true }).click();
  await expect(rail).toHaveCSS('width', '68px');
  await expect(main).toHaveCSS('margin-left', '68px');
  await page.getByRole('button', { name: 'Развернуть сайдбар (Ctrl+B)', exact: true }).click();
  await expect(rail).toHaveCSS('width', '240px');
  await expect(main).toHaveCSS('margin-left', '240px');
  workspace.assertIsolated();
});
