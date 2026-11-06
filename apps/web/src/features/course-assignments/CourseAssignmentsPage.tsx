'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { Copy, KeyRound, Users } from 'lucide-react';
import {
  Button,
  Badge,
  Table,
  SearchInput,
  Input,
} from '@/components/ui';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { useAuthStore } from '@/store/authStore';
import { getAuthSessionEpoch } from '@/lib/auth';
import { useT, type TranslationKey } from '@/i18n/useT';
import { getAssignmentSourceInfo } from '@/lib/assignmentSource';
import { AssignmentSelectionPreview } from '@/features/learning-workspace/AssignmentSelectionPreview';
import { workspaceCopy } from '@/features/learning-workspace/copy';
import { authorSessionScope } from '@/features/course-authoring/authorSession';
import Link from 'next/link';
import { buildTrainingLogBrowserHref } from '@/app/admin/training-log/query';
import { RecordList } from '@/features/workspace-design/RecordList';
import { WorkspacePage, WorkspacePanel, WorkspaceToolbar, WorkspaceEmpty } from '@/features/workspace-design';

interface Course {
  id: string;
  title: string;
  status: string;
}

interface User {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  // Опциональные поля — бэк может вернуть табельный/должность
  // для лучшего UX в поиске.
  personnel_number?: string | null;
  position_name?: string | null;
  has_login_access?: boolean;
}

interface Enrollment {
  id: string;
  user_id: string;
  course_id: string;
  status: string; // 'enrolled' | 'in_progress' | 'completed'
  source: 'manual' | 'position' | 'department' | string;
  enrolled_at: string;
  notification_status?: 'pending' | 'claimed' | 'retry' | 'delivered' | 'dead' | null;
  notification_attempt_count?: number;
  notification_delivered_at?: string | null;
  notification_error?: string | null;
}

interface AccessLink {
  email: string;
  invite_url: string;
}

interface EnrollmentAccess {
  enrollment_id: string;
  user_id: string;
  access_kind: 'course_access' | 'account_activation' | 'access_without_email' | 'personal_link';
  state: 'available' | 'needs_activation' | 'blocked' | 'revoked';
  access_url: string | null;
  expires_at?: string | null;
  message: string;
}

interface NoEmailAccessIssue {
  enrollment_id: string;
  access_url: string;
  temporary_pin: string;
  expires_at?: string;
  link_expires_at?: string;
  completion_window_minutes?: number | null;
}

interface VisibleNoEmailAccess extends NoEmailAccessIssue {
  learner_name: string;
}

interface ReassignmentResult {
  delivery_mode: DeliveryMode;
  personal_access?: NoEmailAccessIssue | null;
}

interface RecurringLearningRule {
  id: string;
  course_id: string | null;
  learning_path_id?: string | null;
  target_type?: 'course' | 'learning_path';
  user_id: string;
  cadence_days: number;
  due_days: number;
  status: 'draft' | 'active' | 'inactive';
  next_run_at: string | null;
  last_run_at: string | null;
  reminder_enabled?: boolean;
  reminder_days_before_due?: number;
}

interface ReminderDraft {
  enabled: boolean;
  daysBeforeDue: string;
}

interface ReminderStatus {
  id: string;
  status: 'queued' | 'sending' | 'sent' | 'failed' | 'skipped' | string;
  attempt_count: number;
  scheduled_at: string;
  delivered_at: string | null;
  last_error_category: string | null;
}

type ReminderHistoryState =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'loaded'; items: ReminderStatus[] }
  | { state: 'error' };

interface RecurringOccurrence {
  id: string;
  rule_id: string;
  scheduled_for: string;
  due_at: string;
  completed_at: string | null;
  status: 'assigned' | 'overdue' | 'completed' | 'completed_late' | 'skipped';
}

// UI-фильтры по статусу (frontend-side, потому что /courses/{id}/enrollments
// возвращает все записи разом — фильтрация дешевле клиентом).
type StatusFilter = 'all' | 'enrolled' | 'in_progress' | 'completed';
type DeliveryMode = 'email' | 'personal_link';

// ── helpers ────────────────────────────────────────────────

function matchesUserQuery(u: User, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return (
    (u.first_name || '').toLowerCase().includes(needle) ||
    (u.last_name || '').toLowerCase().includes(needle) ||
    ((u.first_name + ' ' + u.last_name).toLowerCase().includes(needle)) ||
    (u.email || '').toLowerCase().includes(needle) ||
    (u.personnel_number || '').toLowerCase().includes(needle) ||
    (u.position_name || '').toLowerCase().includes(needle)
  );
}

function matchesCourseQuery(c: Course, q: string): boolean {
  if (!q) return true;
  return (c.title || '').toLowerCase().includes(q.toLowerCase());
}

const STATUS_LABEL_KEYS = {
  enrolled: 'courseAssignments.status.enrolled',
  in_progress: 'courseAssignments.status.inProgress',
  completed: 'courseAssignments.status.completed',
} as const;
const STATUS_BADGE_VARIANT: Record<string, 'default' | 'outline' | 'secondary'> = {
  enrolled: 'outline',
  in_progress: 'secondary',
  completed: 'default',
};
const REMINDER_STATUS_LABEL_KEYS = {
  queued: 'courseAssignments.reminderStatus.queued',
  sending: 'courseAssignments.reminderStatus.sending',
  sent: 'courseAssignments.reminderStatus.sent',
  failed: 'courseAssignments.reminderStatus.failed',
  skipped: 'courseAssignments.reminderStatus.skipped',
} as const;
const NOTIFICATION_STATUS_LABEL_KEYS = {
  pending: 'courseAssignments.notificationStatus.pending',
  claimed: 'courseAssignments.notificationStatus.claimed',
  retry: 'courseAssignments.notificationStatus.retry',
  delivered: 'courseAssignments.notificationStatus.delivered',
  dead: 'courseAssignments.notificationStatus.dead',
} as const;
const REMINDER_ERROR_LABEL_KEYS = {
  configuration_missing: 'courseAssignments.reminderErrors.configurationMissing',
  delivery_uncertain: 'courseAssignments.reminderErrors.deliveryUncertain',
  transport_changed: 'courseAssignments.reminderErrors.transportChanged',
  recipient_missing: 'courseAssignments.reminderErrors.recipientMissing',
  activation_required: 'courseAssignments.reminderErrors.activationRequired',
  ineligible: 'courseAssignments.reminderErrors.ineligible',
  expired: 'courseAssignments.reminderErrors.expired',
  attempt_limit: 'courseAssignments.reminderErrors.attemptLimit',
  retry_window_expired: 'courseAssignments.reminderErrors.retryWindowExpired',
  payload_changed: 'courseAssignments.reminderErrors.payloadChanged',
  provider_timeout: 'courseAssignments.reminderErrors.providerTimeout',
  provider_unreachable: 'courseAssignments.reminderErrors.providerUnreachable',
  provider_rate_limited: 'courseAssignments.reminderErrors.providerRateLimited',
  provider_unavailable: 'courseAssignments.reminderErrors.providerUnavailable',
  provider_rejected: 'courseAssignments.reminderErrors.providerRejected',
  internal_error: 'courseAssignments.reminderErrors.internalError',
} as const;
// ── component ─────────────────────────────────────────────

export default function EnrollmentsPage() {
  const actor = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);
  const sessionEpoch = useAuthStore((s) => s.sessionEpoch);
  const scope = authorSessionScope({ accessToken, user: actor, sessionEpoch });
  return <AssignmentsContent key={`${scope.generation}:${sessionEpoch}`} />;
}

function AssignmentsContent() {
  const { t, tp, lang } = useT();
  const m = workspaceCopy(lang);
  const translatedLabel = (
    labels: Record<string, TranslationKey>,
    value: string,
    fallback?: TranslationKey,
  ) => labels[value] ? t(labels[value]) : fallback ? t(fallback) : value;
  const { confirm, dialog } = useConfirm();
  const [courses, setCourses] = useState<Course[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedCourse, setSelectedCourse] = useState<string>('');
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [repeatReasons, setRepeatReasons] = useState<Record<string, string>>({});
  const [repeatTarget, setRepeatTarget] = useState<string | null>(null);
  const [repeating, setRepeating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [enrollmentReadState, setEnrollmentReadState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const enrollmentRequest = useRef(0);
  const alive = useRef(true);
  const assignmentCommand = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; enrollmentRequest.current += 1; }; }, []);
  const [enrolling, setEnrolling] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set());
  const [accessLinks, setAccessLinks] = useState<AccessLink[]>([]);
  const [issuedNoEmailAccess, setIssuedNoEmailAccess] = useState<VisibleNoEmailAccess | null>(null);
  const [accessStates, setAccessStates] = useState<Record<string, EnrollmentAccess>>({});
  const [recurringRules, setRecurringRules] = useState<RecurringLearningRule[]>([]);
  const [recurringOccurrences, setRecurringOccurrences] = useState<RecurringOccurrence[]>([]);
  const [recurringCourseId, setRecurringCourseId] = useState('');
  const [recurringUserId, setRecurringUserId] = useState('');
  const [cadenceDays, setCadenceDays] = useState(180);
  const [dueDays, setDueDays] = useState(14);
  const [savingRule, setSavingRule] = useState(false);
  const [reminderDrafts, setReminderDrafts] = useState<Record<string, ReminderDraft>>({});
  const [savingReminderRuleIds, setSavingReminderRuleIds] = useState<Set<string>>(new Set());
  const [reminderHistories, setReminderHistories] = useState<Record<string, ReminderHistoryState>>({});
  const searchParams = useSearchParams();
  const [enrollmentFocus, setEnrollmentFocus] = useState<string | null>(() => {
    const value = searchParams.get('enrollment_id');
    return value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value) ? value : null;
  });
  const preselectionApplied = useRef(false);
  const reminderHistoryControllers = useRef<Record<string, AbortController>>({});
  const token = useAuthStore((s) => s.accessToken);
  const userRole = useAuthStore((s) => s.user?.role);
  const tokenRef = useRef(token);
  const selectedCourseRef = useRef(selectedCourse);
  tokenRef.current = token;
  selectedCourseRef.current = selectedCourse;
  const dataRequest = useRef(0);
  const recurringRequest = useRef(0);
  const canManageAssignments = userRole === 'methodologist';
  const [showEnrollmentTable, setShowEnrollmentTable] = useState(false);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const reminderAuthTokenRef = useRef(token);
  const reminderRequestEpoch = useRef(0);
  reminderAuthTokenRef.current = token;

  useEffect(() => {
    reminderRequestEpoch.current += 1;
    setReminderDrafts({});
    setReminderHistories({});
    setSavingReminderRuleIds(new Set());
    return () => {
      reminderRequestEpoch.current += 1;
      Object.values(reminderHistoryControllers.current).forEach((controller) => controller.abort());
      reminderHistoryControllers.current = {};
    };
  }, [token, canManageAssignments]);

  // ── фильтры (UI-side) ──────────────────────────────────
  const [userSearch, setUserSearch] = useState('');
  const [courseSearch, setCourseSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>('email');
  const [completionWindowMinutes, setCompletionWindowMinutes] = useState<number | null>(null);
  const [linkValidityDays, setLinkValidityDays] = useState(7);
  const [dueAt, setDueAt] = useState('');
  const selectionIdentity = JSON.stringify([selectedCourse, [...selectedUsers].sort(), deliveryMode, completionWindowMinutes, linkValidityDays, dueAt, userRole]);
  const selectionIdentityRef = useRef(selectionIdentity);
  const contextEpoch = useRef(0);
  if (selectionIdentityRef.current !== selectionIdentity) contextEpoch.current += 1;
  selectionIdentityRef.current = selectionIdentity;
  const captureCurrentAction = () => {
    const epoch = contextEpoch.current;
    return () => alive.current && Boolean(token) && tokenRef.current === token
      && selectedCourseRef.current === selectedCourse && contextEpoch.current === epoch;
  };

  const fetchData = useCallback(async () => {
    if (!token || !canManageAssignments || !alive.current || tokenRef.current !== token) return;
    const request = ++dataRequest.current;
    const isCurrent = () => alive.current && tokenRef.current === token && dataRequest.current === request;
    try {
      const [coursesRes, usersRes] = await Promise.all([
        fetch(`${API_URL}/v1/courses?per_page=100`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        // Course assignments are learner-only. Team/system users live on
        // /admin/team and must not be mixed into this picker.
        fetch(
          `${API_URL}/v1/users?per_page=500&role=student&is_active=true`,
          { headers: { Authorization: `Bearer ${token}` } },
        ),
      ]);
      if (coursesRes.ok) {
        const data = await coursesRes.json();
        if (!isCurrent()) return;
        setCourses(Array.isArray(data) ? data.filter((course) => course.status === 'published') : []);
      }
      if (usersRes.ok) {
        const data = await usersRes.json();
        if (!isCurrent()) return;
        setUsers(data.users || []);
      }
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [token, API_URL, canManageAssignments]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchRecurringRules = useCallback(async () => {
    if (!token || !canManageAssignments || !alive.current || tokenRef.current !== token) return;
    const request = ++recurringRequest.current;
    const isCurrent = () => alive.current && tokenRef.current === token && recurringRequest.current === request;
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [rulesResponse, occurrencesResponse] = await Promise.all([
        fetch(`${API_URL}/v1/learning-cycles`, { headers }),
        fetch(`${API_URL}/v1/learning-cycles/occurrences`, { headers }),
      ]);
      if (rulesResponse.ok) { const rules = await rulesResponse.json(); if (isCurrent()) setRecurringRules(rules); }
      if (occurrencesResponse.ok) { const occurrences = await occurrencesResponse.json(); if (isCurrent()) setRecurringOccurrences(occurrences); }
    } catch {
      // The assignments workflow remains usable if the preview API is absent.
    }
  }, [API_URL, canManageAssignments, token]);

  useEffect(() => {
    void fetchRecurringRules();
  }, [fetchRecurringRules]);

  const fetchEnrollments = useCallback(async (courseId: string, preserveSelection = false) => {
    if (!alive.current || tokenRef.current !== token) return;
    const request = ++enrollmentRequest.current;
    const isCurrent = () => alive.current && tokenRef.current === token && request === enrollmentRequest.current;
    if (selectedCourseRef.current !== courseId) {
      contextEpoch.current += 1;
      setIssuedNoEmailAccess(null);
      setAccessLinks([]);
    }
    selectedCourseRef.current = courseId;
    setSelectedCourse(courseId);
    if (!preserveSelection) setSelectedUsers(new Set());
    setEnrollments([]);
    setAccessStates({});
    setStatusFilter('all'); // сброс при смене курса
    if (!token || !courseId) { setEnrollmentReadState('idle'); return; }
    setEnrollmentReadState('loading');
    try {
    const res = await fetch(`${API_URL}/v1/courses/${courseId}/enrollments`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!isCurrent()) return;
    if (!res.ok) throw new Error('enrollment_read_failed');
      const items = await res.json() as Enrollment[];
      if (!isCurrent()) return;
      setEnrollments(items);
      if (!assignmentCommand.current) {
        setSelectedUsers((current) => new Set([...current].filter((id) => !items.some((item) => item.user_id === id))));
      }
      setEnrollmentReadState('ready');
      const noEmail = items.filter((item) => !users.find((user) => user.id === item.user_id)?.email);
      const states = await Promise.all(noEmail.map(async (item) => {
        const response = await fetch(`${API_URL}/v1/courses/enrollments/${item.id}/access`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        return response.ok ? await response.json() as EnrollmentAccess : null;
      }));
      if (isCurrent()) setAccessStates(Object.fromEntries(states.filter(Boolean).map((state) => [state!.enrollment_id, state!] as const)));
    } catch {
      if (isCurrent()) setEnrollmentReadState('error');
    }
  }, [API_URL, token, users]);

  const fetchEnrollmentsRef = useRef(fetchEnrollments);
  fetchEnrollmentsRef.current = fetchEnrollments;

  const enrollmentToken = useRef(token);
  useEffect(() => {
    const previous = enrollmentToken.current;
    enrollmentToken.current = token;
    if (previous && token && previous !== token && selectedCourseRef.current) {
      void fetchEnrollments(selectedCourseRef.current, true);
    }
  }, [token, fetchEnrollments]);

  useEffect(() => {
    if (loading || preselectionApplied.current) return;
    const courseId = searchParams.get('courseId') || searchParams.get('course_id') || searchParams.get('course');
    const legacyUser = searchParams.get('employeeId') || searchParams.get('user');
    const explicitUsers = searchParams.getAll('user_id');
    const userIds = [...new Set(explicitUsers.length ? explicitUsers : legacyUser ? [legacyUser] : [])].slice(0, 50);
    // Do not mark contextual preselection complete until every referenced
    // entity is present. Fetch effects can commit their collections in
    // separate renders, and an early ref flip would strand an empty picker.
    if ((courseId && !courses.some((course) => course.id === courseId)) || userIds.some((id) => !users.some((user) => user.id === id))) return;
    if (courseId && courses.some((course) => course.id === courseId)) {
      void fetchEnrollments(courseId);
    }
    if (userIds.length) {
      setSelectedUsers(new Set(userIds));
      const user = userIds.length === 1 ? users.find((item) => item.id === userIds[0]) : undefined;
      setUserSearch(user ? `${user.first_name} ${user.last_name}`.trim() : '');
    }
    preselectionApplied.current = true;
  }, [courses, fetchEnrollments, loading, searchParams, users]);

  const handleEnroll = async () => {
    if (!selectedCourse || selectedUsers.size === 0 || enrolling || assignmentCommand.current || enrollmentReadState !== 'ready' || !alive.current || !canManageAssignments || !token) return;
    const selected = users.filter((user) => selectedUsers.has(user.id));
    const course = courses.find((item) => item.id === selectedCourse);
    if (!course || course.status !== 'published' || selected.length !== selectedUsers.size
      || selected.some((user) => user.role !== 'student')
      || enrollments.some((item) => item.course_id === selectedCourse && selectedUsers.has(item.user_id))) {
      toast.error(m.invalidSelection);
      return;
    }
    const confirmedSelection = selectionIdentity;
    const confirmedEpoch = contextEpoch.current;
    const confirmedAuthEpoch = getAuthSessionEpoch();
    const commandIsCurrent = () => alive.current && selectionIdentityRef.current === confirmedSelection
      && contextEpoch.current === confirmedEpoch && getAuthSessionEpoch() === confirmedAuthEpoch;
    const withoutAccess = selected.filter((user) => user.has_login_access === false);
    const personalLink = deliveryMode === 'personal_link';
    const withoutEmail = selected.filter((user) => !user.email?.trim());
    if (!personalLink && withoutEmail.length > 0) {
      toast.error(t('courseAssignments.validation.missingEmail'), {
        description: t('courseAssignments.validation.missingEmailHint'),
      });
      return;
    }
    if (personalLink && selectedUsers.size !== 1) {
      toast.info(t('courseAssignments.validation.singlePersonalLink'), {
        description: t('courseAssignments.validation.singlePersonalLinkHint'),
      });
      return;
    }
    if (personalLink && dueAt && !Number.isFinite(new Date(dueAt).getTime())) {
      toast.error(m.invalidDate);
      return;
    }
    const dueAtIso = personalLink && dueAt ? new Date(dueAt).toISOString() : null;
    assignmentCommand.current = true;
    const ok = await confirm({
      title: t('courseAssignments.confirm.assignTitle'),
      message: [
        `${course?.title || t('courseAssignments.fallback.selectedCourse')} ${t('courseAssignments.confirm.willBeAssigned')}. ${t('courseAssignments.confirm.selected')}: ${tp('common.counts.learner', selected.length)}.`,
        personalLink
          ? t('courseAssignments.confirm.personalLinkCreated')
          : withoutAccess.length > 0
          ? `${t('courseAssignments.confirm.activationLinksPrepared')}: ${tp('common.counts.learner', withoutAccess.length)}.`
          : '',
      ].filter(Boolean).join(' '),
      variant: 'info',
      confirmLabel: t('courseAssignments.actions.assign'),
    }).catch(() => false);
    if (!ok) { assignmentCommand.current = false; return; }
    if (!commandIsCurrent() || tokenRef.current !== token) {
      assignmentCommand.current = false;
      if (!alive.current) return;
      toast.error(m.selectionChanged);
      return;
    }
    setEnrolling(true);
    try {
      if (personalLink) {
        const selectedUserId = Array.from(selectedUsers)[0];
        const linkExpiresAt = new Date(Date.now() + linkValidityDays * 24 * 60 * 60 * 1000).toISOString();
        const response = await fetch(`${API_URL}/v1/courses/${selectedCourse}/personal-link-enrollment`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            user_id: selectedUserId,
            link_expires_at: linkExpiresAt,
            completion_window_minutes: completionWindowMinutes,
            due_at: dueAtIso,
          }),
        });
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error?.detail || t('courseAssignments.errors.createPersonalAccess'));
        }
        const credential = await response.json() as NoEmailAccessIssue;
        if (!commandIsCurrent()) return;
        const learner = usersById.get(selectedUserId);
        setIssuedNoEmailAccess({
          ...credential,
          learner_name: learner ? `${learner.first_name} ${learner.last_name}`.trim() : selectedUserId,
        });
        toast.success(t('courseAssignments.success.personalLinkReady'));
        setSelectedUsers(new Set());
        await fetchEnrollmentsRef.current(selectedCourse);
        return;
      }
      const res = await fetch(`${API_URL}/v1/courses/${selectedCourse}/enrollments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          user_ids: Array.from(selectedUsers),
          delivery_mode: deliveryMode,
          completion_window_minutes: personalLink ? completionWindowMinutes : null,
          due_at: dueAtIso,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail || 'Assignment failed');
      }
      const created = await res.json();
      if (!commandIsCurrent()) return;
      if (Array.isArray(created) && created.length > 0) {
        toast.success(`${t('courseAssignments.success.assigned')}: ${tp('common.counts.learner', created.length)}`);
      } else {
        toast.info(t('courseAssignments.info.noNewAssignments'));
      }

      if (!personalLink && withoutAccess.length > 0) {
        toast.info(t('courseAssignments.info.accessSetupAfterSave'));
      }
      setSelectedUsers(new Set());
      await fetchEnrollmentsRef.current(selectedCourse);
    } catch (err: any) {
      if (commandIsCurrent()) toast.error(t('common.saveFailed'), { description: err?.message });
    } finally {
      assignmentCommand.current = false;
      if (alive.current) setEnrolling(false);
    }
  };

  const handleUnenroll = async (enrollment: Enrollment) => {
    const scopeCurrent = captureCurrentAction();
    const isCurrent = () => scopeCurrent() && enrollment.course_id === selectedCourse;
    if (!isCurrent()) return;
    const sourceInfo = getAssignmentSourceInfo(enrollment.source);
    if (sourceInfo.managedByRule) {
      toast.info(t(sourceInfo.labelKey), {
        description: t(sourceInfo.descriptionKey),
      });
      return;
    }
    const ok = await confirm({
      title: t('dialogs.confirmUnenrollUser'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok || !isCurrent()) return;
    try {
      const res = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!isCurrent()) return;
      if (!res.ok) throw new Error('Unenroll failed');
      toast.success(t('toast.courseDeleted'));
      fetchEnrollments(selectedCourse);
    } catch (err: any) {
      if (isCurrent()) toast.error(t('common.saveFailed'), { description: err?.message });
    }
  };

  const repeatEnrollment = async (enrollment: Enrollment) => {
    const scopeCurrent = captureCurrentAction();
    const isCurrent = () => scopeCurrent() && enrollment.course_id === selectedCourse;
    const reason = (repeatReasons[enrollment.id] || '').trim();
    if (!reason || !isCurrent() || enrollment.source !== 'manual') return;
    setRepeating(true);
    try {
      const response = await fetch(`${API_URL}/v1/courses/${selectedCourse}/reassignments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          user_id: enrollment.user_id,
          previous_enrollment_id: enrollment.id,
          reason,
        }),
      });
      if (!isCurrent()) return;
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error?.message || error?.detail || t('courseAssignments.repeat.failed'));
      }
      const result = await response.json() as ReassignmentResult;
      if (!isCurrent()) return;
      setIssuedNoEmailAccess(null);
      if (result.delivery_mode === 'personal_link' && result.personal_access) {
        const learner = users.find((item) => item.id === enrollment.user_id);
        setIssuedNoEmailAccess({
          ...result.personal_access,
          learner_name: learner
            ? `${learner.first_name} ${learner.last_name}`.trim()
            : enrollment.user_id,
        });
      }
      toast.success(t('courseAssignments.repeat.success'));
      setRepeatTarget(null);
      setRepeatReasons((current) => ({ ...current, [enrollment.id]: '' }));
      await fetchEnrollments(selectedCourse);
    } catch (error: any) {
      if (isCurrent()) toast.error(t('courseAssignments.repeat.failed'), { description: error?.message });
    } finally {
      if (alive.current) setRepeating(false);
    }
  };

  const toggleUser = (userId: string) => {
    contextEpoch.current += 1;
    setSelectedUsers((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  };

  // ── derived state (фильтрация) ─────────────────────────

  // Курсы для левого picker'а — фильтруем по courseSearch.
  const filteredCourses = useMemo(
    () => courses.filter((c) => matchesCourseQuery(c, courseSearch)),
    [courses, courseSearch],
  );

  // Карта user.id → user для O(1) lookup'а в enrollment table.
  const usersById = useMemo(() => {
    const m = new Map<string, User>();
    for (const u of users) m.set(u.id, u);
    return m;
  }, [users]);

  // Назначения обучения фильтруются по статусу и данным сотрудника.
  const filteredEnrollments = useMemo(() => {
    return enrollments
      .filter((e) => !enrollmentFocus || e.id === enrollmentFocus)
      .filter((e) => statusFilter === 'all' || e.status === statusFilter)
      .filter((e) => {
        const u = usersById.get(e.user_id);
        // Если user не найден (уволен / удалён) — оставляем запись видимой,
        // но поиск не работает (нечего искать).
        if (!userSearch) return true;
        if (!u) return false;
        return matchesUserQuery(u, userSearch);
      });
  }, [enrollments, enrollmentFocus, statusFilter, userSearch, usersById]);

  // Сотрудники для правой колонки — фильтруем по userSearch.
  // Исключаем тех, кто уже записан на выбранный курс (чтобы не было дублей).
  const enrolledUserIds = useMemo(() => {
    return new Set(enrollments.map((e) => e.user_id));
  }, [enrollments]);
  const availableUsers = useMemo(() => {
    if (!selectedCourse || enrollmentReadState !== 'ready') return [];
    return users.filter(
      (u) => u.role === 'student' && matchesUserQuery(u, userSearch) && !enrolledUserIds.has(u.id),
    );
  }, [users, userSearch, enrolledUserIds, selectedCourse, enrollmentReadState]);

  const copyAccessLink = async (url: string, isCurrent = captureCurrentAction()) => {
    if (!isCurrent()) return;
    await navigator.clipboard.writeText(url);
    if (isCurrent()) toast.success(t('courseAssignments.success.accessLinkCopied'));
  };

  const handleAssignmentAccess = async (enrollment: Enrollment, learner?: User) => {
    const scopeCurrent = captureCurrentAction();
    const isCurrent = () => scopeCurrent() && enrollment.course_id === selectedCourse;
    if (!isCurrent()) return;
    const response = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}/access`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!isCurrent()) return;
    if (!response.ok) {
      toast.error(t('courseAssignments.errors.accessState'));
      return;
    }
    const access = await response.json() as EnrollmentAccess;
    if (!isCurrent()) return;
    if (access.access_kind === 'access_without_email' || access.access_kind === 'personal_link') {
      if (access.state === 'available') {
        const approved = await confirm({
          title: t('courseAssignments.confirm.reissueTitle'),
          message: t('courseAssignments.confirm.reissueMessage'),
          variant: 'danger',
          confirmLabel: t('courseAssignments.actions.reissue'),
        });
        if (!approved || !isCurrent()) return;
      }
      const issued = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}/access-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ delivery_mode: 'personal_link' }),
      });
      if (!isCurrent()) return;
      if (!issued.ok) {
        toast.error(t('courseAssignments.errors.preparePersonalAccess'));
        return;
      }
      const credential = await issued.json() as NoEmailAccessIssue;
      if (!isCurrent()) return;
      setAccessStates((current) => ({ ...current, [enrollment.id]: {
        enrollment_id: enrollment.id, user_id: enrollment.user_id,
        access_kind: access.access_kind, state: 'available', access_url: null,
        expires_at: credential.expires_at, message: t('courseAssignments.access.secureActive'),
      } }));
      setIssuedNoEmailAccess({
        ...credential,
        learner_name: learner ? `${learner.first_name} ${learner.last_name}`.trim() : enrollment.user_id,
      });
      return;
    }
    if (access.access_url) {
      await copyAccessLink(access.access_url, isCurrent);
      return;
    }
    if (!learner) return;
    const invitationRes = await fetch(`${API_URL}/v1/users/${learner.id}/invitation-link`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!isCurrent()) return;
    if (!invitationRes.ok) {
      const error = await invitationRes.json().catch(() => ({}));
      if (!isCurrent()) return;
      toast.error(t('courseAssignments.errors.prepareActivation'), { description: error?.detail });
      return;
    }
    const invitation = await invitationRes.json() as AccessLink;
    if (!isCurrent()) return;
    setAccessLinks([invitation]);
    toast.success(t('courseAssignments.success.activationReady'));
  };

  const handleRevokeAssignmentAccess = async (enrollment: Enrollment, learner?: User) => {
    const scopeCurrent = captureCurrentAction();
    const isCurrent = () => scopeCurrent() && enrollment.course_id === selectedCourse;
    if (!isCurrent()) return;
    const approved = await confirm({
      title: t('courseAssignments.confirm.revokeTitle'),
      message: `${t('courseAssignments.confirm.revokeMessagePrefix')} ${learner ? `${learner.first_name} ${learner.last_name}`.trim() : t('courseAssignments.fallback.employee')} ${t('courseAssignments.confirm.revokeMessageSuffix')}`,
      variant: 'danger',
      confirmLabel: t('courseAssignments.actions.revokeAccess'),
    });
    if (!approved || !isCurrent()) return;
    const response = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}/access-policy/revoke`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ reason: 'revoked_from_assignments_ui' }),
    });
    if (!isCurrent()) return;
    if (!response.ok) {
      toast.error(t('courseAssignments.errors.revokeAccess'));
      return;
    }
    setAccessStates((current) => ({
      ...current,
      [enrollment.id]: {
        ...(current[enrollment.id] || {
          enrollment_id: enrollment.id,
          user_id: enrollment.user_id,
          access_kind: 'personal_link',
          access_url: null,
          message: '',
        }),
        state: 'revoked',
        expires_at: null,
        message: t('courseAssignments.access.revoked'),
      },
    }));
    setIssuedNoEmailAccess((current) => current?.enrollment_id === enrollment.id ? null : current);
    toast.success(t('courseAssignments.success.personalAccessRevoked'));
  };

  const resendNotification = async (enrollment: Enrollment) => {
    const scopeCurrent = captureCurrentAction();
    const isCurrent = () => scopeCurrent() && enrollment.course_id === selectedCourse;
    if (!isCurrent()) return;
    const response = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}/notification/resend`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
    });
    if (!isCurrent()) return;
    if (!response.ok) {
      toast.error(t('courseAssignments.errors.resendNotification'));
      return;
    }
    toast.success(t('courseAssignments.success.notificationResent'));
    await fetchEnrollments(selectedCourse);
  };

  const createRecurringRule = async () => {
    const isCurrent = () => alive.current && Boolean(token) && tokenRef.current === token;
    if (!recurringCourseId || !recurringUserId || !isCurrent()) return;
    setSavingRule(true);
    try {
      const response = await fetch(`${API_URL}/v1/learning-cycles`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          course_id: recurringCourseId,
          user_id: recurringUserId,
          cadence_days: cadenceDays,
          due_days: dueDays,
        }),
      });
      if (!isCurrent()) return;
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        if (!isCurrent()) return;
        throw new Error(error?.detail || t('courseAssignments.errors.saveRule'));
      }
      toast.success(t('courseAssignments.success.ruleDraftSaved'));
      await fetchRecurringRules();
    } catch (error: any) {
      if (isCurrent()) toast.error(t('courseAssignments.errors.saveRule'), { description: error?.message });
    } finally {
      if (alive.current) setSavingRule(false);
    }
  };

  const deactivateRecurringRule = async (ruleId: string) => {
    const isCurrent = () => alive.current && Boolean(token) && tokenRef.current === token;
    if (!isCurrent()) return;
    const response = await fetch(`${API_URL}/v1/learning-cycles/${ruleId}/deactivate`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!isCurrent()) return;
    if (response.ok) await fetchRecurringRules();
    else toast.error(t('courseAssignments.errors.stopRule'));
  };

  const reminderDraftFor = (rule: RecurringLearningRule): ReminderDraft => (
    reminderDrafts[rule.id] ?? {
      enabled: rule.reminder_enabled ?? false,
      daysBeforeDue: String(rule.reminder_days_before_due ?? 1),
    }
  );

  const updateReminderDraft = (rule: RecurringLearningRule, update: Partial<ReminderDraft>) => {
    setReminderDrafts((current) => ({
      ...current,
      [rule.id]: { ...reminderDraftFor(rule), ...update },
    }));
  };

  const saveReminderSettings = async (rule: RecurringLearningRule) => {
    const draft = reminderDraftFor(rule);
    const daysBeforeDue = Number(draft.daysBeforeDue);
    if (!Number.isInteger(daysBeforeDue) || daysBeforeDue < 1 || daysBeforeDue > 30) {
      toast.error(t('courseAssignments.validation.reminderDays'));
      return;
    }
    if (savingReminderRuleIds.has(rule.id)) return;

    const requestToken = token;
    const requestEpoch = reminderRequestEpoch.current;
    const isCurrentRequest = () => reminderAuthTokenRef.current === requestToken
      && reminderRequestEpoch.current === requestEpoch;
    setSavingReminderRuleIds((current) => new Set(current).add(rule.id));
    try {
      const response = await fetch(`${API_URL}/v1/learning-cycles/${rule.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          reminder_enabled: draft.enabled,
          reminder_days_before_due: daysBeforeDue,
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error?.detail || t('courseAssignments.errors.saveReminderSettings'));
      }
      const saved = await response.json() as RecurringLearningRule;
      if (!isCurrentRequest()) return;
      setRecurringRules((current) => current.map((item) => item.id === rule.id ? saved : item));
      setReminderDrafts((current) => {
        const { [rule.id]: _savedDraft, ...remaining } = current;
        return remaining;
      });
      toast.success(t('courseAssignments.success.reminderSettingsSaved'));
    } catch (error: any) {
      if (isCurrentRequest()) {
        toast.error(t('courseAssignments.errors.saveReminderSettings'), { description: error?.message });
      }
    } finally {
      if (isCurrentRequest()) {
        setSavingReminderRuleIds((current) => {
          const next = new Set(current);
          next.delete(rule.id);
          return next;
        });
      }
    }
  };

  const loadReminderHistory = async (ruleId: string) => {
    reminderHistoryControllers.current[ruleId]?.abort();
    const controller = new AbortController();
    const requestToken = token;
    reminderHistoryControllers.current[ruleId] = controller;
    setReminderHistories((current) => ({ ...current, [ruleId]: { state: 'loading' } }));
    try {
      const response = await fetch(`${API_URL}/v1/learning-cycles/${ruleId}/reminders`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error('Reminder history request failed');
      const items = await response.json() as ReminderStatus[];
      if (!controller.signal.aborted && reminderAuthTokenRef.current === requestToken) {
        setReminderHistories((current) => ({ ...current, [ruleId]: { state: 'loaded', items } }));
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError' && !controller.signal.aborted && reminderAuthTokenRef.current === requestToken) {
        setReminderHistories((current) => ({ ...current, [ruleId]: { state: 'error' } }));
      }
    }
  };

  const activateRecurringRule = async (ruleId: string) => {
    const isCurrent = () => alive.current && Boolean(token) && tokenRef.current === token;
    if (!isCurrent()) return;
    const response = await fetch(`${API_URL}/v1/learning-cycles/${ruleId}/activate`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
    });
    if (!isCurrent()) return;
    if (response.ok) {
      toast.success(t('courseAssignments.success.ruleStarted'));
      await fetchRecurringRules();
    } else {
      const error = await response.json().catch(() => ({}));
      if (!isCurrent()) return;
      toast.error(t('courseAssignments.errors.startRule'), { description: error?.detail });
    }
  };

  // ── render ────────────────────────────────────────────

  if (!canManageAssignments) {
    return (
      <WorkspacePage id="assignments" title={t('courseAssignments.accessDenied.title')}>
        <WorkspacePanel>
          <p className="text-sm text-muted-foreground">
            {t('courseAssignments.accessDenied.description')}
          </p>
        </WorkspacePanel>
      </WorkspacePage>
    );
  }

  const renderEnrollment = (e: Enrollment, asPanel = false) => {
    const Row = asPanel ? 'div' : 'tr';
    const Cell = asPanel ? 'div' : 'td';
    const u = usersById.get(e.user_id);
    const sourceInfo = getAssignmentSourceInfo(e.source);
    return (
      <Row key={e.id} className={asPanel ? 'grid min-w-0 gap-2 p-4 sm:grid-cols-2' : 'border-t align-top'}>
        <Cell className="p-2 align-top text-sm [overflow-wrap:anywhere]">
                {asPanel && <p className="text-xs font-semibold text-muted-foreground">{t('users.name')}</p>}
          {u ? (
            <>
              <div className="flex min-h-9 items-center font-medium leading-5">
                {u.first_name} {u.last_name}
              </div>
              {u.position_name && (
                <div className="text-xs text-muted-foreground">
                  {u.position_name}
                  {u.personnel_number &&
                    ` · ${u.personnel_number}`}
                </div>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">
              {e.user_id} ({t('courseAssignments.ui.missingUser')})
            </span>
          )}
        </Cell>
        <Cell className="p-2 align-top [overflow-wrap:anywhere]">
                {asPanel && <p className="text-xs font-semibold text-muted-foreground">{t('courses.status')}</p>}
          <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5">
            <Badge
              className="text-sm font-normal leading-5"
              variant={STATUS_BADGE_VARIANT[e.status] || 'outline'}
            >
              {translatedLabel(STATUS_LABEL_KEYS, e.status)}
            </Badge>
          </span>
        </Cell>
        <Cell className="p-2 align-top [overflow-wrap:anywhere]">
                {asPanel && <p className="text-xs font-semibold text-muted-foreground">{t('courseAssignments.ui.source')}</p>}
          <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5" title={t(sourceInfo.descriptionKey)}>
            <Badge className="text-sm font-normal leading-5" variant={sourceInfo.managedByRule ? 'secondary' : 'outline'}>
              {t(sourceInfo.labelKey)}
            </Badge>
          </span>
          <p className="mt-1 max-w-56 text-xs text-muted-foreground">
            {t(sourceInfo.descriptionKey)}
          </p>
        </Cell>
        <Cell className="p-2 align-top [overflow-wrap:anywhere]">
                {asPanel && <p className="text-xs font-semibold text-muted-foreground">{t('courseAssignments.ui.access')}</p>}
          <div data-testid="assignment-primary-line" className="flex min-h-9 flex-wrap items-center gap-2 text-sm leading-5">
            {e.status !== 'completed' && (
              <Button
                className="h-9 whitespace-nowrap text-sm leading-5"
                variant="outline"
                size="sm"
                onClick={() => void handleAssignmentAccess(e, u)}
              >
                {u && !u.email
                  ? accessStates[e.id]?.state === 'available' ? t('courseAssignments.ui.reissueAccess') : t('courseAssignments.ui.createAccess')
                  : t('courseAssignments.ui.getLink')}
              </Button>
            )}
            {u && !u.email && accessStates[e.id]?.state === 'available' && (
              <Button
                className="h-9 whitespace-nowrap text-sm leading-5"
                variant="outline"
                size="sm"
                onClick={() => void handleRevokeAssignmentAccess(e, u)}
              >
                {t('courseAssignments.actions.revokeAccess')}
              </Button>
            )}
            {e.status === 'completed' && accessStates[e.id]?.state !== 'available' && (
              <span className="text-xs text-muted-foreground">{t('courseAssignments.access.revoked')}</span>
            )}
          </div>
          {u && !u.email && accessStates[e.id]?.state === 'available' && accessStates[e.id]?.expires_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t('courseAssignments.ui.activeUntil')} {new Date(accessStates[e.id].expires_at!).toLocaleString()}
            </p>
          )}
        </Cell>
        <Cell className="p-2 align-top [overflow-wrap:anywhere]">
                {asPanel && <p className="text-xs font-semibold text-muted-foreground">{t('courseAssignments.ui.notification')}</p>}
          {e.notification_status ? (
            <div className="space-y-1">
              <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5">
                <Badge className="text-sm font-normal leading-5" variant={e.notification_status === 'delivered' ? 'default' : e.notification_status === 'dead' ? 'outline' : 'secondary'}>
                  {translatedLabel(NOTIFICATION_STATUS_LABEL_KEYS, e.notification_status)}
                </Badge>
              </span>
              {e.notification_error && <p className="text-xs text-muted-foreground">{e.notification_error}</p>}
              <Button variant="outline" size="sm" onClick={() => void resendNotification(e)}>{t('courseAssignments.ui.resend')}</Button>
            </div>
          ) : <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5 text-muted-foreground">{t('courseAssignments.ui.notRequired')}</span>}
        </Cell>
        <Cell className="p-2 align-top [overflow-wrap:anywhere]">
                {asPanel && <p className="text-xs font-semibold text-muted-foreground">{t('courseAssignments.ui.action')}</p>}
          <Button
            data-testid="assignment-primary-line"
            className="h-9 whitespace-nowrap text-sm leading-5"
            variant="outline"
            size="sm"
            onClick={() => handleUnenroll(e)}
            disabled={sourceInfo.managedByRule}
          >
            {sourceInfo.managedByRule ? t('assignmentSources.managedByRule') : t('common.delete')}
          </Button>
          {canManageAssignments && e.source === 'manual' && e.status !== 'cancelled' && e.status !== 'superseded' && (
            <div className="mt-2 space-y-2">
              {repeatTarget === e.id ? (
                <>
                  <label className="block text-xs" htmlFor={`repeat-reason-${e.id}`}>{t('courseAssignments.repeat.reason')}</label>
                  <Input id={`repeat-reason-${e.id}`} value={repeatReasons[e.id] || ''} onChange={(event) => setRepeatReasons((current) => ({ ...current, [e.id]: event.target.value}))} />
                  <p className="text-xs text-muted-foreground">{t('courseAssignments.repeat.historyPreserved')}</p>
                  <Button size="sm" disabled={!repeatReasons[e.id]?.trim() || repeating} onClick={() => void repeatEnrollment(e)}>{t('courseAssignments.repeat.confirm')}</Button>
                </>
              ) : <Button variant="outline" size="sm" onClick={() => setRepeatTarget(e.id)}>{t('courseAssignments.repeat.action')}</Button>}
            </div>
          )}
        </Cell>
      </Row>
    );
  };

  if (loading) return <WorkspacePage id="assignments" title={t('courseAssignments.title')}><p role="status">{t('common.loading')}</p></WorkspacePage>;

  return (
    <WorkspacePage id="assignments" title={t('courseAssignments.title')} icon={<Users />} description={<>{t('courseAssignments.description')}<p>{t('courseAssignments.testsDescription')}</p></>}>

      {accessLinks.length > 0 && (
        <WorkspacePanel className="border-primary/30" bodyClassName="space-y-3" aria-label={t('courseAssignments.ui.activationTitle')}>
            <div className="flex items-start gap-3">
              <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
              <div>
                <h2 className="font-semibold">{t('courseAssignments.ui.activationTitle')}</h2>
                <p className="text-sm text-muted-foreground">
                  {t('courseAssignments.ui.activationDescription')}
                </p>
              </div>
            </div>
            <div className="space-y-2">
              {accessLinks.map((item) => (
                <div key={item.email} className="flex flex-col gap-2 rounded-md border border-border bg-background p-3 sm:flex-row sm:items-center">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.email}</span>
                  <Button variant="outline" size="sm" onClick={() => copyAccessLink(item.invite_url)}>
                    <Copy className="h-4 w-4" aria-hidden="true" />
                    {t('courseAssignments.ui.copyLink')}
                  </Button>
                </div>
              ))}
            </div>
        </WorkspacePanel>
      )}

      {issuedNoEmailAccess && (
        <WorkspacePanel className="border-primary/30" bodyClassName="space-y-2" aria-label={t('courseAssignments.ui.personalAccessTitle')}>
            <h2 className="font-semibold">{t('courseAssignments.ui.personalAccessTitle')}</h2>
            <p className="text-sm text-muted-foreground">
              {issuedNoEmailAccess.learner_name}. {t('courseAssignments.ui.pinNotice')}
            </p>
            <p className="break-all text-sm">{issuedNoEmailAccess.access_url}</p>
            <p className="font-mono text-lg">PIN: {issuedNoEmailAccess.temporary_pin}</p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => void copyAccessLink(issuedNoEmailAccess.access_url)}>
                <Copy className="mr-2 h-4 w-4" aria-hidden="true" />
                {t('courseAssignments.ui.copyLink')}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={async () => {
                  const isCurrent = captureCurrentAction();
                  if (!isCurrent()) return;
                  await navigator.clipboard.writeText(issuedNoEmailAccess.temporary_pin);
                  if (isCurrent()) toast.success(t('courseAssignments.success.pinCopied'));
                }}
              >
                <KeyRound className="mr-2 h-4 w-4" aria-hidden="true" />
                {t('courseAssignments.ui.copyPin')}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t('courseAssignments.ui.expiresAt')} {new Date(issuedNoEmailAccess.link_expires_at || issuedNoEmailAccess.expires_at || '').toLocaleString()}.
              {issuedNoEmailAccess.completion_window_minutes
                ? t('courseAssignments.ui.completionWindow', { minutes: issuedNoEmailAccess.completion_window_minutes })
                : ''}
            </p>
        </WorkspacePanel>
      )}

      <WorkspaceToolbar aria-label={t('courses.title')} className="grid grid-cols-[minmax(0,1fr)] md:grid-cols-2">
            <div className="min-w-0 space-y-2"><h2 className="text-sm font-semibold">{t('courses.title')}</h2>
            <SearchInput
              value={courseSearch}
              onChange={setCourseSearch}
              placeholder={t('courseAssignments.ui.searchCourse')}
            />
            </div>
            <div className="min-w-0">
            <select
              aria-label={t('courseAssignments.ui.courseLabel')}
              value={selectedCourse}
              onChange={(e) => {
                setAccessLinks([]);
                setEnrollmentFocus(null);
                void fetchEnrollments(e.target.value, !selectedCourse);
              }}
              className="w-full min-w-0 max-w-full border rounded-md px-3 py-2 text-sm"
            >
              <option value="">
                {t('courses.selectCourseCount', { count: filteredCourses.length })}
              </option>
              {filteredCourses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
            {courses.length > 0 && filteredCourses.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t('courseAssignments.ui.noCourses')}
              </p>
            )}
            </div>
      </WorkspaceToolbar>

      <div className="min-w-0 space-y-6">
        <WorkspacePanel title={t('courses.enrollments')} padded={false} bodyClassName="min-w-0 space-y-4 p-4 sm:p-6">

            {selectedCourse && (
              <>
                {enrollmentFocus && <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm" role="status">
                  <span>{t('courseAssignments.ui.focusedEnrollment')}</span>
                  <Button size="sm" variant="outline" onClick={() => setEnrollmentFocus(null)}>{t('courseAssignments.ui.showAllEnrollments')}</Button>
                </div>}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <h3 className="font-medium text-sm text-muted-foreground">
                    {t('courses.enrollments')}: {enrollmentReadState === 'ready' ? filteredEnrollments.length : '—'}
                    {filteredEnrollments.length !== enrollments.length &&
                      ` ${t('courseAssignments.ui.ofTotal', { total: enrollments.length })}`}
                  </h3>
                  {/* Status filter — backend уже вернул все,
                     фильтруем UI-сайдом потому что дешевле. */}
                  <select
                    value={statusFilter}
                    onChange={(e) =>
                      setStatusFilter(e.target.value as StatusFilter)
                    }
                    className="text-xs border rounded-md px-2 py-1"
                    aria-label={t('courseAssignments.ui.statusFilter')}
                  >
                    <option value="all">{t('courseAssignments.status.all')}</option>
                    <option value="enrolled">{t('courseAssignments.status.enrolled')}</option>
                    <option value="in_progress">{t('courseAssignments.status.inProgress')}</option>
                    <option value="completed">{t('courseAssignments.status.completed')}</option>
                  </select>
                </div>

                {canManageAssignments && enrollmentReadState === 'ready' && filteredEnrollments.length > 0 && (
                  <Button type="button" variant="outline" aria-pressed={showEnrollmentTable} onClick={() => setShowEnrollmentTable((value) => !value)}>
                    {showEnrollmentTable ? (lang === 'kk' ? 'Карточкалар' : lang === 'en' ? 'Record cards' : 'Карточки записей')
                      : (lang === 'kk' ? 'Толық кесте' : lang === 'en' ? 'Full table' : 'Полная таблица')}
                  </Button>
                )}
                {/* Search inside the enrolled table — when the
                   course has 50+ enrollees. */}
                {enrollments.length > 10 && (
                  <SearchInput
                    value={userSearch}
                    onChange={setUserSearch}
                    placeholder={t('courseAssignments.ui.searchEmployee')}
                  />
                )}

                {enrollmentReadState !== 'ready' ? <p className="text-sm text-muted-foreground">{m.enrollmentsUnknown}</p> : filteredEnrollments.length === 0 ? (
                  <WorkspaceEmpty title={enrollments.length === 0
                      ? t('courseAssignments.emptyEnrollments')
                      : t('courseAssignments.ui.noFilteredEnrollments')} />
                ) : (
                  canManageAssignments && !showEnrollmentTable ? (
                    <RecordList records={filteredEnrollments} getId={(enrollment) => enrollment.id}
                      title={(enrollment) => {
                        const employee = usersById.get(enrollment.user_id);
                        return employee ? `${employee.first_name} ${employee.last_name}` : t('courseAssignments.ui.missingUser');
                      }}
                      status={(enrollment) => translatedLabel(STATUS_LABEL_KEYS, enrollment.status)}
                      detailsLabel={t('courses.enrollments')}
                      renderDetails={(enrollment) => <>
                        {renderEnrollment(enrollment, true)}
                        <div className="border-t border-border px-5 py-3">
                          <Link className="text-sm font-semibold text-primary hover:underline"
                            href={buildTrainingLogBrowserHref({ filters: { enrollment_id: enrollment.id, course_id: enrollment.course_id }, search: '', returnTo: null })}>
                            {t('nav.trainingLog')}
                          </Link>
                        </div>
                      </>} />
                  ) : (
                  <Table className="min-w-0 max-w-full">
                    <thead>
                      <tr>
                        <th className="text-left p-2">{t('users.name')}</th>
                        <th className="text-left p-2">{t('courses.status')}</th>
                        <th className="text-left p-2">{t('courseAssignments.ui.source')}</th>
                        <th className="text-left p-2">{t('courseAssignments.ui.access')}</th>
                        <th className="text-left p-2">{t('courseAssignments.ui.notification')}</th>
                        <th className="text-left p-2">{t('courseAssignments.ui.action')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredEnrollments.map((enrollment) => renderEnrollment(enrollment))}
                    </tbody>
                  </Table>
                  )
                )}
              </>
            )}
        </WorkspacePanel>

        {/* New audience and delivery settings stay separate from existing enrollments. */}
        <WorkspacePanel title={t('courseAssignments.ui.learners')} bodyClassName="space-y-5" actions={
              <Button
                onClick={handleEnroll}
                disabled={
                  !selectedCourse || selectedUsers.size === 0 || enrolling || enrollmentReadState !== 'ready'
                  || (deliveryMode === 'personal_link' && selectedUsers.size !== 1)
                }
              >
                {enrolling
                  ? t('common.loading')
                  : t('courseAssignments.ui.assignCount', { count: selectedUsers.size })}
              </Button>
        }>
          <div className="grid min-w-0 gap-6 xl:grid-cols-2">
            <div className="min-w-0 space-y-4 rounded-xl bg-muted/25 p-4">
            <fieldset className="space-y-3 rounded-md border border-border p-3">
              <legend className="px-1 text-sm font-medium">{t('courseAssignments.ui.deliveryLegend')}</legend>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="delivery-mode"
                  value="email"
                  checked={deliveryMode === 'email'}
                  onChange={() => { contextEpoch.current += 1; setDeliveryMode('email'); }}
                />
                <span><b>{t('courseAssignments.ui.email')}</b><span className="block text-xs text-muted-foreground">{t('courseAssignments.ui.emailHint')}</span></span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="delivery-mode"
                  value="personal_link"
                  checked={deliveryMode === 'personal_link'}
                  onChange={() => { contextEpoch.current += 1; setDeliveryMode('personal_link'); }}
                />
                <span><b>{t('courseAssignments.ui.personalLink')}</b><span className="block text-xs text-muted-foreground">{t('courseAssignments.ui.personalLinkHint')}</span></span>
              </label>
              {deliveryMode === 'personal_link' && (
                <details className="rounded-md border border-border p-3">
                  <summary className="cursor-pointer text-sm font-medium">
                    <span>{t('courseAssignments.deadlineOptions.title')}</span>
                    <span className="mt-1 block text-xs font-normal text-muted-foreground">
                      {t('courseAssignments.deadlineOptions.validity', { days: linkValidityDays })}
                      {' · '}
                      {completionWindowMinutes
                        ? t('courseAssignments.deadlineOptions.window', { minutes: completionWindowMinutes })
                        : t('courseAssignments.deadlineOptions.noWindow')}
                      {dueAt && ` · ${t('courseAssignments.ui.dueDateAria')} ${new Date(dueAt).toLocaleString()}`}
                    </span>
                  </summary>
                  <div data-testid="personal-link-settings-grid" className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label data-testid="personal-link-field" className="grid min-w-0 content-start gap-y-1 text-sm">
                    <span className="leading-5">{t('courseAssignments.ui.completionWindowLabel')}</span>
                    <Input
                      className="h-10"
                      type="number"
                      aria-label={t('courseAssignments.ui.completionWindowLabel')}
                      min={1}
                      max={1440}
                      value={completionWindowMinutes ?? ''}
                      placeholder={t('courseAssignments.ui.unlimited')}
                      onChange={(event) => { contextEpoch.current += 1; setCompletionWindowMinutes(event.target.value ? Number(event.target.value) : null); }}
                    />
                    <span className="block text-xs text-muted-foreground">{t('courseAssignments.ui.completionWindowHint')}</span>
                  </label>
                  <label data-testid="personal-link-field" className="grid min-w-0 content-start gap-y-1 text-sm">
                    <span className="leading-5">{t('courseAssignments.ui.linkValidityLabel')}</span>
                    <Input
                      className="h-10"
                      type="number"
                      aria-label={t('courseAssignments.ui.linkValidityLabel')}
                      min={1}
                      max={31}
                      value={linkValidityDays}
                      onChange={(event) => { contextEpoch.current += 1; setLinkValidityDays(Number(event.target.value)); }}
                    />
                    <span className="block text-xs text-muted-foreground">{t('courseAssignments.ui.linkValidityHint')}</span>
                  </label>
                  <label data-testid="personal-link-field" className="grid min-w-0 gap-y-1 text-sm sm:col-span-2">
                    <span className="leading-5">{t('courseAssignments.ui.dueDateLabel')}</span>
                    <Input
                      className="h-10"
                      type="datetime-local"
                      aria-label={t('courseAssignments.ui.dueDateAria')}
                      value={dueAt}
                      onChange={(event) => { contextEpoch.current += 1; setDueAt(event.target.value); }}
                    />
                    <span className="block text-xs text-muted-foreground">{t('courseAssignments.ui.dueDateHint')}</span>
                  </label>
                  </div>
                </details>
              )}
              {deliveryMode === 'personal_link' && selectedUsers.size > 1 && (
                <p className="text-sm text-warning" role="alert">
                  {t('courseAssignments.ui.singleEmployeeHint')}
                </p>
              )}
            </fieldset>
            <AssignmentSelectionPreview
              lang={lang}
              courseTitle={courses.find((course) => course.id === selectedCourse)?.title}
              names={users.filter((learner) => selectedUsers.has(learner.id)).map((learner) => `${learner.first_name} ${learner.last_name}`.trim())}
              existingCount={enrollmentReadState === 'ready' ? new Set(enrollments.filter((item) => item.course_id === selectedCourse).map((item) => item.user_id)).size : null}
              completedCount={enrollmentReadState === 'ready' ? new Set(enrollments.filter((item) => item.course_id === selectedCourse && item.status === 'completed').map((item) => item.user_id)).size : null}
              deliveryLabel={t(deliveryMode === 'personal_link' ? 'courseAssignments.ui.personalLink' : 'courseAssignments.ui.email')}
            />
            </div>
            <div className="min-w-0 space-y-4">
            {enrollmentReadState === 'loading' && <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p>}
            {enrollmentReadState === 'error' && <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm"><p>{t('common.loadFailed')}</p><Button type="button" variant="outline" size="sm" onClick={() => void fetchEnrollments(selectedCourse)}>{m.retry}</Button></div>}
            <p className="text-sm text-muted-foreground">
              {selectedCourse && enrollmentReadState !== 'ready' ? m.recipientsUnknown : selectedCourse
                ? t('courseAssignments.ui.availableCount', { available: availableUsers.length, total: tp('common.counts.learnerTotal', users.length) })
                : t('courseAssignments.ui.selectCourseHint')}
            </p>
            <SearchInput
              value={userSearch}
              onChange={setUserSearch}
              placeholder={t('courseAssignments.ui.searchLearner')}
            />
            <div className="max-h-96 overflow-y-auto space-y-2 rounded-xl border border-border p-2">
              {selectedCourse && enrollmentReadState !== 'ready' ? null : availableUsers.length === 0 && users.length > 0 ? (
                <p className="text-xs text-muted-foreground p-2">
                  {selectedCourse
                    ? t('courseAssignments.ui.allAlreadyAssigned')
                    : t('courseAssignments.ui.selectCourseToList')}
                </p>
              ) : (
                availableUsers.map((user) => (
                  <label
                    key={user.id}
                    className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer ${
                      selectedUsers.has(user.id)
                        ? 'bg-primary/10'
                        : 'hover:bg-muted'
                    }`}
                  >
                    <input
                      type="checkbox"
                      aria-label={`${user.first_name} ${user.last_name}`.trim()}
                      checked={selectedUsers.has(user.id)}
                      onChange={() => toggleUser(user.id)}
                      disabled={!selectedCourse}
                      className="rounded"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium">
                        {user.first_name} {user.last_name}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {user.position_name && `${user.position_name} · `}
                        {user.email || t('courseAssignments.ui.emailMissing')}
                        {user.personnel_number && ` · ${user.personnel_number}`}
                      </div>
                      {user.has_login_access === false && (
                        <div className="mt-1 text-xs font-medium text-warning">
                          {t('courseAssignments.ui.accessLinkAfterAssignment')}
                        </div>
                      )}
                      {deliveryMode === 'email' && !user.email?.trim() && (
                        <div className="mt-1 text-xs font-medium text-warning">
                          {t('courseAssignments.ui.personalLinkRequired')}
                        </div>
                      )}
                    </div>
                  </label>
                ))
              )}
            </div>
            </div>
          </div>
        </WorkspacePanel>
      </div>

      <WorkspacePanel title={t('courseAssignments.ui.recurringTitle')} description={t('courseAssignments.ui.recurringDescription')} bodyClassName="space-y-4">
          <WorkspaceToolbar className="bg-muted/25 shadow-none">
            <label className="min-w-0 max-w-full text-sm">
              {t('courseAssignments.ui.course')}
              <select className="mt-1 block w-full min-w-0 max-w-full rounded border bg-background px-2 py-1" value={recurringCourseId} onChange={(event) => setRecurringCourseId(event.target.value)}>
                <option value="">{t('courseAssignments.ui.selectCourse')}</option>
                {courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
              </select>
            </label>
            <label className="min-w-0 max-w-full text-sm">
              {t('courseAssignments.ui.learner')}
              <select className="mt-1 block w-full min-w-0 max-w-full rounded border bg-background px-2 py-1" value={recurringUserId} onChange={(event) => setRecurringUserId(event.target.value)}>
                <option value="">{t('courseAssignments.ui.selectLearner')}</option>
                {users.map((learner) => <option key={learner.id} value={learner.id}>{learner.first_name} {learner.last_name}</option>)}
              </select>
            </label>
            <label className="text-sm">
              {t('courseAssignments.ui.cadence')}
              <input className="mt-1 block w-32 rounded border bg-background px-2 py-1" type="number" min={1} max={3660} value={cadenceDays} onChange={(event) => setCadenceDays(Number(event.target.value))} />
            </label>
            <label className="text-sm">
              {t('courseAssignments.ui.dueDays')}
              <input className="mt-1 block w-32 rounded border bg-background px-2 py-1" type="number" min={0} max={365} value={dueDays} onChange={(event) => setDueDays(Number(event.target.value))} />
            </label>
            <Button variant="outline" onClick={() => void createRecurringRule()} disabled={savingRule || !recurringCourseId || !recurringUserId}>
              {t('courseAssignments.ui.saveDraft')}
            </Button>
          </WorkspaceToolbar>
          <p className="text-xs text-muted-foreground">{t('courseAssignments.ui.recurringHint')}</p>
          <div className="space-y-2">
            {recurringRules.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('courseAssignments.ui.noRules')}</p>
            ) : recurringRules.map((rule) => {
              const course = courses.find((item) => item.id === rule.course_id);
              const learner = users.find((item) => item.id === rule.user_id);
              const occurrence = recurringOccurrences.find((item) => item.rule_id === rule.id);
              const reminderDraft = reminderDraftFor(rule);
              const savingReminder = savingReminderRuleIds.has(rule.id);
              const savedReminderEnabled = rule.reminder_enabled ?? false;
              const savedReminderDays = rule.reminder_days_before_due ?? 1;
              const reminderDraftIsSaved = reminderDraft.enabled === savedReminderEnabled
                && Number(reminderDraft.daysBeforeDue) === savedReminderDays;
              const reminderHistory = reminderHistories[rule.id] ?? { state: 'idle' as const };
              const occurrenceLabel = occurrence
                ? translatedLabel({
                    assigned: 'courseAssignments.occurrence.assigned',
                    overdue: 'courseAssignments.occurrence.overdue',
                    completed: 'courseAssignments.occurrence.completed',
                    completed_late: 'courseAssignments.occurrence.completedLate',
                    skipped: 'courseAssignments.occurrence.skipped',
                  }, occurrence.status)
                : null;
              const targetLabel = course?.title || (rule.target_type === 'learning_path' || rule.learning_path_id
                ? t('courseAssignments.ui.learningProgram')
                : t('courseAssignments.ui.learningCourse'));
              return (
                <div key={rule.id} className="space-y-3 rounded border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{targetLabel} · {learner ? `${learner.first_name} ${learner.last_name}` : t('courseAssignments.ui.learnerFallback')}</p>
                    <p className="text-xs text-muted-foreground">{t('courseAssignments.ui.recurrenceSummary', { cadence: rule.cadence_days, due: rule.due_days, next: rule.next_run_at ? new Date(rule.next_run_at).toLocaleString() : t('courseAssignments.ui.notScheduled') })}</p>
                    {occurrence && <p className={`mt-1 text-xs ${occurrence.status === 'overdue' || occurrence.status === 'completed_late' ? 'font-medium text-destructive' : 'text-muted-foreground'}`}>
                      {t('courseAssignments.ui.occurrenceSummary', { status: occurrenceLabel || '', due: new Date(occurrence.due_at).toLocaleString() })}
                      {occurrence.completed_at ? ` ${t('courseAssignments.ui.completedSummary', { completed: new Date(occurrence.completed_at).toLocaleString() })}` : ''}
                    </p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{rule.status === 'draft' ? t('courseAssignments.ui.draft') : rule.status === 'active' ? t('courseAssignments.ui.active') : t('courseAssignments.ui.stopped')}</Badge>
                    {rule.status === 'active' && <Button size="sm" variant="outline" onClick={() => void deactivateRecurringRule(rule.id)}>{t('courseAssignments.ui.stop')}</Button>}
                    {rule.status !== 'active' && <Button size="sm" onClick={() => void activateRecurringRule(rule.id)}>{t('courseAssignments.ui.start')}</Button>}
                  </div>
                  </div>
                  <fieldset className="space-y-2 rounded bg-muted/30 p-3">
                    <legend className="px-1 text-sm font-medium">{t('courseAssignments.ui.reminderTitle')}</legend>
                    <p className="text-xs text-muted-foreground">{t('courseAssignments.ui.reminderDescription')}</p>
                    <div className="flex flex-wrap items-end gap-3">
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={reminderDraft.enabled}
                          disabled={savingReminder}
                          onChange={(event) => updateReminderDraft(rule, { enabled: event.target.checked })}
                        />
                        {t('courseAssignments.ui.enableReminder')}
                      </label>
                      <label className="text-sm">
                        {t('courseAssignments.ui.daysBeforeDue')}
                        <input
                          aria-label={t('courseAssignments.ui.daysBeforeDueForRule', { id: rule.id })}
                          className="mt-1 block w-28 rounded border bg-background px-2 py-1"
                          type="number"
                          min={1}
                          max={30}
                          inputMode="numeric"
                          value={reminderDraft.daysBeforeDue}
                          disabled={savingReminder}
                          onChange={(event) => updateReminderDraft(rule, { daysBeforeDue: event.target.value })}
                        />
                      </label>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void saveReminderSettings(rule)}
                        disabled={savingReminder || reminderDraftIsSaved}
                      >
                        {savingReminder ? t('courseAssignments.ui.saving') : t('courseAssignments.ui.saveReminder')}
                      </Button>
                      <span className="text-xs text-muted-foreground" aria-live="polite">
                        {reminderDraftIsSaved ? t('courseAssignments.ui.saved') : t('courseAssignments.ui.unsaved')}
                      </span>
                    </div>
                  </fieldset>
                  <div className="space-y-2">
                    <Button size="sm" variant="ghost" onClick={() => void loadReminderHistory(rule.id)} disabled={reminderHistory.state === 'loading'}>
                      {reminderHistory.state === 'loading' ? t('courseAssignments.ui.loadingReminderStatuses') : t('courseAssignments.ui.showReminderStatuses')}
                    </Button>
                    <div aria-live="polite">
                      {reminderHistory.state === 'loading' && <p className="text-xs text-muted-foreground">{t('courseAssignments.ui.loadingReminderStatuses')}</p>}
                      {reminderHistory.state === 'error' && <p className="text-xs text-destructive">{t('courseAssignments.ui.reminderHistoryError')}</p>}
                      {reminderHistory.state === 'loaded' && reminderHistory.items.length === 0 && <p className="text-xs text-muted-foreground">{t('courseAssignments.ui.noReminderStatuses')}</p>}
                      {reminderHistory.state === 'loaded' && reminderHistory.items.length > 0 && (
                        <ul className="space-y-1 text-xs text-muted-foreground" aria-label={t('courseAssignments.ui.reminderStatusesForRule', { id: rule.id })}>
                          {reminderHistory.items.map((status) => (
                            <li key={status.id}>
                              {t('courseAssignments.ui.reminderStatusSummary', { status: translatedLabel(REMINDER_STATUS_LABEL_KEYS, status.status, 'courseAssignments.reminderStatus.unknown'), attempts: status.attempt_count, scheduled: new Date(status.scheduled_at).toLocaleString() })}
                              {status.delivered_at ? ` · ${t('courseAssignments.ui.sentSummary', { sent: new Date(status.delivered_at).toLocaleString() })}` : ''}
                              {status.last_error_category ? ` · ${t('courseAssignments.ui.reasonSummary', { reason: translatedLabel(REMINDER_ERROR_LABEL_KEYS, status.last_error_category, 'courseAssignments.reminderErrors.unknown') })}` : ''}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                  </div>
              );
            })}
          </div>
      </WorkspacePanel>

      {dialog}
    </WorkspacePage>
  );
}
