import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import LoginPage from '@/app/login/page';

describe('email OTP login form', () => {
  it('is the default sign-in method and does not inherit the password login email', () => {
    render(<LoginPage />);

    const emailCodeTab = screen.getByRole('tab', { name: 'Код на email' });
    const passwordTab = screen.getByRole('tab', { name: 'Пароль' });
    expect(emailCodeTab).toHaveAttribute('aria-selected', 'true');
    expect(passwordTab).toHaveAttribute('aria-selected', 'false');

    fireEvent.click(passwordTab);
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'admin@example.kz' },
    });
    fireEvent.click(emailCodeTab);

    const emailInput = screen.getByLabelText('Рабочий email');
    expect(emailInput).toHaveValue('');
    expect(emailInput).toHaveAttribute('autocomplete', 'off');
    expect(emailInput).toHaveAttribute('name', 'email-otp');
  });
});
