import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  assignmentSourceLabel,
  formatAssignmentDueAt,
  safeResumeHref,
  selectNextAssignment,
  studentDailyLearningCopy,
  type LearnerAssignment,
} from '@/features/student-daily-learning/nextAssignment';

const authState = vi.hoisted(() => ({ token: 'learner-token' }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { accessToken: string | null }) => unknown) => selector({ accessToken: authState.token }),
}));
vi.mock('@/store/languageStore', () => ({
  useLanguageStore: (selector: (state: { lang: 'ru' }) => unknown) => selector({ lang: 'ru' }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: (key: string) => key, tp: (key: string) => key }),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => <a href={href} {...props}>{children}</a>,
}));
vi.mock('@/components/ui', () => {
  const Wrapper = ({ children, ...props }: { children: React.ReactNode }) => <div {...props}>{children}</div>;
  const Card = ({ children, ...props }: { children: React.ReactNode }) => <article {...props}>{children}</article>;
  const Button = ({ children, ...props }: { children: React.ReactNode; onClick?: () => void }) => <button {...props}>{children}</button>;
  return {
    Card,
    CardHeader: Wrapper,
    CardTitle: Wrapper,
    CardContent: Wrapper,
    Button,
    Badge: Wrapper,
  };
});

import StudentDashboardPage from '@/app/student/page';

const course = (overrides: Partial<LearnerAssignment> = {}): LearnerAssignment => ({
  course_id: '123e4567-e89b-42d3-a456-426614174000',
  title: 'Course',
  enrollment_status: 'in_progress',
  enrolled_at: '2026-09-01T00:00:00Z',
  assignment_due_at: null,
  assignment_source: 'manual',
  resume_href: null,
  ...overrides,
});

describe('learner daily assignment selection', () => {
  it('selects overdue or earliest actual deadline before undated work', () => {
    const undated = course({ course_id: '123e4567-e89b-42d3-a456-426614174001' });
    const later = course({
      course_id: '123e4567-e89b-42d3-a456-426614174002',
      assignment_due_at: '2026-10-20T00:00:00Z',
    });
    const earliest = course({
      assignment_due_at: '2026-09-20T00:00:00Z',
    });
    expect(selectNextAssignment([undated, later, earliest])).toBe(earliest);
  });

  it('ignores completed enrollments even when lesson progress is under 100 percent', () => {
    const completed = course({ enrollment_status: 'completed', progress_percent: 10 });
    const unfinished = course({
      course_id: '123e4567-e89b-42d3-a456-426614174001',
      enrollment_status: 'in_progress',
      progress_percent: 100,
    });
    expect(selectNextAssignment([completed, unfinished])).toBe(unfinished);
  });

  it('returns no recommendation for empty or completed-only assignments', () => {
    expect(selectNextAssignment([])).toBeNull();
    expect(selectNextAssignment([course({ enrollment_status: 'completed' })])).toBeNull();
  });

  it('uses enrollment identity to order duplicate-course occurrences deterministically and ignores invalid dates', () => {
    const second = course({ enrollment_id: 'b', assignment_due_at: 'not-a-date' });
    const first = course({ enrollment_id: 'a', assignment_due_at: 'not-a-date' });
    expect(selectNextAssignment([second, first])).toBe(first);
    expect(formatAssignmentDueAt('not-a-date', 'ru')).toBeNull();
  });

  it('skips an older non-resumable occurrence even when its deadline is earlier', () => {
    const olderUrgent = course({
      enrollment_id: 'older',
      assignment_due_at: '2026-09-01T00:00:00Z',
      can_resume: false,
      resume_href: null,
    });
    const currentDefault = course({
      enrollment_id: 'current',
      assignment_due_at: null,
      can_resume: true,
    });
    expect(selectNextAssignment([olderUrgent, currentDefault])).toBe(currentDefault);
    expect(selectNextAssignment([course()])?.can_resume).toBeUndefined();
  });

  it('allows only the exact relative course route with an optional lesson UUID', () => {
    const id = '123e4567-e89b-42d3-a456-426614174000';
    expect(safeResumeHref(course({ resume_href: `/courses/${id}` }))).toBe(`/courses/${id}`);
    expect(safeResumeHref(course({ resume_href: `/courses/${id}?lessonId=123e4567-e89b-42d3-a456-426614174001` })))
      .toBe(`/courses/${id}?lessonId=123e4567-e89b-42d3-a456-426614174001`);
    expect(safeResumeHref(course({ resume_href: 'https://example.com/courses/other' }))).toBe(`/courses/${id}`);
    expect(safeResumeHref(course({ resume_href: `/courses/${id}/edit` }))).toBe(`/courses/${id}`);
    expect(safeResumeHref(course({ course_id: '../admin', resume_href: '/../admin' }))).toBe('/courses');
  });

  it('localizes assignment sources and learner error recovery in all supported languages', () => {
    expect(assignmentSourceLabel('learning_path', 'ru')).toBe('По учебному пути');
    expect(assignmentSourceLabel('learning_path', 'kk')).toBe('Оқу жолы бойынша');
    expect(assignmentSourceLabel('learning_path', 'en')).toBe('By learning path');
    expect(studentDailyLearningCopy.ru.retry).toBeTruthy();
    expect(studentDailyLearningCopy.kk.loadError).toBeTruthy();
    expect(studentDailyLearningCopy.en.due).toBe('Due');
  });
});

describe('student dashboard request state', () => {
  beforeEach(() => {
    authState.token = 'learner-token';
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('shows a recoverable error and retries the authenticated request', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          user_id: 'learner', full_name: 'Learner', enrolled_courses: [], total_courses: 0,
          completed_courses: 0, total_progress_percent: 0, certificates_count: 0,
        }),
      });
    vi.stubGlobal('fetch', fetchMock);
    render(<StudentDashboardPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить обучение');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('student.enrolledCourses')).toBeInTheDocument();
  });

  it('labels completed courses as viewing the result while preserving active CTAs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        user_id: 'learner', full_name: 'Learner',
        enrolled_courses: [
          { course_id: 'completed-course', title: 'Completed', description: '', enrollment_status: 'completed', can_resume: true, progress_percent: 100, total_lessons: 1, completed_lessons: 1 },
          { course_id: 'active-course', title: 'Active', description: '', enrollment_status: 'in_progress', can_resume: true, progress_percent: 50, total_lessons: 2, completed_lessons: 1 },
          { course_id: 'new-course', title: 'New', description: '', enrollment_status: 'in_progress', can_resume: true, progress_percent: 0, total_lessons: 2, completed_lessons: 0 },
        ],
        total_courses: 3, completed_courses: 1, total_progress_percent: 50, certificates_count: 1,
      }),
    }));
    render(<StudentDashboardPage />);

    expect(await screen.findByText('courses.viewResult')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'courses.viewResult' })).toHaveAttribute('href', '/courses/completed-course');
    expect(screen.getAllByRole('link', { name: 'courses.continueCourse' }).some((link) => link.getAttribute('href') === '/courses/active-course')).toBe(true);
    expect(screen.getAllByText('courses.continueCourse').length).toBeGreaterThan(0);
    expect(screen.getByText('courses.startCourse')).toBeInTheDocument();
  });

  it('keeps a previous occurrence visible without a course link and explains the access boundary', async () => {
    const courseId = '123e4567-e89b-42d3-a456-426614174000';
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        user_id: 'learner', full_name: 'Learner',
        enrolled_courses: [
          {
            enrollment_id: 'older', course_id: courseId, title: 'Older assignment',
            description: '', status: 'published', enrollment_status: 'in_progress', delivery_type: 'native',
            can_resume: false, progress_percent: 20, total_lessons: 5, completed_lessons: 1,
            enrolled_at: '2026-09-01T00:00:00Z', thumbnail_url: null,
            assignment_due_at: '2026-09-15T00:00:00Z', assignment_source: 'manual', resume_href: null,
          },
          {
            enrollment_id: 'current', course_id: courseId, title: 'Current assignment',
            description: '', status: 'published', enrollment_status: 'in_progress', delivery_type: 'native',
            can_resume: true, progress_percent: 0, total_lessons: 5, completed_lessons: 0,
            enrolled_at: '2026-09-20T00:00:00Z', thumbnail_url: null,
            assignment_due_at: null, assignment_source: 'manual', resume_href: `/courses/${courseId}`,
          },
        ],
        total_courses: 2, completed_courses: 0, total_progress_percent: 10, certificates_count: 0,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<StudentDashboardPage />);

    const olderTitle = await screen.findByText('Older assignment');
    const olderCard = olderTitle.closest('article');
    expect(olderCard).not.toBeNull();
    expect(olderCard?.querySelector('a')).toBeNull();
    expect(olderCard).toHaveTextContent('Продолжение этого назначения пока недоступно');
    expect(screen.getAllByText('Current assignment').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link').some((link) => link.getAttribute('href') === `/courses/${courseId}`)).toBe(true);
  });

  it('keeps the access boundary ahead of the completed result action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        user_id: 'learner', full_name: 'Learner',
        enrolled_courses: [{ course_id: 'locked-completed', title: 'Locked completed', description: '', enrollment_status: 'completed', can_resume: false, progress_percent: 100, total_lessons: 1, completed_lessons: 1 }],
        total_courses: 1, completed_courses: 1, total_progress_percent: 100, certificates_count: 1,
      }),
    }));
    render(<StudentDashboardPage />);
    expect(await screen.findByText('Locked completed')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Продолжение этого назначения пока недоступно');
    expect(screen.queryByRole('link', { name: 'courses.viewResult' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'courses.viewCertificate' })).toHaveAttribute('href', '/certificates');
  });

  it('aborts and ignores an old identity response after the auth token changes', async () => {
    let resolveOld!: (value: { ok: boolean; json: () => Promise<unknown> }) => void;
    const oldResponse = new Promise<{ ok: boolean; json: () => Promise<unknown> }>((resolve) => { resolveOld = resolve; });
    const dashboard = (name: string) => ({
      user_id: name, full_name: name, enrolled_courses: [], total_courses: 0,
      completed_courses: 0, total_progress_percent: 0, certificates_count: 0,
    });
    const fetchMock = vi.fn()
      .mockImplementationOnce((_url: string, _options: RequestInit) => oldResponse)
      .mockResolvedValueOnce({ ok: true, json: async () => dashboard('New identity') });
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<StudentDashboardPage />);
    const oldOptions = fetchMock.mock.calls[0][1] as RequestInit;

    authState.token = 'new-learner-token';
    view.rerender(<StudentDashboardPage />);
    expect((oldOptions.signal as AbortSignal).aborted).toBe(true);
    expect(await screen.findByText(/New identity!/)).toBeInTheDocument();

    resolveOld({ ok: true, json: async () => dashboard('Stale identity') });
    await waitFor(() => expect(screen.queryByText(/Stale identity!/)).not.toBeInTheDocument());
    expect(screen.getByText(/New identity!/)).toBeInTheDocument();
  });
});
