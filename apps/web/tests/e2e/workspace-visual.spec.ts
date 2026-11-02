import { expect, test as base, type Locator, type Page } from '@playwright/test';
import { appOrigin, ids, quiz, SyntheticWorkspace } from './learning-workspace-ux-fixtures';
import ru from '../../src/i18n/locales/ru.json';
import kk from '../../src/i18n/locales/kk.json';
import en from '../../src/i18n/locales/en.json';

if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER || appOrigin !== 'http://127.0.0.1:3026') {
  throw new Error('Visual acceptance needs the root-owned loopback3026 app and intercepted APIs.');
}

const courses = [
  { id: 'visual-course-1', title: 'Охрана труда и безопасность на рабочем месте', description: 'Порядок действий сотрудников, безопасная работа и профилактика рисков.', status: 'published', ai_generated: false, delivery_type: 'native', current_release_id: 'visual-release-1' },
  { id: 'visual-course-2', title: 'Информационная безопасность: работа с персональными данными', description: 'Учебный черновик подготовлен из документов. Содержание и тесты требуют проверки.', status: 'draft', ai_generated: true, review_status: 'pending', delivery_type: 'native', current_release_id: null },
  { id: 'visual-course-3', title: 'Пожарная безопасность', description: 'Интерактивный пакет для самостоятельного прохождения обучения.', status: 'published', ai_generated: false, delivery_type: 'scorm', current_release_id: 'visual-release-3' },
  { id: 'visual-course-4', title: 'Адаптация новых сотрудников', description: 'Первые рабочие задачи, корпоративные правила и полезные материалы.', status: 'draft', ai_generated: false, delivery_type: 'native', current_release_id: null },
];
const blueprints = [{ id: 'kz-finance-information-security', title: 'Информационная безопасность для финансовых организаций', description: 'Отраслевая заготовка для адаптации под правила вашей компании.', audience: 'Сотрудники финансовых организаций', estimated_ready_percent: 70, compliance_mode: 'lms_only', tags: ['Казахстан', 'Информационная безопасность'] }];
const baseline = process.env.KAMILYA_VISUAL_BASELINE === '1';
const test = base.extend<{ workspace: SyntheticWorkspace; visualLanguage: 'ru' | 'kk' | 'en' }>({
  visualLanguage: ['ru', { option: true }],
  workspace: [async ({ context, visualLanguage }, use) => {
    const workspace = new SyntheticWorkspace(context, visualLanguage);
    workspace.role = 'methodologist';
    workspace.onGet('/v1/courses', ({ url }) => ({ json: courses.filter((course) => (
      (!url.searchParams.get('status') || course.status === url.searchParams.get('status'))
      && (!url.searchParams.get('q') || course.title.toLowerCase().includes(url.searchParams.get('q')!.toLowerCase()))
    )) }));
    workspace.get('/v1/course-blueprints', blueprints);
    await workspace.install();
    await use(workspace);
    workspace.assertIsolated();
  }, { auto: true }],
});
test.use({ baseURL: appOrigin });
test.setTimeout(60_000);

async function checkCourseActionGeometry(page: Page) {
  const controls = page.locator('[data-course-card] a, [data-course-card] button, [data-course-card] summary');
  for (const control of await controls.all()) {
    if (!await control.isVisible()) continue;
    await control.scrollIntoViewIfNeeded();
    const geometry = await control.evaluate((element) => {
      const rect = Array.from(element.getClientRects()).find((box) => box.width > 0 && box.height > 0)!;
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      return {
        label: element.textContent?.trim() || element.getAttribute('aria-label'),
        textFits: element.scrollWidth <= element.clientWidth + 1,
        hit: hit === element || element.contains(hit),
      };
    });
    expect(geometry.textFits, `No clipped action label: ${geometry.label}`).toBe(true);
    expect(geometry.hit, `Pointer reaches the intended action: ${geometry.label}`).toBe(true);
  }
}

function contrast(foreground: string, background: string) {
  const luminance = (colour: string) => {
    const channels = colour.match(/[\d.]+/g)!.slice(0, 3).map((value) => Number(value) / 255)
      .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

async function enableDarkWorkspace(page: Page) {
  await page.evaluate(() => document.documentElement.classList.add('dark'));
  await expect(page.locator('html')).toHaveClass(/\bdark\b/);
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--background').trim())).toBe('222 40% 10%');
}

async function settledControlColours(control: Locator) {
  // Measure the target theme, not an interpolated colour during theme switching.
  // Keep the real transition and the AA threshold; wait on animation state only.
  await expect.poll(() => control.evaluate((element) => element.getAnimations()
    .filter((animation) => animation.playState === 'running' || animation.pending).length)).toBe(0);
  return control.evaluate((element) => ({ foreground: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor }));
}

for (const width of baseline ? [1440, 390] : [1440, 1270, 768, 390, 360]) {
  test(`course catalogue visual and navigation at ${width}px`, async ({ page, workspace }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/courses');
    await expect(page.getByRole('heading', { name: 'Курсы', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: courses[0].title, exact: true })).toBeVisible();
    await expect(page.locator('article').filter({ has: page.getByRole('link', { name: courses[0].title, exact: true }) })).toHaveCSS('opacity', '1');
    await page.screenshot({ path: info.outputPath(baseline ? `before-${width}.png` : `after-${width}.png`), fullPage: false });
    if (baseline) return;
    await expect(page.locator('[data-catalog-layout="workspace-v1"]')).toBeVisible();
    await expect(page.getByRole('link', { name: courses[0].title, exact: true })).toBeInViewport();
    const templateSection = page.locator('[data-blueprint-catalog]');
    await expect(templateSection).not.toHaveAttribute('open');
    const results = page.locator('[data-course-catalog-results]');
    expect(await results.evaluate((element) => Boolean(element.compareDocumentPosition(document.querySelector('[data-blueprint-catalog]')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(245, 246, 250)');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.getByRole('searchbox', { name: 'Поиск', exact: true }).fill('отсутствующий пример');
    await expect.poll(() => workspace.matching('GET', '/v1/courses').filter((call) => call.url.searchParams.get('q') === 'отсутствующий пример').length).toBeGreaterThan(0);
    await expect(results).toHaveAttribute('aria-busy', 'false');
    await expect(results.locator('[data-course-card]')).toHaveCount(0);
    await page.getByRole('button', { name: 'Сбросить фильтры', exact: true }).click();
    await expect(page.getByRole('link', { name: courses[0].title, exact: true })).toBeVisible();
    await checkCourseActionGeometry(page);
    if (width < 768) {
      await page.getByRole('button', { name: 'Открыть меню', exact: true }).click();
      await expect(page.getByRole('link', { name: 'Курсы', exact: true }).first()).toBeInViewport();
      await page.locator('[data-workspace-rail]').getByRole('button', { name: 'Закрыть меню', exact: true }).click();
    } else {
      await page.getByRole('button', { name: 'Свернуть сайдбар (Ctrl+B)', exact: true }).click();
      await expect(page.locator('[data-workspace-rail]')).toHaveCSS('width', '68px');
      await page.getByRole('button', { name: 'Развернуть сайдбар (Ctrl+B)', exact: true }).click();
    }
    await templateSection.locator('summary').click();
    await expect(templateSection.getByRole('link', { name: 'Адаптировать шаблон', exact: true })).toHaveAttribute('href', '/courses/templates/kz-finance-information-security');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    expect(workspace.calls.filter((call) => call.method !== 'GET' && call.path !== '/v1/auth/refresh')).toEqual([]);
  });
}

if (!baseline) {
  test('catalogue read failure retries without a false empty state', async ({ page, workspace }) => {
    workspace.onGet('/v1/courses', () => ({ status: 503, json: { detail: 'Synthetic unavailable' } }));
    await page.goto('/courses');
    await expect(page.locator('[data-course-catalog-results]').getByText('Synthetic unavailable', { exact: true })).toBeVisible();
    expect(await page.locator('[data-course-card]').count()).toBe(0);
    workspace.get('/v1/courses', courses);
    await page.getByRole('button', { name: 'Повторить', exact: true }).click();
    await expect(page.getByRole('link', { name: courses[0].title, exact: true })).toBeVisible();
  });

  test('dark reduced-motion catalogue keeps visible cards and usable controls', async ({ page }, info) => {
    await page.setViewportSize({ width: 1270, height: 1000 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/courses');
    await expect(page.locator('[data-course-card]').first()).toBeVisible();
    await enableDarkWorkspace(page);
    expect(await page.locator('[data-course-card]').first().evaluate((element) => getComputedStyle(element).opacity)).toBe('1');
    await page.getByRole('searchbox', { name: 'Поиск', exact: true }).focus();
    await expect(page.getByRole('searchbox', { name: 'Поиск', exact: true })).toBeFocused();
    const colours = await settledControlColours(page.locator('[data-ui="button"][data-ui-variant="default"]').first());
    expect(contrast(colours.foreground, colours.background)).toBeGreaterThanOrEqual(4.5);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--background').trim())).toBe('222 40% 10%');
    await page.screenshot({ path: info.outputPath('catalogue-dark.png'), fullPage: false });
  });

  test('dark quiz navigation uses the matching semantic foreground', async ({ page, workspace }) => {
    workspace.role = 'student';
    workspace.learner();
    await page.goto(`/courses/quiz/${ids.quiz}?courseId=${ids.course}&lessonId=${ids.lesson}`);
    await expect(page.getByRole('heading', { name: quiz.title, exact: true })).toBeVisible();
    await enableDarkWorkspace(page);
    const colours = await settledControlColours(page.locator('button[aria-current="step"]'));
    expect(contrast(colours.foreground, colours.background)).toBeGreaterThanOrEqual(4.5);
  });

  test('archive/delete confirmation stays themed in a portal and Cancel does not write', async ({ page, workspace }) => {
    await page.goto('/courses');
    await expect(page.locator('[data-course-card]').first()).toBeVisible();
    await enableDarkWorkspace(page);
    const card = page.locator('[data-course-card]').filter({ has: page.getByRole('link', { name: courses[0].title, exact: true }) });
    await card.locator('summary').focus();
    await page.keyboard.press('Enter');
    await card.getByRole('button', { name: 'Архивировать', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(page.locator('html')).toHaveClass(/dark/);
    expect(await dialog.evaluate((element) => element.closest('[data-app-workspace]'))).toBeNull();
    expect(await dialog.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(await card.evaluate((element) => getComputedStyle(element).backgroundColor));
    await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
    await expect(dialog).toBeHidden();
    await card.locator('summary').press('Enter');
    const draft = page.locator('[data-course-card]').filter({ has: page.getByRole('link', { name: courses[3].title, exact: true }) });
    await draft.locator('summary').click();
    await draft.getByRole('button', { name: 'Удалить', exact: true }).click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
    expect(workspace.calls.filter((call) => call.method !== 'GET' && call.path !== '/v1/auth/refresh')).toEqual([]);
  });

  test('public certificate entry retains its original palette after leaving the workspace', async ({ page }) => {
    await page.goto('/courses');
    await expect(page.locator('[data-app-workspace]')).toBeVisible();
    await page.goto('/verify/certificate');
    await expect(page.locator('[data-app-workspace]')).toHaveCount(0);
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--background').trim())).toBe('36 33% 97%');
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(250, 248, 245)');
  });

  test('2x CSS magnification keeps the catalogue within the document viewport', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/courses');
    await expect(page.locator('[data-course-card]').first()).toBeVisible();
    await page.evaluate(() => { document.documentElement.style.zoom = '2'; });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.body.getBoundingClientRect().right - innerWidth)).toBeLessThanOrEqual(1);
    await checkCourseActionGeometry(page);
  });

  for (const lang of ['ru', 'kk', 'en'] as const) {
    test.describe(`mobile ${lang} labels`, () => {
      test.use({ visualLanguage: lang });
      test('keep controls and readable navigation inside the viewport', async ({ page }) => {
        const messages = { ru, kk, en }[lang];
        await page.setViewportSize({ width: 390, height: 1000 });
        await page.goto('/courses');
        await expect(page.getByRole('heading', { name: messages.courses.title, exact: true })).toBeVisible();
        await page.getByRole('button', { name: messages.sidebar.open, exact: true }).click();
        const headings = page.locator('[data-workspace-rail] nav h2');
        expect(await headings.count()).toBeGreaterThan(2);
        for (const heading of await headings.all()) expect(await heading.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(12);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      });
    });
  }

  for (const width of [1024, 768, 390]) {
    test(`impersonation banner and long tenant context fit at ${width}px`, async ({ page, workspace }) => {
      workspace.presentation = {
        tenantName: 'Синтетическая компания с длинным названием и региональными подразделениями',
        fullName: 'Синтетический методист с длинным именем для проверки интерфейса',
        impersonatedBy: 'synthetic-platform-operator',
      };
      await page.setViewportSize({ width, height: 1000 });
      await page.goto('/courses');
      await expect(page.locator('[data-course-card]').first()).toBeVisible();
      const bar = page.locator('[data-workspace-topbar]');
      const controls = bar.locator('button, select, a');
      for (const control of await controls.all()) {
        if (!await control.isVisible()) continue;
        const geometry = await control.evaluate((element) => {
          const rect = element.getBoundingClientRect();
          const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
          return { fits: rect.left >= 0 && rect.right <= innerWidth + 1 && element.scrollWidth <= element.clientWidth + 1, hit: hit === element || element.contains(hit) };
        });
        expect(geometry.fits).toBe(true);
        expect(geometry.hit).toBe(true);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      expect(workspace.calls.filter((call) => call.method !== 'GET' && call.path !== '/v1/auth/refresh')).toEqual([]);
    });
  }
}
