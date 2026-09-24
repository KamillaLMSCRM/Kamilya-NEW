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
  user: { role: 'methodologist', full_name: 'Test Methodologist', tenant_id: 'tenant-1', user_id: 'methodologist-1' },
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
    if (path === '/v1/admin/learning-actions') return Promise.resolve({ data: {
      summary: {
        training_log: { total: 2, assigned: 1, in_progress: 0, completed: 1, overdue: 0, failed_current: 0, exhausted_attempts: 0, reassigned: 0, cancelled_history: 0, superseded_history: 0 },
        training_issue_count: 0, training_issue_counts: {}, training_items_truncated: false,
        weak_question_count: 0, action_count: 0, actions_truncated: false, open_action_count: 0, overdue_action_count: 0,
      },
      training_items: [], weak_questions: [], actions: [],
    } });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => {
  authState.user = { role: 'methodologist', full_name: 'Test Methodologist', tenant_id: 'tenant-1', user_id: 'methodologist-1' };
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
  it('shows an explicit empty content state when there are no active or problematic jobs', async () => {
    mockExistingRequests([]);

    render(<DashboardPage />);

    expect(await screen.findByText('Активных или проблемных генераций нет.')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/v1/ai/jobs', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it('keeps failed and unknown jobs visible as items that need attention', async () => {
    mockExistingRequests([
      { id: 'failed-job', job_type: 'course_generation', status: 'failed', course_title: 'Failed course', created_at: '2026-09-06T00:00:00Z' },
      { id: 'unknown-job', job_type: 'course_generation', status: 'waiting_for_review', course_title: 'Unknown job', created_at: '2026-09-06T00:00:00Z' },
    ]);

    render(<DashboardPage />);

    expect(await screen.findByText('Контент в работе')).toBeInTheDocument();
    expect(screen.getByText('Failed course')).toBeInTheDocument();
    expect(screen.getByText('Unknown job')).toBeInTheDocument();
    expect(screen.getAllByText('Требует внимания').length).toBeGreaterThan(0);
  });

  it('uses status for urgency while preserving the current pipeline stage', async () => {
    mockExistingRequests([
      {
        id: 'running-job',
        job_type: 'course_generation',
        status: 'running',
        stage: 'architect',
        course_title: 'Course being planned',
        created_at: '2026-09-06T00:00:00Z',
      },
    ]);

    render(<DashboardPage />);

    expect(await screen.findByText('Course being planned')).toBeInTheDocument();
    expect(screen.getByText('architect')).toBeInTheDocument();
    expect(screen.getByText('В работе')).toBeInTheDocument();
  });

  it('ignores cancelled course jobs and non-course AI jobs', async () => {
    mockExistingRequests([
      {
        id: 'cancelled-course-job',
        job_type: 'course_generation',
        status: 'cancelled',
        stage: 'cancelled',
        course_title: 'Cancelled course',
        created_at: '2026-09-06T00:00:00Z',
      },
      {
        id: 'document-reindex-job',
        job_type: 'document_reindex',
        status: 'running',
        stage: 'generating',
        course_title: 'Document indexing',
        created_at: '2026-09-06T00:00:00Z',
      },
    ]);

    render(<DashboardPage />);

    expect(await screen.findByText('Активных или проблемных генераций нет.')).toBeInTheDocument();
    expect(screen.queryByText('Cancelled course')).not.toBeInTheDocument();
    expect(screen.queryByText('Document indexing')).not.toBeInTheDocument();
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
    expect(screen.getByText('demo.login.back').closest('a')).toHaveAttribute('href', '/login?lang=ru');
    expect(screen.getByText('demo.login.register').closest('a')).toHaveAttribute('href', '/register-tenant?lang=ru');
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
