import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));

import {
  canUseLearningInsights,
  LearnerAnswers,
  LearningInsightsPanel,
} from '@/features/learning-insights/LearningInsights';
import { getCourseInsights } from '@/features/learning-insights/api';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.mocked(api);
const verifiedQuestion = {
  question_id: 'question-1',
  question_key: 'key-1',
  text: 'Which control is required?',
  type: 'single_choice',
  explanation: 'Use the approved control.',
  is_correct: false,
  points_earned: 0,
  points_possible: 1,
  choices: [
    { id: 'a', text: 'Skip it', selected: true, correct: false },
    { id: 'b', text: 'Approved control', selected: false, correct: true },
  ],
  review: { status: 'unreviewed' as const, updated_at: null },
};

function aggregate(courseId = 'course-1', question = {}) {
  return {
    course_id: courseId,
    course_title: 'Safety',
    cohort_basis: 'current_structure' as const,
    attempt_basis: 'first_completed' as const,
    included_employees: 3,
    excluded_attempts: 1,
    questions: [{
      question_key: 'key-1',
      question_id: 'question-1',
      quiz_id: 'quiz-1',
      quiz_title: 'Safety quiz',
      content_release_id: 'release-2026-09',
      text: 'Which control is required?',
      lesson_id: 'lesson-1',
      respondents: 3,
      incorrect: 2,
      incorrect_percent: 67,
      latest_respondents: 1,
      latest_unavailable: 0,
      latest_incorrect: 1,
      latest_incorrect_percent: 100,
      improved: 1,
      regressed: 0,
      wrong_choices: [{ id: 'a', text: 'Skip it', count: 2 }],
      review: { status: 'unreviewed', updated_at: null },
      example_attempt_id: 'attempt-1',
      ...question,
    }],
  };
}

function enrollment(courseId = 'course-1') {
  return {
    enrollment_id: 'enrollment-1',
    user_name: 'Synthetic employee',
    course_id: courseId,
    course_title: 'Safety',
    attempts: [{
      id: 'attempt-1',
      quiz_id: 'quiz-1',
      quiz_title: 'Safety quiz',
      content_release_id: 'release-2026-09',
      completed_at: '2026-09-06T10:00:00Z',
      attempt_number: 1,
      score_percent: 0,
      passed: false,
      evidence_status: 'verified',
      lesson_id: 'lesson-1',
      questions: [verifiedQuestion],
    }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

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
});

describe('learning insights panel', () => {
  it('does not make an aggregate request until a course is selected', () => {
    render(<LearningInsightsPanel />);
    expect(screen.getByText(/Select a course|Выберите курс|Журналдан курсты/i)).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it('encodes HTML day filters as Kazakhstan aware inclusive boundaries and preserves aware values', async () => {
    apiMock.get.mockResolvedValue({ data: aggregate() });
    await getCourseInsights('course-1', {
      dateFrom: '2026-09-01',
      dateTo: '2026-09-06',
    });
    expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/admin/learning-insights/courses/course-1?date_from=2026-09-01T00%3A00%3A00%2B05%3A00&date_to=2026-09-06T23%3A59%3A59.999999%2B05%3A00',
    );

    apiMock.get.mockClear();
    await getCourseInsights('course-1', {
      dateFrom: '2026-09-01T08:30:00+05:00',
      dateTo: '2026-09-06T18:00:00Z',
    });
    expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/admin/learning-insights/courses/course-1?date_from=2026-09-01T08%3A30%3A00%2B05%3A00&date_to=2026-09-06T18%3A00%3A00Z',
    );
  });

  it('renders first/latest denominators, release identity, sample warning, and neutral triage', async () => {
    apiMock.get.mockResolvedValueOnce({ data: aggregate() });
    render(<LearningInsightsPanel courseId="course-1" departmentId="department-1" dateFrom="2026-09-01" dateTo="2026-09-06" />);
    expect(await screen.findByText('Which control is required?')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/v1/admin/learning-insights/courses/course-1?department_id=department-1&date_from=2026-09-01T00%3A00%3A00%2B05%3A00&date_to=2026-09-06T23%3A59%3A59.999999%2B05%3A00');
    expect(screen.getByText(/Small sample|Малая выборка|Шағын іріктеме/i)).toBeInTheDocument();
    expect(screen.getByText(/Recurring error|Повторяющаяся ошибка|Қайталанатын қате/i)).toBeInTheDocument();
    expect(screen.getByText('2/3 (67%)')).toBeInTheDocument();
    expect(screen.getByText('1/1 (100%)')).toBeInTheDocument();
    expect(screen.getByText(/Release\/version|Релиз\/версия|Релиз\/нұсқа/i)).toBeInTheDocument();
  });

  it('shows a dash and the missing latest-comparison count when latest is unavailable', async () => {
    apiMock.get.mockResolvedValueOnce({
      data: aggregate('course-1', {
        latest_respondents: 0,
        latest_unavailable: 2,
        latest_incorrect: 0,
        latest_incorrect_percent: null,
      }),
    });
    render(<LearningInsightsPanel courseId="course-1" />);
    expect(await screen.findByText('0/0 (—)')).toBeInTheDocument();
    expect(screen.getByText(/Latest comparison unavailable.*2|Сравнение с последней.*2|Соңғы.*2/i)).toBeInTheDocument();
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });

  it('does not render old aggregate data while course or tenant scope changes, including a late response', async () => {
    const oldResult = aggregate('course-1', { text: 'Old scope question' });
    const newResult = aggregate('course-2', { text: 'New scope question' });
    const oldRequest = deferred<{ data: ReturnType<typeof aggregate> }>();
    const newRequest = deferred<{ data: ReturnType<typeof aggregate> }>();
    apiMock.get.mockImplementation((url) => url.includes('course-1') ? oldRequest.promise : newRequest.promise);

    const { rerender } = render(<LearningInsightsPanel courseId="course-1" />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
    rerender(<LearningInsightsPanel courseId="course-2" />);
    expect(screen.queryByText('Old scope question')).not.toBeInTheDocument();
    await act(async () => oldRequest.resolve({ data: oldResult }));
    await Promise.resolve();
    expect(screen.queryByText('Old scope question')).not.toBeInTheDocument();
    await act(async () => newRequest.resolve({ data: newResult }));
    expect(await screen.findByText('New scope question')).toBeInTheDocument();

    const tenantRequest = deferred<{ data: ReturnType<typeof aggregate> }>();
    apiMock.get.mockImplementationOnce(() => tenantRequest.promise);
    act(() => useAuthStore.setState({ user: { ...useAuthStore.getState().user!, tenant_id: 'tenant-2', tenant: { id: 'tenant-2', name: 'Other tenant' } } }));
    expect(screen.queryByText('New scope question')).not.toBeInTheDocument();
    tenantRequest.resolve({ data: aggregate('course-2', { text: 'Tenant two question' }) });
    expect(await screen.findByText('Tenant two question')).toBeInTheDocument();
  });

  it('keeps learning-insights role gating tenant-bound', () => {
    expect(canUseLearningInsights({ role: 'methodologist', tenant_id: 'tenant-1' })).toBe(true);
    expect(canUseLearningInsights({ role: 'methodologist', tenant_id: null })).toBe(false);
    expect(canUseLearningInsights({ role: 'superadmin', tenant_id: 'tenant-1' })).toBe(false);
    expect(canUseLearningInsights({ role: 'superadmin', tenant_id: null })).toBe(false);
    expect(canUseLearningInsights({ role: 'admin', tenant_id: 'tenant-1' })).toBe(false);
    expect(canUseLearningInsights({ role: 'student', tenant_id: 'tenant-1' })).toBe(false);
  });

  it('loads the tenant course catalog behind the learning-insights role gate for both responsive journal actions', () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), 'src/app/admin/training-log/page.tsx'),
      'utf8',
    );
    const featureSource = fs.readFileSync(
      path.join(process.cwd(), 'src/features/learning-insights/LearningInsights.tsx'),
      'utf8',
    );
    expect(source).toContain("api.get<Array<{ id: string; title: string }>>('/v1/courses')");
    expect(source).toContain('{canInspectLearning && (');
    expect(featureSource).toContain('setSaving(pendingReviews.has(reviewKey));');
  });
});

describe('learner answer dialog', () => {
  it('renders selected/correct labels and quiz release, while hiding unavailable evidence detail', async () => {
    apiMock.get.mockResolvedValueOnce({ data: {
      ...enrollment(),
      attempts: [
        ...enrollment().attempts,
        { id: 'attempt-2', quiz_id: 'quiz-1', quiz_title: 'Safety quiz', content_release_id: null, completed_at: '2026-09-06T11:00:00Z', attempt_number: 2, score_percent: 0, passed: false, evidence_status: 'unavailable', lesson_id: null, questions: [] },
      ],
    } });
    render(<LearnerAnswers enrollmentId="enrollment-1" onClose={vi.fn()} />);
    expect(await screen.findByText('Which control is required?')).toBeInTheDocument();
    expect(screen.getByText(/Selected by employee|Выбрано сотрудником|Қызметкер таңдады/i)).toBeInTheDocument();
    expect(screen.getByText(/Correct answer|Правильный ответ|Дұрыс жауап/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Release\/version|Релиз\/версия|Релиз\/нұсқа/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/historical evidence.*unavailable|Историческое доказательство.*недоступно|тарихи дәлелі.*қолжетімсіз/i)).toBeInTheDocument();
  });

  it('exposes accessible expanded state for attempt details', async () => {
    apiMock.get.mockResolvedValueOnce({ data: enrollment() });
    render(<LearnerAnswers enrollmentId="enrollment-1" onClose={vi.fn()} />);
    const toggle = await screen.findByRole('button', { name: /Attempt|Попытка|Талпыныс/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(toggle).toHaveAttribute('aria-controls');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('synchronizes successful triage across aggregate and answer copies for one tenant/course/question', async () => {
    apiMock.get.mockImplementation((url) => Promise.resolve({ data: url.includes('/courses/') ? aggregate() : enrollment() }));
    apiMock.put.mockResolvedValue({ data: { status: 'resolved', updated_at: '2026-09-06T12:00:00Z' } });
    render(
      <>
        <LearningInsightsPanel courseId="course-1" />
        <LearnerAnswers enrollmentId="enrollment-1" onClose={vi.fn()} />
      </>,
    );
    await waitFor(() => expect(screen.getAllByLabelText(/Methodologist decision|Решение методиста|Әдіскер шешімі/)).toHaveLength(2));
    const controls = screen.getAllByLabelText(/Methodologist decision|Решение методиста|Әдіскер шешімі/);
    fireEvent.change(controls[0], { target: { value: 'resolved' } });
    await waitFor(() => controls.forEach((control) => expect(control).toHaveValue('resolved')));
  });

  it('serializes pending saves across two mounted copies of the same question', async () => {
    let finishFirst!: (value: unknown) => void;
    apiMock.get.mockImplementation((url) => Promise.resolve({ data: url.includes('/courses/') ? aggregate() : enrollment() }));
    apiMock.put.mockImplementationOnce(() => new Promise((resolve) => { finishFirst = resolve; }));
    render(<><LearningInsightsPanel courseId="course-1" /><LearnerAnswers enrollmentId="enrollment-1" onClose={vi.fn()} /></>);
    await waitFor(() => expect(screen.getAllByLabelText(/Methodologist decision|Решение методиста|Әдіскер шешімі/)).toHaveLength(2));
    const controls = screen.getAllByLabelText(/Methodologist decision|Решение методиста|Әдіскер шешімі/);
    fireEvent.change(controls[0], { target: { value: 'train_staff' } });
    await waitFor(() => controls.forEach((control) => expect(control).toBeDisabled()));
    // Even a programmatic event on the other disabled copy must not send a race.
    fireEvent.change(controls[1], { target: { value: 'resolved' } });
    expect(apiMock.put).toHaveBeenCalledTimes(1);
    await act(async () => finishFirst({ data: { status: 'train_staff', updated_at: '2026-09-06T12:00:00Z' } }));
    await waitFor(() => controls.forEach((control) => {
      expect(control).toBeEnabled();
      expect(control).toHaveValue('train_staff');
    }));
    apiMock.put.mockResolvedValueOnce({ data: { status: 'resolved', updated_at: '2026-09-06T12:01:00Z' } });
    fireEvent.change(controls[1], { target: { value: 'resolved' } });
    await waitFor(() => controls.forEach((control) => expect(control).toHaveValue('resolved')));
  });

  it('does not refetch or interrupt a pending review save on an equivalent parent rerender', async () => {
    const save = deferred<{ data: { status: 'resolved'; updated_at: string } }>();
    apiMock.get.mockResolvedValue({ data: aggregate() });
    apiMock.put.mockReturnValueOnce(save.promise as never);
    const props = { courseId: 'course-1', dateFrom: '2026-09-01', dateTo: '2026-09-06' };
    const { rerender } = render(<LearningInsightsPanel {...props} />);
    const select = await screen.findByLabelText(/Methodologist decision|Решение методиста|Әдіскер шешімі/i);

    fireEvent.change(select, { target: { value: 'resolved' } });
    await waitFor(() => expect(select).toBeDisabled());
    rerender(<LearningInsightsPanel {...props} />);

    expect(apiMock.get).toHaveBeenCalledTimes(1);
    expect(select).toBeDisabled();
    await act(async () => save.resolve({ data: { status: 'resolved', updated_at: '2026-09-06T12:00:00Z' } }));
    await waitFor(() => expect(select).toHaveValue('resolved'));
    rerender(<LearningInsightsPanel {...props} />);
    expect(select).toHaveValue('resolved');
  });

  it('keeps the displayed review at its server value when a save fails and offers retry', async () => {
    apiMock.get.mockResolvedValueOnce({ data: enrollment() });
    apiMock.put.mockRejectedValueOnce(new Error('synthetic save failure'));
    render(<LearnerAnswers enrollmentId="enrollment-1" onClose={vi.fn()} />);
    const select = await screen.findByLabelText(/Methodologist decision|Решение методиста|Әдіскер шешімі/i);
    fireEvent.change(select, { target: { value: 'resolved' } });
    await screen.findByText(/save could not be confirmed|Не удалось подтвердить сохранение|Сақтауды растау мүмкін болмады/i);
    expect(select).toHaveValue('unreviewed');
    expect(apiMock.put).toHaveBeenCalledWith('/v1/admin/learning-insights/attempts/attempt-1/questions/question-1/review', { status: 'resolved' });
    fireEvent.click(screen.getByRole('button', { name: /Retry|Повторить|Қайталау/i }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(2));
  });
});
