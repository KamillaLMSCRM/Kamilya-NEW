import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MethodologistDashboard } from '@/features/dashboard/MethodologistDashboard';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }));

const apiMock = vi.mocked(api);

const actionCenter = {
  summary: {
    training_log: {
      total: 10,
      assigned: 3,
      in_progress: 3,
      completed: 4,
      overdue: 2,
      failed_current: 1,
      exhausted_attempts: 1,
      reassigned: 0,
      cancelled_history: 0,
      superseded_history: 0,
    },
    training_issue_count: 3,
    training_issue_counts: { overdue: 2, failed_required_quiz: 1 },
    training_items_truncated: false,
    weak_question_count: 2,
    action_count: 2,
    actions_truncated: false,
    open_action_count: 2,
    overdue_action_count: 1,
  },
  training_items: [
    {
      enrollment_id: '11111111-1111-4111-8111-111111111111',
      user_id: '33333333-3333-4333-8333-333333333333',
      full_name: 'Сотрудник с риском',
      course_id: '22222222-2222-4222-8222-222222222222',
      course_title: 'Безопасность',
      issue_type: 'overdue',
      progress_percent: 25,
      best_score: null,
      quiz_attempts_count: 0,
      assignment_due_at: '2026-09-20T10:00:00Z',
      active_action_id: null,
      active_action_types: [],
    },
  ],
  weak_questions: [],
  actions: [],
};

beforeEach(() => {
  vi.resetAllMocks();
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
    if (path === '/v1/admin/learning-actions') return Promise.resolve({ data: actionCenter });
    if (path === '/v1/courses') return Promise.resolve({ data: [
      { id: 'course-1', title: 'Опубликованный курс', status: 'published' },
      { id: 'course-2', title: 'Черновик', status: 'draft' },
    ] });
    if (path === '/v1/ai/jobs') return Promise.resolve({ data: [
      { id: 'job-1', job_type: 'course_generation', status: 'running', stage: 'generating', course_title: 'Новый курс', created_at: '2026-09-24T10:00:00Z' },
      { id: '0228597d-1111-4111-8111-111111111111', job_type: 'course_generation', status: 'failed', stage: 'review', created_at: '2026-09-24T09:00:00Z' },
    ] });
    return Promise.reject(new Error(`Unexpected path: ${path}`));
  });
});

describe('methodologist operations dashboard', () => {
  it('answers the operational questions from one learning read model', async () => {
    render(<MethodologistDashboard />);

    expect(await screen.findByText('Сотрудник с риском')).toBeInTheDocument();
    expect(screen.getByText('40%')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Просрочено: 2' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Действий открыто: 2' })).toBeInTheDocument();
    expect(screen.getByText('Не удалось создать курс')).toBeInTheDocument();
    expect(screen.getByText('Этап: проверка качества · заявка 0228597d')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/v1/admin/learning-actions', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(apiMock.get).not.toHaveBeenCalledWith('/v1/admin/training-log/summary', expect.anything());
  });

  it('links only truthful training metrics and exact priority assignments to canonical filters', async () => {
    render(<MethodologistDashboard />);

    const expectedReturn = 'return_to=%2Fdashboard';
    expect(await screen.findByRole('link', { name: /Сотрудник с риском/ })).toHaveAttribute(
      'href',
      `/training-log?enrollment_id=11111111-1111-4111-8111-111111111111&course_id=22222222-2222-4222-8222-222222222222&${expectedReturn}`,
    );
    expect(screen.getByRole('link', { name: 'Не начали: 3' })).toHaveAttribute('href', `/training-log?status=assigned&${expectedReturn}`);
    expect(screen.getByRole('link', { name: 'В процессе: 3' })).toHaveAttribute('href', `/training-log?status=in_progress&${expectedReturn}`);
    expect(screen.getByRole('link', { name: 'Завершено: 4' })).toHaveAttribute('href', `/training-log?status=completed&${expectedReturn}`);
    expect(screen.getByRole('link', { name: 'Просрочено: 2' })).toHaveAttribute('href', `/training-log?status=overdue&${expectedReturn}`);
    expect(screen.queryByRole('link', { name: /Тест не пройден/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Попытки исчерпаны/ })).not.toBeInTheDocument();
  });

  it('keeps learning data unknown when the primary read model is unavailable', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/v1/admin/learning-actions') return Promise.reject(new Error('unavailable'));
      return Promise.resolve({ data: [] });
    });

    render(<MethodologistDashboard />);

    expect(await screen.findByRole('status')).toHaveTextContent('Сводка обучения временно недоступна');
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
    expect(screen.queryByTestId('training-overdue')).not.toBeInTheDocument();
  });

  it('does not request learner-level data for a tenant admin', async () => {
    useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: 'admin', roles: ['admin'] } });

    const { container } = render(<MethodologistDashboard />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});
