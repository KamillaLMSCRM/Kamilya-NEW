import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContextualNavigation from '@/components/layout/ContextualNavigation';
import Sidebar from '@/components/layout/Sidebar';
import CoursesPage from '@/app/courses/page';
import { getNavigationRoutes } from '@/lib/routeRegistry';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn().mockResolvedValue({ data: [] }) } }));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ prefetch: vi.fn() }),
}));

const user = { user_id: 'm', tenant_id: 't', tenant: { id: 't', name: 'Test' }, telegram_id: '', role: 'methodologist', roles: ['methodologist'], full_name: 'Test', email: 'test@example.com' };

describe('contextual methodologist navigation', () => {
  it('closes on Escape and returns focus from a link to its trigger', () => {
    const { container } = render(<ContextualNavigation section="courses" />);
    const menu = container.querySelector('details')!;
    menu.open = true;
    const link = screen.getByRole('link', { name: 'Документы' });
    link.focus();
    fireEvent.keyDown(link, { key: 'Escape' });
    expect(menu.open).toBe(false);
    expect(menu.querySelector('summary')).toHaveFocus();
  });

  it('closes on outside pointer, focus exit and link activation', () => {
    const { container } = render(<><ContextualNavigation section="courses" /><button>Outside</button></>);
    const menu = container.querySelector('details')!;
    menu.open = true;
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Outside' }));
    expect(menu.open).toBe(false);
    menu.open = true;
    fireEvent.blur(menu, { relatedTarget: screen.getByRole('button', { name: 'Outside' }) });
    expect(menu.open).toBe(false);
    menu.open = true;
    fireEvent.click(menu.querySelector('a')!);
    expect(menu.open).toBe(false);
  });
  beforeEach(() => {
    useAuthStore.setState({ user });
    useLanguageStore.setState({ lang: 'ru' });
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'false');
  });
  afterEach(() => vi.unstubAllEnvs());

  it.each([
    ['courses', ['/documents', '/quizzes', '/learning-paths']],
    ['staff', ['/positions', '/cohorts', '/candidate-assessments']],
    ['assignments', ['/learning-cycles']],
    ['trainingLog', ['/mandatory-training', '/training-procedures', '/training-retention']],
  ] as const)('provides the %s destinations within its own menu', (section, hrefs) => {
    const { container } = render(<ContextualNavigation section={section} />);
    expect(screen.getByText('Ещё').tagName).toBe('SUMMARY');
    expect(Array.from(container.querySelectorAll('a')).map((link) => link.getAttribute('href')).sort()).toEqual([...hrefs].sort());
  });

  it('keeps every registered methodologist navigation destination reachable', () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'true');
    const { container } = render(<>
      <Sidebar collapsed={false} onToggle={() => {}} />
      <CoursesPage />
      <ContextualNavigation section="staff" />
      <ContextualNavigation section="assignments" />
      <ContextualNavigation section="trainingLog" />
    </>);
    const reachableDestinations = new Set(Array.from(container.querySelectorAll('a')).map((link) => link.getAttribute('href')));
    const missing = getNavigationRoutes('methodologist', 'sidebar')
      .map((route) => route.href)
      .filter((href) => !reachableDestinations.has(href));
    expect(missing).toEqual([]);
  });

  it('respects the workbench feature flag', () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'true');
    const { container } = render(<ContextualNavigation section="assignments" />);
    expect(container.querySelector('a[href="/methodologist-workbench"]')).toBeInTheDocument();
  });

  it.each(['admin', 'student', 'superadmin'])('does not union methodologist permissions into active %s', (role) => {
    useAuthStore.setState({ user: { ...user, role, roles: [role, 'methodologist'] } });
    const { container } = render(<ContextualNavigation section="courses" />);
    expect(container).toBeEmptyDOMElement();
  });
});
