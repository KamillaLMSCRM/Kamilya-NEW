import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/components/ui/Toast', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock('@/i18n/useT', () => {
  const t = (key: string) => key;
  return { useT: () => ({ t, lang: 'en' }) };
});

import LearningCyclesPage from '@/app/learning-cycles/page';
import { useAuthStore } from '@/store/authStore';

const activeHistoryOccurrence = {
  id: 'occurrence-1',
  rule_id: 'rule-1',
  sequence_no: 2,
  user_id: 'learner-1',
  target_type: 'course' as const,
  course_id: 'course-1',
  learning_path_id: null,
  original_due_at: '2030-01-10T10:00:00Z',
  effective_due_at: '2030-01-12T12:30:00Z',
  completed_at: null,
  status: 'assigned',
  is_active: true,
};

function mockLearningCycleData(history = [activeHistoryOccurrence]) {
  apiMock.get.mockImplementation(async (url: string, config?: { params?: Record<string, unknown> }) => {
    if (url === '/v1/learning-cycles/occurrences/course/occurrence-1/events') return { data: [{ id: 'event-1', previous_effective_due_at: '2030-01-10T10:00:00Z', effective_due_at: '2030-01-12T12:30:00Z', reason: 'The learner was assigned to an approved field project.', created_at: '2030-01-09T08:00:00Z' }] };
    if (url === '/v1/learning-cycles/occurrences' && config?.params?.scope === 'history') return { data: history };
    if (url === '/v1/learning-cycles' || url === '/v1/learning-cycles/occurrences') return { data: [] };
    if (url === '/v1/learning-paths') return { data: [] };
    if (url === '/v1/courses') return { data: [{ id: 'course-1', title: 'Safety', status: 'published', delivery_type: 'native' }] };
    if (url === '/v1/users') return { data: { users: [{ id: 'learner-1', full_name: 'Alex Kim' }] } };
    throw new Error(`Unexpected GET ${url}`);
  });
}

describe('learning cycles page catalogs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      accessToken: 'test-token',
      initialized: true,
      user: {
        user_id: 'methodologist-1',
        tenant_id: 'tenant-1',
        tenant: { id: 'tenant-1', name: 'Test tenant' },
        telegram_id: '',
        role: 'methodologist',
        roles: ['methodologist'],
        full_name: 'Methodologist',
        email: 'methodologist@example.test',
      },
    });
  });

  it('loads every course and learner page using backend-supported page sizes', async () => {
    apiMock.get.mockImplementation(async (url: string, config?: { params?: Record<string, number> }) => {
      if (url === '/v1/learning-cycles' || url === '/v1/learning-cycles/occurrences') return { data: [] };
      if (url === '/v1/learning-paths') return { data: [] };
      if (url === '/v1/courses') {
        const page = config?.params?.page;
        return {
          data: page === 1
            ? Array.from({ length: 100 }, (_, index) => ({
                id: `course-${index}`,
                title: `Course ${index}`,
                status: 'published',
                delivery_type: 'native',
              }))
            : [{ id: 'course-100', title: 'Course 100', status: 'published', delivery_type: 'native' }],
        };
      }
      if (url === '/v1/users') {
        const page = config?.params?.page;
        return {
          data: {
            users: page === 1
              ? Array.from({ length: 500 }, (_, index) => ({
                  id: `learner-${index}`,
                  full_name: `Learner ${index}`,
                }))
              : [{ id: 'learner-500', full_name: 'Learner 500' }],
          },
        };
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<LearningCyclesPage />);

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/courses',
      { params: { status: 'published', page: 2, per_page: 100 } },
    ));
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/users',
      { params: { role: 'student', is_active: true, page: 2, per_page: 500 } },
    ));
    expect(await screen.findByRole('option', { name: 'Course 100' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Learner 500' })).toBeInTheDocument();
  });

  it('explains cycle timing fields and disambiguates same-name learners', async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === '/v1/learning-cycles' || url === '/v1/learning-cycles/occurrences') return { data: [] };
      if (url === '/v1/learning-paths') return { data: [] };
      if (url === '/v1/courses') return { data: [
        { id: 'course-aaaa1111', title: 'Safety', status: 'published', delivery_type: 'native' },
        { id: 'course-bbbb2222', title: 'Safety', status: 'published', delivery_type: 'native' },
      ] };
      if (url === '/v1/users') return { data: { users: [
        { id: 'learner-1', full_name: 'Alex Kim', email: 'alex.one@example.test' },
        { id: 'learner-2', full_name: 'Alex Kim', employee_number: 'EMP-002' },
      ] } };
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<LearningCyclesPage />);

    expect(await screen.findByRole('option', { name: 'Alex Kim · alex.one@example.test' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Alex Kim · EMP-002' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Safety · course-a' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Safety · course-b' })).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: 'learningCycles.cadenceDays' })).toHaveAccessibleDescription('learningCycles.cadenceHint');
    expect(screen.getByRole('spinbutton', { name: 'learningCycles.dueDays' })).toHaveAccessibleDescription('learningCycles.dueHint');
  });

  it('requests complete history and renders original and effective deadlines', async () => {
    mockLearningCycleData();

    render(<LearningCyclesPage />);

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/learning-cycles/occurrences',
      { params: { scope: 'history' } },
    ));
    expect(await screen.findByText(new Date(activeHistoryOccurrence.original_due_at).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText(new Date(activeHistoryOccurrence.effective_due_at).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText('learningCycles.deadlineAdjusted')).toBeInTheDocument();
    expect(screen.getAllByText('Safety').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Alex Kim').length).toBeGreaterThan(0);
    expect(screen.getByText('learningCycles.occurrence.assigned')).toBeInTheDocument();
  });

  it('requires an override reason of at least 20 characters', async () => {
    mockLearningCycleData();
    render(<LearningCyclesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'learningCycles.overrideDeadline' }));
    fireEvent.change(screen.getByLabelText('learningCycles.overrideDeadlineLabel'), { target: { value: '2030-01-15T09:45' } });
    fireEvent.change(screen.getByLabelText('learningCycles.overrideReason'), { target: { value: 'Too short a reason.' } });
    fireEvent.submit(screen.getByRole('button', { name: 'learningCycles.overrideSave' }).closest('form')!);

    expect(await screen.findByRole('alert')).toHaveTextContent('learningCycles.overrideReasonError');
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('loads and shows the append-only deadline change reason on demand', async () => {
    mockLearningCycleData();
    render(<LearningCyclesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'learningCycles.historyTitle' }));

    expect(await screen.findByText('The learner was assigned to an approved field project.')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/v1/learning-cycles/occurrences/course/occurrence-1/events');
  });

  it('keeps deadline event history available after the deadline is restored to its original value', async () => {
    const restoredOccurrence = {
      ...activeHistoryOccurrence,
      effective_due_at: activeHistoryOccurrence.original_due_at,
    };
    mockLearningCycleData([restoredOccurrence]);
    render(<LearningCyclesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'learningCycles.historyTitle' }));

    expect(await screen.findByText('The learner was assigned to an approved field project.')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/v1/learning-cycles/occurrences/course/occurrence-1/events');
  });

  it('posts a timezone-aware deadline override and reloads the page data', async () => {
    mockLearningCycleData();
    apiMock.post.mockResolvedValue({ data: {} });
    render(<LearningCyclesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'learningCycles.overrideDeadline' }));
    const localDeadline = '2030-01-15T09:45';
    const reason = 'Business schedule changed for the learner.';
    fireEvent.change(screen.getByLabelText('learningCycles.overrideDeadlineLabel'), { target: { value: localDeadline } });
    fireEvent.change(screen.getByLabelText('learningCycles.overrideReason'), { target: { value: reason } });
    fireEvent.submit(screen.getByRole('button', { name: 'learningCycles.overrideSave' }).closest('form')!);

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/learning-cycles/occurrences/course/occurrence-1/deadline-override',
      { effective_due_at: new Date(localDeadline).toISOString(), reason },
    ));
    await waitFor(() => expect(apiMock.get.mock.calls.filter(([url, config]) => (
      url === '/v1/learning-cycles/occurrences'
      && (config as { params?: { scope?: string } } | undefined)?.params?.scope === 'history'
    ))).toHaveLength(2));
  });
});
