import { expect } from '@playwright/test';
import { appOrigin, course, ids, lessons, test } from './learning-workspace-ux-fixtures';

test.use({ baseURL: appOrigin, serviceWorkers: 'block' });

test('the outline stays in the selected translation while moving between lessons', async ({ page, workspace }) => {
  workspace.author();
  workspace.get(`/v1/courses/${ids.course}`, {
    ...course, source_analysis: { course_language_policy: { primary: 'en', requested: ['en', 'ru'] } },
  });
  workspace.onGet(`/v1/courses/${ids.course}/languages`, ({ url }) => ({
    json: { primary: 'en', available: ['en', 'ru'], content: url.searchParams.get('language') === 'ru' ? {
      [`course.${ids.course}.title`]: 'Безопасность на работе',
      [`module.${ids.module}.title`]: 'Безопасная работа',
      [`lesson.${ids.lesson}.title`]: 'Подготовка',
      [`lesson.${ids.secondLesson}.title`]: 'Сообщение об опасности',
      [`lesson.${ids.secondLesson}.content`]: 'Остановите работу.',
    } : {} },
  }));
  await page.goto(`/courses/${ids.course}/edit?lessonId=${ids.lesson}`);
  const locale = page.getByLabel('Course language');
  await locale.selectOption('ru');
  await expect(page.getByRole('heading', { name: 'Безопасная работа', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Подготовка', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Сообщение об опасности', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Сообщение об опасности', exact: true })).toBeVisible();
  await expect(page.getByText('Остановите работу.')).toBeVisible();
  await expect(locale).toHaveValue('ru');
  await locale.selectOption('en');
  await expect(page.getByRole('heading', { name: 'Safe work', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Report a hazard', exact: true })).toBeVisible();
});

test('the learner preview opens in the editor language and retains changes across lessons', async ({ page, workspace }) => {
  workspace.learner();
  workspace.author();
  workspace.get(`/v1/courses/${ids.course}`, {
    ...course, source_analysis: { course_language_policy: { primary: 'en', requested: ['en', 'ru'] } },
  });
  workspace.onGet(`/v1/courses/${ids.course}/languages`, ({ url }) => ({
    json: { primary: 'en', available: ['en', 'ru'], content: url.searchParams.get('language') === 'ru' ? {
      [`lesson.${ids.lesson}.title`]: 'Подготовка',
      [`lesson.${ids.secondLesson}.title`]: 'Сообщение об опасности',
    } : {} },
  }));

  await page.goto(`/courses/${ids.course}/edit?lessonId=${ids.lesson}`);
  await page.getByRole('combobox', { name: 'Course language' }).selectOption('ru');
  await expect(page.getByRole('heading', { name: 'Подготовка', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open as learner', exact: true }).click();
  await expect(page).toHaveURL(`/courses/${ids.course}?lessonId=${ids.lesson}&language=ru`);
  await expect(page.getByRole('heading', { name: 'Подготовка', exact: true })).toBeVisible();

  const language = page.getByRole('combobox', { name: 'Course language' });
  await expect(language).toHaveValue('ru');
  await language.selectOption('en');
  await expect(page.getByRole('heading', { name: lessons[0].title, exact: true })).toBeVisible();
  await page.getByRole('button', { name: /Report a hazard/ }).click();
  await expect(page).toHaveURL(`/courses/${ids.course}?lessonId=${ids.secondLesson}&language=en`);
  await page.reload();
  await expect(page.getByRole('heading', { name: lessons[1].title, exact: true })).toBeVisible();
  await expect(language).toHaveValue('en');
});

for (const width of [390, 1024, 1440]) {
  test(`visual lesson blocks retain Markdown, save once and survive reload at ${width}`, async ({ page, workspace }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    workspace.author();
    let persisted = lessons[0].content;
    workspace.onGet(`/v1/lessons/${ids.lesson}`, () => ({ json: { ...lessons[0], content: persisted } }));
    workspace.command('PATCH', `/v1/lessons/${ids.lesson}`, call => {
      persisted = (call.body as { content: string }).content;
      return { json: { ...lessons[0], content: persisted } };
    });
    await page.goto(`/courses/${ids.course}/edit?lessonId=${ids.lesson}`);
    await expect(page.getByRole('button', { name: 'Visual editor', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: 'Prepare safely', exact: true })).toBeVisible();
    expect(await page.getByRole('heading', { name: 'Prepare safely', exact: true }).evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThan(24);
    expect(await page.getByRole('list').filter({ has: page.getByText('Inspect equipment.', { exact: true }) }).evaluate(el => getComputedStyle(el).listStyleType)).toBe('disc');
    expect(workspace.matching('PATCH', `/v1/lessons/${ids.lesson}`)).toHaveLength(0);
    await page.getByRole('button', { name: 'Markdown', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Lesson content', exact: true })).toHaveValue(lessons[0].content);
    await page.getByRole('button', { name: 'Visual editor', exact: true }).click();
    await page.getByRole('button', { name: 'Add block', exact: true }).click();
    await page.getByRole('group', { name: 'Add block', exact: true }).getByRole('button', { name: 'Key rule', exact: true }).click();
    const content = page.getByRole('textbox', { name: /Block content:/ });
    await content.fill('Stop when the indicator is red.');
    await page.getByRole('button', { name: 'Done', exact: true }).click();
    await expect(page.getByText('Stop when the indicator is red.', { exact: true })).toBeVisible();
    const expected = `${lessons[0].content}\n\n> Stop when the indicator is red.`;
    await page.getByRole('button', { name: 'Markdown', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Lesson content', exact: true })).toHaveValue(expected);
    await page.getByRole('button', { name: 'Visual editor', exact: true }).click();
    const save = page.getByRole('button', { name: 'Save', exact: true });
    await save.scrollIntoViewIfNeeded();
    const box = await save.boundingBox(); expect(box).not.toBeNull();
    expect(await save.evaluate(el => { const b = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2)); })).toBe(true);
    await save.click();
    await expect(save).toBeDisabled();
    expect(workspace.matching('PATCH', `/v1/lessons/${ids.lesson}`)).toHaveLength(1);
    expect(persisted).toBe(expected);
    await page.reload();
    await expect(page.getByText('Stop when the indicator is red.', { exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`${width}-visual-lesson.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
