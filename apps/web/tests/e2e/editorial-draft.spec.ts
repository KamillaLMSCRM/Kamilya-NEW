import { test, expect } from '@playwright/test';
import { appOrigin, assignment, course, evidenceEvent, ids, lessons, quiz, quizAttempt, quizResult, structure, SyntheticWorkspace } from './learning-workspace-ux-fixtures';

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

test('editor leads through scoped quiz review, publication, and assignment settings', async ({ page, context }, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const workspace = new SyntheticWorkspace(context, 'ru');
  workspace.author();
  workspace.assignments();
  const draft = { ...course, status: 'draft', ai_generated: true, requires_approval: false };
  workspace.get(`/v1/courses/${ids.course}`, draft);
  workspace.get(`/v1/courses/${ids.course}/approval-policy`, { course_id: ids.course, requires_approval: false, review_enabled: true });
  const authorQuiz = { ...quiz, review_status: 'needs_review', questions: quiz.questions.map((question) => ({
    ...question, type: 'MCQ', choices: question.choices.map((choice, index) => ({ ...choice, is_correct: index === 0 })),
  })) };
  workspace.get('/v1/quizzes/grouped', { courses: [
    { ...draft, modules: [{ ...structure.modules[0], lessons: [{ ...lessons[0], quiz: authorQuiz }] }] },
    { ...draft, id: ids.document, title: 'Another course', modules: [{ ...structure.modules[0], lessons: [{ ...lessons[0], quiz: authorQuiz }] }] },
  ], orphans: [] });
  await workspace.install();
  await page.goto(`${appOrigin}/courses/${ids.course}/edit`);
  const workflow = page.getByRole('region', { name: 'Путь до назначения' });
  await expect(workflow.getByRole('region', { name: 'Проверка черновика' })).toBeVisible();
  await expect(workflow.getByRole('link', { name: 'Назначить курс' })).toHaveCount(0);
  await workflow.screenshot({ path: info.outputPath('release-workflow-desktop.png'), animations: 'disabled' });
  await workflow.getByRole('link', { name: 'Проверить тесты курса' }).click();
  await expect(page).toHaveURL(`${appOrigin}/quizzes?courseId=${ids.course}`);
  await expect(page.getByRole('button', { name: /Another course/ })).toHaveCount(0);
  await page.getByRole('button', { name: /Prepare safely.*Требует проверки/ }).click();
  workspace.command('POST', `/v1/quizzes/${ids.quiz}/approve`, () => ({ json: { ...authorQuiz, review_status: 'approved' } }));
  await page.getByRole('button', { name: 'Одобрить после проверки' }).click();
  await expect(page.getByRole('button', { name: 'Одобрить после проверки' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Вернуться к выпуску курса' }).click();
  workspace.command('POST', `/v1/courses/${ids.course}/review`, () => ({ json: { ...draft, review_status: 'approved' } }));
  await workflow.getByRole('button', { name: 'Одобрить курс', exact: true }).click();
  workspace.command('POST', `/v1/courses/${ids.course}/publish`, () => ({ json: { ...draft, status: 'published', review_status: 'approved' } }));
  await workflow.getByRole('button', { name: 'Опубликовать', exact: true }).click();
  await workflow.getByRole('link', { name: 'Назначить курс', exact: true }).click();
  await expect(page).toHaveURL(`${appOrigin}/assignments?courseId=${ids.course}`);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('radio', { name: /Персональная ссылка и PIN/ }).check();
  const deadlines = page.getByText('Дополнительные настройки сроков', { exact: true });
  const timer = page.getByRole('spinbutton', { name: 'Время на прохождение после первого входа, минут' });
  await expect(page.getByText(/Ссылка действует 7 дн/)).toBeVisible();
  await expect(timer).toBeHidden();
  await deadlines.click();
  await expect(timer).toBeVisible();
  await timer.fill('30');
  await deadlines.click();
  await expect(page.getByText(/На прохождение 30 мин/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Назначить (1)' })).toHaveCount(0);
  await page.getByRole('checkbox', { name: 'Synthetic Learner' }).check();
  await page.screenshot({ path: info.outputPath('assignment-deadlines-mobile.png'), animations: 'disabled', fullPage: true });
  await page.getByRole('button', { name: 'Назначить (1)' }).click();
  const confirm = page.getByRole('dialog');
  await expect(confirm).toContainText(course.title);
  const enrollPath = `/v1/courses/${ids.course}/personal-link-enrollment`;
  expect(workspace.matching('POST', enrollPath)).toHaveLength(0);
  workspace.command('POST', enrollPath, () => ({ status: 201, json: {
    enrollment_id: ids.enrollment, user_id: ids.learner, access_url: `${appOrigin}/access/synthetic`,
    temporary_pin: '123456', link_expires_at: new Date(Date.now() + 7 * 86400000).toISOString(), completion_window_minutes: 30,
  } }));
  await confirm.getByRole('button', { name: 'Назначить', exact: true }).click();
  await expect(page.getByText('PIN: 123456', { exact: true })).toBeVisible();
  expect(workspace.matching('POST', enrollPath)).toHaveLength(1);
  expect(workspace.matching('POST', enrollPath)[0].body).toMatchObject({
    user_id: ids.learner, completion_window_minutes: 30, due_at: null, link_expires_at: expect.any(String),
  });
  workspace.assertIsolated();
});

test('last quiz guides the learner to completion and separates the certificate from evidence', async ({ page, context }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const workspace = new SyntheticWorkspace(context, 'ru');
  workspace.learner();
  workspace.get(`/v1/courses/${ids.course}/structure`, { modules: [{ ...structure.modules[0], lessons: [lessons[0]] }] });
  workspace.command('POST', `/v1/quizzes/${ids.quiz}/submit`, () => {
    workspace.get(`/v1/quizzes/${ids.quiz}/attempts`, [quizAttempt]);
    workspace.get(`/v1/progress/courses/${ids.course}/completed-ids`, { completed_lesson_ids: [ids.lesson] });
    return { json: { ...quizResult, training_evidence_event_id: null } };
  });
  workspace.get(`/v1/training-evidence/events/mine/${ids.evidence}`, {
    ...evidenceEvent, procedure_type: 'training', record_type: 'course_completion',
    procedure_title: course.title, confirmation_status: 'pending',
  });
  workspace.get(`/v1/training-evidence/events/mine/${ids.evidence}/signed-scans`, { status: 'awaiting_return', scans: [] });
  workspace.command('POST', `/v1/courses/${ids.course}/complete`, () => {
    workspace.get('/v1/student/dashboard', { enrolled_courses: [{ ...assignment, enrollment_status: 'completed' }] });
    workspace.onGet('/v1/training-evidence/events/mine', () => ({ status: 503 }));
    return { json: { status: 'completed', certificate_id: ids.revision, training_evidence_event_id: ids.evidence } };
  });
  await workspace.install();
  await page.goto(`${appOrigin}/courses/${ids.course}?lessonId=${ids.lesson}`);
  await page.getByRole('link', { name: 'Начать тест' }).click();
  await page.getByRole('radio', { name: 'Stop and report the damage' }).check();
  await page.getByRole('button', { name: 'Завершить тест' }).click();
  await page.getByRole('button', { name: 'Перейти к завершению курса' }).click();
  await expect(page).toHaveURL(`${appOrigin}/courses/${ids.course}?lessonId=${ids.lesson}#finish-course`);
  const finish = page.getByRole('button', { name: 'Завершить курс' });
  await expect(finish).toBeFocused();
  expect(workspace.matching('POST', `/v1/courses/${ids.course}/complete`)).toHaveLength(0);
  await finish.click();
  await expect(page.getByRole('heading', { name: 'Обучение завершено' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Сертификат', exact: true })).toHaveAttribute('href', '/certificates');
  await expect(page.getByRole('heading', { name: 'Документальное подтверждение' })).toBeVisible();
  await expect(page.getByText('Ожидает подтверждения', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('completion-mobile.png'), animations: 'disabled', fullPage: true });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Обучение завершено' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Сертификат', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Повторить' })).toBeVisible();
  expect(workspace.matching('POST', `/v1/courses/${ids.course}/complete`)).toHaveLength(1);
  workspace.assertIsolated();
});
