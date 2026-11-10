import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { AxeResults } from 'axe-core';
import { appOrigin, course, ids, test } from './learning-workspace-ux-fixtures';

test.use({ baseURL: appOrigin, serviceWorkers: 'block' });
const uuid = (index: number) => `74000000-0000-4000-8000-${String(index).padStart(12, '0')}`;
async function smoke(page: Page) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const severe = await page.evaluate(async () => {
    const axe = (window as typeof window & { axe: { run: () => Promise<AxeResults> } }).axe;
    return (await axe.run()).violations.filter((item) => item.impact === 'critical' || item.impact === 'serious').map((item) => item.id);
  });
  expect(severe).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
}

for (const width of [390, 915, 1024, 1440]) {
  test(`context menu and compact editor at ${width}`, async ({ page, workspace }, info) => {
    await page.setViewportSize({ width, height: 900 });
    workspace.author();
    workspace.get('/v1/courses', [course]);
    workspace.get('/v1/course-blueprints', []);
    await page.goto('/courses');
    await expect(page.locator('[data-methodologist-records]')).toBeVisible();
    const trigger = page.locator('summary').filter({ hasText: /^More$/ });
    const menu = trigger.locator('..');
    await trigger.focus();
    await trigger.press('Enter');
    const documents = menu.getByRole('link', { name: 'Documents', exact: true });
    await documents.focus();
    await documents.press('Escape');
    await expect(menu).not.toHaveAttribute('open');
    await expect(trigger).toBeFocused();
    await trigger.press('Enter');
    await page.getByRole('heading', { name: 'Courses', exact: true }).click();
    await expect(menu).not.toHaveAttribute('open');
    await page.goto(`/courses/${ids.course}/edit`);
    const checks = page.locator('[data-publication-checks]');
    await expect(page.getByRole('textbox', { name: 'Add Module', exact: true })).toBeVisible();
    await expect(checks).not.toHaveAttribute('open');
    await expect(page.getByRole('button', { name: 'Open findings and sources' })).toBeVisible();
    expect(await page.getByRole('heading', { name: 'Course structure', exact: true }).evaluate((element) => element.getBoundingClientRect().top)).toBeLessThan(900);
    await page.screenshot({ path: info.outputPath('compact-editor.png') });
    await checks.locator('summary').click();
    await expect(checks.getByRole('button', { name: 'Approve course', exact: true })).toBeVisible();
    await expect(checks.getByText('Saved content is not an assessment of meaning.', { exact: false })).toBeVisible();
    await checks.locator('summary').press('Space');
    await expect(checks).not.toHaveAttribute('open');
    expect(workspace.calls.filter((call) => call.method !== 'GET' && call.path !== '/v1/auth/refresh')).toHaveLength(0);
    await smoke(page);
  });

  test(`independent dashboard sources and queue bounds at ${width}`, async ({ page, workspace }, info) => {
    await page.setViewportSize({ width, height: 900 });
    workspace.role = 'methodologist';
    workspace.get('/v1/admin/onboarding-status', { steps: [], completed: true, trial_ends_at: null, trial_days_remaining: null,
      plan: null, max_users: null, active_users: 0, role: 'methodologist', trial_state: 'not_started', trial_access_state: 'allowed', trial_exhausted_limits: [], trial_usage: {} });
    workspace.get('/v1/admin/learning-actions', {
      summary: { training_log: { total: 10, assigned: 10, in_progress: 0, completed: 0, overdue: 0, failed_current: 0, exhausted_attempts: 0, reassigned: 0, cancelled_history: 0, superseded_history: 0 },
        training_issue_count: 10, training_issue_counts: { not_started: 10 }, training_items_truncated: false,
        weak_question_count: 0, action_count: 0, actions_truncated: false, open_action_count: 0, overdue_action_count: 0 },
      training_items: Array.from({ length: 10 }, (_, index) => ({ enrollment_id: uuid(index + 1), user_id: uuid(index + 20), full_name: `Employee ${index + 1}`,
        course_id: ids.course, course_title: 'Synthetic safety course', issue_type: 'not_started', progress_percent: 0, best_score: null, quiz_attempts_count: 0,
        assignment_due_at: null, active_action_id: null, active_action_types: [] })), weak_questions: [], actions: [],
    });
    workspace.get('/v1/courses', Array.from({ length: 100 }, (_, index) => ({ ...course, id: uuid(index + 100), title: `Review course ${index + 1}`, status: 'draft', ai_generated: true, review_status: 'pending' })));
    let jobsFail = true;
    workspace.onGet('/v1/ai/jobs', () => jobsFail ? { status: 503, json: {} } : { json: Array.from({ length: 20 }, (_, index) => ({ id: uuid(index + 300), job_type: 'course_generation',
      status: index < 6 ? 'running' : 'completed', stage: 'generating', course_title: `Generation ${index + 1}`, created_at: '2026-11-10T00:00:00Z' })) });
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    workspace.onGet('/v1/admin/mandatory-training/summary', async () => {
      await gate;
      return { json: { total: 0, materialized: 0, missing_enrollment: 0, protected_assignment: 0, stale_managed_enrollment: 0, action_materialize: 0, action_review_stale: 0 } };
    });
    try {
      await page.goto('/dashboard');
      await expect(page.getByRole('button', { name: /^Employee 1 / })).toBeVisible();
      await expect(page.getByText(/Showing 3 of 10/)).toBeVisible();
      await expect(page.getByRole('region', { name: 'Mandatory training' })).toContainText('Loading tasks');
      const retry = page.getByRole('button', { name: 'Retry loading · Generation jobs', exact: true });
      await expect(retry).toBeVisible();
      jobsFail = false;
      await retry.click();
      await expect(page.getByRole('button', { name: /^Generation 1 / })).toBeVisible();
      await expect(page.getByText(/Showing 5; the overall total is unknown/)).toHaveCount(2);
      await expect(page.getByRole('link', { name: 'All drafts', exact: true })).toHaveAttribute('href', '/courses?status=draft');
      expect(workspace.matching('GET', '/v1/admin/learning-actions')).toHaveLength(1);
      expect(workspace.matching('GET', '/v1/courses')).toHaveLength(1);
      expect(workspace.matching('GET', '/v1/ai/jobs')).toHaveLength(2);
      await page.screenshot({ path: info.outputPath('dashboard-independent.png') });
      release();
      await expect(page.getByRole('region', { name: 'Mandatory training' })).toHaveCount(0);
      await page.getByText(/Only the latest 20 jobs/).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('dashboard-bounds.png') });
      await smoke(page);
    } finally { release(); }
  });
}
