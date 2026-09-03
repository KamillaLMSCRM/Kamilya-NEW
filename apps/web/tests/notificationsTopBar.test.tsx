import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TopBar from '@/components/layout/TopBar';
import { useAuthStore } from '@/store/authStore';
import type { Notification, NotificationInboxResponse } from '@/lib/notifications';

const mocks = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}));

vi.mock('@/lib/notifications', async () => {
  const actual = await vi.importActual<typeof import('@/lib/notifications')>('@/lib/notifications');
  return {
    ...actual,
    listNotifications: mocks.listNotifications,
    markNotificationRead: mocks.markNotificationRead,
  };
});

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      const copy: Record<string, string> = {
        'topbar.notifications': 'Notifications',
        'topbar.notificationsLoading': 'Loading notifications',
        'topbar.notificationsError': 'Could not load notifications',
        'topbar.notificationsRetry': 'Retry',
        'topbar.noNotifications': 'No notifications',
        'topbar.notificationAssigned': `Assigned ${String(values?.course ?? '')}`.trim(),
        'topbar.notificationReminder': `Reminder ${String(values?.course ?? '')}`.trim(),
        'topbar.notificationOverdue': `Overdue ${String(values?.course ?? '')}`.trim(),
        'topbar.notificationUnknown': 'Unknown notification',
        'topbar.notificationReadError': 'Could not mark notification as read',
        'topbar.markAllRead': 'Mark all as read',
        'topbar.markingAllRead': 'Marking all as read',
        'topbar.activeRole': 'Active role',
        'sidebar.open': 'Open menu',
        'common.search': 'Search',
        'topbar.openCommandPalette': 'Open command palette',
        'nav.myProfile': 'My profile',
      };
      if (key === 'topbar.unreadCount') return `Unread notifications: ${String(values?.count ?? '')}`;
      return copy[key] ?? key;
    },
  }),
}));

vi.mock('@/components/LanguageSwitcher', () => ({
  LanguageSwitcher: () => null,
}));

vi.mock('@/components/layout/ContextualHelpButton', () => ({
  ContextualHelpButton: () => null,
}));

vi.mock('@/components/support/SupportRequestDialog', () => ({
  SupportRequestDialog: () => null,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function makeUser(userId: string, tenantId: string, role = 'methodologist') {
  return {
    user_id: userId,
    tenant_id: tenantId,
    role,
    roles: [role],
    full_name: 'Test User',
    tenant: { name: `Tenant ${tenantId}` },
  } as never;
}

function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: 'notification-1',
    kind: 'course_review_assigned',
    context: { course_title: 'Course title' },
    action_path: '/course-review-requests/00000000-0000-4000-8000-000000000000',
    read_at: null,
    created_at: '2026-09-03T00:00:00.000Z',
    ...overrides,
  };
}

function inbox(items: Notification[], unreadCount = items.filter((item) => !item.read_at).length): NotificationInboxResponse {
  return { items, unread_count: unreadCount };
}

let restoreLocation: (() => void) | null = null;

function mockLocationAssign() {
  const originalLocation = window.location;
  const assign = vi.fn();
  Object.defineProperty(window, 'location', { configurable: true, value: { assign } });
  restoreLocation = () => {
    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
    restoreLocation = null;
  };
  return assign;
}

beforeEach(() => {
  mocks.listNotifications.mockReset();
  mocks.markNotificationRead.mockReset();
  useAuthStore.setState({
    accessToken: 'test-token',
    user: makeUser('user-1', 'tenant-1'),
    initialized: true,
  });
});

afterEach(() => restoreLocation?.());

describe('TopBar notification UI', () => {
  it('shows loading and then the ready empty state', async () => {
    const request = deferred<NotificationInboxResponse>();
    mocks.listNotifications.mockReturnValueOnce(request.promise);

    render(<TopBar title="Dashboard" />);
    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Loading notifications');

    request.resolve(inbox([]));
    expect(await screen.findByText('No notifications')).toBeInTheDocument();
  });

  it('shows an API error and retries the list request', async () => {
    mocks.listNotifications
      .mockRejectedValueOnce(new Error('list failed'))
      .mockResolvedValueOnce(inbox([]));

    render(<TopBar />);
    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));

    expect(await screen.findByText('Could not load notifications')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('No notifications')).toBeInTheDocument();
    expect(mocks.listNotifications).toHaveBeenCalledTimes(2);
  });

  it('marks an unread notification read, decrements the badge, and navigates', async () => {
    const notification = makeNotification({ id: 'notification-read' });
    const actionPath = notification.action_path as string;
    mocks.listNotifications.mockResolvedValueOnce(inbox([notification], 1));
    mocks.markNotificationRead.mockResolvedValueOnce({ ...notification, read_at: '2026-09-03T01:00:00.000Z' });
    const assign = mockLocationAssign();

    render(<TopBar />);
    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));
    const menuItem = await screen.findByRole('menuitem', { name: 'Assigned Course title' });

    expect(screen.getByLabelText('Unread notifications: 1')).toBeInTheDocument();
    fireEvent.click(menuItem);

    await waitFor(() => expect(mocks.markNotificationRead).toHaveBeenCalledWith('notification-read'));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(actionPath));
    await waitFor(() => expect(screen.queryByLabelText('Unread notifications: 1')).not.toBeInTheDocument());
  });

  it('keeps the notification in place and does not navigate when marking read fails', async () => {
    const notification = makeNotification({ id: 'notification-failed-read' });
    mocks.listNotifications.mockResolvedValueOnce(inbox([notification], 1));
    mocks.markNotificationRead.mockRejectedValueOnce(new Error('read failed'));
    const assign = mockLocationAssign();

    render(<TopBar />);
    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Assigned Course title' }));

    expect(await screen.findByText('Could not mark notification as read')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Unread notifications: 1')).toBeInTheDocument();
  });

  it('renders an allowlisted path with an unknown kind as non-actionable', async () => {
    const notification = makeNotification({ kind: 'future_notification_kind', context: {} });
    mocks.listNotifications.mockResolvedValueOnce(inbox([notification], 1));

    render(<TopBar />);
    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));

    expect(await screen.findByRole('note', { name: 'Unknown notification' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem')).not.toBeInTheDocument();
  });

  it('discards a list response from the old user and tenant identity', async () => {
    const request = deferred<NotificationInboxResponse>();
    const oldIdentityNotification = makeNotification({
      id: 'old-identity-notification',
      context: { course_title: 'Old identity course' },
    });
    mocks.listNotifications.mockReturnValueOnce(request.promise);

    render(<TopBar />);
    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Loading notifications');

    useAuthStore.setState({ user: makeUser('user-2', 'tenant-2') });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Notifications' })).toHaveAttribute('aria-expanded', 'false'));

    request.resolve(inbox([oldIdentityNotification], 1));
    await waitFor(() => expect(screen.queryByLabelText('Unread notifications: 1')).not.toBeInTheDocument());
    expect(screen.queryByText('Old identity course')).not.toBeInTheDocument();
  });
});
