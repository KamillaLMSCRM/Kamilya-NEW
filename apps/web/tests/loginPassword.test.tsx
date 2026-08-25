import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import LoginPage from '@/app/login/page';

describe('password login', () => {
  it('remains available for accounts provisioned by an administrator', () => {
    render(<LoginPage />);

    const passwordTab = screen.getByRole('tab', { name: 'Пароль' });
    expect(passwordTab).toHaveAttribute('aria-selected', 'false');
    fireEvent.click(passwordTab);
    expect(passwordTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email');
    expect(screen.getByLabelText('Пароль')).toHaveAttribute('type', 'password');
    expect(
      screen.getByText(/получили от администратора/i),
    ).toBeInTheDocument();
  });
});
