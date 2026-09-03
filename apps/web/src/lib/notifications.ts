import { api } from '@/lib/api';

export type WorkflowNotificationKind =
  | 'course_review_assigned'
  | 'course_review_reminder'
  | 'course_review_overdue';

export interface NotificationContext {
  course_title?: string | null;
  due_at?: string | null;
  [key: string]: unknown;
}

export interface Notification {
  id: string;
  kind: string;
  context: NotificationContext;
  action_path: string | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationInboxResponse {
  items: Notification[];
  unread_count: number;
}

export interface MarkAllNotificationsReadResponse {
  updated: number;
  unread_count: number;
}

const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const REVIEW_REQUEST_PATH = new RegExp(`^/course-review-requests/${UUID}$`, 'i');
const ADMIN_APPROVAL_PATH = new RegExp(`^/admin/course-approvals\\?courseId=${UUID}$`, 'i');
const ACTIONABLE_KINDS = new Set<WorkflowNotificationKind>([
  'course_review_assigned',
  'course_review_reminder',
  'course_review_overdue',
]);

export function getSafeNotificationActionPath(
  actionPath: string | null | undefined,
  kind?: string,
): string | null {
  if (!kind || !ACTIONABLE_KINDS.has(kind as WorkflowNotificationKind)) return null;
  if (typeof actionPath !== 'string') return null;
  return REVIEW_REQUEST_PATH.test(actionPath) || ADMIN_APPROVAL_PATH.test(actionPath)
    ? actionPath
    : null;
}

export async function listNotifications(limit = 20): Promise<NotificationInboxResponse> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new RangeError('Notification limit must be an integer from 1 to 50');
  }
  const response = await api.get<NotificationInboxResponse>(`/v1/notifications?limit=${limit}`);
  return response.data;
}

export async function markNotificationRead(id: string): Promise<Notification> {
  const response = await api.post<Notification>(
    `/v1/notifications/${encodeURIComponent(id)}/read`,
  );
  return response.data;
}

export async function markAllNotificationsRead(): Promise<MarkAllNotificationsReadResponse> {
  const response = await api.post<MarkAllNotificationsReadResponse>('/v1/notifications/read-all');
  return response.data;
}
