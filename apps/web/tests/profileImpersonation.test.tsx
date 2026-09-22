import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ProfilePage from '@/app/profile/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

describe('profile during tenant impersonation', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    useAuthStore.setState({
      accessToken: 'impersonation-token',
      initialized: true,
      user: {
        user_id: 'operator-1',
        tenant_id: 'tenant-1',
        tenant: { id: 'tenant-1', name: 'Demo tenant' },
        telegram_id: '',
        role: 'methodologist',
        roles: ['methodologist'],
        full_name: 'Platform Operator',
        email: 'operator@example.com',
        impersonated_by: 'operator-1',
        impersonated_role: 'methodologist',
      },
    });
  });

  it('shows a read-only explanation without requesting or editing the operator profile', async () => {
    render(<ProfilePage />);

    expect(await screen.findByText('settings.impersonationProfileTitle')).toBeInTheDocument();
    expect(screen.getByText('Platform Operator')).toBeInTheDocument();
    expect(screen.getByText('operator@example.com')).toBeInTheDocument();
    await waitFor(() => expect(api.get).not.toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'common.save' })).not.toBeInTheDocument();
  });
});
