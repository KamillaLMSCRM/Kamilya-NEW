import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const fetchMock = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => ({ error: vi.fn(), info: vi.fn(), success: vi.fn() }));
const authState = vi.hoisted(() => ({ token: 'test-token', role: 'methodologist' }));

vi.stubGlobal('fetch', fetchMock);
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector({
    accessToken: authState.token, user: { role: authState.role },
  }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: (key: string) => key === 'common.loading' ? 'Загрузка' : key, tp: (_key: string, count: number) => `${count}` }),
}));
vi.mock('@/components/ui/ConfirmDialog', () => ({ useConfirm: () => ({ confirm: vi.fn(), dialog: null }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: toastMock }));

import CourseAssignmentsPage from '@/features/course-assignments/CourseAssignmentsPage';

const rule = {
  id: 'rule-1', course_id: 'course-1', user_id: 'user-1', cadence_days: 180, due_days: 14,
  status: 'active', next_run_at: null, last_run_at: null, reminder_enabled: false, reminder_days_before_due: 1,
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function installFetchMock(overrides: Partial<Record<string, () => Promise<Response>>> = {}) {
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
    if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [{ id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'aliya@example.kz', role: 'student' }] }));
    if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
    if (!init?.method && url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([rule]));
    if (!init?.method && url.endsWith('/v1/learning-cycles/rule-1/reminders')) return overrides.history?.() ?? Promise.resolve(jsonResponse([]));
    if (init?.method === 'PATCH' && url.endsWith('/v1/learning-cycles/rule-1')) return overrides.patch?.() ?? Promise.resolve(jsonResponse({ ...rule, reminder_enabled: true, reminder_days_before_due: 30 }));
    if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([]));
    throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
  });
}

async function renderRule() {
  render(<CourseAssignmentsPage />);
  return await screen.findByText('Охрана труда · Алия Садыкова');
}

describe('recurring reminder settings', () => {
  beforeEach(() => {
    authState.token = 'test-token';
    authState.role = 'methodologist';
    fetchMock.mockReset();
    toastMock.error.mockReset();
    toastMock.success.mockReset();
    installFetchMock();
  });

  it('defaults off, validates the 1–30-day field, and sends only reminder settings', async () => {
    await renderRule();
    const checkbox = screen.getByRole('checkbox', { name: 'Включить напоминание' });
    expect(checkbox).not.toBeChecked();
    const lead = screen.getByRole('spinbutton', { name: /За сколько дней до срока для правила rule-1/ });
    fireEvent.click(checkbox);
    fireEvent.change(lead, { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить напоминание' }));
    expect(toastMock.error).toHaveBeenCalledWith('Укажите срок напоминания от 1 до 30 дней');
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false);

    fireEvent.change(lead, { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить напоминание' }));
    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/v1/learning-cycles/rule-1') && init?.method === 'PATCH');
      expect(patchCall).toBeDefined();
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ reminder_enabled: true, reminder_days_before_due: 30 });
    });
    expect(screen.getByText('Сохранено')).toBeInTheDocument();

    fireEvent.change(lead, { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить напоминание' }));
    await waitFor(() => {
      const patches = fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/v1/learning-cycles/rule-1') && init?.method === 'PATCH');
      expect(patches).toHaveLength(2);
      expect(JSON.parse(String(patches[1][1]?.body))).toEqual({ reminder_enabled: true, reminder_days_before_due: 1 });
    });
  });

  it('retains an unsaved draft after a failed PATCH and blocks duplicate submission', async () => {
    let resolvePatch: ((response: Response) => void) | undefined;
    installFetchMock({ patch: () => new Promise((resolve) => { resolvePatch = resolve; }) });
    await renderRule();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Включить напоминание' }));
    const save = screen.getByRole('button', { name: 'Сохранить напоминание' });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(1);
    expect(screen.getByRole('checkbox', { name: 'Включить напоминание' })).toBeDisabled();
    expect(screen.getByRole('spinbutton', { name: /За сколько дней до срока для правила rule-1/ })).toBeDisabled();
    resolvePatch?.(jsonResponse({ detail: 'failed' }, 500));
    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Не удалось сохранить настройки напоминания', expect.anything()));
    expect(screen.getByRole('checkbox', { name: 'Включить напоминание' })).toBeChecked();
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
  });

  it('keeps the affected settings locked until a delayed successful PATCH has committed', async () => {
    let resolvePatch: ((response: Response) => void) | undefined;
    installFetchMock({ patch: () => new Promise((resolve) => { resolvePatch = resolve; }) });
    await renderRule();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Включить напоминание' }));
    fireEvent.change(screen.getByRole('spinbutton', { name: /За сколько дней до срока for rule-1|За сколько дней до срока для правила rule-1/ }), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить напоминание' }));
    expect(screen.getByRole('checkbox', { name: 'Включить напоминание' })).toBeDisabled();
    expect(screen.getByRole('spinbutton', { name: /За сколько дней до срока для правила rule-1/ })).toBeDisabled();
    resolvePatch?.(jsonResponse({ ...rule, reminder_enabled: true, reminder_days_before_due: 30 }));
    await waitFor(() => expect(screen.getByText('Сохранено')).toBeInTheDocument());
    expect(screen.getByRole('checkbox', { name: 'Включить напоминание' })).not.toBeDisabled();
  });

  it('loads safe statuses lazily and distinguishes loading, empty, and error states', async () => {
    let resolveHistory: ((response: Response) => void) | undefined;
    installFetchMock({ history: () => new Promise((resolve) => { resolveHistory = resolve; }) });
    await renderRule();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/reminders'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Показать статусы напоминаний' }));
    expect(screen.getByText('Загрузка статусов напоминаний…')).toBeInTheDocument();
    resolveHistory?.(jsonResponse([]));
    expect(await screen.findByText('Статусов напоминаний пока нет.')).toBeInTheDocument();

    installFetchMock({ history: () => Promise.resolve(jsonResponse({ detail: 'unavailable' }, 500)) });
    fireEvent.click(screen.getByRole('button', { name: 'Показать статусы напоминаний' }));
    expect(await screen.findByText('Не удалось загрузить статусы напоминаний. Попробуйте ещё раз.')).toBeInTheDocument();
  });

  it('renders returned safe delivery states without implying global delivery is enabled', async () => {
    installFetchMock({ history: () => Promise.resolve(jsonResponse([{ id: 'status-1', status: 'unexpected_status', attempt_count: 2, scheduled_at: '2026-09-05T10:00:00Z', delivered_at: '2026-09-05T10:01:00Z', last_error_category: 'provider_unavailable' }])) });
    await renderRule();
    fireEvent.click(screen.getByRole('button', { name: 'Показать статусы напоминаний' }));
    const statuses = await screen.findByRole('list', { name: 'Статусы напоминаний для правила rule-1' });
    expect(within(statuses).getByText(/Статус неизвестен/)).toBeInTheDocument();
    expect(within(statuses).getByText(/Сервис отправки временно недоступен/)).toBeInTheDocument();
    expect(within(statuses).getByText(/отправлено/)).toBeInTheDocument();
    expect(within(statuses).queryByText(/provider_unavailable|unexpected_status/)).not.toBeInTheDocument();
    expect(screen.getByText(/не включает доставку глобально/)).toBeInTheDocument();
  });

  it.each([200, 500])('aborts history and ignores stale saves (HTTP %s) after the auth token changes', async (status) => {
    let resolvePatch: ((response: Response) => void) | undefined;
    let historySignal: AbortSignal | undefined;
    installFetchMock({
      patch: () => new Promise((resolve) => { resolvePatch = resolve; }),
      history: () => new Promise(() => {}),
    });
    const view = render(<CourseAssignmentsPage />);
    await screen.findByText('Охрана труда · Алия Садыкова');
    fireEvent.click(screen.getByRole('button', { name: 'Показать статусы напоминаний' }));
    historySignal = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/reminders'))?.[1]?.signal as AbortSignal;
    fireEvent.click(screen.getByRole('checkbox', { name: 'Включить напоминание' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить напоминание' }));
    authState.token = 'next-token';
    view.rerender(<CourseAssignmentsPage />);
    await waitFor(() => expect(historySignal?.aborted).toBe(true));
    await act(async () => {
      resolvePatch?.(status === 200
        ? jsonResponse({ ...rule, reminder_enabled: true, reminder_days_before_due: 1 })
        : jsonResponse({ detail: 'stale failure' }, 500));
    });
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Включить напоминание' })).not.toBeChecked());
    expect(toastMock.success).not.toHaveBeenCalledWith('Настройки напоминания сохранены');
    expect(toastMock.error).not.toHaveBeenCalledWith('Не удалось сохранить настройки напоминания', expect.anything());
    view.unmount();
  });

  it.each([200, 500])('does not emit save feedback after unmount (HTTP %s)', async (status) => {
    let resolvePatch: ((response: Response) => void) | undefined;
    installFetchMock({ patch: () => new Promise((resolve) => { resolvePatch = resolve; }) });
    const view = render(<CourseAssignmentsPage />);
    await screen.findByText('Охрана труда · Алия Садыкова');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Включить напоминание' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить напоминание' }));
    view.unmount();
    await act(async () => {
      resolvePatch?.(status === 200
        ? jsonResponse({ ...rule, reminder_enabled: true, reminder_days_before_due: 1 })
        : jsonResponse({ detail: 'late failure' }, 500));
    });
    expect(toastMock.success).not.toHaveBeenCalled();
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it('keeps concurrent rule history responses with their own cards', async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url.includes('/v1/courses?')) return Promise.resolve(jsonResponse([{ id: 'course-1', title: 'Охрана труда', status: 'published' }]));
      if (!init?.method && url.includes('/v1/users?')) return Promise.resolve(jsonResponse({ users: [
        { id: 'user-1', first_name: 'Алия', last_name: 'Садыкова', email: 'a@example.kz', role: 'student' },
        { id: 'user-2', first_name: 'Бек', last_name: 'Иманов', email: 'b@example.kz', role: 'student' },
      ] }));
      if (!init?.method && url.endsWith('/v1/learning-cycles/occurrences')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/v1/learning-cycles')) return Promise.resolve(jsonResponse([rule, { ...rule, id: 'rule-2', course_id: null, learning_path_id: 'path-2', target_type: 'learning_path', user_id: 'user-2' }]));
      if (!init?.method && url.endsWith('/v1/courses/course-1/enrollments')) return Promise.resolve(jsonResponse([]));
      if (!init?.method && url.endsWith('/rule-1/reminders')) return new Promise((resolve) => { resolveFirst = resolve; });
      if (!init?.method && url.endsWith('/rule-2/reminders')) return Promise.resolve(jsonResponse([{ id: 'status-2', status: 'sent', attempt_count: 1, scheduled_at: '2026-09-05T10:00:00Z', delivered_at: '2026-09-05T10:01:00Z', last_error_category: null }]));
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`);
    });
    render(<CourseAssignmentsPage />);
    expect(await screen.findByText('Программа обучения · Бек Иманов')).toBeInTheDocument();
    expect(screen.queryByText(/path-2/)).not.toBeInTheDocument();
    const showButtons = screen.getAllByRole('button', { name: 'Показать статусы напоминаний' });
    fireEvent.click(showButtons[0]);
    fireEvent.click(showButtons[1]);
    const secondStatuses = await screen.findByRole('list', { name: 'Статусы напоминаний для правила rule-2' });
    expect(within(secondStatuses).getByText(/Отправлено/)).toBeInTheDocument();
    resolveFirst?.(jsonResponse([{ id: 'status-1', status: 'failed', attempt_count: 1, scheduled_at: '2026-09-05T10:00:00Z', delivered_at: null, last_error_category: 'provider_timeout' }]));
    const firstStatuses = await screen.findByRole('list', { name: 'Статусы напоминаний для правила rule-1' });
    expect(within(firstStatuses).getByText(/Не доставлено/)).toBeInTheDocument();
    expect(within(secondStatuses).queryByText(/Не доставлено/)).not.toBeInTheDocument();
  });
});
