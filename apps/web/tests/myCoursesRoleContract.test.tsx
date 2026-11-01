import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
const authState = vi.hoisted(() => ({ token: 'token-a' as string | null, user: { user_id: 'learner-1', tenant_id: 'tenant-1', role: 'student' } }));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { accessToken: string | null; user: typeof authState.user }) => unknown) => selector({ accessToken: authState.token, user: authState.user }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'common.loading': 'Loading',
      'common.all': 'All',
      'common.none': 'None',
      'common.error': 'Error',
      'common.loadFailed': 'Could not load courses',
      'common.retry': 'Retry',
      'student.enrolledCourses': 'My courses',
      'student.inProgress': 'In progress',
      'student.completed': 'Completed',
      'student.noCourses': 'No assigned courses',
      'courses.startCourse': 'Start course',
      'courses.continueCourse': 'Continue course',
      'courses.viewResult': 'View result',
      'courses.viewCertificate': 'View certificate',
      'courses.browse': 'Available courses',
      'courses.viewAll': 'View all courses',
    }[key] ?? key),
    tp: (key: string, value: number) => `${value} lessons`,
  }),
}));

import MyCoursesPage from '@/app/my-courses/page';

const assignedCourse = {
  course_id: '123e4567-e89b-42d3-a456-426614174000',
  title: '安全 курс',
  description: 'Assigned course',
  status: 'published',
  enrollment_status: 'completed',
  progress_percent: 100,
  total_lessons: 4,
  completed_lessons: 4,
  enrolled_at: '2026-10-01T00:00:00Z',
};

describe('my courses student role contract', () => {
  beforeEach(() => {
    authState.token = 'token-a';
    authState.user = { user_id: 'learner-1', tenant_id: 'tenant-1', role: 'student' };
    apiMock.get.mockReset();
    apiMock.get.mockResolvedValue({ data: { enrolled_courses: [assignedCourse] } });
  });

  it('shows assigned course navigation, certificate navigation, and filters without a catalog CTA', async () => {
    render(<MyCoursesPage />);

    expect(await screen.findByRole('link', { name: 'View result' })).toHaveAttribute('href', `/courses/${assignedCourse.course_id}`);
    expect(screen.getByRole('link', { name: 'View certificate' })).toHaveAttribute('href', '/certificates');
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'In progress' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Completed' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'View all courses' })).not.toBeInTheDocument();
    expect(screen.queryByText('Available courses')).not.toBeInTheDocument();
  });

  it('wraps the mobile header filters instead of allowing horizontal overflow', async () => {
    render(<MyCoursesPage />);

    const heading = await screen.findByRole('heading', { name: 'My courses' });
    const header = heading.parentElement;
    const filters = screen.getByRole('button', { name: 'All' }).parentElement;

    expect(header).toHaveClass('flex-wrap');
    expect(filters).toHaveClass('flex-wrap');
    expect(header).toHaveClass('min-w-0');
  });

  it('shows a localized error and retries successfully after an API failure', async () => {
    apiMock.get
      .mockRejectedValueOnce(new Error('request failed'))
      .mockResolvedValueOnce({ data: { enrolled_courses: [assignedCourse] } });

    render(<MyCoursesPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load courses');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('link', { name: 'View result' })).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledTimes(2);
  });

  it('does not refetch when only the access token rotates within the same session', async () => {
    const { rerender } = render(<MyCoursesPage />);
    await screen.findByRole('link', { name: 'View result' });
    expect(apiMock.get).toHaveBeenCalledTimes(1);

    authState.token = 'token-b';
    rerender(<MyCoursesPage />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
  });

  it('does not repopulate courses when logout occurs before a late response', async () => {
    let resolveRequest: (value: { data: { enrolled_courses: typeof assignedCourse[] } }) => void = () => undefined;
    apiMock.get.mockReturnValueOnce(new Promise((resolve) => { resolveRequest = resolve; }));

    const { rerender } = render(<MyCoursesPage />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));

    authState.token = null;
    rerender(<MyCoursesPage />);
    expect(screen.queryByRole('link', { name: 'View result' })).not.toBeInTheDocument();

    await act(async () => {
      resolveRequest({ data: { enrolled_courses: [assignedCourse] } });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'View result' })).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  it('keeps same-course occurrences separate and obeys can_resume, deadline and server resume link', async () => {
    apiMock.get.mockResolvedValue({ data: { enrolled_courses: [
      { ...assignedCourse, enrollment_id: 'old', title: 'Older occurrence', can_resume: false, enrollment_status: 'in_progress', assignment_due_at: '2026-01-01T00:00:00Z' },
      { ...assignedCourse, enrollment_id: 'current', title: 'Current occurrence', can_resume: true, enrollment_status: 'in_progress', resume_href: `/courses/${assignedCourse.course_id}?lessonId=123e4567-e89b-42d3-a456-426614174001` },
    ] } });
    render(<MyCoursesPage />);
    await screen.findByText('Older occurrence');
    expect(screen.getByRole('status')).toHaveTextContent('Продолжение этого назначения пока недоступно');
    expect(screen.getByText('Срок прошёл')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Continue course' })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Continue course' })).toHaveAttribute('href', `/courses/${assignedCourse.course_id}?lessonId=123e4567-e89b-42d3-a456-426614174001`);
    fireEvent.click(screen.getByRole('button', { name: 'In progress' }));
    expect(screen.getByRole('button', { name: 'In progress' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('clears visible courses immediately when the actor or tenant scope changes', async () => {
    const view = render(<MyCoursesPage />);
    await screen.findByRole('link', { name: 'View result' });
    apiMock.get.mockResolvedValue({ data: { enrolled_courses: [] } });
    authState.user = { ...authState.user, user_id: 'learner-2', tenant_id: 'tenant-2' };
    view.rerender(<MyCoursesPage />);
    expect(screen.queryByRole('link', { name: 'View result' })).not.toBeInTheDocument();
    await screen.findByText('No assigned courses');
    expect(apiMock.get).toHaveBeenCalledTimes(2);
  });
});
