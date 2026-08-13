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
  useSearchParams: () => new URLSearchParams('courseId=course-1&employeeId=user-1'),
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
      if (!init?.method && url.endsWith('/v1/learning-cycles')) {
        return Promise.resolve(jsonResponse([]));
      }
      if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) {
        return Promise.resolve(jsonResponse([]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/learning-cycles')) {
        return Promise.resolve(jsonResponse({ id: 'rule-1', status: 'draft' }, 201));
      }
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([{ id: 'enrollment-1' }]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/users/user-1/invitation-link')) {
        return Promise.resolve(jsonResponse({
          email: 'aliya@example.kz',
          invite_url: 'https://app.kml.kz/accept-invite?token=test',
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

  it('shows recurring learning controls with independent occurrence semantics', async () => {
    render(<CourseAssignmentsPage />);

    expect(await screen.findByText('Повторное обучение')).toBeInTheDocument();
    expect(screen.getByText(/Каждый запуск создаёт отдельный период/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить черновик' })).toBeDisabled();
    expect(screen.getByText(/уже проходил этот курс/)).toBeInTheDocument();
  });

  it('saves only a recurring draft from the assignments page', async () => {
    render(<CourseAssignmentsPage />);

    fireEvent.change(await screen.findByRole('combobox', { name: 'Курс' }), {
      target: { value: 'course-1' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Обучающийся' }), {
      target: { value: 'user-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/learning-cycles'),
      expect.objectContaining({ method: 'POST' }),
    ));
    expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument();
  });

  it('renders overdue and completed-late occurrence reporting', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'a@example.kz', role: 'student' }, { id: 'user-2', first_name: 'Бек', last_name: 'Иманов', email: 'b@example.kz', role: 'student' }] }));
      if (url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([]));
      if (url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([
        { id: 'o1', rule_id: 'r1', scheduled_for: '2026-01-01T00:00:00Z', due_at: '2026-01-10T00:00:00Z', completed_at: null, status: 'overdue' },
        { id: 'o2', rule_id: 'r2', scheduled_for: '2026-01-01T00:00:00Z', due_at: '2026-01-10T00:00:00Z', completed_at: '2026-01-12T00:00:00Z', status: 'completed_late' },
      ]));
      if (url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([
        { id: 'r1', course_id: 'course-1', user_id: 'user-1', cadence_days: 180, due_days: 14, status: 'active', next_run_at: null, last_run_at: null },
        { id: 'r2', course_id: 'course-1', user_id: 'user-2', cadence_days: 180, due_days: 14, status: 'active', next_run_at: null, last_run_at: null },
      ]));
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<CourseAssignmentsPage />);
    expect(await screen.findByText(/Последний период: Просрочено/)).toBeInTheDocument();
    expect(await screen.findByText(/Последний период: Завершено с опозданием/)).toBeInTheDocument();
    expect(screen.getByText(/Завершено: 12/)).toBeInTheDocument();
  });

  it('keeps account activation separate from course assignment', async () => {
    render(<CourseAssignmentsPage />);

    const assignButton = await screen.findByRole('button', { name: 'Назначить (1)' });
    fireEvent.click(assignButton);

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Назначить обучение?',
        confirmLabel: 'Назначить',
      }),
    ));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/course-1/enrollments'),
      expect.objectContaining({ method: 'POST' }),
    ));
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/users/user-1/invitation-link'),
      expect.anything(),
    );
  });

  it('lets the methodologist explicitly choose a personal link and completion window', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student', has_login_access: true }] }));
      if (!init?.method && url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([]));
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/personal-link-enrollment')) return Promise.resolve(jsonResponse({
        enrollment_id: 'enrollment-1', user_id: 'user-1', access_url: 'https://app.kml.kz/access/opaque', temporary_pin: '123456', expires_at: '2026-08-20T00:00:00Z', completion_window_minutes: 30,
      }, 201));
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });

    render(<CourseAssignmentsPage />);
    expect(await screen.findByRole('checkbox')).toBeChecked();
    fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));
    fireEvent.change(screen.getByLabelText('Время на прохождение после первого входа, минут'), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Назначить (1)' }));

    await waitFor(() => {
      const assignmentCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input).endsWith('/v1/courses/course-1/personal-link-enrollment') && init?.method === 'POST'
      ));
      expect(assignmentCall).toBeDefined();
      expect(JSON.parse(String(assignmentCall?.[1]?.body))).toEqual(expect.objectContaining({
        user_id: 'user-1',
        completion_window_minutes: 30,
        due_at: null,
      }));
    });
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/enrollments/enrollment-1/access-link'),
      expect.anything(),
    );
    expect(await screen.findByText('PIN: 123456')).toBeInTheDocument();
  });

  it('requires personal-link credentials to be issued one learner at a time', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [
        { id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: null, role: 'student' },
        { id: 'user-2', first_name: 'Бек', last_name: 'Иманов', email: null, role: 'student' },
      ] }));
      if (url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([]));
      if (url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      if (url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<CourseAssignmentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Очистить' }));
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Бек Иманов' }));
    fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));

    expect(screen.getByRole('button', { name: 'Назначить (2)' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('выберите одного сотрудника');
  });

  it('retrieves access from the persistent assignment action after reload', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student' }] }));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'enrolled', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z' }]));
      if (!init?.method && url.endsWith('/v1/courses/enrollments/enrollment-1/access')) return Promise.resolve(jsonResponse({ enrollment_id: 'enrollment-1', user_id: 'user-1', access_kind: 'account_activation', state: 'available', access_url: 'https://app.kml.kz/accept-invite?token=test', message: 'ready' }));
      throw new Error(`Unexpected request: ${url}`);
    });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    render(<CourseAssignmentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Получить ссылку' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://app.kml.kz/accept-invite?token=test'));
  });

  it('shows durable notification failure and exposes explicit resend', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student' }] }));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'enrolled', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z', notification_status: 'dead', notification_error: 'provider_rejected' }]));
      if (init?.method === 'POST' && url.endsWith('/v1/courses/enrollments/enrollment-1/notification/resend')) return Promise.resolve(jsonResponse({ enrollment_id: 'enrollment-1', notification_id: 'notification-1', status: 'pending' }));
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });
    render(<CourseAssignmentsPage />);
    expect(await screen.findByText('Не доставлено')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Отправить повторно' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/notification/resend'),
      expect.objectContaining({ method: 'POST' }),
    ));
  });
});
