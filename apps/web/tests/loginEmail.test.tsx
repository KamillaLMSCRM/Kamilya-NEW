import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import LoginPage from '@/app/login/page';

describe('email OTP login form', () => {
  it('starts with an empty email field and does not inherit the password login email', () => {
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'admin@example.kz' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Код' }));

    const emailInput = screen.getByLabelText('Рабочий email');
    expect(emailInput).toHaveValue('');
    expect(emailInput).toHaveAttribute('autocomplete', 'off');
    expect(emailInput).toHaveAttribute('name', 'email-otp');
  });
});
