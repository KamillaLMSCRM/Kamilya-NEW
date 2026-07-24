import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AdminTeamPage from '@/app/admin/team/page';
import { useAuthStore } from '@/store/authStore';

const existingUser = {
  id: 'user-123',
  email: 'owner@example.com',
  first_name: 'Tenant',
  last_name: 'Owner',
  role: 'admin',
  roles: ['admin'],
  is_active: true,
  created_at: '2026-07-24T00:00:00Z',
  last_login: null,
};

describe('tenant team modal', () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: 'test-token',
      user: {
        user_id: existingUser.id,
        tenant_id: 'tenant-123',
        tenant: { id: 'tenant-123', name: 'Test company' },
        telegram_id: '',
        role: 'admin',
        roles: ['admin'],
        full_name: 'Tenant Owner',
        email: existingUser.email,
      },
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return new Response(JSON.stringify({
          ...existingUser,
          roles: ['admin', 'methodologist'],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({ users: [existingUser], total: 1 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('keeps the form stable and assigns a role through the existing-account endpoint', async () => {
    render(<AdminTeamPage />);
    await screen.findByText(existingUser.email);

    fireEvent.click(screen.getByRole('button', { name: /\+/ }));
    const emailInput = document.querySelector<HTMLInputElement>('input[name^="team_member_email_"]');
    expect(emailInput).not.toBeNull();
    fireEvent.change(emailInput!, {
      target: { value: existingUser.email },
    });

    expect(document.querySelector('input[name^="team_member_first_name_"]')).toBeDisabled();
    expect(document.querySelector('input[name^="team_member_last_name_"]')).toBeDisabled();
    expect(document.querySelector('input[name^="team_member_password_"]')).toBeDisabled();
    expect(screen.getByText(/переключать рабочий режим/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Добавить роль' }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/v1/users/user-123/roles'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ role: 'methodologist' }),
        }),
      );
    });
    expect(useAuthStore.getState().user?.role).toBe('admin');
    expect(useAuthStore.getState().user?.roles).toEqual(['admin', 'methodologist']);
  });
});
