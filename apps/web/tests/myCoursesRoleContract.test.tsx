import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
const authState = vi.hoisted(() => ({ token: 'token-a' as string | null }));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { accessToken: string | null }) => unknown) => selector({ accessToken: authState.token }),
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
      'courses.viewCertificate': 'View certificate',
      'courses.browse': 'Available courses',
      'courses.viewAll': 'View all courses',
    }[key] ?? key),
    tp: (key: string, value: number) => `${value} lessons`,
  }),
}));

import MyCoursesPage from '@/app/my-courses/page';

const assignedCourse = {
  course_id: 'course-1',
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
    apiMock.get.mockReset();
    apiMock.get.mockResolvedValue({ data: { enrolled_courses: [assignedCourse] } });
  });

  it('shows assigned course navigation, certificate navigation, and filters without a catalog CTA', async () => {
    render(<MyCoursesPage />);

    expect(await screen.findByRole('link', { name: 'Continue course' })).toHaveAttribute('href', '/courses/course-1');
    expect(screen.getByRole('link', { name: 'View certificate' })).toHaveAttribute('href', '/certificates');
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'In progress' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Completed' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'View all courses' })).not.toBeInTheDocument();
    expect(screen.queryByText('Available courses')).not.toBeInTheDocument();
  });

  it('shows a localized error and retries successfully after an API failure', async () => {
    apiMock.get
      .mockRejectedValueOnce(new Error('request failed'))
      .mockResolvedValueOnce({ data: { enrolled_courses: [assignedCourse] } });

    render(<MyCoursesPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load courses');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('link', { name: 'Continue course' })).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledTimes(2);
  });

  it('does not refetch when only the access token rotates within the same session', async () => {
    const { rerender } = render(<MyCoursesPage />);
    await screen.findByRole('link', { name: 'Continue course' });
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
    expect(screen.queryByRole('link', { name: 'Continue course' })).not.toBeInTheDocument();

    await act(async () => {
      resolveRequest({ data: { enrolled_courses: [assignedCourse] } });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Continue course' })).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
