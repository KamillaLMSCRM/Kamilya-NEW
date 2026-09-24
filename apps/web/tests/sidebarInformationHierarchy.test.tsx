import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import Sidebar from '@/components/layout/Sidebar';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

const methodologist = {
  user_id: 'methodologist-1',
  tenant_id: 'tenant-1',
  tenant: { id: 'tenant-1', name: 'Тестовая организация' },
  telegram_id: '',
  role: 'methodologist',
  roles: ['methodologist'],
  full_name: 'Тестовый методист',
  email: 'methodologist@example.com',
};

describe('methodologist sidebar information hierarchy', () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: 'test-token', user: methodologist });
    useLanguageStore.setState({ lang: 'ru' });
  });

  it('uses task language and makes sections and nested items visually distinct', () => {
    const { container } = render(<Sidebar collapsed={false} onToggle={() => {}} />);

    expect(screen.getByRole('link', { name: 'Обзор обучения' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Панель управления' })).not.toBeInTheDocument();

    const contentHeading = screen.getByRole('heading', { name: 'Курсы и материалы' });
    expect(contentHeading).toHaveClass('text-sm', 'font-bold', 'text-primary/80');
    expect(contentHeading).not.toHaveClass('text-xs');
    expect(contentHeading).not.toHaveClass('uppercase');
    expect(contentHeading.closest('[data-sidebar-section]')).toHaveClass('border-t');

    const staffLink = screen.getByRole('link', { name: 'Сотрудники и структура' });
    expect(staffLink).toHaveClass('text-sm', 'font-medium');
    expect(staffLink).not.toHaveClass('text-[15px]');
    const groupToggle = staffLink.parentElement?.querySelector('button');
    expect(groupToggle).not.toBeNull();
    fireEvent.click(groupToggle!);

    const positionLink = screen.getByRole('link', { name: 'Должности' });
    expect(positionLink).toHaveClass('text-sm');
    const nestedList = positionLink.closest('ul');
    expect(nestedList).toHaveClass('ml-8', 'border-l-2', 'border-primary/30');
    expect(container.querySelectorAll('nav h2').length).toBeGreaterThan(2);
  });
});
