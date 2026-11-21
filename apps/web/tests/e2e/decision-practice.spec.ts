import { expect, test } from '@playwright/test';
import { appOrigin, ids, lessons, structure, SyntheticWorkspace } from './learning-workspace-ux-fixtures';
import { practiceCopy, type DecisionPractice } from '../../src/features/course-authoring/DecisionPractice';

const practice: DecisionPractice = {
  title: { ru: 'Приём смены', kk: 'Ауысымды қабылдау' },
  steps: [
    { id: 'first', text: { ru: 'Вы получили журнал', kk: 'Сіз журналды алдыңыз' }, choices: [
      { target: 'checked', label: { ru: 'Сверить записи', kk: 'Жазбаларды салыстыру' } },
      { target: 'signed', label: { ru: 'Подписать сразу', kk: 'Бірден қол қою' } },
    ] },
    { id: 'checked', text: { ru: 'Вы заметили пропуск', kk: 'Сіз бос жолды байқадыңыз' }, choices: [] },
    { id: 'signed', text: { ru: 'Пропуск остался', kk: 'Бос жол қалды' }, choices: [] },
  ],
};

for (const [lang, width] of [['ru', 1440], ['kk', 390]] as const) {
  test(`assigned lesson practice resumes and restarts in ${lang} at ${width}px`, async ({ page, context }) => {
    const workspace = new SyntheticWorkspace(context, lang);
    workspace.learner();
    workspace.get(`/v1/courses/${ids.course}/languages`, { primary: 'ru', available: ['ru', 'kk'], content: {} });
    workspace.get(`/v1/courses/${ids.course}/structure`, {
      modules: [{ ...structure.modules[0], lessons: [{ ...lessons[0], decision_practice: { practice, revision: 'published' } }, lessons[1]] }],
    });
    await workspace.install();
    await page.setViewportSize({ width, height: 880 });
    await page.goto(appOrigin + `/courses/${ids.course}?lessonId=${ids.lesson}`);
    await page.getByRole('combobox', { name: lang === 'ru' ? 'Язык курса' : 'Курс тілі' }).selectOption(lang);
    const copy = practiceCopy(lang);
    const panel = page.getByRole('region', { name: copy.name });
    await panel.getByRole('button', { name: copy.start }).click();
    await panel.getByRole('button', { name: practice.steps[0].choices[0].label[lang] }).click();
    await expect(panel.getByRole('heading', { name: copy.outcome })).toBeFocused();
    await expect(panel.getByText(practice.steps[1].text[lang])).toBeVisible();
    await page.reload();
    await expect(panel.getByText(practice.steps[1].text[lang])).toBeVisible();
    await panel.getByRole('button', { name: copy.restart }).click();
    await panel.getByRole('button', { name: practice.steps[0].choices[1].label[lang] }).click();
    await expect(panel.getByText(practice.steps[2].text[lang])).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    workspace.assertIsolated();
  });
}
