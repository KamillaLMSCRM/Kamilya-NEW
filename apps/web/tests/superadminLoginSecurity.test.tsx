import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import DemoLoginPage from '@/app/login/demo/page';
import LoginPage from '@/app/login/page';
import SuperadminLoginPage from '@/app/superadmin/login/page';

describe('platform operator login exposure', () => {
  it('does not advertise the privileged login from the public login page', () => {
    render(<LoginPage />);

    expect(screen.queryByText(/суперадмин/i)).not.toBeInTheDocument();
    expect(document.querySelector('a[href="/superadmin/login"]')).toBeNull();
  });

  it('does not advertise the privileged login from the public demo page', () => {
    render(<DemoLoginPage />);

    expect(screen.queryByText(/суперадмин/i)).not.toBeInTheDocument();
    expect(document.querySelector('a[href="/superadmin/login"]')).toBeNull();
  });

  it('starts with empty operator credentials supplied by the application', () => {
    render(<SuperadminLoginPage />);

    expect(screen.getByLabelText('Email')).toHaveValue('');
    expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'off');
    expect(screen.getByLabelText('Пароль')).toHaveValue('');
    expect(screen.getByLabelText('Пароль')).toHaveAttribute('autocomplete', 'off');
    expect(screen.getByRole('button', { name: 'Войти как суперадмин' })).toBeDisabled();
    expect(screen.queryByText(/Askar/i)).not.toBeInTheDocument();
  });
});
