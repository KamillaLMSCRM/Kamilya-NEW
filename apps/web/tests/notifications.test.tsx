import { describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import {
  getSafeNotificationActionPath,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '@/lib/notifications';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

describe('notification inbox HTTP V2 client', () => {
  it('uses the exact bounded list route and returns the DTO', async () => {
    const data = { items: [], unread_count: 2 };
    vi.spyOn(api, 'get').mockResolvedValueOnce({ data } as never);
    await expect(listNotifications()).resolves.toEqual(data);
    expect(api.get).toHaveBeenCalledWith('/v1/notifications?limit=20');
  });

  it('uses exact read and read-all routes', async () => {
    vi.spyOn(api, 'post').mockResolvedValueOnce({ data: { id: 'n1' } }).mockResolvedValueOnce({ data: { updated: 1, unread_count: 0 } });
    await markNotificationRead('n1');
    await markAllNotificationsRead();
    expect(api.post).toHaveBeenNthCalledWith(1, '/v1/notifications/n1/read');
    expect(api.post).toHaveBeenNthCalledWith(2, '/v1/notifications/read-all');
  });

  it('rejects invalid limits and unsafe action paths', () => {
    expect(listNotifications(0)).rejects.toThrow(RangeError);
    expect(getSafeNotificationActionPath('https://evil.example/course-review-requests/1', 'course_review_assigned')).toBeNull();
    expect(getSafeNotificationActionPath('/course-review-requests/00000000-0000-4000-8000-000000000000', 'course_review_assigned')).toBe('/course-review-requests/00000000-0000-4000-8000-000000000000');
    expect(getSafeNotificationActionPath('/admin/course-approvals?courseId=00000000-0000-4000-8000-000000000000&x=1', 'course_review_overdue')).toBeNull();
    expect(getSafeNotificationActionPath('/course-review-requests/00000000-0000-4000-8000-000000000000', 'future_kind')).toBeNull();
  });
});

describe('notification locale contract', () => {
  it('keeps equal notification keys in RU, KK and EN', () => {
    expect(Object.keys(kk.topbar)).toEqual(Object.keys(ru.topbar));
    expect(Object.keys(en.topbar)).toEqual(Object.keys(ru.topbar));
    for (const locale of [ru, kk, en]) {
      expect(locale.topbar.notificationAssigned).toBeTruthy();
      expect(locale.topbar.notificationUnknown).toBeTruthy();
    }
  });
});
