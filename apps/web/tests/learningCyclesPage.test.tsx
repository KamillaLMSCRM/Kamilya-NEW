import { render, screen, waitFor } from '@testing-library/react';
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
});
