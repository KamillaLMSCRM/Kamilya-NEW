import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.hoisted(() => vi.fn());
const params = vi.hoisted(() => ({ get: () => null }));
vi.mock('@/lib/api', () => ({ api: { get, post: vi.fn(), put: vi.fn() } }));
vi.mock('next/navigation', () => ({ useSearchParams: () => params }));
import CourseApprovalsPage from '@/app/admin/course-approvals/page';
import { useAuthStore } from '@/store/authStore';
import type { AuthUser } from '@/lib/auth';

function principal(role: string, tenant = 'tenant-a'): AuthUser {
  return { user_id: 'synthetic-user', tenant_id: tenant, tenant: { id: tenant, name: 'Synthetic' }, telegram_id: 'synthetic', role, full_name: 'Synthetic', email: null };
}

const request = { request_id: 'request-1', revision_id: 'revision-1', outcome: 'pending', delivery_mode: 'personal_link', reviewer_ids: [] };
function responseFor(url: string) {
  if (url.startsWith('/v1/course-approval-courses?') || url.startsWith('/v1/courses?')) return { data: [{ id: 'course-a', title: 'Synthetic course', requires_approval: false }] };
  if (url === '/v1/course-approval-requests') return { data: [request] };
  if (url.endsWith('/approval-policy')) return { data: { course_id: 'course-a', requires_approval: false, review_enabled: true } };
  throw new Error(`Unexpected API request: ${url}`);
}

describe('approval page through the actual API client', () => {
  beforeEach(() => {
    get.mockReset().mockImplementation(async (url: string) => responseFor(url));
    useAuthStore.setState({ user: principal('admin'), initialized: true });
  });
  afterEach(() => { cleanup(); useAuthStore.setState({ user: null }); });

  it('loads admin metadata and policy without authoring or requester controls', async () => {
    get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/courses?')) throw new Error('Admin cannot read authoring catalog');
      return responseFor(url);
    });
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('course-a'));
    expect(get).toHaveBeenCalledWith('/v1/course-approval-courses?page=1&per_page=100');
    expect(get.mock.calls.some(([url]) => url.startsWith('/v1/courses?'))).toBe(false);
    await waitFor(() => expect(screen.getByRole('checkbox')).toBeEnabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    for (const name of ['Создать снимок и запрос', 'Отменить запрос', 'Повторить доставку', 'Сменить доступ', 'Отозвать доступ']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole('heading', { name: 'Запрос request-' })).toBeInTheDocument();
  });

  it('preserves authoring and requester controls for the methodologist', async () => {
    useAuthStore.setState({ user: principal('methodologist') });
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Создать снимок и запрос' })).toBeInTheDocument());
    expect(get).toHaveBeenCalledWith('/v1/courses?page=1&per_page=100');
    expect(screen.getByRole('button', { name: 'Отменить запрос' })).toBeInTheDocument();
  });

  it.each(['admin', 'methodologist'])('does not present unavailable history as an empty success for %s', async (role) => {
    useAuthStore.setState({ user: principal(role) });
    let failed = true;
    let resolveHistory!: (value: unknown) => void;
    get.mockImplementation(async (url: string) => {
      if (failed) throw new Error('Synthetic unavailable read');
      if (url === '/v1/course-approval-requests') return new Promise((resolve) => { resolveHistory = resolve; });
      return responseFor(url);
    });
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить'));
    expect(screen.queryByText('Активных запросов на согласование нет.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Создать снимок и запрос' })).not.toBeInTheDocument();
    failed = false;
    fireEvent.click(screen.getByRole('button', { name: /^Обновить$/ }));
    expect(screen.queryByText('Активных запросов на согласование нет.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Создать снимок и запрос' })).not.toBeInTheDocument();
    await act(async () => resolveHistory(responseFor('/v1/course-approval-requests')));
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('course-a'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Запрос request-' })).toBeInTheDocument();
  });

  it('discards a pending response from the previous tenant', async () => {
    let resolveOld!: (value: unknown) => void;
    get.mockImplementation((url: string) => url.startsWith('/v1/course-approval-courses?')
      ? new Promise((resolve) => { resolveOld = resolve; }) : Promise.resolve(responseFor(url)));
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
    get.mockImplementation(async (url: string) => url.startsWith('/v1/course-approval-courses?')
      ? { data: [{ id: 'course-b', title: 'New tenant course', requires_approval: false }] } : responseFor(url));
    act(() => useAuthStore.setState({ user: principal('admin', 'tenant-b') }));
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('course-b'));
    await act(async () => resolveOld({ data: [{ id: 'old-course', title: 'Old tenant course' }] }));
    expect(screen.queryByText('Old tenant course')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue('course-b');
  });

  it.each(['student', 'superadmin', 'org_admin'])('does not fetch the catalog for unsupported active role %s', async (role) => {
    useAuthStore.setState({ user: principal(role) });
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(screen.queryByText('Загрузка…')).not.toBeInTheDocument());
    expect(get).not.toHaveBeenCalled();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});
