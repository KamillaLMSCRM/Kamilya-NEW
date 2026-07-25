import { expect, test, type Page, type Route } from '@playwright/test';

const tenantId = '11111111-1111-4111-8111-111111111111';

function catalogItem(
  lifecycleStatus: 'active' | 'deletion_pending' | 'delete_failed',
) {
  const failed = lifecycleStatus === 'delete_failed';
  return {
    id: failed
      ? '22222222-2222-4222-8222-222222222222'
      : '33333333-3333-4333-8333-333333333333',
    source_family_id: failed
      ? '22222222-2222-4222-8222-222222222222'
      : '33333333-3333-4333-8333-333333333333',
    title: failed ? 'Архивная инструкция' : 'Политика безопасности',
    filename: failed ? 'archive.pdf' : 'safety-policy.pdf',
    content_type: 'application/pdf',
    size: 2048,
    description: failed ? 'Очистка требует повторного запуска' : 'Утверждённый источник',
    category: 'general',
    index: {
      status: 'ready',
      error_code: null,
      message: null,
      chunks_total: 4,
      chunks_indexed: 4,
      indexed_at: '2026-07-24T12:00:00Z',
      revision: 1,
    },
    version: 1,
    is_latest: true,
    lifecycle_status: lifecycleStatus,
    deletion_error_code: failed ? 'document_cleanup_failed' : null,
    deletion_error_message: failed ? 'Storage temporarily unavailable' : null,
    deletion_job_id: failed ? 'cleanup-job-1' : null,
    created_at: '2026-07-24T12:00:00Z',
    updated_at: '2026-07-24T12:00:00Z',
    usages_summary: {
      total: 0,
      courses: 0,
      positions: 0,
      lessons: 0,
      active_jobs: 0,
    },
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function mockDocumentLibraryApi(page: Page) {
  await page.route('**/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith('/auth/refresh')) {
      await fulfillJson(route, {
        access_token: 'local-playwright-token',
        user: {
          user_id: '44444444-4444-4444-8444-444444444444',
          tenant_id: tenantId,
          tenant: { id: tenantId, name: 'QA Tenant', slug: 'qa-tenant' },
          telegram_id: '900000004',
          role: 'methodologist',
          roles: ['methodologist'],
          full_name: 'Методист QA',
          email: 'methodologist@example.test',
        },
      });
      return;
    }
    if (url.pathname.endsWith('/documents/catalog')) {
      const lifecycle = (
        url.searchParams.get('lifecycle_status') || 'active'
      ) as 'active' | 'deletion_pending' | 'delete_failed';
      await fulfillJson(route, {
        items: [catalogItem(lifecycle)],
        page: { next_cursor: null, has_more: false, limit: 25 },
      });
      return;
    }
    if (url.pathname.endsWith('/reindex') && request.method() === 'POST') {
      await fulfillJson(route, {
        document_id: '33333333-3333-4333-8333-333333333333',
        index_status: 'processing',
        revision: 2,
        job_id: 'reindex-job-1',
        status_url: '/api/v1/ai/jobs/reindex-job-1',
      }, 202);
      return;
    }
    if (url.pathname.endsWith('/ai/jobs/reindex-job-1')) {
      await fulfillJson(route, {
        id: 'reindex-job-1',
        status: 'completed',
        progress: 100,
        stage: 'completed',
        message: 'Document index rebuilt',
      });
      return;
    }
    if (url.pathname.includes('/documents/') && url.pathname.endsWith('/download')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: '%PDF-local-qa',
      });
      return;
    }
    if (url.pathname.includes('/documents/') && request.method() === 'DELETE') {
      await fulfillJson(route, {
        document_id: url.pathname.split('/').at(-1),
        lifecycle_status: 'deletion_pending',
        job_id: 'cleanup-job-1',
        status_url: '/api/v1/ai/jobs/cleanup-job-1',
      }, 202);
      return;
    }
    await fulfillJson(route, []);
  });
}

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet', width: 820, height: 1180 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`document library recovery and version actions fit ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await mockDocumentLibraryApi(page);
    await page.goto('/documents');

    await expect(page.getByRole('heading', { name: 'Документы' })).toBeVisible();
    await expect(page.getByText('Политика безопасности')).toBeVisible();
    await expect(page.getByText('v1')).toBeVisible();
    await expect(page.getByText('Последняя')).toBeVisible();
    await expect(page.getByRole('button', { name: /Переиндексировать: Политика безопасности/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Загрузить новую версию: Политика безопасности/ })).toBeVisible();

    await page.getByRole('button', { name: /Загрузить новую версию: Политика безопасности/ }).click();
    const versionDialog = page.getByRole('dialog');
    await expect(versionDialog.getByRole('heading', { name: 'Новая версия документа' })).toBeVisible();
    await expect(versionDialog.getByText(/будет создана версия 2/)).toBeVisible();
    await versionDialog.getByRole('button', { name: 'Отмена' }).click();

    await page.getByRole('tab', { name: 'Требуют внимания' }).click();
    await expect(page.getByText('Архивная инструкция')).toBeVisible();
    await expect(page.getByText('Ошибка удаления')).toBeVisible();
    await expect(page.getByRole('button', { name: /Повторить удаление: Архивная инструкция/ })).toBeVisible();

    const overflow = await page.evaluate(() => ({
      body: document.body.scrollWidth - window.innerWidth,
      root: document.documentElement.scrollWidth - window.innerWidth,
    }));
    expect(overflow.body).toBeLessThanOrEqual(1);
    expect(overflow.root).toBeLessThanOrEqual(1);
  });
}
