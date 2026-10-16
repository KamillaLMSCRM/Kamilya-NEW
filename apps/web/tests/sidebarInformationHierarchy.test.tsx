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

  it('shows the Russian methodologist guide below the logo and opens it safely in a new tab', () => {
    const { container } = render(<Sidebar collapsed={false} onToggle={() => {}} />);

    const guide = screen.getByRole('link', { name: /Видеоинструкция методиста/ });
    expect(guide).toHaveAttribute('href', '/guides/methodologist.html');
    expect(guide).toHaveAttribute('target', '_blank');
    expect(guide).toHaveAttribute('rel', 'noopener noreferrer');
    expect(guide).toHaveTextContent('8 процессов: от документа до результатов');
    expect(guide.compareDocumentPosition(container.querySelector('#sidebar-nav')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([
    ['admin', ['admin']],
    ['admin', ['admin', 'methodologist']],
    ['student', ['student']],
    ['superadmin', ['superadmin']],
  ])('does not show the guide for active role %s even when assigned roles are %j', (role, roles) => {
    useAuthStore.setState({ user: { ...methodologist, role, roles } as typeof methodologist });
    render(<Sidebar collapsed={false} onToggle={() => {}} />);
    expect(screen.queryByRole('link', { name: /Видеоинструкция методиста/ })).not.toBeInTheDocument();
  });

  it('keeps the guide accessible when collapsed and closes the mobile drawer when selected', () => {
    const onClose = vi.fn();
    render(<Sidebar collapsed mobileOpen onToggle={() => {}} onClose={onClose} />);

    const guide = screen.getByRole('link', { name: 'Видеоинструкция методиста' });
    expect(guide).toHaveAttribute('aria-label', 'Видеоинструкция методиста');
    expect(guide).toHaveAttribute('title', 'Видеоинструкция методиста');
    fireEvent.click(guide);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it.each([false, true])('keeps the desktop toggle above the guide content when collapsed=%s', (collapsed) => {
    render(<Sidebar collapsed={collapsed} onToggle={() => {}} />);
    const toggle = screen.getByRole('button', { name: collapsed ? 'Развернуть сайдбар (Ctrl+B)' : 'Свернуть сайдбар (Ctrl+B)' });
    expect(toggle).toHaveClass('top-12');
    expect(toggle).not.toHaveClass('top-20');
  });

  it.each([
    ['kk', 'Әдіскерге арналған бейненұсқаулық', 'Нұсқаулық орыс тілінде'],
    ['en', 'Methodologist video guide', 'Guide is in Russian'],
  ] as const)('labels the %s guide link and discloses that the guide is in Russian', (lang, label, disclosure) => {
    useLanguageStore.setState({ lang });
    render(<Sidebar collapsed={false} onToggle={() => {}} />);
    const guide = screen.getByRole('link', { name: label });
    expect(guide).toHaveTextContent(disclosure);
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
