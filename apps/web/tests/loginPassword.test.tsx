import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import LoginPage from '@/app/login/page';

describe('password login', () => {
  it('is visible by default for accounts provisioned by an administrator', () => {
    render(<LoginPage />);

    expect(screen.getByRole('button', { name: 'Пароль' })).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email');
    expect(screen.getByLabelText('Пароль')).toHaveAttribute('type', 'password');
    expect(
      screen.getByText(/получили от администратора/i),
    ).toBeInTheDocument();
  });
});
