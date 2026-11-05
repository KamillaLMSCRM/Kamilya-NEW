import { expect, test as base, type BrowserContext, type Page, type TestInfo } from '@playwright/test';
import { appOrigin, course, ids, lessons, sourceDocument, SyntheticWorkspace, timestamp } from './learning-workspace-ux-fixtures';

// Narrow A acceptance on the real built application. Every API is synthetic;
// unexpected reads, mutations and external traffic fail the test.
if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER || appOrigin !== 'http://127.0.0.1:3027') {
  throw new Error('Narrow A visual acceptance needs the root-owned loopback3027 app.');
}

const questionKey = 'a'.repeat(64);
const campaign = {
  id: '71000000-0000-4000-8000-000000000101',
  title: 'Synthetic candidate assessment',
  status: 'active',
  expires_at: '2030-06-15T12:00:00Z',
};
const courseWithRelease = { ...course, current_release_id: ids.revision };
const activeJob = {
  id: 'job-active', status: 'running', job_type: 'course_generation', course_id: ids.course,
  created_at: timestamp, updated_at: timestamp, stage: 'generating', message: '',
  progress: 40, queue_position: null, estimated_wait_seconds: null,
  tenant_active_jobs: 1, tenant_active_limit: 2,
};
const failedJob = {
  id: 'job-failed', status: 'failed', job_type: 'course_generation', course_id: null,
  created_at: timestamp, updated_at: timestamp, stage: 'review', message: 'Synthetic failure',
  errors: ['synthetic_failure'], progress: 60, queue_position: null, estimated_wait_seconds: null,
  tenant_active_jobs: 0, tenant_active_limit: 2,
};
const learningPayload = {
  summary: {
    training_log: { total: 12, assigned: 2, in_progress: 3, completed: 6, overdue: 1, failed_current: 1, exhausted_attempts: 0, reassigned: 0, cancelled_history: 0, superseded_history: 0 },
    training_issue_count: 2, training_issue_counts: { overdue: 1, failed_required_quiz: 1 },
    training_items_truncated: false, weak_question_count: 1, action_count: 1,
    actions_truncated: false, open_action_count: 1, overdue_action_count: 1,
  },
  training_items: [{
    enrollment_id: ids.enrollment, user_id: ids.learner, full_name: 'Synthetic Learner',
    course_id: ids.course, course_title: course.title, issue_type: 'overdue',
    progress_percent: 25, best_score: 40, quiz_attempts_count: 1,
    assignment_due_at: timestamp, active_action_id: null, active_action_types: [],
  }],
  weak_questions: [],
  actions: [],
};
const weakPayload = {
  ...learningPayload,
  summary: { ...learningPayload.summary, weak_question_count: 1 },
  weak_questions: [{
    question_key: questionKey, question_id: ids.question, quiz_id: ids.quiz,
    content_release_id: ids.revision, text: 'Which control is required?',
    quiz_title: 'Safety quiz', respondents: 8, incorrect_percent: 62.5,
    active_action_id: null, active_action_types: [],
  }],
};
const mandatorySummary = {
  total: 0, materialized: 0, missing_enrollment: 0, protected_assignment: 0,
  stale_managed_enrollment: 0, action_materialize: 0, action_review_stale: 0,
};
const documentsFixture = {
  items: [sourceDocument],
  page: { next_cursor: null, has_more: false, limit: 25 },
};

const test = base;
test.use({ baseURL: appOrigin, serviceWorkers: 'block', viewport: { width: 1440, height: 1000 } });
test.setTimeout(90_000);

async function openWorkspace(context: BrowserContext, lang: 'ru' | 'kk' | 'en' = 'ru') {
  const workspace = new SyntheticWorkspace(context, lang);
  await workspace.install();
  return workspace;
}

async function installNarrowAFixtures(workspace: SyntheticWorkspace) {
  workspace.role = 'methodologist';
  workspace.trainingLog();
  workspace.author();
  workspace.onGet('/v1/admin/learning-actions', ({ url }) => ({
    json: url.searchParams.get('course_id') ? weakPayload : learningPayload,
  }));
  workspace.get('/v1/courses', [courseWithRelease]);
  workspace.get('/v1/ai/jobs', [activeJob, failedJob]);
  workspace.get('/v1/ai/jobs/job-failed', failedJob);
  workspace.get('/v1/admin/mandatory-training/summary', mandatorySummary);
  workspace.get('/v1/admin/onboarding-status', { steps: [] });
  workspace.get('/v1/course-blueprints', []);
  workspace.get('/v1/documents/catalog', documentsFixture);
  workspace.get('/v1/youtube/limits', { enabled: false });
  workspace.get('/v1/admin/source-actuality', { items: [] });
  workspace.get('/v1/admin/staff/import/mappings', []);
  workspace.get('/v1/organization-units/tree', { roots: [] });
  workspace.get('/v1/users', { users: [], total: 0 });
  workspace.get('/v1/candidate-assessments', [campaign]);
  workspace.get(`/v1/admin/learning-insights/courses/${ids.course}`, {
    course_id: ids.course, course_title: course.title, cohort_basis: 'current_structure',
    attempt_basis: 'first_completed', included_employees: 0, excluded_attempts: 0, questions: [],
  });
}

async function noPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

async function shot(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: false });
}

async function fullShot(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true });
}

async function seriousAxeViolations(page: Page) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  return page.evaluate(async () => {
    const target = document.querySelector('[data-redesign-page]') ?? document;
    const result = await (window as unknown as { axe: { run: (node: Element | Document, options: object) => Promise<{ violations: Array<{ id: string; impact: string; nodes: Array<{ target: string[]; html: string; failureSummary?: string }> }> }> } }).axe.run(target, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
    });
    return result.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map((violation) => ({
        id: violation.id,
        nodes: violation.nodes.map((node) => ({
          target: node.target,
          html: node.html,
          failureSummary: node.failureSummary,
        })),
      }));
  });
}

for (const width of [390, 768, 1270, 1440] as const) {
  test.describe(`Narrow A responsive matrix at ${width}px`, () => {
    test.use({ viewport: { width, height: 1000 } });

    test('changed surfaces keep hierarchy, focus and overflow', async ({ page, context }, info) => {
      const workspace = await openWorkspace(context);
      await installNarrowAFixtures(workspace);

      await page.goto('/dashboard');
      await expect(page.getByRole('heading', { name: 'Требует внимания' })).toBeVisible();
      await expect(page.getByRole('link', { name: /заявка job-fail/ })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Опубликовано: 1' })).toHaveAttribute('href', '/courses?status=published');
      await noPageOverflow(page);
      await page.locator('a[href="/courses?status=published"]').first().focus();
      await expect(page.locator('a[href="/courses?status=published"]').first()).toBeFocused();
      await page.keyboard.press('Tab');
      await expect(page.locator(':focus')).not.toHaveCount(0);
      await shot(page, info, `${width}-dashboard`);

      await page.goto('/courses?status=published');
      await expect(page.getByLabel('Статус')).toHaveValue('published');
      await expect(page.getByRole('heading', { name: course.title })).toBeVisible();
      await noPageOverflow(page);
      await shot(page, info, `${width}-courses`);

      await page.goto('/training-log?action_focus=weak_questions');
      const courseSelect = page.getByRole('combobox', { name: 'Курс для разбора вопросов' });
      await expect(courseSelect).toBeVisible();
      await noPageOverflow(page);
      await shot(page, info, `${width}-training-log`);

      await page.goto('/documents');
      const activeDocuments = page.getByRole('button', { name: 'Активные' });
      await expect(activeDocuments).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByRole('button', { name: 'Требуют внимания' })).toHaveAttribute('aria-pressed', 'false');
      await activeDocuments.focus();
      await page.keyboard.press('Tab');
      await expect(page.locator(':focus')).not.toHaveCount(0);
      await noPageOverflow(page);
      await shot(page, info, `${width}-documents`);

      await page.goto('/staff');
      await expect(page.getByRole('link', { name: 'Приглашения' })).toHaveAttribute('href', '/invitations');
      await noPageOverflow(page);
      await shot(page, info, `${width}-staff`);

      await page.goto(`/courses/${ids.course}/edit`);
      await expect(page.getByRole('link', { name: 'Открыть решения по согласованию' })).toHaveAttribute('href', `/admin/course-approvals?courseId=${ids.course}`);
      const editorMoveUp = page.getByRole('button', { name: 'Переместить модуль выше' });
      const editorMoveBox = await editorMoveUp.boundingBox();
      expect(editorMoveBox?.width ?? 0).toBeGreaterThanOrEqual(24);
      expect(editorMoveBox?.height ?? 0).toBeGreaterThanOrEqual(24);
      await noPageOverflow(page);
      await shot(page, info, `${width}-editor`);

      await page.goto('/candidate-assessments');
      await expect(page.getByRole('heading', { name: 'Тестирование кандидатов' })).toBeVisible();
      await expect(page.getByText(/Активна · до 15\.06\.2030/)).toBeVisible();
      await noPageOverflow(page);
      await fullShot(page, info, `${width}-candidate-assessments`);

      workspace.assertIsolated();
    });
  });
}

test.describe('Narrow A deep links and contextual flows', () => {
  test('Back and Forward restore weak-question course filters', async ({ page, context }) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.goto('/training-log?action_focus=weak_questions');
    await page.getByRole('combobox', { name: 'Курс для разбора вопросов' }).selectOption(ids.course);
    await expect(page).toHaveURL(new RegExp(`course_id=${ids.course}`));
    await page.goBack();
    await expect(page).toHaveURL(/training-log\?action_focus=weak_questions$/);
    await expect(page.getByRole('combobox', { name: 'Курс для разбора вопросов' })).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(new RegExp(`course_id=${ids.course}`));
    await expect(page.getByText('Which control is required?')).toBeVisible();
    workspace.assertIsolated();
  });

  test('catalogue Back and Forward restore the selected status', async ({ page, context }) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.goto('/courses?status=published');
    await page.getByLabel('Статус', { exact: true }).selectOption('draft');
    await expect(page).toHaveURL(/status=draft$/);
    await page.goBack();
    await expect(page.getByLabel('Статус', { exact: true })).toHaveValue('published');
    await page.goForward();
    await expect(page.getByLabel('Статус', { exact: true })).toHaveValue('draft');
    workspace.assertIsolated();
  });

  test('module-title draft blocks approval and survives Cancel', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.goto(`/courses/${ids.course}/edit`);
    const moduleSection = page.locator('section[aria-labelledby^="module-"]').first();
    await moduleSection.getByRole('button', { name: 'Редактировать', exact: true }).click();
    const title = moduleSection.locator('input');
    await title.fill('Unsaved module title');
    await page.getByRole('link', { name: 'Открыть решения по согласованию' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Отмена' }).click();
    await expect(title).toHaveValue('Unsaved module title');
    await expect(page).toHaveURL(new RegExp(`/courses/${ids.course}/edit`));
    await shot(page, info, '1440-module-dirty-cancel');
    workspace.assertIsolated();
  });

  test('failed generation opens its exact job context without starting generation', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.goto('/ai/generate?job_id=job-failed');

    await expect(page.locator('[data-generation-workspace]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Создать новый курс' })).toBeVisible();
    await expect(page.getByText('Ошибка', { exact: true })).toBeVisible();
    expect(workspace.matching('POST', '/v1/ai/jobs/generate-course')).toHaveLength(0);
    await noPageOverflow(page);
    await shot(page, info, '1440-failed-generation');
    workspace.assertIsolated();
  });

  test('weak-question focus offers a course choice and survives reload', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.goto('/training-log?action_focus=weak_questions');

    const courseSelect = page.getByRole('combobox', { name: 'Курс для разбора вопросов' });
    await courseSelect.selectOption(ids.course);
    await expect(page).toHaveURL(new RegExp(`course_id=${ids.course}`));
    await expect(page).toHaveURL(/action_focus=weak_questions/);
    await expect(page.getByText('Which control is required?')).toBeVisible();

    await page.reload();
    await expect(page.getByText('Which control is required?')).toBeVisible();
    await expect(page.getByRole('combobox', { name: 'Курс для разбора вопросов' })).toHaveCount(0);
    await shot(page, info, '1440-weak-questions-selected');
    workspace.assertIsolated();
  });

  test('course editor keeps courseId and protects unsaved lesson text', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.goto(`/courses/${ids.course}/edit`);

    const approval = page.getByRole('link', { name: 'Открыть решения по согласованию' });
    await expect(approval).toHaveAttribute('href', `/admin/course-approvals?courseId=${ids.course}`);
    const moveUp = page.getByRole('button', { name: 'Переместить модуль выше' });
    const moveBox = await moveUp.boundingBox();
    expect(moveBox?.width ?? 0).toBeGreaterThanOrEqual(24);
    expect(moveBox?.height ?? 0).toBeGreaterThanOrEqual(24);

    await page.getByRole('button', { name: lessons[0].title, exact: true }).click();
    const content = page.getByLabel('Содержание урока');
    await content.fill(`${lessons[0].content}\n\nUnsaved synthetic note`);
    await approval.click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText('Изменения не сохранены')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Отмена' }).click();
    await expect(page).toHaveURL(new RegExp(`/courses/${ids.course}/edit`));
    await expect(approval).toBeFocused();
    await noPageOverflow(page);
    await shot(page, info, '1440-editor-dirty-guard');
    workspace.assertIsolated();
  });
});

for (const lang of ['en', 'kk'] as const) {
  test.describe(`candidate assessment ${lang} locale`, () => {
    test.use({ viewport: { width: 390, height: 1000 } });
    test(`renders ${lang} status and locale date`, async ({ page, context }, info) => {
      const workspace = await openWorkspace(context, lang);
      await installNarrowAFixtures(workspace);
      await page.goto('/candidate-assessments');
      await expect(page.getByText(lang === 'en' ? /Active · until 15\/06\/2030/ : /Белсенді · дейін 15\.06\.2030/)).toBeVisible();
      await expect(page.getByText(/^active ·/)).toHaveCount(0);
      await noPageOverflow(page);
      await fullShot(page, info, `390-candidate-${lang}`);
      workspace.assertIsolated();
    });
  });
}

test.describe('candidate assessment states', () => {
  test.use({ viewport: { width: 390, height: 1000 } });

  test('shows loading and confirmed empty states distinctly', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    workspace.role = 'methodologist';
    workspace.onGet('/v1/candidate-assessments', async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
      return { json: [] };
    });
    workspace.get('/v1/courses', []);

    await page.goto('/candidate-assessments');
    await expect(page.getByText('Загружаем кампании…')).toBeVisible();
    await expect(page.getByText('Кампаний пока нет. Создайте первую кампанию.')).toBeVisible();
    await expect(page.getByText('Нет опубликованных курсов с готовой версией.')).toBeVisible();
    await fullShot(page, info, '390-candidate-empty');
    workspace.assertIsolated();
  });

  test('keeps the usable course list when campaigns fail', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    workspace.role = 'methodologist';
    workspace.onGet('/v1/candidate-assessments', () => ({ status: 500, json: { detail: 'synthetic failure' } }));
    workspace.get('/v1/courses', [courseWithRelease]);

    await page.goto('/candidate-assessments');
    await expect(page.getByText('Не удалось загрузить оценки кандидатов.')).toBeVisible();
    await expect(page.getByLabel('Опубликованный курс')).toContainText(course.title);
    await fullShot(page, info, '390-candidate-partial-error');
    workspace.assertIsolated();
  });
});

test.describe('candidate assessment dark and reduced motion', () => {
  test.use({ viewport: { width: 390, height: 1000 }, colorScheme: 'dark' });

  test('uses dark tokens and honors reduced motion', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
    await page.goto('/candidate-assessments');
    await page.evaluate(() => document.documentElement.classList.add('dark'));
    expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
    const panelBackground = await page.locator('[data-workspace-panel]').first().evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(panelBackground).not.toBe('rgb(255, 255, 255)');
    await noPageOverflow(page);
    await fullShot(page, info, '390-candidate-dark-reduced-motion');
    workspace.assertIsolated();
  });
});

test.describe('automated accessibility on changed surfaces', () => {
  test('dashboard and candidate assessment have no serious/critical axe findings', async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Требует внимания' })).toBeVisible();
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-dashboard-axe');

    await page.goto('/documents');
    await expect(page.getByRole('button', { name: 'Активные' })).toHaveAttribute('aria-pressed', 'true');
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-documents-axe');

    await page.goto('/training-log?action_focus=weak_questions');
    await expect(page.getByRole('combobox', { name: 'Курс для разбора вопросов' })).toBeVisible();
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-training-log-axe');

    await page.goto('/candidate-assessments');
    await expect(page.getByText(/Активна · до/)).toBeVisible();
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-candidate-axe');
    await page.goto('/staff');
    await expect(page.getByRole('link', { name: 'Приглашения' })).toBeVisible();
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-staff-axe');
    await page.goto(`/courses/${ids.course}/edit`);
    await expect(page.getByRole('link', { name: 'Открыть решения по согласованию' })).toBeVisible();
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-editor-axe');
    await page.goto('/courses');
    await expect(page.getByRole('heading', { name: course.title })).toBeVisible();
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-courses-axe');
    await page.goto('/ai/generate?job_id=job-failed');
    await expect(page.getByRole('button', { name: 'Создать новый курс' })).toBeVisible();
    expect(await seriousAxeViolations(page)).toEqual([]);
    await shot(page, info, '1440-generation-axe');
    workspace.assertIsolated();
  });
});

for (const role of ['admin', 'student', 'superadmin'] as const) {
  test(`active ${role} cannot enter methodologist surfaces even with assigned methodologist role`, async ({ page, context }, info) => {
    const workspace = await openWorkspace(context);
    await installNarrowAFixtures(workspace);
    workspace.learner();
    workspace.get('/v1/users', { users: [], total: 0 });
    workspace.get('/v1/admin/super/tenants', { tenants: [] });
    workspace.role = role;
    workspace.assignedRoles = role === 'superadmin' ? ['superadmin'] : [role, 'methodologist'];
    const target = role === 'admin' ? '/admin' : role === 'student' ? '/student' : '/admin/super';
    for (const route of ['/dashboard', '/documents', '/staff', '/candidate-assessments', '/ai/generate', `/courses/${ids.course}/edit`]) {
      const before = workspace.calls.length;
      await page.goto(route);
      await expect(page).toHaveURL(`${appOrigin}${target}`);
      await expect(page.locator('[data-redesign-page="candidate-assessments"], [data-redesign-page="staff"], [data-generation-workspace]')).toHaveCount(0);
      expect(workspace.calls.slice(before).filter(call => /\/v1\/(candidate-assessments|ai\/jobs|documents\/catalog|organization-units\/tree)$/.test(call.path))).toEqual([]);
    }
    await shot(page, info, `1440-role-${role}-boundary`);
    workspace.assertIsolated();
  });
}

test('active admin reporting does not expose methodologist actions from a secondary role', async ({ page, context }, info) => {
  const workspace = await openWorkspace(context);
  await installNarrowAFixtures(workspace);
  workspace.role = 'admin';
  workspace.assignedRoles = ['admin', 'methodologist'];
  await page.goto('/training-log?action_focus=weak_questions');
  await expect(page.locator('[data-redesign-page="training-log"]')).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Курс для разбора вопросов' })).toHaveCount(0);
  expect(workspace.matching('GET', '/v1/courses')).toHaveLength(0);
  expect(workspace.matching('GET', '/v1/admin/learning-actions')).toHaveLength(0);
  await shot(page, info, '1440-active-admin-readonly');
  workspace.assertIsolated();
});

test('a full first page does not claim tenant course totals', async ({ page, context }, info) => {
  const workspace = await openWorkspace(context);
  await installNarrowAFixtures(workspace);
  workspace.get('/v1/courses', Array.from({ length: 100 }, (_, index) => ({ ...courseWithRelease, id: `71000000-0000-4000-8000-${String(1000 + index).padStart(12, '0')}` })));
  await page.goto('/dashboard');
  await expect(page.getByText(/Общие итоги по курсам неизвестны/)).toBeVisible();
  await expect(page.getByRole('link', { name: 'Все курсы: —' })).toBeVisible();
  await page.getByRole('link', { name: 'Все курсы: —' }).scrollIntoViewIfNeeded();
  await shot(page, info, '1440-first100-dashboard');
  await page.goto('/candidate-assessments');
  await expect(page.getByText(/Загружены первые 100 опубликованных курсов/)).toBeVisible();
  workspace.assertIsolated();
});
