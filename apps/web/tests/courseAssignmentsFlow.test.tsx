import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const fetchMock = vi.hoisted(() => vi.fn());
const confirmMock = vi.hoisted(() => vi.fn().mockResolvedValue(true));
const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  info: vi.fn(),
  success: vi.fn(),
}));

vi.stubGlobal('fetch', fetchMock);
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('course_id=course-1&user_id=user-1'),
}));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: any) => unknown) => selector({
    accessToken: 'test-token',
    user: { role: 'methodologist' },
  }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'common.loading': 'Загрузка',
      'common.saveFailed': 'Не удалось сохранить',
      'courses.title': 'Курсы',
      'courses.enrollments': 'Назначения',
      'courses.selectCourseCount': 'Выберите курс',
      'users.name': 'Имя',
      'courses.status': 'Статус',
    }[key] ?? key),
    tp: (_key: string, count: number) => `${count} обучающихся`,
  }),
}));
vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: confirmMock, dialog: null }),
}));
vi.mock('@/components/ui/Toast', () => ({ toast: toastMock }));

import CourseAssignmentsPage from '@/features/course-assignments/CourseAssignmentsPage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('contextual course assignment flow', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    confirmMock.mockClear();
    toastMock.error.mockClear();
    toastMock.info.mockClear();
    toastMock.success.mockClear();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) {
        return Promise.resolve(jsonResponse([
          { id: 'course-1', title: 'Охрана труда', status: 'published' },
          { id: 'course-draft', title: 'Черновик', status: 'draft' },
        ]));
      }
      if (!init?.method && url.includes('/v1/users?')) {
        return Promise.resolve(jsonResponse({
          users: [{
            id: 'user-1',
            first_name: 'Алия',
            last_name: 'Садыкова',
            email: 'aliya@example.kz',
            role: 'student',
            personnel_number: 'EMP-001',
            has_login_access: false,
          }],
        }));
      }
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([{ id: 'enrollment-1' }]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/users/invitations/bulk')) {
        return Promise.resolve(jsonResponse({
          created: [{
            email: 'aliya@example.kz',
            invite_url: 'https://app.kml.kz/accept-invite?token=test',
          }],
          skipped_existing: [],
          invalid: [],
        }));
      }
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });
  });

  it('preselects the course and employee from contextual query parameters', async () => {
    render(<CourseAssignmentsPage />);

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Курс для назначения' })).toHaveValue('course-1');
    });
    expect(screen.getByRole('checkbox')).toBeChecked();
    expect(screen.queryByRole('option', { name: 'Черновик' })).not.toBeInTheDocument();
    expect(screen.getByText('После назначения будет создана ссылка доступа')).toBeInTheDocument();
  });

  it('confirms the assignment and creates an access link for a learner without login', async () => {
    render(<CourseAssignmentsPage />);

    const assignButton = await screen.findByRole('button', { name: 'Назначить (1)' });
    fireEvent.click(assignButton);

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Назначить обучение?',
        confirmLabel: 'Назначить',
      }),
    ));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/v1/users/invitations/bulk'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
    expect(await screen.findByText('Ссылки доступа для новых обучающихся')).toBeInTheDocument();
    expect(screen.getByText('aliya@example.kz')).toBeInTheDocument();
  });
});
