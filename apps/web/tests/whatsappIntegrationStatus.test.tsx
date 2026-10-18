import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import IntegrationsPage from '@/app/admin/settings/integrations/page';
import { getWhatsAppStatus } from '@/features/integrations/api';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/features/integrations/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/features/integrations/api')>(),
  listIntegrations: vi.fn().mockResolvedValue([]),
  getWhatsAppStatus: vi.fn(),
}));

const statusMock = vi.mocked(getWhatsAppStatus);
const idle = { status: 'not_started' as const, phone_number: null, qr: null, qr_expires_at: null };

describe('WhatsApp status readiness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ accessToken: 'synthetic-token' });
    statusMock.mockResolvedValue(idle);
  });
  afterEach(() => vi.useRealTimers());

  it('does not refetch immediately whenever a fresh status object arrives', async () => {
    render(<IntegrationsPage />);
    await screen.findByRole('heading', { name: /WhatsApp/ });
    await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(statusMock).toHaveBeenCalledTimes(1);
  });

  it('shows an unavailable status instead of pretending the channel can start, and retries', async () => {
    statusMock.mockRejectedValueOnce(new Error('Synthetic gateway unavailable'));
    render(<IntegrationsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic gateway unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(statusMock).toHaveBeenCalledTimes(2);
  });
});
