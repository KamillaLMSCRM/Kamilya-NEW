import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SupportRequestDialog } from '@/components/support/SupportRequestDialog';
import { api } from '@/lib/api';

vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/api', () => ({
  api: { post: vi.fn() },
}));

describe('SupportRequestDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/assignments?course=example');
  });

  it('submits the problem context and shows the support reference', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        id: 'c8d946bd-7d93-49a0-9f53-61f06586f341',
        reference: 'KML-C8D946BD',
        delivery_status: 'sent',
        created_at: '2026-08-21T10:00:00Z',
      },
    });

    render(<SupportRequestDialog />);
    fireEvent.click(screen.getByRole('button', { name: 'support.open' }));
    fireEvent.change(screen.getByLabelText('support.category'), { target: { value: 'learning' } });
    fireEvent.change(screen.getByLabelText('support.subject'), { target: { value: 'Course does not open' } });
    fireEvent.change(screen.getByLabelText('support.message'), {
      target: { value: 'The assigned course returns an error after opening.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'support.submit' }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith('/v1/support/requests', {
      category: 'learning',
      subject: 'Course does not open',
      message: 'The assigned course returns an error after opening.',
      current_path: '/assignments?course=example',
    });
    expect(await screen.findByText('KML-C8D946BD')).toBeInTheDocument();
  });
});
