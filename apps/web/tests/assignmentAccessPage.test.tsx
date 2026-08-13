import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const replace = vi.fn();
const login = vi.fn();
vi.mock('next/navigation', () => ({ useParams: () => ({ token: 'opaque-token' }), useRouter: () => ({ replace }) }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: any) => selector({ login }) }));
vi.mock('@/components/brand/Logo', () => ({ Logo: () => <div /> }));

import AssignmentAccessPage from '@/app/access/[token]/page';

describe('assignment access page', () => {
  beforeEach(() => { vi.resetAllMocks(); });

  it('exchanges exactly a six-digit PIN and starts the learner session', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: 'jwt',
        user: { role: 'student' },
        assigned_course_id: 'course-42',
        enrollment_id: 'enrollment-42',
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<AssignmentAccessPage />);
    fireEvent.change(screen.getByLabelText('PIN'), { target: { value: '12a34567' } });
    fireEvent.click(screen.getByRole('button', { name: 'Открыть обучение' }));
    await waitFor(() => expect(login).toHaveBeenCalledWith('jwt', { role: 'student' }));
    expect(fetchMock.mock.calls[0][0]).toContain('/v1/assignment-access/opaque-token/exchange');
    expect(replace).toHaveBeenCalledWith('/courses/course-42');
  });
});
