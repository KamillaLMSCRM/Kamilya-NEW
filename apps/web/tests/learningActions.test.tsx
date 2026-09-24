import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { LearningActionCenter } from '@/features/learning-actions/LearningActionCenter';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.mocked(api);
const questionKey = 'a'.repeat(64);

const payload = {
  summary: { training_issue_count: 1, training_issue_counts: { overdue: 1 }, training_items_truncated: false, weak_question_count: 1, action_count: 1, actions_truncated: false, open_action_count: 1, overdue_action_count: 1 },
  training_items: [{
    enrollment_id: 'enrollment-1',
    user_id: 'user-1',
    full_name: 'Synthetic Learner',
    course_id: 'course-1',
    course_title: 'Safety',
    issue_type: 'overdue',
    progress_percent: 20,
    best_score: 40,
    quiz_attempts_count: 2,
    assignment_due_at: '2026-09-20T10:00:00Z',
    active_action_id: null,
    active_action_types: [],
  }],
  weak_questions: [{
    question_key: questionKey,
    question_id: 'question-1',
    quiz_id: 'quiz-1',
    content_release_id: 'release-1',
    text: 'Which control is required?',
    quiz_title: 'Safety quiz',
    respondents: 8,
    incorrect_percent: 62.5,
    active_action_id: null,
    active_action_types: [],
  }],
  actions: [{
    id: 'action-1',
    tenant_id: 'tenant-1',
    target_type: 'enrollment',
    target_key: 'enrollment:enrollment-2',
    enrollment_id: 'enrollment-2',
    course_id: 'course-1',
    quiz_id: null,
    content_release_id: null,
    question_id: null,
    question_key: null,
    issue_type: 'stalled',
    action_type: 'manual_review',
    status: 'open',
    owner_id: 'methodologist-1',
    created_by: 'methodologist-1',
    due_at: null,
    comment: 'Check the blocker',
    baseline_snapshot: { progress_percent: 10 },
    outcome_snapshot: null,
    resolution: null,
    resolution_note: null,
    created_at: '2026-09-24T10:00:00Z',
    updated_at: '2026-09-24T10:00:00Z',
    closed_at: null,
  }],
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
      full_name: 'Methodologist',
      email: 'methodologist@example.test',
    },
  });
  apiMock.get.mockResolvedValue({ data: payload });
  apiMock.post.mockResolvedValue({ data: payload.actions[0] });
});

describe('learning action center', () => {
  it('fails safe to an empty state for a stale or incomplete API payload', async () => {
    apiMock.get.mockResolvedValueOnce({ data: { items: [] } });
    render(<LearningActionCenter />);

    expect(await screen.findByText(/There are no situations|Сейчас нет ситуаций|жағдай жоқ/i)).toBeInTheDocument();
  });

  it('shows current occurrence issues, privacy-safe weak questions, and open actions', async () => {
    render(<LearningActionCenter courseId="course-1" />);

    expect(await screen.findByText('Synthetic Learner')).toBeInTheDocument();
    expect(screen.getByText('Which control is required?')).toBeInTheDocument();
    expect(screen.getByText('Check the blocker')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/v1/admin/learning-actions?course_id=course-1');
  });

  it('warns when the server returns a bounded partial list', async () => {
    apiMock.get.mockResolvedValueOnce({
      data: { ...payload, summary: { ...payload.summary, training_items_truncated: true } },
    });
    render(<LearningActionCenter courseId="course-1" />);

    expect(await screen.findByRole('status')).toHaveTextContent(/Only part|Показана только часть|бір бөлігі/i);
  });

  it('allows another action type while disabling the already active type', async () => {
    apiMock.get.mockResolvedValueOnce({
      data: {
        ...payload,
        training_items: [{ ...payload.training_items[0], active_action_id: 'action-reminder', active_action_types: ['reminder'] }],
      },
    });
    render(<LearningActionCenter courseId="course-1" />);
    await screen.findByText('Synthetic Learner');
    fireEvent.click(screen.getAllByRole('button', { name: /Create action|Создать действие|Әрекет құру/i })[0]);

    const select = screen.getByLabelText(/Action type|Тип действия|Әрекет түрі/i);
    expect(select).toHaveValue('reassignment');
    expect(screen.getByRole('option', { name: /Send reminder|Напомнить|Еске салу/i })).toBeDisabled();
  });

  it('creates an occurrence-bound action and reloads the center', async () => {
    render(<LearningActionCenter courseId="course-1" />);
    await screen.findByText('Synthetic Learner');

    fireEvent.click(screen.getAllByRole('button', { name: /Create action|Создать действие|Әрекет құру/i })[0]);
    fireEvent.change(screen.getByLabelText(/Action type|Тип действия|Әрекет түрі/i), {
      target: { value: 'reassignment' },
    });
    fireEvent.change(screen.getByLabelText(/Comment|Комментарий|Түсініктеме/i), {
      target: { value: 'Repeat the mandatory course' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Save action|Сохранить действие|Әрекетті сақтау/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/learning-actions', expect.objectContaining({
      target_type: 'enrollment',
      enrollment_id: 'enrollment-1',
      issue_type: 'overdue',
      action_type: 'reassignment',
      comment: 'Repeat the mandatory course',
    })));
    expect(apiMock.get).toHaveBeenCalledTimes(2);
  });

  it('closes an action through the explicit observed-outcome seam', async () => {
    render(<LearningActionCenter courseId="course-1" />);
    await screen.findByText('Check the blocker');
    fireEvent.click(screen.getByRole('button', { name: /Record outcome|Зафиксировать результат|Нәтижені тіркеу/i }));
    fireEvent.click(screen.getByRole('button', { name: /Close action|Закрыть действие|Әрекетті жабу/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/admin/learning-actions/action-1/close',
      { resolution: 'observed', note: null },
    ));
  });

  it('requires a note for a manual outcome before closing', async () => {
    render(<LearningActionCenter courseId="course-1" />);
    await screen.findByText('Check the blocker');
    fireEvent.click(screen.getByRole('button', { name: /Record outcome|Зафиксировать результат|Нәтижені тіркеу/i }));
    fireEvent.change(screen.getByLabelText(/How it ended|Как завершено|Қалай аяқталды/i), {
      target: { value: 'manual' },
    });

    expect(screen.getByRole('button', { name: /Close action|Закрыть действие|Әрекетті жабу/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Outcome explanation|Пояснение результата|Нәтиже түсіндірмесі/i), {
      target: { value: 'Reviewed with the learner' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Close action|Закрыть действие|Әрекетті жабу/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/admin/learning-actions/action-1/close',
      { resolution: 'manual', note: 'Reviewed with the learner' },
    ));
  });

  it('keeps the form open and shows a recoverable error when saving fails', async () => {
    apiMock.post.mockRejectedValueOnce(new Error('synthetic failure'));
    render(<LearningActionCenter courseId="course-1" />);
    await screen.findByText('Synthetic Learner');

    fireEvent.click(screen.getAllByRole('button', { name: /Create action|Создать действие|Әрекет құру/i })[0]);
    fireEvent.click(screen.getByRole('button', { name: /Save action|Сохранить действие|Әрекетті сақтау/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not save|Не удалось сохранить|сақтау мүмкін болмады/i);
    expect(screen.getByRole('button', { name: /Save action|Сохранить действие|Әрекетті сақтау/i })).toBeInTheDocument();
  });

  it('creates a question action with the full immutable question identity', async () => {
    render(<LearningActionCenter courseId="course-1" />);
    await screen.findByText('Which control is required?');

    fireEvent.click(screen.getAllByRole('button', { name: /Create action|Создать действие|Әрекет құру/i })[1]);
    fireEvent.click(screen.getByRole('button', { name: /Save action|Сохранить действие|Әрекетті сақтау/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/learning-actions', expect.objectContaining({
      target_type: 'question',
      course_id: 'course-1',
      quiz_id: 'quiz-1',
      content_release_id: 'release-1',
      question_id: 'question-1',
      question_key: questionKey,
      issue_type: 'weak_question',
    })));
  });
});
