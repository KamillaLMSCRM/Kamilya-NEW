import { readFile } from 'node:fs/promises';
import { expect, type Page, type TestInfo } from '@playwright/test';
import type { SourceReview } from '@/features/source-editorial-review/contract';
import {
  appOrigin, audience, course, existingEnrollment, ids, lessons, newEnrollment,
  quiz, quizAttempt, quizResult, reviewAttempt, reviewSummary, snapshotHash,
  sourceDocument, test, timestamp, trainingRows,
} from './learning-workspace-ux-fixtures';

// Real Next production pages, never HTML prototypes. Root owns build/server on3024.
// Collection itself fails if the ordinary config could start a development server.
if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER) {
  throw new Error('Set PLAYWRIGHT_SKIP_WEBSERVER=1 and use the root-owned loopback app on3024.');
}
test.use({ baseURL: appOrigin, serviceWorkers: 'block' });

async function noPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - window.innerWidth,
  }));
  expect(overflow.root, 'No document-level horizontal overflow').toBeLessThanOrEqual(1);
  expect(overflow.body, 'No body-level horizontal overflow').toBeLessThanOrEqual(1);
}

async function capture(page: Page, info: TestInfo, name: string) {
  await noPageOverflow(page);
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true });
}

function learnerExit(page: Page) {
  return page.getByRole('navigation', { name: 'My Courses', exact: true })
    .getByRole('link', { name: 'My Courses', exact: true });
}

function filterScope(url: URL) {
  return Object.fromEntries([...url.searchParams.entries()]
    .filter(([key]) => !['limit', 'offset', 'format', 'lang'].includes(key))
    .sort(([left], [right]) => left.localeCompare(right)));
}

for (const viewport of [
  { name: 'desktop1440', width: 1440, height: 900 },
  { name: 'tablet1024', width: 1024, height: 900 },
  { name: 'narrowDesktop915', width: 915, height: 900 },
  { name: 'mobile390', width: 390, height: 844 },
]) {
  test.describe(viewport.name, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });
    test.setTimeout(60_000);

    if (viewport.width === 1440 || viewport.width === 390) test('methodologist continues the first course from a saved source decision to assignment', async ({ page, workspace }, info) => {
      workspace.trainingLog();
      workspace.author();
      workspace.get('/v1/admin/onboarding-status', { steps: [] });
      workspace.get('/v1/admin/mandatory-training/summary', { total: 0 });
      workspace.get('/v1/ai/jobs', []);
      const quote = 'Report breaks in the shift log.';
      const reason = 'The document owner confirmed the current shift procedure.';
      const reviewPath = `/documents/${ids.document}/editorial-review`;
      const reviewApi = '/v1' + reviewPath;
      let review: SourceReview = {
        document_id: ids.document, document_version: 3, title: sourceDocument.title, revision: 7,
        status: 'in_review', error: null, original_text: quote, working_text: quote,
        questions: [{ id: 'shift-log', start: 0, end: quote.length, quote,
          reason: 'Which log records breaks?', resolution: null }],
        automatic: [], journal: [], approval: null,
      };
      workspace.onGet(reviewApi, () => ({ json: review }));
      workspace.onGet('/v1/documents/editorial-review/queue', () => ({ json: {
        items: [{ document_id: ids.document, title: sourceDocument.title, status: review.status,
          open_questions: review.questions.filter((question) => !question.resolution).length }],
      } }));
      const openTask = async (action: string) => {
        await page.goto('/dashboard');
        await page.getByRole('button', { name: new RegExp(sourceDocument.title) }).click();
        const link = page.getByRole('link', { name: action, exact: true });
        await expect(link).toHaveAttribute('href', `${reviewPath}?document_id=${ids.document}`);
        await link.click();
        await expect(page).toHaveURL(`${appOrigin}${reviewPath}?document_id=${ids.document}`);
      };
      await openTask('Continue review');

      const approvalButton = page.getByRole('region', { name: 'Source review' }).getByRole('button', { name: 'Approve edition' });
      await expect(approvalButton).toBeDisabled();
      await page.getByRole('button', { name: 'Go to first open question' }).click();
      await page.getByRole('radio', { name: 'Keep wording' }).check();
      await page.getByLabel('Reason for the decision').fill(reason);
      workspace.command('POST', reviewApi, ({ body }) => {
        expect(body).toMatchObject({ action: 'resolve', expected_revision: 7, item_id: 'shift-log', decision: 'keep', reason });
        review = { ...review, revision: 8, questions: review.questions.map((question) => ({ ...question,
          resolution: { id: question.id, start: 0, end: quote.length,
            before: quote, after: quote, reason, decision: 'keep' } })) };
        return { json: review };
      });
      await page.getByRole('button', { name: 'Save decision' }).click();
      await expect(page.getByRole('status').filter({ hasText: 'Decision saved' })).toBeVisible();
      await page.getByRole('button', { name: 'Go to approval' }).click();
      await expect(approvalButton).toBeFocused();
      await expect(approvalButton).toBeInViewport();
      await capture(page, info, 'source-ready-for-approval');

      await openTask('Go to approval');
      await expect(page.getByText(reason, { exact: true })).toBeVisible();
      workspace.command('POST', reviewApi, ({ body }) => {
        expect(body).toMatchObject({ action: 'approve', expected_revision: 8 });
        review = { ...review, status: 'approved', revision: 9, approval: {
          document_id: ids.document, approval_id: ids.revision, revision: 9,
          working_sha256: snapshotHash, created_at: timestamp,
        } };
        return { json: review };
      });
      await approvalButton.click();
      await expect(page.getByRole('link', { name: 'Continue to generation', exact: true }))
        .toHaveAttribute('href', `/ai/generate?document_id=${ids.document}`);

      workspace.assignments();
      const editorCourse = { ...course, status: 'draft', review_status: 'approved' };
      const editorApi = `/v1/courses/${ids.course}`;
      workspace.get(editorApi, editorCourse);
      await page.goto(`/courses/${ids.course}/edit`);
      workspace.command('POST', editorApi + '/publish', () => {
        const published = { ...editorCourse, status: 'published' };
        workspace.get(editorApi, published);
        return { json: published };
      });
      await page.getByRole('button', { name: 'Publish', exact: true }).click();
      const assignLink = page.locator(`header a[href="/assignments?courseId=${ids.course}"]`);
      await expect(assignLink).toBeVisible();
      await expect(assignLink).toBeInViewport();
      await capture(page, info, 'course-ready-for-assignment');
      await assignLink.click();
      await expect(page.getByRole('combobox', { name: 'Course to assign' })).toHaveValue(ids.course);
      await expect(page.getByRole('checkbox', { name: 'Synthetic Learner', exact: true })).toBeVisible();
    });

    test('learner focus reader has keyboard outline, optional help and a direct exit', async ({ page, workspace }, info) => {
      workspace.learner();
      await page.goto(`/courses/${ids.course}?lessonId=${ids.lesson}`);
      await expect(page.getByRole('heading', { name: lessons[0].title, exact: true })).toBeVisible();
      await expect(page.locator('main[data-learning-focused="true"]')).toBeVisible();
      await expect(learnerExit(page)).toHaveAttribute('href', '/my-courses');
      await expect(learnerExit(page)).toBeInViewport();

      const outline = page.getByRole('navigation', { name: 'Course outline', exact: true });
      const toggle = page.getByRole('button', { name: 'Course outline', exact: true });
      if (viewport.width < 1280) {
        await expect(outline).toBeHidden();
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await toggle.focus();
        await page.keyboard.press('Enter');
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
      }
      const secondLesson = outline.getByRole('button', { name: `Lesson: ${lessons[1].title}`, exact: true });
      await secondLesson.focus();
      await expect(secondLesson).toBeFocused();
      await page.keyboard.press('Enter');
      const heading = page.getByRole('heading', { name: lessons[1].title, exact: true });
      await expect(heading).toBeVisible();
      if (viewport.width >= 768 && viewport.width < 1280) {
        await expect.poll(() => heading.evaluate((node) => node.clientWidth)).toBeGreaterThan(500);
      }
      await expect(heading).toBeFocused();
      await expect(page.getByText('Stop work and notify the supervisor.', { exact: true })).toBeVisible();
      if (viewport.width < 1280) await expect(toggle).toHaveAttribute('aria-expanded', 'false');

      const help = page.getByRole('button', { name: 'Lesson help', exact: true });
      await expect(help).toHaveAttribute('aria-expanded', 'false');
      await expect(page.getByRole('complementary', { name: 'Lesson help' })).toHaveCount(0);
      await help.focus();
      await page.keyboard.press('Enter');
      await expect(help).toHaveAttribute('aria-expanded', 'true');
      await expect(page.getByRole('complementary', { name: 'Lesson help' })).toBeVisible();
      await expect.poll(() => workspace.matching('GET', '/v1/learner/assistant/messages').length).toBeGreaterThan(0);
      // Opening help reads history only; no assistant/model command is armed.
      expect(workspace.calls.filter((call) => call.method !== 'GET' && call.path !== '/v1/auth/refresh')).toEqual([]);
      await help.press('Enter');
      await expect(help).toHaveAttribute('aria-expanded', 'false');
      await expect(learnerExit(page)).toBeVisible();
      await capture(page, info, 'learner-reader');
      await learnerExit(page).click();
      await expect(page).toHaveURL(`${appOrigin}/my-courses`);
      await expect(page.getByRole('heading', { name: 'My Courses', exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { name: course.title, exact: true })).toBeVisible();
      await expect(page.locator('main[data-learning-focused="true"]')).toHaveCount(0);
      await noPageOverflow(page);
    });

    if (viewport.width === 1440) test('methodologist reader keeps the global rail and readable lesson width below xl', async ({ page, workspace }, info) => {
      workspace.learner();
      workspace.role = 'methodologist';

      for (const width of [1024, 915]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(`/courses/${ids.course}?lessonId=${ids.lesson}`);

        await expect(page.locator('aside[data-workspace-rail="true"]')).toBeVisible();
        await expect(page.locator('main[data-learning-focused="false"]')).toBeVisible();
        const heading = page.getByRole('heading', { name: lessons[0].title, exact: true });
        await expect(heading).toBeVisible();
        await expect.poll(() => heading.evaluate((node) => node.clientWidth)).toBeGreaterThan(300);

        const outline = page.getByRole('navigation', { name: 'Course outline', exact: true });
        const toggle = page.getByRole('button', { name: 'Course outline', exact: true });
        await expect(outline).toBeHidden();
        await toggle.click();
        await expect(outline).toBeVisible();
        await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
        await capture(page, info, `methodologist-reader-${width}`);
      }
    });

    if (viewport.width === 1440 || viewport.width === 390) test('methodologist quiz preview uses and returns to the chosen course language', async ({ page, workspace }) => {
      workspace.learner();
      workspace.role = 'methodologist';
      const quizTitle = 'Проверка знаний';
      const question = 'Что нужно сделать с повреждённым оборудованием?';
      const choice = 'Остановиться и сообщить о повреждении';
      const quizPath = `/v1/quizzes/${ids.quiz}`;
      workspace.onGet(`/v1/courses/${ids.course}/languages`, ({ url }) => ({
        json: { primary: 'en', available: ['en', 'ru'], content: url.searchParams.get('language') === 'ru'
          ? { [`quiz.${ids.quiz}.title`]: quizTitle } : {} },
      }));
      workspace.onGet(quizPath, ({ url }) => ({
        json: url.searchParams.get('language') === 'ru' ? {
          ...quiz, title: quizTitle, questions: [{ ...quiz.questions[0], text: question,
            choices: [{ ...quiz.questions[0].choices[0], text: choice }, quiz.questions[0].choices[1]],
          }],
        } : quiz,
      }));
      await page.goto(`/courses/${ids.course}?lessonId=${ids.lesson}&language=ru`);
      await expect(page.getByRole('heading', { name: quizTitle, exact: true })).toBeVisible();
      await page.getByRole('link', { name: 'Start quiz', exact: true }).click();
      await expect(page).toHaveURL(/\/preview\?.*language=ru/);
      await expect(page.getByRole('heading', { name: quizTitle, exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { name: question, exact: true })).toBeVisible();
      await expect(page.getByText(choice, { exact: true })).toBeVisible();
      const quizLanguages = workspace.matching('GET', quizPath).map(({ url }) => url.searchParams.get('language'));
      expect(quizLanguages).not.toHaveLength(0);
      expect(new Set(quizLanguages)).toEqual(new Set(['ru']));
      await page.getByRole('link', { name: 'Return to course', exact: true }).click();
      await expect(page).toHaveURL(`/courses/${ids.course}?lessonId=${ids.lesson}&language=ru`);
      await expect(page.getByRole('heading', { name: quizTitle, exact: true })).toBeVisible();
      expect(workspace.matching('POST', `${quizPath}/submit`)).toHaveLength(0);
    });

    test('learner submits a real quiz UI and sees aggregate result with not-required evidence', async ({ page, workspace }, info) => {
      workspace.learner();
      await page.goto(`/courses/${ids.course}?lessonId=${ids.lesson}`);
      await page.getByRole('link', { name: 'Start quiz', exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/courses/quiz/${ids.quiz}\\?`));
      await expect(page.getByRole('heading', { name: quiz.title, exact: true })).toBeVisible();
      const finish = page.getByRole('button', { name: 'Finish Quiz', exact: true });
      await expect(finish).toBeDisabled();
      await page.getByRole('radio', { name: 'Stop and report the damage', exact: true }).check();
      await expect(finish).toBeEnabled();
      expect(workspace.matching('POST', `/v1/quizzes/${ids.quiz}/submit`)).toHaveLength(0);
      workspace.command('POST', `/v1/quizzes/${ids.quiz}/submit`, () => {
        workspace.get(`/v1/quizzes/${ids.quiz}/attempts`, [quizAttempt]);
        return { json: quizResult };
      });
      await finish.click();
      await expect(page.getByRole('status').filter({ hasText: quizResult.message })).toBeVisible();
      await expect(page.getByText('100% · Pass Score: 80%', { exact: true })).toBeVisible();
      await expect(page.getByText('You passed the test. This does not mean the whole course is complete.', { exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Confirmation not required', exact: true })).toBeVisible();
      await expect(page.getByText('No additional confirmation is required for this result.', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Confirm the completed action with the code from the email.', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Download completion record', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Get a code', exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Confirm action', exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Download test result', exact: true })).toBeVisible();
      await expect(page.getByRole('radio')).toHaveCount(0);
      await expect(page.getByText(quiz.questions[0].text, { exact: true })).toHaveCount(0);
      await expect(page.getByText('Correct answer', { exact: true })).toHaveCount(0);
      await expect(page.getByText('Explanation', { exact: true })).toHaveCount(0);
      await expect(learnerExit(page)).toBeVisible();
      const submitted = workspace.matching('POST', `/v1/quizzes/${ids.quiz}/submit`);
      expect(submitted).toHaveLength(1);
      expect(submitted[0].body).toEqual({
        answers: [{ question_id: ids.question, selected_choice_ids: [ids.safeChoice] }],
        time_spent_seconds: expect.any(Number),
      });
      expect(workspace.matching('GET', `/v1/training-evidence/events/mine/${ids.evidence}`)).toHaveLength(1);
      expect(workspace.matching('POST', `/v1/courses/${ids.course}/complete`)).toHaveLength(0);
      await capture(page, info, 'learner-aggregate-result');
    });

    test('author edits canonical Markdown, checks preview and guards dirty navigation', async ({ page, workspace }, info) => {
      workspace.author();
      await page.goto(`/courses/${ids.course}/edit?lessonId=${ids.lesson}`);
      await page.locator('[data-lesson-format-menu] summary').click();
      await page.getByRole('button', { name: 'Markdown', exact: true }).click();
      const content = page.getByRole('textbox', { name: 'Lesson content', exact: true });
      await expect(content).toHaveValue(lessons[0].content);
      await page.locator('[data-publication-checks] > summary').click();
      await expect(page.getByText('No unsaved course changes', { exact: true })).toBeVisible();
      await content.fill('Inspect equipment');
      await content.press('ControlOrMeta+A');
      const toolbar = page.getByRole('toolbar', { name: 'Text formatting', exact: true });
      await toolbar.getByRole('button', { name: 'Bold', exact: true }).click();
      await expect(content).toHaveValue('**Inspect equipment**');
      await expect(content).toBeFocused();
      await toolbar.getByRole('button', { name: 'Bold', exact: true }).focus();
      await page.keyboard.press('ArrowRight');
      await expect(toolbar.getByRole('button', { name: 'Italic', exact: true })).toBeFocused();
      await expect(page.getByRole('status').filter({ hasText: /^Unsaved changes$/ })).toBeVisible();
      await expect(page.getByText('Save or discard unsaved course changes before approval or publication.', { exact: true }).first()).toBeVisible();
      await expect(page.getByRole('button', { name: 'Approve course', exact: true })).toBeDisabled();
      await page.getByRole('group', { name: 'Lesson view mode', exact: true })
        .getByRole('button', { name: 'Preview', exact: true }).click();
      await expect(page.locator('article strong').filter({ hasText: /^Inspect equipment$/ })).toBeVisible();
      await page.getByRole('button', { name: 'Next lesson', exact: true }).click();
      const dirtyDialog = page.getByRole('dialog', { name: 'Changes are not saved', exact: true });
      await expect(dirtyDialog).toBeVisible();
      await dirtyDialog.getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(dirtyDialog).toBeHidden();
      expect(workspace.matching('PATCH', `/v1/lessons/${ids.lesson}`)).toHaveLength(0);
      workspace.command('PATCH', `/v1/lessons/${ids.lesson}`, () => {
        const saved = { ...lessons[0], content: '**Inspect equipment**' };
        workspace.get(`/v1/lessons/${ids.lesson}`, saved);
        return { json: saved };
      });
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await expect(page.getByRole('status').filter({ hasText: /^Saved$/ })).toBeVisible();
      await expect(page.getByText('No unsaved course changes', { exact: true })).toBeVisible();
      expect(workspace.matching('PATCH', `/v1/lessons/${ids.lesson}`)[0].body)
        .toEqual({ title: lessons[0].title, content: '**Inspect equipment**' });
      await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
      await expect(page.getByRole('link', { name: 'Open review decisions', exact: true }))
        .toHaveAttribute('href', `/admin/course-approvals?courseId=${ids.course}`);
      await capture(page, info, 'author-saved-markdown');
    });

    test('document inspection reports partial index metadata without invented extraction or approval', async ({ page, workspace }, info) => {
      workspace.documents();
      await page.goto('/documents');
      await page.getByRole('button', { name: sourceDocument.title, exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'Original and processing status', exact: true });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText(sourceDocument.filename, { exact: true })).toBeVisible();
      await expect(dialog.locator('dl > div').filter({ hasText: 'Document version' }).locator('dd')).toHaveText('v3');
      await expect(dialog.locator('dl > div').filter({ hasText: 'Index revision' }).locator('dd')).toHaveText('7');
      await expect(dialog.locator('dl > div').filter({ hasText: 'Usage' }).locator('dd')).toHaveText('—');
      await expect(dialog.getByText('Index partially ready', { exact: true })).toBeVisible();
      await expect(dialog.getByText('Indexed fragments: 2 / 3', { exact: true })).toBeVisible();
      await expect(dialog.getByText('Index readiness does not approve the meaning of lessons or questions.', { exact: true })).toBeVisible();
      await expect(dialog.getByText('Page-level extracted text is not available here. Check the original; use the existing new-version upload to correct the source.', { exact: true })).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'Original file', exact: true })).toBeEnabled();
      await expect(dialog.getByRole('textbox')).toHaveCount(0);
      await capture(page, info, 'document-source-inspection');
      await page.keyboard.press('Escape');
      await expect(dialog).toBeHidden();
      await expect(page.getByRole('button', { name: sourceDocument.title, exact: true })).toBeFocused();
    });

    test('unsaved question survives actual Next Back and Forward without a write', async ({ page, workspace }, info) => {
      workspace.author();
      workspace.get('/v1/courses', [course]);
      workspace.get('/v1/course-blueprints', []);
      await page.goto('/courses');
      await expect(page.getByRole('heading', { name: 'Courses', exact: true })).toBeVisible();
      await page.locator('summary').filter({ hasText: /^More$/ }).click();
      const quizzesLink = page.locator('a[href="/quizzes"]').first();
      await quizzesLink.click();
      await expect(page).toHaveURL(`${appOrigin}/quizzes`);
      const courseToggle = page.getByRole('button', { name: new RegExp(course.title) }).first();
      if (await courseToggle.getAttribute('aria-expanded') === 'false') await courseToggle.click();
      await page.getByText(lessons[0].title, { exact: true }).click();
      await expect(page.getByRole('heading', { name: quiz.title, exact: true })).toBeVisible();
      await page.getByRole('article', { name: 'Question 1', exact: true }).getByRole('button', { name: 'Edit', exact: true }).click();
      await page.getByRole('textbox', { name: 'Question text', exact: true }).fill('Keep this unsaved history draft');
      await page.goBack();
      await expect(page).toHaveURL(`${appOrigin}/courses`);
      await page.goForward();
      await expect(page).toHaveURL(`${appOrigin}/quizzes`);
      await expect(page.getByRole('textbox', { name: 'Question text', exact: true })).toHaveValue('Keep this unsaved history draft');
      expect(workspace.calls.filter((call) => ['PATCH', 'PUT', 'POST'].includes(call.method) && call.path !== '/v1/auth/refresh')).toEqual([]);
      await capture(page, info, 'question-history-draft');
    });

    if (viewport.width === 1440 || viewport.width === 390) test('assignment audience filters use group members and position', async ({ page, workspace }) => {
      workspace.assignments();
      const users = [
        { ...audience[0], position_id: ids.department },
        { ...audience[1], position_id: ids.module, position_name: 'Engineer' },
      ];
      workspace.get('/v1/users', { users, total: users.length });
      workspace.get('/v1/positions', [{ id: ids.department, name: 'Operator' }, { id: ids.module, name: 'Engineer' }]);
      workspace.get('/v1/cohorts', [{ id: ids.evidence, name: 'First shift' }]);
      workspace.get(`/v1/cohorts/${ids.evidence}`, { id: ids.evidence, name: 'First shift', user_ids: [users[0].id] });
      workspace.get(`/v1/courses/${ids.course}/enrollments`, []);
      await page.goto('/assignments');
      await expect(page.getByRole('link', { name: 'Learning groups', exact: true })).toHaveAttribute('href', '/cohorts');
      await page.getByRole('combobox', { name: 'Course to assign', exact: true }).selectOption(ids.course);
      const first = page.getByRole('checkbox', { name: 'Synthetic Learner', exact: true });
      const second = page.getByRole('checkbox', { name: 'Existing Graduate', exact: true });
      await expect(second).toBeVisible();
      const group = page.getByRole('combobox', { name: 'Learning group', exact: true });
      await group.selectOption(ids.evidence);
      await expect(first).toBeVisible();
      await expect(second).toHaveCount(0);
      await page.getByRole('combobox', { name: 'Position', exact: true }).selectOption(ids.module);
      await expect(first).toHaveCount(0);
      await expect(page.getByText('No eligible employees match these filters.')).toBeVisible();
      await group.selectOption('');
      await expect(second).toBeVisible();
      expect(workspace.matching('POST', `/v1/courses/${ids.course}/enrollments`)).toHaveLength(0);
      await noPageOverflow(page);
    });

    test('assignment selection excludes existing history and writes only after explicit confirmation', async ({ page, workspace }, info) => {
      workspace.assignments();
      await page.goto('/assignments');
      await page.getByRole('combobox', { name: 'Course to assign', exact: true }).selectOption(ids.course);
      const preview = page.getByRole('region', { name: 'Review recipients before confirming', exact: true });
      await expect(preview).toHaveCount(0);
      await expect(page.getByRole('checkbox', { name: 'Existing Graduate', exact: true })).toHaveCount(0);
      await page.getByRole('checkbox', { name: 'Synthetic Learner', exact: true }).check();
      await expect(preview.locator('dl > div').filter({ hasText: 'Already assigned' }).locator('dd')).toHaveText('1');
      await expect(preview.locator('dl > div').filter({ hasText: 'Of these, completed' }).locator('dd')).toHaveText('1');
      await expect(preview.locator('dl > div').filter({ hasText: /^Selected/ }).locator('dd')).toHaveText('1');
      await expect(preview.getByRole('listitem')).toHaveText('Synthetic Learner');
      await expect(preview.getByText('Creation starts only after confirmation. The server response determines the final count.', { exact: true })).toBeVisible();
      expect(workspace.matching('POST', `/v1/courses/${ids.course}/enrollments`)).toHaveLength(0);
      await page.getByRole('button', { name: 'Assign (1)', exact: true }).click();
      const confirmation = page.getByRole('dialog', { name: 'Assign training?', exact: true });
      await expect(confirmation).toContainText(course.title);
      expect(workspace.matching('POST', `/v1/courses/${ids.course}/enrollments`)).toHaveLength(0);
      await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(page.getByRole('checkbox', { name: 'Synthetic Learner', exact: true })).toBeChecked();
      await page.getByRole('button', { name: 'Assign (1)', exact: true }).click();
      await expect(confirmation).toBeVisible();
      await capture(page, info, 'assignment-explicit-confirmation');
      workspace.command('POST', `/v1/courses/${ids.course}/enrollments`, () => {
        workspace.get(`/v1/courses/${ids.course}/enrollments`, [existingEnrollment, newEnrollment]);
        return { json: [newEnrollment] };
      });
      await confirmation.getByRole('button', { name: 'Assign', exact: true }).click();
      await expect(confirmation).toBeHidden();
      await expect(preview).toHaveCount(0);
      await expect(page.getByTestId('assignment-selection-empty')).toHaveText('0 employees selected');
      await expect(page.getByRole('checkbox', { name: 'Synthetic Learner', exact: true })).toHaveCount(0);
      await page.getByRole('button', { name: 'Current assignments', exact: true }).click();
      await expect(page.getByRole('heading', { name: /: 2$/ })).toBeVisible();
      expect(workspace.matching('POST', `/v1/courses/${ids.course}/enrollments`)).toHaveLength(1);
      expect(workspace.matching('POST', `/v1/courses/${ids.course}/enrollments`)[0].body).toEqual({
        user_ids: [audience[0].id], delivery_mode: 'email', completion_window_minutes: null, due_at: null,
      });
      await noPageOverflow(page);
    });

    test('approval displays the pinned snapshot and requires a separate decision confirmation', async ({ page, workspace }, info) => {
      workspace.role = 'methodologist';
      workspace.get(`/v1/course-approval-requests/${ids.request}`, reviewSummary);
      // Starting/resuming this reviewer attempt is the one expected render-time command.
      workspace.command('POST', `/v1/course-approval-requests/${ids.request}/attempts`, () => ({ json: reviewAttempt }));
      await page.goto(`/course-review-requests/${ids.request}`);
      await expect(page.getByRole('heading', { name: 'Course version review', exact: true })).toBeVisible();
      await expect(page.getByText('This is the frozen version three, not a current draft.', { exact: true })).toBeVisible();
      await page.getByText('Snapshot · v3', { exact: true }).click();
      await expect(page.locator('[data-redesign-page="review-request"] details')).toContainText(ids.request);
      await expect(page.locator('[data-redesign-page="review-request"] details')).toContainText(snapshotHash);
      await expect(page.getByRole('button', { name: 'Return for changes', exact: true })).toBeDisabled();
      await page.getByRole('button', { name: 'Approve version', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'Save the decision for this snapshot?', exact: true });
      await expect(dialog).toContainText(ids.reviewAttempt);
      await expect(dialog).toContainText(snapshotHash);
      await expect(dialog).toContainText('Publishing the course is a separate action.');
      expect(workspace.matching('POST', `/v1/course-review-attempts/${ids.reviewAttempt}/decision`)).toHaveLength(0);
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(dialog).toBeHidden();
      await page.getByRole('button', { name: 'Approve version', exact: true }).click();
      await capture(page, info, 'approval-pinned-confirmation');
      workspace.command('POST', `/v1/course-review-attempts/${ids.reviewAttempt}/decision`, () => ({ json: {
        revision_id: ids.revision, decision: 'approve', outcome: 'approved', activity_state: 'completed',
      } }));
      await dialog.getByRole('button', { name: 'Confirm decision', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Decision saved', exact: true })).toBeVisible();
      const decisions = workspace.matching('POST', `/v1/course-review-attempts/${ids.reviewAttempt}/decision`);
      expect(decisions).toHaveLength(1);
      expect(decisions[0].body).toEqual({ decision: 'approve', reason: null, acknowledge_incomplete_warning: false });
      expect(workspace.calls.filter((call) => call.path.endsWith('/publish'))).toEqual([]);
      await noPageOverflow(page);
    });

    if (viewport.width === 1440 || viewport.width === 390) test('employee journal scopes rows, summary and CSV to the chosen employee', async ({ page, workspace }) => {
      workspace.trainingLog();
      const employee = trainingRows[0];
      await page.goto(`/training-log?user_id=${employee.user_id}`);
      await expect(page.getByRole('status').filter({ hasText: `Employee records · ${employee.full_name}` })).toBeVisible();
      await expect(page.getByRole('button', { name: new RegExp(employee.full_name) })).toBeVisible();
      await expect(page.getByText(trainingRows[1].full_name, { exact: true })).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'Methodologist action center' })).toHaveCount(0);
      const downloaded = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
      await downloaded;
      const calls = workspace.matching('GET', '/v1/admin/training-log');
      expect(calls.some((call) => call.url.searchParams.get('format') === 'csv')).toBe(true);
      expect(calls.every((call) => call.url.searchParams.get('user_id') === employee.user_id)).toBe(true);
      expect(workspace.matching('GET', '/v1/admin/training-log/summary').map((call) => call.url.searchParams.get('user_id')))
        .toContain(employee.user_id);
      await page.getByRole('button', { name: 'Show all employees' }).click();
      await expect(page).not.toHaveURL(/user_id=/);
      await expect(page.getByRole('heading', { name: 'Methodologist action center' })).toBeVisible();
    });

    if (viewport.width === 1440 || viewport.width === 390) test('employee card restores an exact historical enrollment, answers, PDF and journal context', async ({ page, workspace }, info) => {
      workspace.trainingLog();
      const original = trainingRows[101];
      const certificateId = 'a09726e9-207d-428e-a43d-cbf781d589a3';
      const selected = {
        ...original, content_release_version: 2, quiz_attempts_count: 2, best_score: 100,
        certificate_id: certificateId, certificate_number: 'QA-ARCHIVED', certificate_status: 'expired',
      };
      const active = { ...selected, content_release_version: 3, enrollment_id: trainingRows[100].enrollment_id, certificate_number: 'QA-CURRENT' };
      const journalRows = [...trainingRows.slice(0, 101), selected];
      workspace.onGet('/v1/admin/training-log', ({ url }) => {
        const scoped = url.searchParams.get('user_id') === selected.user_id;
        const enrollmentId = url.searchParams.get('enrollment_id');
        const rows = scoped ? [active, selected].filter((row) => !enrollmentId || row.enrollment_id === enrollmentId) : journalRows;
        const offset = Number(url.searchParams.get('offset'));
        const limit = Number(url.searchParams.get('limit'));
        return { json: { items: rows.slice(offset, offset + limit), total: rows.length, offset, limit, reporting_scope: 'tenant' } };
      });
      workspace.get(`/v1/admin/learning-insights/enrollments/${selected.enrollment_id}`, {
        enrollment_id: selected.enrollment_id, course_id: selected.course_id,
        course_title: selected.course_title, user_name: selected.full_name,
        attempts: [1, 2].map((number) => ({
          id: `historical-attempt-${number}`, quiz_id: ids.quiz, quiz_title: 'Archived safety test',
          content_release_id: ids.revision, release_version: 2, completed_at: selected.enrolled_at, attempt_number: number,
          score_percent: number === 1 ? 50 : 100, passed: number === 2,
          evidence_status: 'verified', lesson_id: ids.lesson, questions: [{
            question_id: ids.question, question_key: ids.question, text: 'What requires a supervisor check?',
            type: 'single_choice', explanation: null, is_correct: number === 2, points_possible: 1,
            points_earned: number === 2 ? 1 : 0, choices: [
              { id: ids.safeChoice, text: 'Damaged equipment', selected: number === 2, correct: true },
              { id: ids.unsafeChoice, text: 'All routine operations', selected: number === 1, correct: false },
            ], review: { status: 'unreviewed', updated_at: null },
          }],
        })),
      });
      workspace.onGet(`/v1/certificates/${certificateId}/download`, () => ({
        body: '%PDF-1.4\nSynthetic certificate\n%%EOF', contentType: 'application/pdf',
      }));
      workspace.get(`/v1/knowledge-checks/employees/${selected.user_id}/assignments`, {
        items: [{ id: 'standalone-assignment', title: 'Independent equipment assessment', revision: 4,
          status: 'passed', due_at: null, attempt_limit: 2, attempts_count: 1,
          attempts: [{ id: 'standalone-attempt', number: 1, completed_at: selected.enrolled_at, score_percent: 100, passed: true }] }],
        has_more: false,
      });
      workspace.get(`/v1/knowledge-checks/employees/${selected.user_id}/attempts/standalone-attempt`, {
        assignment_id: 'standalone-assignment', answers: [{ question_id: 'first', selected_choice_ids: ['correct'] }],
        snapshot: { questions: [{ id: 'first', type: 'MCQ', text: 'Which valve closes first?',
          choices: [{ id: 'correct', text: 'Inlet', is_correct: true }, { id: 'wrong', text: 'Outlet', is_correct: false }] }] },
      });
      const journal = '/training-log?history=true&journal_page=2';
      await page.goto(journal);
      await page.getByRole('button', { name: /Synthetic employee 102 Synthetic workplace safety/ }).click();
      await page.getByRole('link', { name: selected.full_name, exact: true }).click();
      await expect(page).toHaveURL(/journal_page=2.*employee_card=.*card_enrollment=/);
      await page.reload();
      const card = page.getByRole('dialog', { name: 'Employee record' });
      await expect(card.getByText('QA-ARCHIVED', { exact: true })).toBeVisible();
      await expect(card.getByText('Revision 2', { exact: true })).toBeVisible();
      await expect(card.getByText('Revision 3', { exact: true })).toHaveCount(0);
      await expect(card.getByText('QA-CURRENT', { exact: true })).toHaveCount(0);
      await expect(card.getByText('Test attempts: 2')).toBeVisible();
      await card.getByRole('button', { name: /Review answers|Learner answers|Answer review/i }).click();
      await expect.poll(() => workspace.matching('GET', `/v1/admin/learning-insights/enrollments/${selected.enrollment_id}`).length).toBe(1);
      await expect(card.getByText('Score: 50%', { exact: true })).toBeVisible();
      await expect(card.getByText('Score: 100%', { exact: true })).toBeVisible();
      await expect(card.getByText('What requires a supervisor check?', { exact: true })).toHaveCount(2);
      const download = page.waitForEvent('download');
      await card.getByRole('button', { name: 'Download certificate PDF' }).click();
      expect((await download).suggestedFilename()).toBe('certificate-QA-ARCHIVED.pdf');
      expect(workspace.matching('GET', `/v1/certificates/${certificateId}/download`)[0].url.searchParams.get('direct')).toBe('true');
      await card.getByRole('button', { name: 'Standalone knowledge checks' }).click();
      await expect(card.getByRole('heading', { name: 'Independent equipment assessment' })).toBeVisible();
      await card.getByRole('button', { name: 'Review answers' }).click();
      await expect(card.getByText('Which valve closes first?', { exact: true })).toBeVisible();
      await noPageOverflow(page);
      await card.getByRole('button', { name: 'Back to training log' }).click();
      await expect(page).toHaveURL(appOrigin + journal);
      await expect(page.getByRole('button', { name: /Synthetic employee 102 Synthetic workplace safety/ })).toHaveAttribute('aria-pressed', 'true');
      await page.locator('#lang-select').selectOption('ru');
      await page.getByRole('link', { name: selected.full_name, exact: true }).click();
      const russianCard = page.getByRole('dialog', { name: 'Карточка сотрудника' });
      await expect(russianCard.getByRole('button', { name: 'Скачать PDF сертификата' })).toBeVisible();
      await page.screenshot({ path: info.outputPath(`employee-card-${viewport.width}.png`) });
      await russianCard.getByRole('button', { name: 'Назад в журнал' }).click();
      await page.locator('#lang-select').selectOption('kk');
      await page.getByRole('link', { name: selected.full_name, exact: true }).click();
      await expect(page.getByRole('dialog', { name: 'Қызметкер карточкасы' })
        .getByRole('button', { name: 'Сертификаттың PDF файлын жүктеу' })).toBeVisible();
    });

    test('training log keeps restricted scope, current/history filters and whole-filter CSV at both sizes', async ({ page, workspace }, info) => {
      workspace.trainingLog();
      await page.goto(`/training-log?department_id=${ids.department}&delivery_type=native`);
      await expect(page.getByRole('heading', { name: 'Training log', exact: true })).toBeVisible();
      await expect(page.getByRole('status').filter({ hasText: 'Only employees in the organization units and groups assigned to you are shown.' })).toBeVisible();
      await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('in_progress');
      await expect(page.getByText('Total rows: 101', { exact: true })).toBeVisible();
      await expect.poll(() => workspace.matching('GET', '/v1/admin/training-log')
        .some((call) => call.url.searchParams.get('status') === 'in_progress')).toBe(true);
      const history = page.getByRole('checkbox', { name: 'Include historical assignments', exact: true });
      // URL-owned controlled state commits asynchronously through Next navigation.
      await history.click();
      await expect(history).toBeChecked();
      await expect(page.getByText('Total rows: 102', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Next', exact: true }).click();
      await expect.poll(() => workspace.matching('GET', '/v1/admin/training-log')
        .some((call) => call.url.searchParams.get('history') === 'true' && call.url.searchParams.get('offset') === '100')).toBe(true);
      // Methodologists start with record cards; the comparison table is explicit.
      await expect(page.getByRole('button', { name: 'Synthetic employee 101 Synthetic workplace safety 50%', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Synthetic employee 102 Synthetic workplace safety 50%', exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Full table', exact: true }).click();
      const visibleRows = viewport.width < 1024
        ? page.getByTestId('training-log-mobile-list')
        : page.locator('.training-log-table-scroll');
      await expect(visibleRows.getByText('Synthetic employee 101', { exact: true })).toBeVisible();
      await expect(visibleRows.getByText('Synthetic employee 102', { exact: true })).toBeVisible();
      await expect(visibleRows.getByText('Superseded history', { exact: true })).toBeVisible();
      await expect(visibleRows.getByText('Synthetic employee 001', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Download CSV', exact: true })).toBeEnabled();
      const downloaded = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
      const download = await downloaded;
      expect(download.suggestedFilename()).toMatch(/^training-log-.*\.csv$/);
      const file = info.outputPath('synthetic-training-log.csv');
      await download.saveAs(file);
      const bytes = await readFile(file);
      expect([...bytes.subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
      const csv = bytes.toString('utf8');
      expect(csv).toContain('Synthetic employee 001');
      expect(csv).toContain('Synthetic employee 102');
      expect(csv.trim().split(/\r?\n/)).toHaveLength(103);
      const csvCall = workspace.matching('GET', '/v1/admin/training-log')
        .find((call) => call.url.searchParams.get('format') === 'csv');
      expect(csvCall).toBeDefined();
      const scope = { department_id: ids.department, delivery_type: 'native', history: 'true', status: 'in_progress' };
      expect(filterScope(csvCall!.url)).toEqual(scope);
      expect(csvCall!.url.searchParams.get('lang')).toBe('en');
      expect(csvCall!.url.searchParams.get('offset')).toBe('100');
      await expect.poll(() => workspace.matching('GET', '/v1/admin/training-log/summary')
        .some((call) => JSON.stringify(filterScope(call.url)) === JSON.stringify(filterScope(csvCall!.url)))).toBe(true);
      await capture(page, info, 'training-log-history-export');
    });
  });
}
