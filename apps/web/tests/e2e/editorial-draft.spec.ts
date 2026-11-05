import { test, expect } from '@playwright/test';
import { appOrigin, course, ids, SyntheticWorkspace } from './learning-workspace-ux-fixtures';

if (appOrigin !== 'http://127.0.0.1:3026') throw new Error('Requires task-owned loopback3026, all APIs intercepted.');
test.setTimeout(60_000);

for (const conflict of [false, true]) {
  test(`human draft review ${conflict ? 'conflict on mobile' : 'saved on desktop'}`, async ({ page, context }, info) => {
    await page.setViewportSize(conflict ? { width: 390, height: 844 } : { width: 1440, height: 1050 });
    const workspace = new SyntheticWorkspace(context, 'ru'); workspace.author();
    const inspected = { course_id: ids.course, has_active_hold: true, content_snapshot_hash: 'a'.repeat(64),
      available_revisions: ['synthetic-rev1'],
      source_documents: [{ document_id: ids.document, title: 'Синтетический регламент', filename: 'synthetic.md', authoritative_revision: 'synthetic-rev1' }],
      active_defects: [{ defect_id: 'p30-synthetic', description: 'Проверьте условие допуска.',
        target_title: 'Подготовка: кто проверяет оборудование?', evidence: { unverified: true,
          observation: 'Вопрос не указывает полномочия исполнителя.', possible_answers: ['Работник', 'Ответственный'],
          source_quotes: ['До начала работы оборудование проверяет ответственное лицо.'] } }],
      resolutions_history: [], draft_review: { version: 'p30-editorial-draft-v1', generation_status: 'draft_prepared',
        self_review_status: 'needs_attention', human_review_required: true, issues: [], observations: [] } };
    workspace.get(`/v1/courses/${ids.course}/source-uncertainty`, inspected);
    workspace.command('POST', `/v1/courses/${ids.course}/resolve-source-uncertainty`, () => conflict
      ? { status: 409, json: { detail: { code: 'source_uncertainty_resolution_rejected' } } }
      : { json: { ...course, status: 'draft', ai_generated: true, review_status: 'pending' } });
    await workspace.install();
    await page.goto(`${appOrigin}/courses/${ids.course}/edit`);
    await page.getByRole('button', { name: 'Открыть замечания и источники' }).click();
    const panel = page.getByRole('region', { name: 'Проверка черновика' });
    await expect(panel.getByText('Черновик подготовлен')).toBeVisible();
    await panel.getByText('Основание замечания — требует проверки').click();
    await expect(panel.getByText('Вопрос не указывает полномочия исполнителя.')).toBeVisible();
    await expect(panel.getByText('До начала работы оборудование проверяет ответственное лицо.')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath(conflict ? 'mobile-review.png' : 'desktop-review.png'), fullPage: true });
    await panel.getByRole('textbox', { name: 'Решение по замечанию' }).fill('Проверены условия и исправлена формулировка вопроса.');
    await panel.getByRole('textbox', { name: 'Итог проверки' }).fill('Уроки и тесты сверены с указанной версией источника.');
    await panel.getByRole('checkbox').check();
    await panel.getByRole('button', { name: 'Сохранить решения по этой версии' }).click();
    if (conflict) await expect(panel.getByRole('status')).toContainText('Содержание или источник изменились');
    else await expect.poll(() => workspace.matching('POST', `/v1/courses/${ids.course}/resolve-source-uncertainty`).length).toBe(1);
    expect(workspace.calls.some((call) => /\/(review|publish)$/.test(call.path) && call.method === 'POST')).toBe(false);
    const body = workspace.matching('POST', `/v1/courses/${ids.course}/resolve-source-uncertainty`)[0].body as Record<string, unknown>;
    expect(body.expected_content_hash).toBe('a'.repeat(64));
    workspace.assertIsolated();
  });
}
