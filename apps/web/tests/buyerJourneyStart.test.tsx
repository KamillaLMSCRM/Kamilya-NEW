import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DashboardPage from '@/app/dashboard/page';
import DemoLoginPage from '@/app/login/demo/page';
import { OnboardingChecklist } from '@/components/admin/OnboardingChecklist';
import en from '@/i18n/locales/en.json';
import kk from '@/i18n/locales/kk.json';
import ru from '@/i18n/locales/ru.json';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const authState = vi.hoisted(() => ({
  accessToken: 'test-token',
  user: { role: 'methodologist', full_name: 'Test Methodologist' },
  login: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector?: (state: typeof authState) => unknown) => selector ? selector(authState) : authState,
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: (key: string) => key, lang: 'ru' }),
}));
vi.mock('@/lib/auth', () => ({ clearStoredAuth: vi.fn() }));
vi.mock('@/components/brand/Logo', () => ({ Logo: () => <span>Kamilya</span> }));

const onboardingStatus = {
  steps: [
    { id: 'team', label: 'Admin-owned step', done: false, href: '/admin/team', badge: null, owner: 'admin' },
    { id: 'first_course', label: 'Methodologist-owned step', done: false, href: '/ai/generate', badge: null, owner: 'methodologist' },
  ],
  completed: false,
  trial_ends_at: null,
  trial_days_remaining: null,
  plan: null,
  max_users: null,
  active_users: 0,
  role: 'admin',
  trial_state: 'not_trial',
  trial_access_state: 'not_applicable',
  trial_exhausted_limits: [],
  trial_usage: {},
};

function mockExistingRequests(jobs: Array<Record<string, unknown>>) {
  apiMock.get.mockImplementation((path: string) => {
    if (path === '/v1/ai/jobs') return Promise.resolve({ data: jobs });
    if (path === '/v1/users?page=1&per_page=1&role=student&is_active=true&include_students=true') {
      return Promise.resolve({ data: { total: 0 } });
    }
    if (path === '/v1/enrollments/stats') return Promise.resolve({ data: { total: 0, completed: 0 } });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => {
  authState.user = { role: 'methodologist', full_name: 'Test Methodologist' };
  authState.accessToken = 'test-token';
  apiMock.get.mockReset();
  apiMock.post.mockReset();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => onboardingStatus,
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('buyer-journey START presentation', () => {
  it('hides the AI board only when the existing jobs API returns no active, failed, or unknown jobs', async () => {
    mockExistingRequests([]);

    render(<DashboardPage />);

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/ai/jobs'));
    expect(screen.queryByText('dashboard.aiPipeline')).not.toBeInTheDocument();
  });

  it('keeps failed and unknown existing jobs visible in the AI board', async () => {
    mockExistingRequests([
      { id: 'failed-job', status: 'failed', course_title: 'Failed course', created_at: '2026-09-06T00:00:00Z' },
      { id: 'unknown-job', status: 'waiting_for_review', course_title: 'Unknown job', created_at: '2026-09-06T00:00:00Z' },
    ]);

    render(<DashboardPage />);

    expect(await screen.findByText('dashboard.aiPipeline')).toBeInTheDocument();
    expect(screen.getByText('Failed course')).toBeInTheDocument();
    expect(screen.getByText('Unknown job')).toBeInTheDocument();
    expect(screen.getByText('dashboard.kanban.failed')).toBeInTheDocument();
    expect(screen.getByText('dashboard.kanban.needsAttention')).toBeInTheDocument();
  });

  it('keeps the active session role authoritative and offers the alternate template basis without changing server steps', async () => {
    render(<OnboardingChecklist />);

    expect(await screen.findByText('Methodologist-owned step')).toBeInTheDocument();
    expect(screen.queryByText('Admin-owned step')).not.toBeInTheDocument();
    expect(screen.getByText('onboarding.basisStart').closest('a')).toHaveAttribute('href', '/courses');
  });

  it('places the API-free interactive preview before shared demo role choices', () => {
    render(<DemoLoginPage />);

    const preview = screen.getByText('demo.login.openExample').closest('a');
    expect(preview).toHaveAttribute('href', '/login/example?lang=ru');
    expect(screen.getByText('demo.login.exampleSubtitle')).toBeInTheDocument();
    expect(screen.getByText('demo.login.workspaceSubtitle')).toBeInTheDocument();
    expect(preview?.compareDocumentPosition(screen.getByText('users.roleMethodologist'))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it.each([['RU', ru], ['KK', kk], ['EN', en]] as const)('uses clear localized START wording in %s', (_, locale) => {
    expect(locale.dashboard.aiPipeline).not.toBe('AI Pipeline');
    expect(locale.courses.blueprint.complianceModes.lmsOnly).not.toBe('LMS only');
    expect(locale.courses.blueprint.steps.checklistDescription).not.toMatch(/server|сервер/i);
    expect(locale.demo.login.exampleSubtitle).toBeTruthy();
    expect(locale.onboarding.basisStart).toBeTruthy();
  });
});
