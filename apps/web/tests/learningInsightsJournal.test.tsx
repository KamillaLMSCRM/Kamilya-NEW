import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }));
vi.mock('@/i18n/useT', () => {
  const t = (key: string) => key;
  return { useT: () => ({ lang: 'en', t }) };
});

import AdminTrainingLogPage from '@/app/admin/training-log/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.mocked(api);

function setActor(tenantId: string, role = 'methodologist') {
  useAuthStore.setState({
    accessToken: 'synthetic-token', initialized: true,
    user: {
      user_id: `synthetic-${tenantId}`, tenant_id: tenantId,
      tenant: { id: tenantId, name: 'Synthetic tenant' },
      role, roles: [role], telegram_id: '', full_name: 'Synthetic methodologist',
      email: 'synthetic@example.test',
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  setActor('tenant-a');
  apiMock.get.mockImplementation(async (url: string) => {
    if (url === '/v1/courses') return { data: [{ id: 'course-a', title: 'Synthetic catalog-only course' }] } as never;
    if (url.includes('/summary')) return { data: { total: 0, assigned: 0, in_progress: 0, completed: 0, overdue: 0 } } as never;
    if (url.startsWith('/v1/admin/training-log?')) return { data: { items: [], total: 0, limit: 100, offset: 0 } } as never;
    throw new Error('Unexpected synthetic route');
  });
});

describe('learning insights journal integration', () => {
  it('keeps superadmin behind the canonical active-methodologist role boundary', async () => {
    setActor('tenant-a', 'superadmin');
    const originalGet = apiMock.get.getMockImplementation()!;
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/admin/training-log?')) return { data: { items: [{
        user_id: 'learner-a', full_name: 'Synthetic learner', email: null, personnel_number: null,
        department_id: null, department_name: null, position_id: null, position_name: null,
        course_id: 'course-a', course_title: 'Synthetic completed course', delivery_type: 'native',
        enrollment_id: 'enrollment-a', enrollment_status: 'completed', enrollment_source: 'manual',
        enrolled_at: null, completed_at: null, cycle_id: null, cycle_type: null, cycle_scheduled_for: null,
        latest_evidence_event_id: 'evidence-a', evidence_procedure_type: null,
        evidence_confirmation_status: 'confirmed', evidence_state: 'ready', evidence_events: [],
        computed_status: 'completed', progress_percent: 100, best_score: 100, quiz_attempts_count: 1,
        certificate_id: null, certificate_number: null, certificate_issued_at: null, kiosk_last_seen_at: null,
      }], total: 1, limit: 100, offset: 0 } } as never;
      return originalGet(url);
    });
    render(<AdminTrainingLogPage />);
    expect(await screen.findByText('trainingLog.forbidden')).toBeInTheDocument();
    expect(screen.queryAllByRole('button', { name: /Разбор ответов|Answer review|Review answers|Жауап/ })).toHaveLength(0);
    expect(screen.queryAllByRole('button', { name: /trainingLog.evidence.(pdf|zip|shareButton)/ })).toHaveLength(0);
  });

  it('loads selectable courses even when the current journal page is empty', async () => {
    render(<AdminTrainingLogPage />);
    expect(await screen.findByRole('option', { name: 'Synthetic catalog-only course' })).toBeInTheDocument();
  });

  it('does not violate hook ordering when authorization changes', async () => {
    render(<AdminTrainingLogPage />);
    await screen.findByRole('option', { name: 'Synthetic catalog-only course' });
    await act(async () => setActor('tenant-a', 'student'));
    expect(screen.getByText('trainingLog.forbidden')).toBeInTheDocument();
    await act(async () => setActor('tenant-a', 'methodologist'));
    expect(await screen.findByRole('option', { name: 'Synthetic catalog-only course' })).toBeInTheDocument();
  });

  it('hides the previous tenant catalog while the next tenant request is unresolved', async () => {
    render(<AdminTrainingLogPage />);
    await screen.findByRole('option', { name: 'Synthetic catalog-only course' });
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === '/v1/courses') return await new Promise<never>(() => {});
      return { data: url.includes('/summary') ? { total: 0 } : { items: [], total: 0 } } as never;
    });
    await act(async () => setActor('tenant-b'));
    await waitFor(() => expect(screen.queryByRole('option', { name: 'Synthetic catalog-only course' })).not.toBeInTheDocument());
  });
});
