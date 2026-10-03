import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Sidebar from '@/components/layout/Sidebar';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

const navigationState = { pathname: '/' };
vi.mock('next/navigation', () => ({
  usePathname: () => navigationState.pathname,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ prefetch: vi.fn() }),
}));

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
    navigationState.pathname = '/';
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

  it('keeps the resource family and staff group open on a child detail route', () => {
    navigationState.pathname = '/positions/retained-id';
    render(<Sidebar collapsed={false} onToggle={() => {}} />);
    expect(screen.getByRole('link', { name: 'Должности' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Сотрудники и структура' })).toHaveClass('text-foreground');
  });

  it('preserves Next navigation on both canvas PDF preview routes', () => {
    useAuthStore.setState({ user: { ...methodologist, role: 'admin', roles: ['admin'] } });
    navigationState.pathname = '/admin';
    const { container, rerender } = render(<Sidebar collapsed={false} onToggle={() => {}} />);
    for (const href of ['/admin/certificates/settings', '/admin/training-evidence/settings']) {
      expect(container.querySelector(`a[href="${href}"]`)).toHaveAttribute('data-testid', 'next-link');
    }
    expect(container.querySelector('a[href="/profile"]')).toHaveAttribute('data-testid', 'next-link');
    for (const pathname of ['/admin/certificates/settings', '/admin/training-evidence/settings']) {
      navigationState.pathname = pathname;
      rerender(<Sidebar collapsed={false} onToggle={() => {}} />);
      expect(container.querySelector('a[href="/admin"]')).toHaveAttribute('data-testid', 'next-link');
      expect(container.querySelector('a[href="/profile"]')).toHaveAttribute('data-testid', 'next-link');
    }
  });
});
