import { expect } from '@playwright/test';
import { appOrigin, course, ids, lessons, structure, test } from './learning-workspace-ux-fixtures';

test.use({ baseURL: appOrigin, serviceWorkers: 'block' });

test('expired editor reads recover once without replacing the author or losing the editor', async ({ page, workspace }, info) => {
  workspace.author();
  let firstReads = 0;
  let release!: () => void;
  const bothStarted = new Promise<void>((resolve) => { release = resolve; });
  for (const [path, data] of [
    [`/v1/courses/${ids.course}`, { ...course, status: 'draft', ai_generated: true }],
    [`/v1/courses/${ids.course}/structure`, structure],
  ] as const) {
    let requests = 0;
    workspace.onGet(path, async () => {
      if (++requests !== 1) return { json: data };
      if (++firstReads === 2) release();
      await bothStarted;
      return { status: 401, json: { detail: 'Synthetic expired access token' } };
    });
  }
  await page.goto(`/courses/${ids.course}/edit?lessonId=${ids.lesson}`);
  const content = page.getByRole('textbox', { name: 'Lesson content', exact: true });
  await expect(content).toHaveValue(lessons[0].content);
  await content.fill('Unsaved text survives ordinary token refresh');
  await expect(content).toHaveValue('Unsaved text survives ordinary token refresh');
  await expect(page.getByText('Synthetic Author', { exact: true })).toBeVisible();
  expect(workspace.matching('POST', '/v1/auth/refresh')).toHaveLength(2); // startup + shared 401 recovery
  expect(workspace.matching('GET', `/v1/courses/${ids.course}`)).toHaveLength(2);
  expect(workspace.matching('GET', `/v1/courses/${ids.course}/structure`)).toHaveLength(2);
  expect(workspace.calls.filter((call) => call.method !== 'GET' && call.path !== '/v1/auth/refresh')).toHaveLength(0);
  await page.screenshot({ path: info.outputPath('editor-recovered-with-unsaved-text.png') });
});

test('expired impersonation does not use the platform refresh cookie or replace the author', async ({ page, workspace }) => {
  workspace.author();
  workspace.presentation = { impersonatedBy: ids.author };
  for (const path of [`/v1/courses/${ids.course}`, `/v1/courses/${ids.course}/structure`]) {
    workspace.onGet(path, () => ({ status: 401, json: { detail: 'Synthetic expired impersonation' } }));
  }
  await page.goto(`/courses/${ids.course}/edit`);
  await expect(page.getByRole('alert').filter({ hasText: 'Could not load the workspace' })).toBeVisible();
  await expect(page.getByText('Synthetic Author', { exact: true })).toBeVisible();
  expect(workspace.matching('POST', '/v1/auth/refresh')).toHaveLength(1); // startup only
  expect(workspace.matching('GET', `/v1/courses/${ids.course}`)).toHaveLength(1);
  expect(workspace.matching('GET', `/v1/courses/${ids.course}/structure`)).toHaveLength(1);
});
