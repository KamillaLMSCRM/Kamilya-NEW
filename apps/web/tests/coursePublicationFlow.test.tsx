import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: () => ({
    user: { id: 'methodologist-1', role: 'methodologist' },
  }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'courses.reviewRequired': 'Требует проверки',
      'courses.reviewCourse': 'Проверить',
      'common.edit': 'Редактировать',
      'common.actionsFor': 'Действия',
    }[key] || key),
  }),
}));
vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: vi.fn(), dialog: null }),
}));
vi.mock('@/components/ui/Toast', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

import CoursesPage from '@/app/courses/page';

describe('course publication flow', () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.post.mockReset();
    apiMock.delete.mockReset();
  });

  it('routes an unapproved AI draft to review instead of calling publish', async () => {
    apiMock.get.mockResolvedValue({
      data: [{
        id: 'course-1',
        title: 'AI draft',
        description: 'Generated course',
        status: 'draft',
        ai_generated: true,
        review_status: 'pending',
        delivery_type: 'native',
      }],
    });

    render(<CoursesPage />);

    expect(await screen.findByText('Требует проверки')).toBeInTheDocument();
    const reviewLink = screen.getByRole('link', { name: 'Проверить' });
    expect(reviewLink).toHaveAttribute('href', '/courses/course-1/edit');
    expect(screen.queryByRole('button', { name: 'courses.publish' })).not.toBeInTheDocument();

    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('keeps direct publication available for an approved AI draft', async () => {
    apiMock.get.mockResolvedValue({
      data: [{
        id: 'course-2',
        title: 'Approved draft',
        description: 'Reviewed course',
        status: 'draft',
        ai_generated: true,
        review_status: 'approved',
        delivery_type: 'native',
      }],
    });

    render(<CoursesPage />);

    expect(await screen.findByRole('button', { name: 'courses.publish' })).toBeInTheDocument();
    expect(screen.queryByText('Требует проверки')).not.toBeInTheDocument();
  });
});
