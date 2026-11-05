import { expect, test as base, type Page } from '@playwright/test';
import { appOrigin, course, ids, lessons, structure, SyntheticWorkspace, timestamp } from './learning-workspace-ux-fixtures';

// Whole-LMS composition acceptance on the real built application. Every API is
// synthetic; unexpected calls, mutations and external traffic fail the test.
if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER || appOrigin !== 'http://127.0.0.1:3027') {
  throw new Error('Whole-LMS visual acceptance needs the root-owned loopback3027 app.');
}

const test = base.extend<{ workspace: SyntheticWorkspace }>({
  workspace: [async ({ context }, use) => {
    const workspace = new SyntheticWorkspace(context, 'ru');
    await workspace.install();
    await use(workspace);
    workspace.assertIsolated();
  }, { auto: true }],
});
test.use({ baseURL: appOrigin, serviceWorkers: 'block' });
test.setTimeout(60_000);
test.afterEach(async ({ page }, info) => {
  await page.screenshot({ path: info.outputPath('reviewed-page.png'), fullPage: false }).catch(() => undefined);
});

async function expectComposition(page: Page, id: string) {
  await expect(page.locator(`[data-redesign-page="${id}"]`)).toBeVisible();
  expect(await page.getByRole('heading', { level: 1 }).count()).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await expect(page.locator('header[data-workspace-header], [data-workspace-panel], [data-public-workspace]').first()).toBeVisible();
}

const documents = {
  items: [{
    id: ids.document, source_family_id: ids.document, title: 'Инструкция по охране труда',
    filename: 'instruction.pdf', content_type: 'application/pdf', size: 2048,
    description: 'Синтетический источник для проверки композиции.',
    category: 'general', version: 2, is_latest: true, lifecycle_status: 'active',
    deletion_error_code: null, deletion_error_message: null, deletion_job_id: null,
    created_by: ids.author, created_at: timestamp, updated_at: timestamp,
    index: { status: 'ready', error_code: null, message: null, chunks_total: 4, chunks_indexed: 4, indexed_at: timestamp, revision: 3 },
    usages_summary: { total: 1, courses: 1, positions: 0, lessons: 1, active_jobs: 0 },
  }],
  page: { next_cursor: null, has_more: false, limit: 25 },
};

for (const width of [1440, 390] as const) {
  test.describe(`workspace composition at ${width}px`, () => {
    test.use({ viewport: { width, height: 1000 } });

    test('documents library', async ({ page, workspace }) => {
      workspace.documents();
      workspace.get('/v1/documents/catalog', documents);
      await page.goto('/documents');
      await expectComposition(page, 'documents');
    });

    test('learner dashboard and assigned courses', async ({ page, workspace }) => {
      workspace.learner();
      await page.goto('/student');
      await expectComposition(page, 'student');
      await page.goto('/my-courses');
      await expectComposition(page, 'my-courses');
    });

    test('quiz library', async ({ page, workspace }) => {
      workspace.author();
      await page.goto('/quizzes');
      await expectComposition(page, 'quiz-authoring');
    });

    test('assignment workspace', async ({ page, workspace }) => {
      workspace.assignments();
      await page.goto('/assignments');
      await expectComposition(page, 'assignments');
    });

    test('training log', async ({ page, workspace }) => {
      workspace.trainingLog();
      await page.goto('/training-log');
      await expectComposition(page, 'training-log');
    });

    test('profile', async ({ page }) => {
      await page.goto('/profile');
      await expectComposition(page, 'profile');
    });

    test('methodologist dashboard', async ({ page, workspace }) => {
      workspace.role = 'methodologist';
      workspace.get('/v1/admin/learning-actions', {
        summary: { training_log: null, training_issue_count: 0, training_issue_counts: {}, training_items_truncated: false, weak_question_count: 0, action_count: 0, actions_truncated: false, open_action_count: 0, overdue_action_count: 0 },
        training_items: [], weak_questions: [], actions: [],
      });
      workspace.get('/v1/courses', [course]);
      workspace.get('/v1/ai/jobs', []);
      workspace.get('/v1/admin/mandatory-training/summary', { total: 0, materialized: 0, missing_enrollment: 0, protected_assignment: 0, stale_managed_enrollment: 0, action_materialize: 0, action_review_stale: 0 });
      workspace.get('/v1/admin/onboarding-status', { steps: [] });
      await page.goto('/dashboard');
      await expectComposition(page, 'dashboard');
    });

    test('course reader', async ({ page, workspace }) => {
      workspace.learner();
      await page.goto(`/courses/${ids.course}?lessonId=${ids.lesson}`);
      await expectComposition(page, 'course-reader');
      await expect(page.getByRole('heading', { level: 1, name: lessons[0].title, exact: true })).toBeVisible();
      expect(structure.modules[0].lessons).toHaveLength(2);
    });
  });
}

test.describe('public LMS composition', () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test.beforeEach(async ({ workspace }) => { workspace.expectsSession = false; });

  test('sign-in', async ({ page, workspace }) => {
    workspace.get('/v1/auth/capabilities', { telegram_login_enabled: false });
    await page.goto('/login');
    await expectComposition(page, 'login');
    await expect(page.getByRole('tab', { name: /Код|email/i }).first()).toBeVisible();
  });

  test('certificate verification', async ({ page }) => {
    await page.goto('/verify/certificate');
    await expectComposition(page, 'certificate-verification');
    await expect(page.getByRole('button', { name: /Проверить/i })).toBeVisible();
  });

  test('privacy notice keeps readable legal content and contents navigation', async ({ page }) => {
    await page.goto('/legal/privacy');
    await expectComposition(page, 'legal-privacy');
    await expect(page.getByRole('navigation', { name: 'Уведомление о конфиденциальности' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible();
  });
});
