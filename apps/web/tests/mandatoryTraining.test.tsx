import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MandatoryTrainingPage from '@/app/mandatory-training/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }));

const apiMock = vi.mocked(api);

beforeEach(() => {
  vi.resetAllMocks();
  useLanguageStore.setState({ lang: 'ru' });
  useAuthStore.setState({
    accessToken: 'synthetic-token',
    initialized: true,
    user: {
      user_id: 'methodologist-1',
      tenant_id: 'tenant-1',
      tenant: { id: 'tenant-1', name: 'Synthetic tenant' },
      telegram_id: '',
      role: 'methodologist',
      roles: ['methodologist'],
      full_name: 'Тестовый методист',
      email: 'methodologist@example.test',
    },
  });
  apiMock.get.mockImplementation((path: string) => {
    if (path === '/v1/admin/mandatory-training/summary') return Promise.resolve({ data: {
      total: 2,
      materialized: 0,
      missing_enrollment: 1,
      protected_assignment: 1,
      stale_managed_enrollment: 0,
      action_materialize: 1,
      action_review_stale: 0,
    } });
    if (path === '/v1/admin/mandatory-training') return Promise.resolve({ data: {
      items: [
        {
          user_id: 'user-1',
          full_name: 'Аида Садыкова',
          personnel_number: 'PN-101',
          is_active: true,
          organization_unit_id: 'unit-1',
          organization_unit_path: ['Центральный офис', 'Операции'],
          position_id: 'position-1',
          position_name: 'Специалист',
          course_id: 'course-1',
          course_title: 'Безопасность',
          delivery_type: 'native',
          requirement_state: 'missing_enrollment',
          assignment_reason: {
            kind: 'department',
            source_ref_id: 'unit-1',
            source_name: 'Операции',
            scope_path_ids: ['root-1', 'unit-1'],
            scope_path_names: ['Центральный офис', 'Операции'],
            reason_code: 'mandatory_training.reason.department',
          },
          action_required: 'materialize',
          enrollment_id: null,
          enrollment_source: null,
          enrollment_status: null,
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    } });
    return Promise.reject(new Error(`Unexpected path: ${path}`));
  });
});

describe('mandatory training matrix', () => {
  it('explains missing assignments without requiring domain knowledge', async () => {
    render(<MandatoryTrainingPage />);

    expect(await screen.findByRole('heading', { name: 'Обязательное обучение' })).toBeInTheDocument();
    expect(screen.getAllByText('Аида Садыкова')).toHaveLength(2);
    expect(screen.getAllByText('Безопасность')).toHaveLength(2);
    expect(screen.getAllByText('Назначение ещё не создано').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('По подразделению')).toHaveLength(2);
    expect(screen.getAllByText(/Центральный офис → Операции/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/Операции/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Нужно создать назначение')).toHaveLength(2);
    expect(screen.getByText('1', { selector: '[data-testid="missing-enrollment-count"]' })).toBeInTheDocument();
  });

  it('shows a truthful error instead of replacing unavailable data with zeros', async () => {
    apiMock.get.mockRejectedValue(new Error('offline'));

    render(<MandatoryTrainingPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить матрицу');
    expect(screen.queryByTestId('missing-enrollment-count')).not.toBeInTheDocument();
  });

  it('shows the canonical progress, deadline, and evidence state for a real assignment', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith('/summary')) return Promise.resolve({ data: {
        total: 1, materialized: 1, missing_enrollment: 0,
        protected_assignment: 0, stale_managed_enrollment: 0,
        action_materialize: 0, action_review_stale: 0,
      } });
      return Promise.resolve({ data: {
        items: [{
          user_id: 'user-2', full_name: 'Бек Нуров', personnel_number: 'PN-102', is_active: true,
          organization_unit_id: 'unit-1', organization_unit_path: ['Центральный офис'],
          position_id: 'position-1', position_name: 'Специалист', course_id: 'course-2',
          course_title: 'Охрана труда', delivery_type: 'native', requirement_state: 'materialized',
          assignment_reason: { kind: 'position', source_ref_id: 'position-1', source_name: 'Специалист', scope_path_ids: [], scope_path_names: [], reason_code: 'mandatory_training.reason.position' },
          action_required: 'none', enrollment_id: 'enrollment-2', enrollment_source: 'position', enrollment_status: 'enrolled',
          computed_status: 'in_progress', progress_percent: 40, assignment_due_at: '2026-09-25T00:00:00Z',
          deadline_state: 'overdue', deadline_status: 'overdue', certificate_status: 'none',
          latest_evidence_event_id: 'event-1', evidence_confirmation_status: 'pending',
          evidence_signed_copy_status: 'uploaded_pending_review', evidence_state: 'forming',
        }],
        total: 1, limit: 100, offset: 0,
      } });
    });

    render(<MandatoryTrainingPage />);

    expect((await screen.findAllByText('40%')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Просрочено').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Скан ожидает проверки').length).toBeGreaterThanOrEqual(2);
  });

  it('does not request tenant rows for a learner', async () => {
    useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: 'student', roles: ['student'] } });

    const { container } = render(<MandatoryTrainingPage />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it('does not hide rows beyond the first server page', async () => {
    apiMock.get.mockImplementation((path: string, config?: { params?: Record<string, unknown> }) => {
      if (path.endsWith('/summary')) return Promise.resolve({ data: {
        total: 101, materialized: 101, missing_enrollment: 0,
        protected_assignment: 0, stale_managed_enrollment: 0,
        action_materialize: 0, action_review_stale: 0,
      } });
      const offset = Number(config?.params?.offset ?? 0);
      return Promise.resolve({ data: {
        items: offset === 100 ? [{
          user_id: 'user-101', full_name: 'Последний сотрудник', personnel_number: 'PN-201', is_active: true,
          organization_unit_id: null, organization_unit_path: [], position_id: null, position_name: null,
          course_id: 'course-101', course_title: 'Последний курс', delivery_type: 'native',
          requirement_state: 'materialized', assignment_reason: {
            kind: 'organization', source_ref_id: 'rule-1', source_name: null,
            scope_path_ids: [], scope_path_names: [], reason_code: 'mandatory_training.reason.organization',
          }, action_required: 'none', enrollment_id: 'enrollment-101',
          enrollment_source: 'organization', enrollment_status: 'enrolled',
        }] : [],
        total: 101, limit: 100, offset,
      } });
    });

    render(<MandatoryTrainingPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница' }));
    expect(await screen.findAllByText('Последний сотрудник')).toHaveLength(2);
    expect(screen.getByText('101–101 из 101')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/admin/mandatory-training',
      expect.objectContaining({ params: expect.objectContaining({ limit: 100, offset: 100 }) }),
    );
  });
});
