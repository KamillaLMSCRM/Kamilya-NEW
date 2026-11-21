import { expect, test, type Page } from '@playwright/test';
import { appOrigin, ids, quiz, quizAttempt, quizResult, SyntheticWorkspace } from './learning-workspace-ux-fixtures';
import { getCopy } from '../../src/features/knowledge-checks/copy';
import { matchingCopy } from '../../src/features/quiz/MatchingPairs';
import ru from '../../src/i18n/locales/ru.json';
import kk from '../../src/i18n/locales/kk.json';

if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER) throw new Error('Use an isolated loopback server.');
test.use({ baseURL: appOrigin });

const choicesFor = (language: 'ru' | 'kk') => {
  const texts = language === 'ru' ? ['Журнал', 'Подписать', 'Комплект', 'Осмотреть']
    : ['Журнал', 'Қол қою', 'Жинақ', 'Көзбен тексеру'];
  return texts.map((text, i) => ({
    id: '74000000-0000-4000-8000-00000000000' + (i + 1), text,
    match_side: i % 2 ? 'right' : 'left', order_index: i,
  }));
};

for (const language of ['ru', 'kk'] as const) {
  for (const width of [390, 1440]) {
    for (const mode of ['course', 'standalone'] as const) {
      test(`matching pairs refresh and retake ${mode} ${language} ${width}px`, async ({ page, context }) => {
        const workspace = new SyntheticWorkspace(context, language);
        const courseCopy = (language === 'ru' ? ru : kk).quiz;
        const checkCopy = getCopy(language);
        const choices = choicesFor(language);
        const question = { ...quiz.questions[0], type: 'matching_pairs', choices,
          text: language === 'ru' ? 'Сопоставьте предмет и действие' : 'Зат пен әрекетті сәйкестендіріңіз' };
        const retries = ['74000000-0000-4000-8000-000000000091', '74000000-0000-4000-8000-000000000092'];
        const records: Array<typeof quizAttempt & { status: string; number: number }> = [];
        let saved: { answers: { question_id: string; selected_choice_ids: string[] }[] } = { answers: [] };
        let active = false;
        const checkPath = `/v1/knowledge-checks/assignments/${ids.enrollment}`;
        const coursePath = `/v1/quizzes/${ids.quiz}`;
        const attempt = () => ({
          id: retries[records.length], assignment_id: ids.enrollment, number: records.length + 1, status: 'started',
          started_at: quizAttempt.started_at, completed_at: null, answers: saved.answers,
          snapshot: { title: quiz.title, instructions: '', questions: [question] },
        });
        const check = () => ({ id: ids.enrollment, check_id: ids.quiz, title: quiz.title, revision: 1,
          due_at: null, status: active ? 'in_progress' : records.at(-1)?.passed ? 'passed' : 'assigned',
          attempt_limit: 2, attempts_count: records.length + Number(active), passed: records.at(-1)?.passed ?? false,
          score_percent: records.at(-1)?.score_percent ?? null, attempts: active ? [...records, attempt()] : records,
        });
        const grade = (body: unknown) => {
          const cells = (body as typeof saved).answers[0].selected_choice_ids;
          expect(cells).toHaveLength(4);
          const pairs = new Map([[cells[0], cells[1]], [cells[2], cells[3]]]);
          const pass = pairs.get(choices[0].id) === choices[1].id && pairs.get(choices[2].id) === choices[3].id;
          expect(pass).toBe(records.length === 1);
          const result = { ...quizAttempt, id: retries[records.length], number: records.length + 1, status: 'submitted',
            passed: pass, earned_points: Number(pass), score_percent: pass ? 100 : 0 };
          records.push(result);
          active = false;
          return result;
        };

        workspace.learner();
        workspace.get('/v1/courses/' + ids.course + '/languages', { primary: 'ru', available: ['ru', 'kk'], content: {} });
        workspace.get(coursePath, { ...quiz, attempt_enrollment_id: ids.enrollment, questions: [question] });
        workspace.onGet(coursePath + '/attempts', () => ({ json: records }));
        workspace.onGet(checkPath, () => ({ json: check() }));
        for (const id of retries) workspace.onGet('/v1/knowledge-checks/attempts/' + id, () => ({ json: attempt() }));
        await workspace.install();
        await page.setViewportSize({ width, height: 880 });
        const courseMode = mode === 'course';
        if (courseMode) {
          await page.goto(`/courses/${ids.course}?lessonId=${ids.lesson}`);
          await page.getByLabel(language === 'ru' ? 'Язык курса' : 'Курс тілі', { exact: true }).selectOption(language);
          const start = page.getByRole('link', { name: courseCopy.startQuiz, exact: true });
          await expect(start).toHaveAttribute('href', new RegExp('[?&]language=' + language + '$'));
          await start.click();
        } else {
          await page.goto(`/my-knowledge-checks/${ids.enrollment}`);
          workspace.command('POST', checkPath + '/start', () => {
            active = true; saved = { answers: [] }; return { json: attempt() };
          });
          await page.getByRole('button', { name: checkCopy.start, exact: true }).click();
        }
        const select = (index: number) => page.getByRole('combobox', { name: choices[index].text, exact: true });
        const optionOrder = async (surface: Page) => surface.getByRole('combobox', { name: choices[0].text, exact: true })
          .getByRole('option').allTextContents();
        const submit = page.getByRole('button', { name: courseMode ? courseCopy.finish : checkCopy.submit, exact: true });
        await expect(page.getByText(matchingCopy(language).learnerHint, { exact: true })).toBeVisible();
        await expect(submit).toBeDisabled();
        const initial = await optionOrder(page);
        await select(0).selectOption(choices[3].id);
        await expect(submit).toBeDisabled();
        if (!courseMode) {
          workspace.command('PUT', '/v1/knowledge-checks/attempts/' + retries[0] + '/answers', ({ body }) => {
            saved = body as typeof saved; return { json: attempt() };
          });
          await page.getByRole('button', { name: checkCopy.saveAnswers, exact: true }).click();
          await expect(page.getByRole('status').filter({ hasText: checkCopy.saved })).toBeVisible();
        }
        await page.reload();
        await expect(select(0)).toHaveValue(choices[3].id);
        expect(await optionOrder(page)).toEqual(initial);
        await select(2).selectOption(choices[1].id);
        const registerSubmit = (attemptIndex: number) => {
          if (courseMode) {
            workspace.command('POST', coursePath + '/submit', ({ body }) => {
              const result = grade(body); return { json: { ...quizResult, attempt: result, passed: result.passed } };
            });
          } else {
            workspace.command('POST', '/v1/knowledge-checks/attempts/' + retries[attemptIndex] + '/submit', ({ body }) => ({
              json: grade(body),
            }));
            page.once('dialog', dialog => dialog.accept());
          }
        };
        registerSubmit(0);
        await submit.click();
        if (courseMode) {
          await page.getByRole('button', { name: courseCopy.tryAgain, exact: true }).click();
        } else {
          await page.getByRole('button', { name: checkCopy.start, exact: true }).click();
          workspace.command('POST', checkPath + '/start', () => {
            active = true; saved = { answers: [] }; return { json: attempt() };
          });
          await page.getByRole('button', { name: checkCopy.start, exact: true }).click();
        }
        await expect(select(0)).toHaveValue('');
        const retry = await optionOrder(page);
        expect(retry).not.toEqual(initial);
        await page.reload();
        await expect(select(0)).toHaveValue('');
        expect(await optionOrder(page)).toEqual(retry);
        await select(0).selectOption(choices[1].id);
        await select(2).selectOption(choices[3].id);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        registerSubmit(1);
        await submit.click();
        await expect.poll(() => records.map(({ score_percent }) => score_percent)).toEqual([0, 100]);
        if (!courseMode) {
          await page.reload();
          await expect(page.getByRole('listitem').filter({ hasText: /100%$/ })).toBeVisible();
          await expect(page.getByRole('listitem').filter({ hasText: /(?:\s)0%$/ })).toBeVisible();
        }
        workspace.assertIsolated();
      });
    }
  }
}
