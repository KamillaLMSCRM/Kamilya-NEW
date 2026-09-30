import { expect, test } from '@playwright/test';

// Synthetic browser acceptance only: run a dedicated loopback Next server on
// 3014 and set PLAYWRIGHT_SKIP_WEBSERVER=1. No customer API/credentials are used.
test.use({ baseURL: 'http://127.0.0.1:3014' });

const courseId = '10000000-0000-4000-8000-000000000001';
const lessonId = '10000000-0000-4000-8000-000000000002';
const enrollmentId = '10000000-0000-4000-8000-000000000003';
const learner = {
  user_id: '10000000-0000-4000-8000-000000000004',
  tenant_id: '10000000-0000-4000-8000-000000000005',
  role: 'student', roles: ['student'], first_name: 'Тест', last_name: 'Обучающийся',
  email: 'synthetic@example.invalid', tenant: { id: 'tenant-synthetic', name: 'Synthetic QA' },
};
const assignment = {
  enrollment_id: enrollmentId, course_id: courseId, title: 'Охрана труда: следующий шаг',
  description: '', status: 'published', enrollment_status: 'in_progress', delivery_type: 'native',
  progress_percent: 100, total_lessons: 2, completed_lessons: 2, enrolled_at: '2026-09-01T00:00:00Z',
  thumbnail_url: null, assignment_due_at: '2026-09-20T12:00:00Z', assignment_source: 'manual',
  can_resume: true, resume_href: `/courses/${courseId}?lessonId=${lessonId}`,
};

for (const width of [1440, 390]) {
  test(`learner recommendation and safe continuation at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const unexpectedMutations: string[] = [];
    const externalRequests: string[] = [];
    await page.route('**/*', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname.includes('/v1/')) {
        const path = url.pathname.slice(url.pathname.indexOf('/v1/'));
        let body: unknown;
        if (path === '/v1/auth/refresh') {
          body = { access_token: 'synthetic-qa-token', user: learner };
        } else {
          if (!['GET', 'OPTIONS'].includes(request.method())) unexpectedMutations.push(path);
          if (path === '/v1/users/me') body = learner;
          else if (path === '/v1/student/dashboard') body = {
            user_id: learner.user_id, full_name: 'Тест Обучающийся',
            enrolled_courses: [assignment, {
              ...assignment, enrollment_id: '10000000-0000-4000-8000-000000000006',
              title: 'Другое назначение того же курса', can_resume: false, resume_href: null,
            }], total_courses: 2, completed_courses: 0, total_progress_percent: 100, certificates_count: 0,
          };
          else body = [];
        }
        await route.fulfill({ status: 200, json: body, headers: {
          'access-control-allow-origin': 'http://127.0.0.1:3014',
          'access-control-allow-credentials': 'true',
          'access-control-allow-methods': 'GET, POST, OPTIONS',
          'access-control-allow-headers': 'authorization, content-type',
        } });
      } else if (url.origin === 'http://127.0.0.1:3014') {
        await route.continue();
      } else {
        externalRequests.push(url.origin);
        await route.abort();
      }
    });
    await page.goto('/student');
    await expect(page.getByRole('heading', { name: assignment.title }).first()).toBeVisible();
    await expect(page.getByText('Основание назначения: Назначено вручную').first()).toBeVisible();
    await expect(page.getByText(/Срок:.*20/).first()).toBeVisible();
    const continuation = page.locator(`a[href="${assignment.resume_href}"]`).first();
    await expect(continuation).toBeVisible();
    await expect(page.getByText('Другое назначение того же курса')).toBeVisible();
    await expect(page.getByText('Уроки пройдены. Завершите оставшиеся шаги в курсе.')).toBeVisible();
    await expect(page.getByText('Продолжение этого назначения пока недоступно. Обратитесь к методисту, чтобы согласовать способ продолжения.')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`learner-${width}.png`), fullPage: true });
    expect(unexpectedMutations).toEqual([]);
    expect(externalRequests).toEqual([]);
  });
}
