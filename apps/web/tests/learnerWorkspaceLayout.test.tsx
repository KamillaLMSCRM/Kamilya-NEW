import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ pathname: '/courses/course-1', token: 'session-token' }));
const guard = vi.hoisted(() => vi.fn((_options: unknown) => vi.fn()));
const initialize = vi.hoisted(() => vi.fn(async () => undefined));
const logout = vi.hoisted(() => vi.fn(async () => undefined));
vi.mock('next/navigation', () => ({ usePathname: () => state.pathname, useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('@/components/layout/Sidebar', () => ({ default: ({ onClose }: { onClose: () => void }) => <aside data-testid="app-sidebar"><button onClick={onClose}>Close navigation</button></aside> }));
vi.mock('@/components/layout/TopBar', () => ({ default: ({ onMenuClick }: { onMenuClick: () => void }) => <header><button onClick={onMenuClick}>Open navigation</button></header> }));
vi.mock('@/components/CommandPalette', () => ({ default: () => null }));
vi.mock('@/components/demo/DemoBanner', () => ({ DemoBanner: () => null }));
vi.mock('@/components/demo/DemoLimitProvider', () => ({ DemoLimitProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }));
vi.mock('@/lib/auth', () => ({ getAccessToken: () => state.token, getCurrentUser: () => null, subscribeAuth: () => undefined }));
vi.mock('@/lib/sessionDeadline', () => ({ startSessionDeadlineGuard: guard, getSessionExpiryMs: () => null }));
const translate = vi.hoisted(() => (key: string) => key);
vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: translate }) }));

import Layout from '@/components/layout/Layout';
import { useAuthStore } from '@/store/authStore';

describe('focused learner layout retains session guards', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.pathname = '/courses/course-1';
    state.token = 'session-token';
    localStorage.clear();
    useAuthStore.setState({ accessToken: state.token, initialized: true, initialize, logout, user: { user_id: 'learner-1', role: 'student' } as never });
  });

  it('removes the permanent app rail only for learners and still opens navigation on demand', () => {
    render(<Layout><p>Lesson content</p></Layout>);
    expect(screen.queryByTestId('app-sidebar')).not.toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveAttribute('data-learning-focused', 'true');
    expect(screen.getByRole('main').closest('[data-app-workspace]')).toHaveAttribute('data-app-workspace', 'v1');
    expect(screen.getByRole('main')).not.toHaveClass('app-shell-main');
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(screen.getByTestId('app-sidebar')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close navigation' }));
    expect(screen.queryByTestId('app-sidebar')).not.toBeInTheDocument();
  });

  it('still initializes auth and does not render course content before auth initialization', () => {
    useAuthStore.setState({ initialized: false });
    render(<Layout><p>Lesson content</p></Layout>);
    expect(initialize).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Lesson content')).not.toBeInTheDocument();
  });

  it('retains deadline logout and refuses to expire a newer session', () => {
    render(<Layout><p>Lesson content</p></Layout>);
    const options = guard.mock.calls[0]?.[0] as unknown as { accessToken: string; onExpired: () => void };
    expect(options.accessToken).toBe('session-token');
    state.token = 'newer-session';
    act(() => options.onExpired());
    expect(logout).not.toHaveBeenCalled();
    state.token = 'session-token';
    act(() => options.onExpired());
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it('keeps the normal application rail on assigned-course lists', () => {
    state.pathname = '/my-courses';
    render(<Layout><p>Assignments</p></Layout>);
    expect(screen.getByTestId('app-sidebar')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveClass('app-shell-main');
  });

  it.each(['/courses/course-1', '/courses/quiz/quiz-1'])('provides an always-visible assigned-courses exit on focused route %s', (pathname) => {
    state.pathname = pathname;
    render(<Layout><p>Learning content</p></Layout>);
    const exit = screen.getByRole('link', { name: 'student.enrolledCourses' });
    expect(exit).toHaveAttribute('href', '/my-courses');
    expect(exit).not.toHaveClass('md:hidden', 'hidden');
    expect(exit).toBeVisible();
  });
});
