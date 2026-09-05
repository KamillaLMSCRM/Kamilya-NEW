import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    lang: 'en',
    t: (key: string) => ({
      'trainingLog.badge.deadlineActive': 'On track',
      'trainingLog.badge.deadlineOverdue': 'Overdue',
      'trainingLog.badge.completedOnTime': 'Completed on time',
      'trainingLog.badge.completedLate': 'Completed late',
    }[key] ?? key),
  }),
}));

import AdminTrainingLogPage from '@/app/admin/training-log/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.mocked(api);

function trainingLogRow(deadline: Record<string, unknown>) {
  return {
    user_id: 'user-1', full_name: 'Test learner', email: null, personnel_number: null,
    department_id: null, department_name: null, position_id: null, position_name: null,
    course_id: 'course-1', course_title: 'Deadline course', delivery_type: 'native',
    enrollment_status: 'in_progress', enrollment_source: 'manual', enrolled_at: null,
    completed_at: null, cycle_id: null, cycle_type: null, cycle_scheduled_for: null,
    enrollment_id: 'enrollment-1', latest_evidence_event_id: null, evidence_procedure_type: null,
    evidence_confirmation_status: 'not_required', evidence_state: 'incomplete', evidence_events: [],
    computed_status: 'in_progress', progress_percent: 50, best_score: null, quiz_attempts_count: 0,
    certificate_id: null, certificate_number: null, certificate_issued_at: null, kiosk_last_seen_at: null,
    ...deadline,
  };
}

function renderTrainingLog(deadline: Record<string, unknown>) {
  apiMock.get.mockImplementation(async (url: string) => {
    if (url.includes('/summary')) return { data: { total: 1, assigned: 0, in_progress: 1, completed: 0, overdue: 0 } } as never;
    if (url.startsWith('/v1/admin/training-log?')) return { data: { items: [trainingLogRow(deadline)], total: 1, limit: 100, offset: 0 } } as never;
    throw new Error(`Unexpected GET ${url}`);
  });
  render(<AdminTrainingLogPage />);
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    accessToken: 'test-token', initialized: true,
    user: {
      user_id: 'methodologist-1', tenant_id: 'tenant-1', tenant: { id: 'tenant-1', name: 'Test tenant' },
      telegram_id: '', role: 'methodologist', roles: ['methodologist'], full_name: 'Methodologist',
      email: 'methodologist@example.test',
    },
  });
});

describe('training log deadline presentation', () => {
  it.each([
    ['legacy missing fields', {}],
    ['a missing status', { cycle_due_at: '2026-09-10T00:00:00Z' }],
    ['a null deadline', { cycle_due_at: null, deadline_status: 'active' }],
    ['an unknown status', { cycle_due_at: '2026-09-10T00:00:00Z', deadline_status: 'future_status' }],
  ])('does not show a misleading active badge for %s', async (_scenario, deadline) => {
    renderTrainingLog(deadline);
    await screen.findAllByText('Deadline course');
    expect(screen.queryByText('On track')).not.toBeInTheDocument();
  });

  it('renders the overdue deadline state', async () => {
    renderTrainingLog({ cycle_due_at: '2026-09-10T00:00:00Z', deadline_status: 'overdue' });
    expect(await screen.findAllByText('Overdue')).toHaveLength(2);
  });

  it('renders the completed-late deadline state', async () => {
    renderTrainingLog({ cycle_due_at: '2026-09-10T00:00:00Z', deadline_status: 'completed_late' });
    expect(await screen.findAllByText('Completed late')).toHaveLength(2);
  });

  it('renders the active deadline state only with a complete valid deadline', async () => {
    renderTrainingLog({ cycle_due_at: '2026-09-10T00:00:00Z', deadline_status: 'active' });
    expect(await screen.findAllByText('On track')).toHaveLength(2);
  });
});
