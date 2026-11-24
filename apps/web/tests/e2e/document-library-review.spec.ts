import { expect } from '@playwright/test';
import { appOrigin, course, ids, sourceDocument, test, timestamp } from './learning-workspace-ux-fixtures';

if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER) throw new Error('Use the dedicated loopback build for the document review tests.');

test.use({ baseURL: appOrigin, serviceWorkers: 'block' });

const original = 'Use the current training checklist.';
const explanation = 'Verified against the checklist.';
const reviewPath = '/v1/documents/' + ids.document + '/editorial-review';
const reviewPage = reviewPath.replace('/v1', '');
const cataloguePage = '/documents?document_id=' + ids.document;
const documentRoute = '/v1/documents/' + ids.document;
const question = {
  id: 'reference', quote: original, start: 0, end: original.length,
  reason: 'Confirm the applicable checklist.', resolution: null,
};
const decision = { decision: 'keep' as const, before: original, after: original, reason: explanation, start: 0, end: original.length };
const openReview = {
  document_id: ids.document, title: sourceDocument.title, status: 'in_review', revision: 5,
  document_version: 1, pdf: false, preparation: null, questions: [question], automatic: [],
  original_text: original, working_text: original, journal: [], approval: null,
};
const resolved = { ...openReview, revision: 6, questions: [{ ...question, resolution: decision }] };
const approved = {
  ...resolved, status: 'approved', revision: 7,
  approval: { approval_id: ids.reviewAttempt, created_at: timestamp, revision: 7 },
};
const unused = { total: 0, courses: 0, positions: 0, lessons: 0, active_jobs: 0 };
const used = { ...unused, courses: 1, total: 1 };
const catalogue = { next_cursor: null, has_more: false, limit: 25 };

for (const [width, height] of [[1440, 900], [390, 844]]) {
  test.describe('review and source actions at ' + width, () => {
    test.use({ viewport: { width, height } });

    test('reopens a keep decision and deletes the approved document without generation', async ({ page, workspace }) => {
      workspace.documents();
      let review: typeof openReview | typeof resolved | typeof approved = openReview;
      let deleted = false;
      workspace.onGet(reviewPath, () => ({ json: review }));
      workspace.onGet('/v1/documents/catalog', ({ url }) => {
        expect(url.searchParams.get('document_id')).toBe(ids.document);
        expect(url.searchParams.get('include_source_review')).toBe('true');
        return { json: {
          items: deleted ? [] : [{ ...sourceDocument, source_review_status: review.status, usages_summary: unused }],
          page: catalogue,
        } };
      });

      await page.goto(reviewPage);
      await page.getByRole('radio', { name: 'Keep wording', exact: true }).check();
      const save = page.getByRole('button', { name: 'Save decision', exact: true });
      await expect(save).toBeDisabled();
      await page.getByLabel('Reason for the decision', { exact: true }).fill(explanation);
      workspace.command('POST', reviewPath, ({ body }) => {
        expect(body).toMatchObject({ action: 'resolve', decision: 'keep', item_id: question.id, reason: explanation, expected_revision: 5 });
        expect(body).not.toHaveProperty('replacement');
        review = resolved;
        return { json: review };
      });
      await save.click();
      await expect(page.getByText('Original wording kept', { exact: true })).toBeVisible();

      await page.reload();
      await expect(page.getByText('Original wording kept', { exact: true })).toBeVisible();
      workspace.command('POST', reviewPath, ({ body }) => {
        expect(body).toMatchObject({ action: 'approve', expected_revision: 6 });
        review = approved;
        return { json: review };
      });
      await page.getByRole('button', { name: 'Approve edition', exact: true }).click();
      await expect(page.getByRole('link', { name: 'Create course', exact: true })).toHaveAttribute('href', '/ai/generate?document_id=' + ids.document);

      await page.getByRole('link', { name: 'Back to document', exact: true }).click();
      await expect(page).toHaveURL(appOrigin + cataloguePage);
      await expect(page.getByRole('link', { name: 'Open review', exact: true })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Create course', exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);

      workspace.command('DELETE', documentRoute, () => {
        deleted = true;
        return { status: 202, json: { document_id: ids.document, lifecycle_status: 'deletion_pending' } };
      });
      await page.getByRole('button', { name: 'Delete: ' + sourceDocument.title, exact: true }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click();
      await expect(page.getByRole('button', { name: sourceDocument.title, exact: true })).toHaveCount(0);
      expect(workspace.matching('POST', '/v1/ai/generate-course')).toHaveLength(0);
    });

    test('preselects the exact source and opens the course that prevents deletion', async ({ page, workspace }) => {
      workspace.documents();
      const source = { ...sourceDocument, source_review_status: 'approved', index: { ...sourceDocument.index, status: 'ready' }, usages_summary: used };
      workspace.get('/v1/documents/catalog', { items: [source], page: catalogue });
      workspace.get('/v1/documents/editorial-review/status', { required: true, documents: { [ids.document]: 'approved' } });
      workspace.get(documentRoute + '/usages', {
        items: [{ type: 'course_source', id: ids.course, title: course.title, status: 'draft',
          route: '/courses/' + ids.course, blocks_delete: true }],
        summary: used, page: { limit: 100, next_cursor: null, has_more: false },
      });
      await page.goto(cataloguePage);
      await page.getByRole('button', { name: 'Delete: ' + source.title, exact: true }).click();
      const modal = page.getByRole('dialog');
      await expect(modal.getByRole('link', { name: new RegExp(course.title) })).toHaveAttribute('href', '/courses/' + ids.course);
      await modal.getByRole('button', { name: 'Close', exact: true }).click();
      expect(workspace.matching('DELETE', documentRoute)).toHaveLength(0);

      workspace.command('POST', '/v1/ai/document-compatibility', ({ body }) => {
        expect(body).toMatchObject({ documents: [ids.document] });
        return { json: { compatible: false } };
      });
      await page.getByRole('link', { name: 'Create course', exact: true }).click();
      await expect(page).toHaveURL(appOrigin + '/ai/generate?document_id=' + ids.document);
      await expect.poll(() => workspace.matching('POST', '/v1/ai/document-compatibility').length).toBe(1);
      expect(workspace.matching('POST', '/v1/ai/generate-course')).toHaveLength(0);
    });
  });
}
