import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MethodologistDashboard } from '@/features/dashboard/MethodologistDashboard';
import { buildMethodologistDashboard } from '@/features/dashboard/model';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

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
    if (path === '/v1/admin/learning-actions') return Promise.resolve({ data: actionCenter });
    if (path === '/v1/courses?per_page=100') return Promise.resolve({ data: [
      { id: 'course-1', title: 'Опубликованный курс', status: 'published' },
      { id: 'course-2', title: 'Черновик', status: 'draft' },
    ] });
    if (path === '/v1/ai/jobs') return Promise.resolve({ data: [
      { id: 'job-1', job_type: 'course_generation', status: 'running', stage: 'generating', course_title: 'Новый курс', created_at: '2026-09-24T10:00:00Z' },
      { id: '0228597d-1111-4111-8111-111111111111', job_type: 'course_generation', status: 'failed', stage: 'review', created_at: '2026-09-24T09:00:00Z' },
    ] });
    if (path === '/v1/admin/mandatory-training/summary') return Promise.resolve({ data: {
      total: 12,
      materialized: 9,
      missing_enrollment: 2,
      protected_assignment: 1,
      stale_managed_enrollment: 1,
      action_materialize: 2,
      action_review_stale: 1,
    } });
    return Promise.reject(new Error(`Unexpected path: ${path}`));
  });
});

describe('methodologist operations dashboard', () => {
  it('ignores a delayed old-tenant source even when its transport ignores abort', async () => {
    const original = apiMock.get.getMockImplementation()!;
    let resolveOld!: (value: { data: typeof actionCenter }) => void;
    const oldRead = new Promise<{ data: typeof actionCenter }>((resolve) => { resolveOld = resolve; });
    apiMock.get.mockImplementation((path, config) => path === '/v1/admin/learning-actions' ? oldRead : original(path, config));
    render(<MethodologistDashboard />);
    await screen.findByRole('button', { name: /заявка 0228597d/ });
    apiMock.get.mockImplementation((path, config) => path === '/v1/admin/learning-actions'
      ? Promise.resolve({ data: { ...actionCenter, training_items: [{ ...actionCenter.training_items[0], full_name: 'Current tenant employee' }] } }) : original(path, config));
    act(() => useAuthStore.setState({ user: { ...useAuthStore.getState().user!, tenant_id: 'new-tenant' } }));
    expect(await screen.findByRole('button', { name: /Current tenant employee/ })).toBeVisible();
    await act(async () => resolveOld({ data: actionCenter }));
    expect(screen.queryByRole('button', { name: /Сотрудник с риском/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Current tenant employee/ })).toBeVisible();
  });
  it('renders ready tasks while an optional source remains unresolved', async () => {
    const original = apiMock.get.getMockImplementation()!;
    apiMock.get.mockImplementation((path, config) => path === '/v1/admin/mandatory-training/summary'
      ? new Promise(() => {}) : original(path, config));
    render(<MethodologistDashboard />);
    expect(await screen.findByRole('button', { name: /Сотрудник с риском/ })).toBeVisible();
    expect(await screen.findByRole('button', { name: /заявка 0228597d/ })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Обязательное обучение' })).toHaveTextContent('Загрузка задач');
    expect(screen.getByTestId('mandatory-missing-unavailable')).toHaveTextContent('—');
  });

  it('retries only the failed jobs source without clearing ready learning tasks', async () => {
    const original = apiMock.get.getMockImplementation()!;
    let failed = true;
    apiMock.get.mockImplementation((path, config) => path === '/v1/ai/jobs' && failed
      ? Promise.reject(new Error('Jobs unavailable')) : original(path, config));
    render(<MethodologistDashboard />);
    const retry = await screen.findByRole('button', { name: /Повторить.*Задания генерации/ });
    const employee = screen.getByRole('button', { name: /Сотрудник с риском/ });
    failed = false;
    fireEvent.click(retry);
    expect(employee).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /заявка 0228597d/ })).toBeVisible();
    expect(apiMock.get.mock.calls.filter(([path]) => path === '/v1/ai/jobs')).toHaveLength(2);
    expect(apiMock.get.mock.calls.filter(([path]) => path === '/v1/admin/learning-actions')).toHaveLength(1);
    expect(apiMock.get.mock.calls.filter(([path]) => path === '/v1/courses?per_page=100')).toHaveLength(1);
  });

  it('does not claim complete job totals from the bounded twenty-job endpoint', () => {
    const model = buildMethodologistDashboard({ learning: null, courses: [], mandatory: null,
      jobs: Array.from({ length: 20 }, (_, index) => ({ id: String(index), job_type: 'course_generation', status: 'completed', created_at: '2026-11-10T00:00:00Z' })),
    });
    expect(model.content.jobsTruncated).toBe(true);
    expect(model.content.jobTotal).toBeNull();
    expect(model.content.activeJobs).toBeNull();
    expect(model.content.attentionJobs).toBeNull();
  });

  it('labels all local list limits including training and review slices', async () => {
    const original = apiMock.get.getMockImplementation()!;
    apiMock.get.mockImplementation((path, config) => {
      if (path === '/v1/admin/learning-actions') return Promise.resolve({ data: { ...actionCenter,
        summary: { ...actionCenter.summary, training_issue_count: 10 },
        training_items: Array.from({ length: 10 }, (_, index) => ({ ...actionCenter.training_items[0], enrollment_id: String(index) })),
      } });
      if (path === '/v1/courses?per_page=100') return Promise.resolve({ data: Array.from({ length: 8 }, (_, index) => ({ id: String(index), title: `Review ${index}`, status: 'draft', ai_generated: true, review_status: 'pending' })) });
      return original(path, config);
    });
    render(<MethodologistDashboard />);
    expect(await screen.findByText(/Показано 3 из 10/)).toBeVisible();
    expect(await screen.findByText(/Показано 5 из 8/)).toBeVisible();
    expect(screen.getByRole('link', { name: 'Все черновики' })).toHaveAttribute('href', '/courses?status=draft');
  });

  it.each([0, 2])('does not present a truncated source count of %i as a tenant total', async (count) => {
    const original = apiMock.get.getMockImplementation()!;
    apiMock.get.mockImplementation((path, config) => path === '/v1/admin/learning-actions'
      ? Promise.resolve({ data: { ...actionCenter,
        summary: { ...actionCenter.summary, training_issue_count: count, training_items_truncated: true },
        training_items: Array.from({ length: count }, (_, index) => ({ ...actionCenter.training_items[0], enrollment_id: String(index) })),
      } }) : original(path, config));
    render(<MethodologistDashboard />);
    expect(await screen.findByText(`Показано ${count}; общий итог неизвестен.`, { exact: false })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Проблемных назначений: —' })).toBeVisible();
    expect(screen.getAllByText(/Проверена только часть записей обучения/).length).toBeGreaterThan(0);
    const group = screen.getByRole('heading', { name: 'Проблемные назначения' }).parentElement?.parentElement;
    expect(group).not.toBeNull();
    expect(within(group!).queryByText(`Показано ${count} из ${count}.`, { exact: false })).not.toBeInTheDocument();
    if (count === 0) {
      expect(screen.getByText('В загруженной части списка таких задач нет.')).toBeVisible();
      expect(screen.queryByText('Сейчас нет выявленных проблем по обучению.')).not.toBeInTheDocument();
    }
  });

  it('retains exact source totals when only the visible three-item slice is limited', async () => {
    const original = apiMock.get.getMockImplementation()!;
    apiMock.get.mockImplementation((path, config) => path === '/v1/admin/learning-actions'
      ? Promise.resolve({ data: { ...actionCenter,
        summary: { ...actionCenter.summary, training_issue_count: 5, training_items_truncated: false },
        training_items: Array.from({ length: 5 }, (_, index) => ({ ...actionCenter.training_items[0], enrollment_id: String(index) })),
      } }) : original(path, config));
    render(<MethodologistDashboard />);
    expect(await screen.findByText(/Показано 3 из 5/)).toBeVisible();
    expect(screen.getByRole('link', { name: 'Проблемных назначений: 5' })).toBeVisible();
    expect(screen.queryByText(/Проверена только часть записей обучения/)).not.toBeInTheDocument();
  });
  it.each([
    ['ru', 'Сохранение или проверка результата', 'Не удалось создать курс'],
    ['en', 'Saving or result verification required', 'Course generation failed'],
    ['kk', 'Сақтау немесе нәтижені тексеру қажет', 'Курсты жасау мүмкін болмады'],
  ] as const)('shows reconciliation without claiming failure in %s', async (lang, label, failedLabel) => {
    useLanguageStore.setState({ lang });
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/v1/ai/jobs') return Promise.resolve({ data: [
        { id: 'job-reconcile', job_type: 'course_generation', status: 'reconciliation_required', stage: 'saving', created_at: '2026-09-24T10:00:00Z' },
      ] });
      return Promise.resolve({ data: path === '/v1/courses' ? [] : null });
    });
    render(<MethodologistDashboard />);
    expect(await screen.findByRole('button', { name: new RegExp(label) })).toBeInTheDocument();
    expect(screen.queryByText(failedLabel)).not.toBeInTheDocument();
  });
  it.each([99, 100])('does not claim complete totals from a full bounded catalogue (%s)', (count) => {
    const model = buildMethodologistDashboard({ learning: null, mandatory: null, jobs: [],
      courses: Array.from({ length: count }, (_, index) => ({ id: String(index), title: 'Course', status: 'published' })),
    });
    expect(model.content.coursesTruncated).toBe(count === 100);
    expect(model.content.totalCourses).toBe(count === 100 ? null : 99);
    expect(model.content.publishedCourses).toBe(count === 100 ? null : 99);
    expect(model.content.draftCourses).toBe(count === 100 ? null : 0);
  });
  it('counts every relevant generation while limiting only the visible job list', () => {
    const jobs = [
      ...Array.from({ length: 6 }, (_, index) => ({
        id: `active-${index}`,
        job_type: 'course_generation',
        status: 'running',
        created_at: `2026-09-24T10:0${index}:00Z`,
      })),
      {
        id: 'failed-1',
        job_type: 'course_generation',
        status: 'failed',
        created_at: '2026-09-24T09:00:00Z',
      },
      {
        id: 'completed-1',
        job_type: 'course_generation',
        status: 'completed',
        created_at: '2026-09-24T08:00:00Z',
      },
    ];

    const model = buildMethodologistDashboard({
      learning: null,
      courses: [],
      jobs,
      mandatory: null,
    });

    expect(model.content.activeJobs).toBe(6);
    expect(model.content.attentionJobs).toBe(1);
    expect(model.content.jobs).toHaveLength(5);
  });

  it('answers the operational questions from one learning read model', async () => {
    render(<MethodologistDashboard />);

    expect(await screen.findByRole('button', { name: /Сотрудник с риском/ })).toBeInTheDocument();
    expect(screen.getByText('40%')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Просрочено: 2' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Действий открыто: 2' })).toBeInTheDocument();
    expect(screen.getByText('Не удалось создать курс')).toBeInTheDocument();
    expect(screen.getByText('Этап: проверка качества · заявка 0228597d')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Без назначения: 2' })).toHaveAttribute('href', '/mandatory-training?action_required=materialize');
    expect(screen.getByRole('link', { name: 'Требует сверки: 1' })).toHaveAttribute('href', '/mandatory-training?action_required=review_stale');
    fireEvent.click(screen.getByRole('button', { name: /заявка 0228597d/ }));
    expect(within(screen.getByRole('region', { name: 'Детали задачи' })).getByRole('link', { name: 'Открыть задание генерации' })).toHaveAttribute(
      'href',
      '/ai/generate?job_id=0228597d-1111-4111-8111-111111111111',
    );
    expect(screen.getByRole('link', { name: 'Все курсы: 2' })).toHaveAttribute('href', '/courses');
    expect(screen.getByRole('link', { name: 'Опубликовано: 1' })).toHaveAttribute('href', '/courses?status=published');
    expect(screen.getByRole('link', { name: 'Черновики: 1' })).toHaveAttribute('href', '/courses?status=draft');
    expect(apiMock.get).toHaveBeenCalledWith('/v1/admin/learning-actions', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(apiMock.get).not.toHaveBeenCalledWith('/v1/admin/training-log/summary', expect.anything());
  });

  it('places actionable situations before the completion summary in DOM order', async () => {
    render(<MethodologistDashboard />);

    const attention = await screen.findByRole('heading', { name: 'Требует внимания' });
    const health = screen.getByRole('heading', { name: 'Состояние обучения' });

    expect(attention.compareDocumentPosition(health) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('links only truthful training metrics and exact priority assignments to canonical filters', async () => {
    render(<MethodologistDashboard />);

    const expectedReturn = 'return_to=%2Fdashboard';
    fireEvent.click(await screen.findByRole('button', { name: /Сотрудник с риском/ }));
    expect(within(screen.getByRole('region', { name: 'Детали задачи' })).getByRole('link', { name: 'Открыть запись в журнале' })).toHaveAttribute(
      'href',
      `/training-log?enrollment_id=11111111-1111-4111-8111-111111111111&course_id=22222222-2222-4222-8222-222222222222&${expectedReturn}`,
    );
    expect(screen.getByRole('link', { name: 'Не начали: 3' })).toHaveAttribute('href', `/training-log?status=assigned&${expectedReturn}`);
    expect(screen.getByRole('link', { name: 'В процессе: 3' })).toHaveAttribute('href', `/training-log?status=in_progress&${expectedReturn}`);
    expect(screen.getByRole('link', { name: 'Завершено: 4' })).toHaveAttribute('href', `/training-log?status=completed&${expectedReturn}`);
    expect(screen.getByRole('link', { name: 'Просрочено: 2' })).toHaveAttribute('href', `/training-log?status=overdue&${expectedReturn}`);
    expect(screen.getByRole('link', { name: 'Тест не пройден: 1' })).toHaveAttribute(
      'href',
      `/training-log?assessment_status=failed&${expectedReturn}`,
    );
    expect(screen.getByRole('link', { name: 'Попытки исчерпаны: 1' })).toHaveAttribute(
      'href',
      `/training-log?assessment_status=exhausted&${expectedReturn}`,
    );
    expect(screen.getByRole('link', { name: 'Действий открыто: 2' })).toHaveAttribute(
      'href',
      '/training-log?return_to=%2Fdashboard&action_focus=open#learning-action-center',
    );
  });

  it('keeps learning data unknown when the primary read model is unavailable', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/v1/admin/learning-actions') return Promise.reject(new Error('unavailable'));
      if (path === '/v1/admin/mandatory-training/summary') return Promise.reject(new Error('unavailable'));
      return Promise.resolve({ data: [] });
    });

    render(<MethodologistDashboard />);

    expect(await screen.findByRole('status')).toHaveTextContent('Сводка обучения временно недоступна');
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
    expect(screen.queryByTestId('training-overdue')).not.toBeInTheDocument();
  });

  it('updates one detail panel in place and does not retain selection across filters or tenants', async () => {
    render(<MethodologistDashboard />);
    const employee = await screen.findByRole('button', { name: /Сотрудник с риском/ });
    const job = screen.getByRole('button', { name: /заявка 0228597d/ });
    const panel = within(screen.getByRole('region', { name: 'Детали задачи' }));
    expect(panel.getByRole('link')).toHaveAttribute('href', expect.stringContaining('/training-log?'));
    const initialReads = apiMock.get.mock.calls.length;
    fireEvent.click(employee);
    expect(employee).toHaveAttribute('aria-pressed', 'true');
    expect(panel.getByText('25%')).toBeVisible();
    fireEvent.click(job);
    expect(employee).toHaveAttribute('aria-pressed', 'false');
    expect(job).toHaveAttribute('aria-pressed', 'true');
    expect(panel.queryByText('25%')).not.toBeInTheDocument();
    expect(panel.getByRole('link')).toHaveAttribute('href', '/ai/generate?job_id=0228597d-1111-4111-8111-111111111111');
    fireEvent.click(screen.getByRole('button', { name: 'Обучение сотрудников' }));
    expect(within(screen.getByRole('region', { name: 'Детали задачи' })).getByRole('link')).toHaveAttribute('href', expect.stringContaining('/training-log?'));
    expect(apiMock.get).toHaveBeenCalledTimes(initialReads);
    fireEvent.click(screen.getByRole('button', { name: /Сотрудник с риском/ }));
    const user = useAuthStore.getState().user!;
    apiMock.get.mockImplementation(() => new Promise(() => {}));
    act(() => useAuthStore.setState({ user: { ...user, tenant_id: 'tenant-2' } }));
    expect(screen.queryByText('Сотрудник с риском')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Детали задачи' })).not.toBeInTheDocument();
  });

  it('does not present unavailable generation or mandatory data as confirmed zero', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/v1/admin/learning-actions') return Promise.resolve({ data: actionCenter });
      if (path === '/v1/courses?per_page=100') return Promise.resolve({ data: [
        { id: 'course-1', title: 'Опубликованный курс', status: 'published' },
      ] });
      if (path === '/v1/ai/jobs') return Promise.reject(new Error('jobs unavailable'));
      if (path === '/v1/admin/mandatory-training/summary') return Promise.reject(new Error('mandatory unavailable'));
      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    render(<MethodologistDashboard />);

    expect(await screen.findByText('Данные о генерациях недоступны. Список не заменён нулём.')).toBeInTheDocument();
    expect(screen.queryByText('Активных или проблемных генераций нет.')).not.toBeInTheDocument();
    expect(screen.getByTestId('mandatory-missing-unavailable')).toHaveTextContent('—');
    expect(screen.getByTestId('mandatory-stale-unavailable')).toHaveTextContent('—');
  });

  it('labels canonical generation stages without a false preparation fallback', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/v1/admin/learning-actions') return Promise.resolve({ data: actionCenter });
      if (path === '/v1/courses?per_page=100') return Promise.resolve({ data: [
        { id: 'course-1', title: 'Опубликованный курс', status: 'published' },
      ] });
      if (path === '/v1/ai/jobs') return Promise.resolve({ data: [
        { id: 'job-a', job_type: 'course_generation', status: 'running', stage: 'content_generation', created_at: '2026-09-24T10:00:00Z' },
        { id: 'job-b', job_type: 'course_generation', status: 'failed', stage: 'failed', created_at: '2026-09-24T09:00:00Z' },
      ] });
      if (path === '/v1/admin/mandatory-training/summary') return Promise.resolve({ data: {
        total: 0, materialized: 0, missing_enrollment: 0, protected_assignment: 0,
        stale_managed_enrollment: 0, action_materialize: 0, action_review_stale: 0,
      } });
      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    render(<MethodologistDashboard />);

    expect(await screen.findByText('Этап: генерация содержания · заявка job-a')).toBeInTheDocument();
    expect(screen.getByText('Этап: ошибка · заявка job-b')).toBeInTheDocument();
    expect(screen.queryByText(/Этап: подготовка/)).not.toBeInTheDocument();
  });

  it('does not request learner-level data for a tenant admin', async () => {
    useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: 'admin', roles: ['admin'] } });

    const { container } = render(<MethodologistDashboard />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});
