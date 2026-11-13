import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const fetchMock = vi.hoisted(() => vi.fn());
const queryState = vi.hoisted(() => ({ value: 'courseId=course-1&employeeId=user-1' }));
const confirmMock = vi.hoisted(() => vi.fn().mockResolvedValue(true));
const assignmentAuth = vi.hoisted(() => ({ accessToken: 'test-token', sessionEpoch: 0, user: { role: 'methodologist', user_id: 'actor-1', tenant_id: 'tenant-1' } }));
const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  info: vi.fn(),
  success: vi.fn(),
}));

vi.stubGlobal('fetch', fetchMock);
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(queryState.value),
}));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: any) => unknown) => selector(assignmentAuth),
}));
vi.mock('@/i18n/useT', async () => {
  const { default: ru } = await import('@/i18n/locales/ru.json');
  const translate = (key: string, params?: Record<string, string | number>) => {
    const value = key.split('.').reduce<unknown>((current, part) => (
      current && typeof current === 'object' && part in current
        ? (current as Record<string, unknown>)[part]
        : undefined
    ), ru);
    if (typeof value !== 'string') return key;
    return value.replace(/\{(\w+)\}/g, (_, name: string) => String(params?.[name] ?? `{${name}}`));
  };
  return {
    useT: () => ({
      t: translate,
      tp: (_key: string, count: number) => `${count} обучающихся`,
    }),
  };
});
vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: confirmMock, dialog: null }),
}));
vi.mock('@/components/ui/Toast', () => ({ toast: toastMock }));

import CourseAssignmentsPage from '@/features/course-assignments/CourseAssignmentsPage';
import { getAuthSessionEpoch, setAuth } from '@/lib/auth';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function openManagementMode() {
  const button = await screen.findByRole('button', { name: 'Текущие назначения' });
  fireEvent.click(button);
  await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'true'));
}

describe('contextual course assignment flow', () => {
  beforeEach(() => {
    assignmentAuth.accessToken = 'test-token';
    assignmentAuth.sessionEpoch = getAuthSessionEpoch();
    assignmentAuth.user = { role: 'methodologist', user_id: 'actor-1', tenant_id: 'tenant-1' };
    queryState.value = 'courseId=course-1&employeeId=user-1';
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

  it('distinguishes an unassigned published course from an empty course catalogue', async () => {
    render(<CourseAssignmentsPage />);
    await screen.findByRole('heading', { name: 'Обучающиеся' });
    expect(screen.getByTestId('selected-assignment-course')).toHaveTextContent('Охрана труда');
    expect(screen.queryByText('Курсов пока нет')).not.toBeInTheDocument();
  });

  it('preselects the course and employee from contextual query parameters', async () => {
    render(<CourseAssignmentsPage />);

    const courseSelect = await screen.findByRole('combobox', { name: 'Курс для назначения' });
    await waitFor(() => {
      expect(courseSelect).toHaveValue('course-1');
      expect(screen.getByRole('checkbox')).toBeChecked();
    });
    expect(screen.queryByRole('option', { name: 'Черновик' })).not.toBeInTheDocument();
    expect(screen.getByText('После назначения будет создана ссылка доступа')).toBeInTheDocument();
  });

  it('opens the selected-course recipient composer before existing assignments', async () => {
    queryState.value = 'course_id=course-1';
    render(<CourseAssignmentsPage />);
    expect(await screen.findByRole('heading', { name: 'Обучающиеся' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Назначения обучения' })).not.toBeInTheDocument();
    await openManagementMode();
    expect(await screen.findByRole('heading', { name: 'Назначения обучения' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Обучающиеся' })).not.toBeInTheDocument();
  });

  it('keeps recipient selection before delivery settings in the composer DOM order', async () => {
    queryState.value = 'course_id=course-1';
    render(<CourseAssignmentsPage />);
    const heading = await screen.findByRole('heading', { name: 'Обучающиеся' });
    const composer = heading.closest('[data-workspace-panel]') as HTMLElement;
    const recipientSearch = within(composer).getByPlaceholderText('Найти обучающегося по имени, email или табельному…');
    const delivery = within(composer).getByRole('group', { name: 'Как сотрудник получит доступ' });

    expect(recipientSearch.compareDocumentPosition(delivery) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(composer).getByTestId('assignment-selection-empty')).toHaveTextContent('Выбрано сотрудников: 0');
  });

  it('does not silently replace an invalid or unpublished deep-linked course', async () => {
    queryState.value = 'courseId=course-draft';
    render(<CourseAssignmentsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Этот курс недоступен или не опубликован. Выберите другой курс.');
    expect(screen.getByRole('combobox', { name: 'Курс для назначения' })).toHaveValue('');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('opens enrollment deep links in management mode while user links open the composer', async () => {
    queryState.value = 'courseId=course-1&enrollment_id=11111111-1111-4111-8111-111111111111';
    render(<CourseAssignmentsPage />);
    expect(await screen.findByRole('heading', { name: 'Назначения обучения' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Обучающиеся' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Текущие назначения' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps a manual selection when the same session refreshes its access token', async () => {
    queryState.value = 'courseId=course-1';
    const view = render(<CourseAssignmentsPage />);
    const checkbox = await screen.findByRole('checkbox');
    await waitFor(() => expect(checkbox).toBeEnabled());
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    assignmentAuth.accessToken = 'refreshed-token';
    view.rerender(<CourseAssignmentsPage />);
    await waitFor(() => expect(screen.getByRole('checkbox')).toBeChecked());
  });

  it('clears a manual selection when the actor or tenant changes', async () => {
    queryState.value = 'courseId=course-1';
    const view = render(<CourseAssignmentsPage />);
    const checkbox = await screen.findByRole('checkbox');
    await waitFor(() => expect(checkbox).toBeEnabled());
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    assignmentAuth.user = { role: 'methodologist', user_id: 'actor-2', tenant_id: 'tenant-2' };
    view.rerender(<CourseAssignmentsPage />);
    await waitFor(() => expect(screen.getByRole('checkbox')).not.toBeChecked());
  });

  it('does not replace refreshed course data with a delayed response from the old token', async () => {
    queryState.value = '';
    const fallback = fetchMock.getMockImplementation()!;
    let resolveOld!: (value: Response) => void;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (!init?.method && String(input).includes('/v1/courses?')) {
        const authorization = (init?.headers as Record<string, string> | undefined)?.Authorization;
        if (authorization === 'Bearer test-token') return new Promise((resolve) => { resolveOld = resolve; });
        return Promise.resolve(jsonResponse([{ id: 'new-course', title: 'Новый список', status: 'published' }]));
      }
      return fallback(input, init);
    });
    const view = render(<CourseAssignmentsPage />);
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
    assignmentAuth.accessToken = 'refreshed-token';
    view.rerender(<CourseAssignmentsPage />);
    expect(await screen.findAllByRole('option', { name: 'Новый список' })).not.toHaveLength(0);
    await act(async () => resolveOld(jsonResponse([{ id: 'stale', title: 'Устаревший список', status: 'published' }])));
    expect(screen.queryByRole('option', { name: 'Устаревший список' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('option', { name: 'Новый список' })).not.toHaveLength(0);
  });

  it('reloads enrollment state on token refresh and ignores the old delayed response', async () => {
    queryState.value = 'courseId=course-1';
    const fallback = fetchMock.getMockImplementation()!;
    let resolveOld!: (value: Response) => void;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (!init?.method && String(input).endsWith('/v1/courses/course-1/enrollments')) {
        const authorization = (init?.headers as Record<string, string> | undefined)?.Authorization;
        if (authorization === 'Bearer test-token') return new Promise((resolve) => { resolveOld = resolve; });
        return Promise.resolve(jsonResponse([]));
      }
      return fallback(input, init);
    });
    const view = render(<CourseAssignmentsPage />);
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
    assignmentAuth.accessToken = 'refreshed-token';
    view.rerender(<CourseAssignmentsPage />);
    expect(await screen.findByRole('checkbox', { name: 'Алия Садыкова' })).toBeInTheDocument();
    await act(async () => resolveOld(jsonResponse([{ id: 'stale', user_id: 'user-1', course_id: 'course-1', status: 'enrolled', source: 'manual' }])));
    expect(screen.getByRole('checkbox', { name: 'Алия Садыкова' })).toBeInTheDocument();
  });

  it('keeps the mobile assignment cards and selectors shrinkable while the enrollment table owns horizontal scrolling', async () => {
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (!init?.method && String(input).endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([{
          id: 'enrollment-1',
          user_id: 'user-1',
          course_id: 'course-1',
          status: 'enrolled',
          source: 'manual',
          enrolled_at: '2026-09-01T00:00:00Z',
        }]));
      }
      return fallback(input, init);
    });

    render(<CourseAssignmentsPage />);

    const courseSelect = await screen.findByRole('combobox', { name: 'Курс для назначения' });
    await openManagementMode();
    const assignmentGrid = courseSelect.closest('.grid');
    expect(assignmentGrid).toHaveClass('min-w-0', 'grid-cols-[minmax(0,1fr)]');
    expect(assignmentGrid?.children[0]).toHaveClass('min-w-0');
    expect(assignmentGrid?.children[1]).toHaveClass('min-w-0');
    expect(courseSelect).toHaveClass('w-full', 'min-w-0', 'max-w-full');
    fireEvent.click(await screen.findByRole('button', { name: /Полная таблица|Full table/ }));
    await waitFor(() => expect(screen.getAllByText('Алия Садыкова')).toHaveLength(2));

    // The staff card may render before the separate enrollment request settles.
    // Wait for the actual table rather than inferring readiness from staff names.
    const table = await screen.findByRole('table');
    expect(table?.parentElement).toHaveClass('overflow-x-auto', 'min-w-0', 'max-w-full');

    const recurringSelects = document.querySelectorAll('label select');
    expect(recurringSelects).toHaveLength(2);
    for (const select of recurringSelects) {
      expect(select).toHaveClass('w-full', 'min-w-0', 'max-w-full');
      expect(select.closest('label')).toHaveClass('min-w-0', 'max-w-full');
    }
  });

  it('focuses the exact linked enrollment without executing a command and can show all', async () => {
    const target = '10000000-0000-4000-8000-000000000001';
    queryState.value = `course_id=course-1&enrollment_id=${target}`;
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (!init?.method && String(input).endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([
          { id: target, user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual' },
          { id: '10000000-0000-4000-8000-000000000002', user_id: 'user-1', course_id: 'course-1', status: 'enrolled', source: 'manual' },
        ]));
      }
      return fallback(input, init);
    });
    render(<CourseAssignmentsPage />);
    expect(await screen.findByText('Показано выбранное назначение. Операции запускаются отдельно от плана.')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Назначить повторно' })).toHaveLength(1));
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Показать все назначения' }));
    const rows = screen.getAllByRole('button', { pressed: false }).filter((button) => button.hasAttribute('aria-controls'));
    expect(rows).toHaveLength(1);
    fireEvent.click(rows[0]);
    expect(rows[0]).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Назначить повторно' })).toBeInTheDocument();
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it('requires a reason to repeat a manual assignment and refreshes the assignment list', async () => {
    let enrollmentReads = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student' }] }));
      if (!init?.method && url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) {
        enrollmentReads += 1;
        return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z' }]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/reassignments')) return Promise.resolve(jsonResponse({ previous_enrollment: { id: 'enrollment-1' }, new_enrollment: { id: 'enrollment-2' } }, 201));
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });

    render(<CourseAssignmentsPage />);
    await openManagementMode();
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить повторно' }));
    const submit = screen.getByRole('button', { name: 'Создать повторное назначение' });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Причина повторного назначения (обязательно)'), { target: { value: 'Annual recertification' } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/course-1/reassignments'),
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ user_id: 'user-1', previous_enrollment_id: 'enrollment-1', reason: 'Annual recertification' }) }),
    ));
    await waitFor(() => expect(enrollmentReads).toBeGreaterThanOrEqual(2));
    expect(toastMock.success).toHaveBeenCalledWith('Новое назначение создано; прежняя история сохранена.');
  });

  it('does not revive a late reassignment after switching A to B and back to A', async () => {
    const fallback = fetchMock.getMockImplementation()!;
    let resolveRepeat!: (value: Response) => void;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([
        { id: 'course-1', title: 'Первый', status: 'published' }, { id: 'course-2', title: 'Второй', status: 'published' },
      ]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([
        { id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual' },
      ]));
      if (!init?.method && url.endsWith('/v1/courses/course-2/enrollments')) return Promise.resolve(jsonResponse([]));
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/reassignments')) return new Promise((resolve) => { resolveRepeat = resolve; });
      return fallback(input, init);
    });
    render(<CourseAssignmentsPage />);
    await openManagementMode();
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить повторно' }));
    fireEvent.change(screen.getByLabelText('Причина повторного назначения (обязательно)'), { target: { value: 'Повторное обучение' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать повторное назначение' }));
    await waitFor(() => expect(resolveRepeat).toBeTypeOf('function'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Курс для назначения' }), { target: { value: 'course-2' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Курс для назначения' }), { target: { value: 'course-1' } });
    await act(async () => resolveRepeat(jsonResponse({ delivery_mode: 'personal_link', personal_access: {
      enrollment_id: 'new-enrollment', access_url: 'https://example.invalid/secret', temporary_pin: '123456',
    } }, 201)));
    expect(screen.getByRole('combobox', { name: 'Курс для назначения' })).toHaveValue('course-1');
    expect(screen.queryByText('PIN: 123456')).not.toBeInTheDocument();
  });

  it('clears an already issued personal link and PIN when the course changes', async () => {
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([
        { id: 'course-1', title: 'Первый', status: 'published' }, { id: 'course-2', title: 'Второй', status: 'published' },
      ]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([
        { id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual' },
      ]));
      if (!init?.method && url.endsWith('/v1/courses/course-2/enrollments')) return Promise.resolve(jsonResponse([]));
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/reassignments')) return Promise.resolve(jsonResponse({
        delivery_mode: 'personal_link', personal_access: { enrollment_id: 'new-enrollment', access_url: 'https://example.invalid/secret', temporary_pin: '123456' },
      }, 201));
      return fallback(input, init);
    });
    render(<CourseAssignmentsPage />);
    await openManagementMode();
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить повторно' }));
    fireEvent.change(screen.getByLabelText('Причина повторного назначения (обязательно)'), { target: { value: 'Повторное обучение' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать повторное назначение' }));
    expect(await screen.findByText('PIN: 123456')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Курс для назначения' }), { target: { value: 'course-2' } });
    expect(screen.queryByText('PIN: 123456')).not.toBeInTheDocument();
  });

  it('shows the API reason when a repeated assignment cannot be created', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student' }] }));
      if (!init?.method && url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z' }]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/reassignments')) {
        return Promise.resolve(jsonResponse({ error: 'conflict', message: 'Extend the historical access policy first' }, 409));
      }
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });

    render(<CourseAssignmentsPage />);
    await openManagementMode();
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить повторно' }));
    fireEvent.change(screen.getByLabelText('Причина повторного назначения (обязательно)'), { target: { value: 'Repeat diagnostics' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать повторное назначение' }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith(
      'Не удалось создать повторное назначение',
      { description: 'Extend the historical access policy first' },
    ));
  });

  it('reveals the fresh protected link and PIN returned for a repeated personal-link assignment', async () => {
    let repeatCalls = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student' }] }));
      if (!init?.method && url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) {
        return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z' }]));
      }
      if (init?.method === 'POST' && url.endsWith('/v1/courses/course-1/reassignments')) {
        repeatCalls += 1;
        if (repeatCalls > 1) {
          return Promise.resolve(jsonResponse({ delivery_mode: 'email', personal_access: null }, 201));
        }
        return Promise.resolve(jsonResponse({
          delivery_mode: 'personal_link',
          personal_access: {
            enrollment_id: 'enrollment-2',
            access_url: 'https://app.kml.kz/access/fresh-repeat-token',
            temporary_pin: '482913',
            expires_at: '2026-10-01T00:00:00Z',
            link_expires_at: '2026-10-01T00:00:00Z',
            completion_window_minutes: 120,
          },
        }, 201));
      }
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });

    render(<CourseAssignmentsPage />);
    await openManagementMode();
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить повторно' }));
    fireEvent.change(screen.getByLabelText('Причина повторного назначения (обязательно)'), { target: { value: 'Repeat protected access' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать повторное назначение' }));

    const accessCard = (await screen.findByRole('heading', { name: 'Персональный доступ сотрудника' })).parentElement;
    expect(accessCard).not.toBeNull();
    expect(within(accessCard!).getByText('https://app.kml.kz/access/fresh-repeat-token')).toBeInTheDocument();
    expect(within(accessCard!).getByText('PIN: 482913')).toBeInTheDocument();
    expect(within(accessCard!).getByText(/Алия Садыкова/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Назначить повторно' }));
    fireEvent.change(screen.getByLabelText('Причина повторного назначения (обязательно)'), { target: { value: 'Repeat by email' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать повторное назначение' }));
    await waitFor(() => expect(repeatCalls).toBe(2));
    await waitFor(() => expect(screen.queryByText('https://app.kml.kz/access/fresh-repeat-token')).not.toBeInTheDocument());
  });

  it('shows recurring learning controls with independent occurrence semantics', async () => {
    render(<CourseAssignmentsPage />);
    await openManagementMode();

    expect(await screen.findByText('Повторное обучение')).toBeInTheDocument();
    expect(screen.getByText(/У каждого повторного назначения свой срок и результат/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить черновик' })).toBeDisabled();
    expect(screen.getByText(/уже проходил этот курс/)).toBeInTheDocument();
  });

  it('saves only a recurring draft from the assignments page', async () => {
    render(<CourseAssignmentsPage />);
    await openManagementMode();

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

  it('does not reload recurring rules with an old token after a delayed save', async () => {
    const fallback = fetchMock.getMockImplementation()!;
    let resolveSave!: (value: Response) => void;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST' && String(input).endsWith('/v1/learning-cycles')) return new Promise((resolve) => { resolveSave = resolve; });
      return fallback(input, init);
    });
    const view = render(<CourseAssignmentsPage />);
    await openManagementMode();
    fireEvent.change(await screen.findByRole('combobox', { name: 'Курс' }), { target: { value: 'course-1' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Обучающийся' }), { target: { value: 'user-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    await waitFor(() => expect(resolveSave).toBeTypeOf('function'));
    assignmentAuth.accessToken = 'refreshed-token';
    view.rerender(<CourseAssignmentsPage />);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/v1/learning-cycles')
      && !init?.method && (init?.headers as Record<string, string>)?.Authorization === 'Bearer refreshed-token')).toBe(true));
    const oldReads = () => fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/v1/learning-cycles')
      && !init?.method && (init?.headers as Record<string, string>)?.Authorization === 'Bearer test-token').length;
    const before = oldReads();
    await act(async () => resolveSave(jsonResponse({ id: 'rule-1', status: 'draft' }, 201)));
    expect(oldReads()).toBe(before);
    expect(toastMock.success).not.toHaveBeenCalled();
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
    await openManagementMode();
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

  it('does not assign after the delivery selection changes during confirmation', async () => {
    let resolve!: (value: boolean) => void;
    confirmMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    render(<CourseAssignmentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить (1)' }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));
    await act(async () => resolve(true));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
    expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining('изменился'));
  });

  it('does not revive a confirmation after a learner is deselected and reselected', async () => {
    let resolve!: (value: boolean) => void;
    confirmMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    render(<CourseAssignmentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить (1)' }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    const learner = screen.getByRole('checkbox', { name: 'Алия Садыкова' });
    fireEvent.click(learner);
    fireEvent.click(learner);
    await act(async () => resolve(true));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  });

  it('requires fresh confirmation when the access token rotates during confirmation', async () => {
    let resolve!: (value: boolean) => void;
    confirmMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const view = render(<CourseAssignmentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Назначить (1)' }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    assignmentAuth.accessToken = 'refreshed-token';
    view.rerender(<CourseAssignmentsPage />);
    await act(async () => resolve(true));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
    expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining('изменился'));
  });

  it('opens only one confirmation for repeated assignment clicks', async () => {
    let resolve!: (value: boolean) => void;
    confirmMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    render(<CourseAssignmentsPage />);
    const button = await screen.findByRole('button', { name: 'Назначить (1)' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(confirmMock).toHaveBeenCalledTimes(1);
    await act(async () => resolve(false));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  });

  it.each(['email', 'personal_link'] as const)('does not restore course A after its delayed %s assignment completes', async (delivery) => {
    let resolve!: (value: Response) => void;
    const baseline = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([
        { id: 'course-1', title: 'Охрана труда', status: 'published' }, { id: 'course-2', title: 'Другой курс', status: 'published' },
      ]));
      if (!init?.method && url.endsWith('/v1/courses/course-2/enrollments')) return Promise.resolve(jsonResponse([]));
      if (init?.method === 'POST') return new Promise((done) => { resolve = done; });
      return baseline(input, init);
    });
    render(<CourseAssignmentsPage />);
    const assign = await screen.findByRole('button', { name: 'Назначить (1)' });
    if (delivery === 'personal_link') fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));
    fireEvent.click(assign);
    await waitFor(() => expect(resolve).toBeTypeOf('function'));
    const picker = screen.getByRole('combobox', { name: 'Курс для назначения' });
    fireEvent.change(picker, { target: { value: 'course-2' } });
    await screen.findByRole('checkbox', { name: 'Алия Садыкова' });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Алия Садыкова' }));
    await act(async () => resolve(jsonResponse(delivery === 'email' ? [{ id: 'new' }] : { access_url: 'https://example.invalid/old', temporary_pin: '123456' })));
    expect(picker).toHaveValue('course-2');
    expect(screen.getByRole('checkbox', { name: 'Алия Садыкова' })).toBeChecked();
    expect(screen.queryByText('https://example.invalid/old')).not.toBeInTheDocument();
  });

  it.each(['pending', 'failed'] as const)('does not call unknown enrollment data empty or fully assigned (%s)', async (state) => {
    queryState.value = 'courseId=course-1&employeeId=user-1';
    const baseline = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (!init?.method && String(input).endsWith('/v1/courses/course-1/enrollments')) return state === 'pending'
        ? new Promise(() => {}) : Promise.resolve(jsonResponse({}, 503));
      return baseline(input, init);
    });
    render(<CourseAssignmentsPage />);
    await screen.findByRole('button', { name: 'Назначить (1)' });
    if (state === 'failed') await screen.findByRole('alert');
    expect(screen.queryByText('На этот курс пока никто не записан')).not.toBeInTheDocument();
    expect(screen.queryByText('Все обучающиеся уже назначены на этот курс')).not.toBeInTheDocument();
    expect(await screen.findByText('Доступность получателей уточняется после загрузки назначений.')).toBeInTheDocument();
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
    fireEvent.click(screen.getByText('Дополнительные настройки сроков'));
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
    await openManagementMode();
    fireEvent.click(await screen.findByRole('button', { name: 'Получить ссылку' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://app.kml.kz/accept-invite?token=test'));
  });

  it('revokes an active personal link without deleting the assignment', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: null, role: 'student' }] }));
      if (!init?.method && url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z' }]));
      if (!init?.method && url.endsWith('/v1/courses/enrollments/enrollment-1/access')) return Promise.resolve(jsonResponse({ enrollment_id: 'enrollment-1', user_id: 'user-1', access_kind: 'personal_link', state: 'available', access_url: null, expires_at: '2026-09-07T06:30:21Z', message: 'ready' }));
      if (init?.method === 'POST' && url.endsWith('/v1/courses/enrollments/enrollment-1/access-policy/revoke')) return Promise.resolve(jsonResponse({ enrollment_id: 'enrollment-1', delivery_mode: 'personal_link', state: 'revoked' }));
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });

    render(<CourseAssignmentsPage />);
    await openManagementMode();

    fireEvent.click(await screen.findByRole('button', { name: 'Отозвать доступ' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/enrollments/enrollment-1/access-policy/revoke'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ reason: 'revoked_from_assignments_ui' }),
      }),
    ));
    expect(toastMock.success).toHaveBeenCalledWith('Персональный доступ отозван');
    expect(screen.queryByRole('button', { name: 'Перевыпустить доступ' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Создать доступ' })).not.toBeInTheDocument();
    expect(screen.getByText('Доступ отозван')).toBeInTheDocument();
  });

  it('does not revoke access after the actor changes while confirmation is open', async () => {
    const fallback = fetchMock.getMockImplementation()!;
    let resolve!: (value: boolean) => void;
    confirmMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: null, role: 'student' }] }));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'completed', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z' }]));
      if (!init?.method && url.endsWith('/v1/courses/enrollments/enrollment-1/access')) return Promise.resolve(jsonResponse({ enrollment_id: 'enrollment-1', user_id: 'user-1', access_kind: 'personal_link', state: 'available', access_url: null, message: 'ready' }));
      return fallback(input, init);
    });
    const view = render(<CourseAssignmentsPage />);
    await openManagementMode();
    fireEvent.click(await screen.findByRole('button', { name: 'Отозвать доступ' }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    assignmentAuth.user = { role: 'methodologist', user_id: 'actor-2', tenant_id: 'tenant-2' };
    view.rerender(<CourseAssignmentsPage />);
    await act(async () => resolve(true));
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).includes('/access-policy/revoke') && init?.method === 'POST')).toHaveLength(0);
  });

  it('keeps enrollment controls aligned and discloses personal-link deadlines on demand', async () => {
    queryState.value = 'courseId=course-1&employeeId=user-1';
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student' }] }));
      if (url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([{ id: 'enrollment-1', user_id: 'user-1', course_id: 'course-1', status: 'enrolled', source: 'manual', enrolled_at: '2026-01-01T00:00:00Z' }]));
      if (url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([]));
      if (url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<CourseAssignmentsPage />);
    await screen.findByTestId('selected-assignment-course');
    fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));
    const settings = screen.getByText('Дополнительные настройки сроков');
    expect(settings.closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText(/Ссылка действует 7 дн/)).toBeVisible();
    fireEvent.click(settings);
    expect(settings.closest('details')).toHaveAttribute('open');
    expect(screen.getByTestId('personal-link-settings-grid')).toHaveClass('sm:grid-cols-2');
    const fields = screen.getAllByTestId('personal-link-field');
    expect(fields).toHaveLength(3);
    fields.forEach((field) => {
      expect(field).toHaveClass('min-w-0');
      expect(field.querySelector('input')).toHaveClass('h-10');
    });
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
    await openManagementMode();
    expect(await screen.findByText('Не доставлено')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Отправить повторно' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/notification/resend'),
      expect.objectContaining({ method: 'POST' }),
    ));
  });

it('preserves one-time credentials and reloads using the refreshed token', async () => {
  let resolve!: (value: Response) => void;
  const baseline = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' && String(input).endsWith('/personal-link-enrollment')) return new Promise((done) => { resolve = done; });
    if (!init?.method && String(input).endsWith('/v1/courses/course-1/enrollments') && (init?.headers as Record<string, string>)?.Authorization === 'Bearer refreshed-token') return Promise.resolve(jsonResponse([{ id: 'enrollment-1', course_id: 'course-1', user_id: 'user-1', status: 'enrolled' }]));
    return baseline(input, init);
  });
  const view = render(<CourseAssignmentsPage />);
  const assign = await screen.findByRole('button', { name: 'Назначить (1)' });
  fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));
  fireEvent.click(assign);
  await waitFor(() => expect(resolve).toBeTypeOf('function'));
  assignmentAuth.accessToken = 'refreshed-token';
  view.rerender(<CourseAssignmentsPage />);
  await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => !init?.method && String(input).endsWith('/v1/courses/course-1/enrollments') && (init?.headers as Record<string, string>)?.Authorization === 'Bearer refreshed-token')).toBe(true));
  await openManagementMode();
  await screen.findByRole('heading', { name: 'Назначения обучения: 1' });
  await act(async () => resolve(jsonResponse({ enrollment_id: 'enrollment-1', user_id: 'user-1', access_url: 'https://example.invalid/once', temporary_pin: '123456' }, 201)));
  expect(await screen.findByText('https://example.invalid/once')).toBeInTheDocument();
  expect(screen.getByText(/PIN: 123456/)).toBeInTheDocument();
  await waitFor(() => expect(fetchMock.mock.calls.filter(([input, init]) => !init?.method && String(input).endsWith('/v1/courses/course-1/enrollments') && (init?.headers as Record<string, string>)?.Authorization === 'Bearer refreshed-token').length).toBeGreaterThanOrEqual(2));
});

it('does not reveal an in-flight credential after the acting user changes', async () => {
  let resolve!: (value: Response) => void;
  const baseline = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' && String(input).endsWith('/personal-link-enrollment')) return new Promise((done) => { resolve = done; });
    return baseline(input, init);
  });
  const view = render(<CourseAssignmentsPage />);
  const assign = await screen.findByRole('button', { name: 'Назначить (1)' });
  fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));
  fireEvent.click(assign);
  await waitFor(() => expect(resolve).toBeTypeOf('function'));
  assignmentAuth.user = { ...assignmentAuth.user, user_id: 'actor-2' };
  assignmentAuth.accessToken = 'other-actor-token';
  view.rerender(<CourseAssignmentsPage />);
  await act(async () => resolve(jsonResponse({ enrollment_id: 'enrollment-1', user_id: 'user-1', access_url: 'https://example.invalid/private', temporary_pin: '123456' }, 201)));
  expect(screen.queryByText('https://example.invalid/private')).not.toBeInTheDocument();
  expect(screen.queryByText('123456')).not.toBeInTheDocument();
});


it('does not reveal an in-flight credential after same-identity session replacement', async () => {
  let resolve!: (value: Response) => void;
  const baseline = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' && String(input).endsWith('/personal-link-enrollment')) return new Promise((done) => { resolve = done; });
    return baseline(input, init);
  });
  const view = render(<CourseAssignmentsPage />);
  const assign = await screen.findByRole('button', { name: 'Назначить (1)' });
  fireEvent.click(screen.getByRole('radio', { name: /Персональная ссылка и PIN/i }));
  fireEvent.click(assign);
  await waitFor(() => expect(resolve).toBeTypeOf('function'));
  setAuth('new-session-token', assignmentAuth.user as Parameters<typeof setAuth>[1]);
  assignmentAuth.sessionEpoch = getAuthSessionEpoch();
  assignmentAuth.accessToken = 'new-session-token';
  view.rerender(<CourseAssignmentsPage />);
  await act(async () => resolve(jsonResponse({ enrollment_id: 'enrollment-1', user_id: 'user-1', access_url: 'https://example.invalid/private', temporary_pin: '123456' }, 201)));
  expect(screen.queryByText('https://example.invalid/private')).not.toBeInTheDocument();
  expect(screen.queryByText(/PIN: 123456/)).not.toBeInTheDocument();
});

});
