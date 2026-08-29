'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { Copy, KeyRound } from 'lucide-react';
import {
  Card,
  CardContent,
  Button,
  Badge,
  Table,
  SearchInput,
  Input,
} from '@/components/ui';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { getAssignmentSourceInfo } from '@/lib/assignmentSource';

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
  state: 'available' | 'needs_activation' | 'blocked';
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

interface RecurringLearningRule {
  id: string;
  course_id: string;
  user_id: string;
  cadence_days: number;
  due_days: number;
  status: 'draft' | 'active' | 'inactive';
  next_run_at: string | null;
  last_run_at: string | null;
}

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

const STATUS_LABELS: Record<string, string> = {
  enrolled: 'Записан',
  in_progress: 'В процессе',
  completed: 'Пройден',
};
const STATUS_BADGE_VARIANT: Record<string, 'default' | 'outline' | 'secondary'> = {
  enrolled: 'outline',
  in_progress: 'secondary',
  completed: 'default',
};
// ── component ─────────────────────────────────────────────

export default function EnrollmentsPage() {
  const { t, tp } = useT();
  const { confirm, dialog } = useConfirm();
  const [courses, setCourses] = useState<Course[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedCourse, setSelectedCourse] = useState<string>('');
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [loading, setLoading] = useState(true);
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
  const searchParams = useSearchParams();
  const preselectionApplied = useRef(false);
  const token = useAuthStore((s) => s.accessToken);
  const userRole = useAuthStore((s) => s.user?.role);
  const canManageAssignments = userRole === 'methodologist';
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  // ── фильтры (UI-side) ──────────────────────────────────
  const [userSearch, setUserSearch] = useState('');
  const [courseSearch, setCourseSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>('email');
  const [completionWindowMinutes, setCompletionWindowMinutes] = useState<number | null>(null);
  const [linkValidityDays, setLinkValidityDays] = useState(7);
  const [dueAt, setDueAt] = useState('');

  const fetchData = useCallback(async () => {
    if (!token || !canManageAssignments) return;
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
        setCourses(Array.isArray(data) ? data.filter((course) => course.status === 'published') : []);
      }
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users || []);
      }
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, canManageAssignments]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchRecurringRules = useCallback(async () => {
    if (!token || !canManageAssignments) return;
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [rulesResponse, occurrencesResponse] = await Promise.all([
        fetch(`${API_URL}/v1/learning-cycles`, { headers }),
        fetch(`${API_URL}/v1/learning-cycles/occurrences`, { headers }),
      ]);
      if (rulesResponse.ok) setRecurringRules(await rulesResponse.json());
      if (occurrencesResponse.ok) setRecurringOccurrences(await occurrencesResponse.json());
    } catch {
      // The assignments workflow remains usable if the preview API is absent.
    }
  }, [API_URL, canManageAssignments, token]);

  useEffect(() => {
    void fetchRecurringRules();
  }, [fetchRecurringRules]);

  const fetchEnrollments = useCallback(async (courseId: string) => {
    setSelectedCourse(courseId);
    setSelectedUsers(new Set());
    setStatusFilter('all'); // сброс при смене курса
    if (!token || !courseId) return;
    const res = await fetch(`${API_URL}/v1/courses/${courseId}/enrollments`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const items = await res.json() as Enrollment[];
      setEnrollments(items);
      const noEmail = items.filter((item) => !users.find((user) => user.id === item.user_id)?.email);
      const states = await Promise.all(noEmail.map(async (item) => {
        const response = await fetch(`${API_URL}/v1/courses/enrollments/${item.id}/access`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        return response.ok ? await response.json() as EnrollmentAccess : null;
      }));
      setAccessStates(Object.fromEntries(states.filter(Boolean).map((state) => [state!.enrollment_id, state!] as const)));
    }
  }, [API_URL, token, users]);

  useEffect(() => {
    if (loading || preselectionApplied.current) return;
    const courseId = searchParams.get('courseId') || searchParams.get('course_id') || searchParams.get('course');
    const userId = searchParams.get('employeeId') || searchParams.get('user_id') || searchParams.get('user');
    if (courseId && courses.some((course) => course.id === courseId)) {
      void fetchEnrollments(courseId);
    }
    if (userId && users.some((user) => user.id === userId)) {
      setSelectedUsers(new Set([userId]));
      const user = users.find((item) => item.id === userId);
      setUserSearch(user ? `${user.first_name} ${user.last_name}`.trim() : '');
    }
    preselectionApplied.current = true;
  }, [courses, fetchEnrollments, loading, searchParams, users]);

  const handleEnroll = async () => {
    if (!selectedCourse || selectedUsers.size === 0) return;
    const selected = users.filter((user) => selectedUsers.has(user.id));
    const course = courses.find((item) => item.id === selectedCourse);
    const withoutAccess = selected.filter((user) => user.has_login_access === false);
    const personalLink = deliveryMode === 'personal_link';
    const withoutEmail = selected.filter((user) => !user.email?.trim());
    if (!personalLink && withoutEmail.length > 0) {
      toast.error('У выбранных сотрудников нет email', {
        description: 'Укажите email в карточке сотрудника или выберите персональную ссылку и PIN.',
      });
      return;
    }
    if (personalLink && selectedUsers.size !== 1) {
      toast.info('Персональный доступ создаётся по одному сотруднику', {
        description: 'Выберите одного человека, чтобы одноразовый PIN не потерялся и не попал другому адресату.',
      });
      return;
    }
    const dueAtIso = personalLink && dueAt ? new Date(dueAt).toISOString() : null;
    const ok = await confirm({
      title: 'Назначить обучение?',
      message: [
        `${course?.title || 'Выбранный курс'} будет назначен. Выбрано: ${tp('common.counts.learner', selected.length)}.`,
        personalLink
          ? 'Для каждого сотрудника будет создана персональная ссылка и PIN.'
          : withoutAccess.length > 0
          ? `Ссылки активации будут подготовлены: ${tp('common.counts.learner', withoutAccess.length)}.`
          : '',
      ].filter(Boolean).join(' '),
      variant: 'info',
      confirmLabel: 'Назначить',
    });
    if (!ok) return;
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
          throw new Error(error?.detail || 'Не удалось создать назначение и персональный доступ');
        }
        const credential = await response.json() as NoEmailAccessIssue;
        const learner = usersById.get(selectedUserId);
        setIssuedNoEmailAccess({
          ...credential,
          learner_name: learner ? `${learner.first_name} ${learner.last_name}`.trim() : selectedUserId,
        });
        toast.success('Курс назначен, персональная ссылка и PIN готовы');
        setSelectedUsers(new Set());
        await fetchEnrollments(selectedCourse);
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
      if (Array.isArray(created) && created.length > 0) {
        toast.success(`Назначено: ${tp('common.counts.learner', created.length)}`);
      } else {
        toast.info('Новых назначений нет: выбранные обучающиеся уже назначены или недоступны');
      }

      if (!personalLink && withoutAccess.length > 0) {
        toast.info('Назначение сохранено: настройте доступ у сотрудника в списке назначений.');
      }
      setSelectedUsers(new Set());
      await fetchEnrollments(selectedCourse);
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: err?.message });
    } finally {
      setEnrolling(false);
    }
  };

  const handleUnenroll = async (enrollment: Enrollment) => {
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
    if (!ok) return;
    try {
      const res = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Unenroll failed');
      toast.success(t('toast.courseDeleted'));
      fetchEnrollments(selectedCourse);
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: err?.message });
    }
  };

  const toggleUser = (userId: string) => {
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
      .filter((e) => statusFilter === 'all' || e.status === statusFilter)
      .filter((e) => {
        const u = usersById.get(e.user_id);
        // Если user не найден (уволен / удалён) — оставляем запись видимой,
        // но поиск не работает (нечего искать).
        if (!userSearch) return true;
        if (!u) return false;
        return matchesUserQuery(u, userSearch);
      });
  }, [enrollments, statusFilter, userSearch, usersById]);

  // Сотрудники для правой колонки — фильтруем по userSearch.
  // Исключаем тех, кто уже записан на выбранный курс (чтобы не было дублей).
  const enrolledUserIds = useMemo(() => {
    return new Set(enrollments.map((e) => e.user_id));
  }, [enrollments]);
  const availableUsers = useMemo(() => {
    return users.filter(
      (u) => u.role === 'student' && matchesUserQuery(u, userSearch) && !enrolledUserIds.has(u.id),
    );
  }, [users, userSearch, enrolledUserIds]);

  const copyAccessLink = async (url: string) => {
    await navigator.clipboard.writeText(url);
    toast.success('Ссылка доступа скопирована');
  };

  const handleAssignmentAccess = async (enrollment: Enrollment, learner?: User) => {
    const response = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}/access`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      toast.error('Не удалось получить состояние доступа');
      return;
    }
    const access = await response.json() as EnrollmentAccess;
    if (access.access_kind === 'access_without_email' || access.access_kind === 'personal_link') {
      if (access.state === 'available') {
        const approved = await confirm({
          title: 'Перевыпустить доступ?',
          message: 'Действующая ссылка и PIN будут отозваны. Новый PIN показывается только один раз.',
          variant: 'danger',
          confirmLabel: 'Перевыпустить',
        });
        if (!approved) return;
      }
      const issued = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}/access-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ delivery_mode: 'personal_link' }),
      });
      if (!issued.ok) {
        toast.error('Не удалось подготовить доступ без email');
        return;
      }
      const credential = await issued.json() as NoEmailAccessIssue;
      setAccessStates((current) => ({ ...current, [enrollment.id]: {
        enrollment_id: enrollment.id, user_id: enrollment.user_id,
        access_kind: access.access_kind, state: 'available', access_url: null,
        expires_at: credential.expires_at, message: 'Защищённый доступ активен',
      } }));
      setIssuedNoEmailAccess({
        ...credential,
        learner_name: learner ? `${learner.first_name} ${learner.last_name}`.trim() : enrollment.user_id,
      });
      return;
    }
    if (access.access_url) {
      await copyAccessLink(access.access_url);
      return;
    }
    if (!learner) return;
    const invitationRes = await fetch(`${API_URL}/v1/users/${learner.id}/invitation-link`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!invitationRes.ok) {
      const error = await invitationRes.json().catch(() => ({}));
      toast.error('Не удалось подготовить активацию', { description: error?.detail });
      return;
    }
    const invitation = await invitationRes.json() as AccessLink;
    setAccessLinks([invitation]);
    toast.success('Ссылка активации подготовлена');
  };

  const resendNotification = async (enrollment: Enrollment) => {
    const response = await fetch(`${API_URL}/v1/courses/enrollments/${enrollment.id}/notification/resend`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      toast.error('Не удалось повторно отправить уведомление');
      return;
    }
    toast.success('Уведомление поставлено на повторную отправку');
    await fetchEnrollments(selectedCourse);
  };

  const createRecurringRule = async () => {
    if (!recurringCourseId || !recurringUserId) return;
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
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error?.detail || 'Не удалось сохранить правило');
      }
      toast.success('Черновик повторного обучения сохранён');
      await fetchRecurringRules();
    } catch (error: any) {
      toast.error('Не удалось сохранить правило', { description: error?.message });
    } finally {
      setSavingRule(false);
    }
  };

  const deactivateRecurringRule = async (ruleId: string) => {
    const response = await fetch(`${API_URL}/v1/learning-cycles/${ruleId}/deactivate`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.ok) await fetchRecurringRules();
    else toast.error('Не удалось остановить правило');
  };

  const activateRecurringRule = async (ruleId: string) => {
    const response = await fetch(`${API_URL}/v1/learning-cycles/${ruleId}/activate`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
    });
    if (response.ok) {
      toast.success('Повторное обучение запущено');
      await fetchRecurringRules();
    } else {
      const error = await response.json().catch(() => ({}));
      toast.error('Не удалось запустить правило', { description: error?.detail });
    }
  };

  // ── render ────────────────────────────────────────────

  if (!canManageAssignments) {
    return (
      <Card>
        <CardContent className="p-6 space-y-2">
          <h1 className="text-xl font-semibold">Назначения курсов</h1>
          <p className="text-sm text-muted-foreground">
            Этот раздел доступен методологу. Администратор тенанта управляет
            командой, доступами и настройками организации, но не назначает
            учебные траектории обучающимся.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Назначения и доступ</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Назначайте опубликованные курсы сотрудникам и явно выбирайте способ доступа: email либо
          персональная ссылка и PIN для открытия на телефоне без обычного входа.
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Тесты уроков становятся доступны вместе с курсом — назначать их отдельно не нужно.
        </p>
      </div>

      {accessLinks.length > 0 && (
        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="space-y-3 p-4">
            <div className="flex items-start gap-3">
              <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
              <div>
                <h2 className="font-semibold">Ссылка активации аккаунта</h2>
                <p className="text-sm text-muted-foreground">
                  Это отдельный шаг от назначения курса. Назначенный курс уже сохранён.
                </p>
              </div>
            </div>
            <div className="space-y-2">
              {accessLinks.map((item) => (
                <div key={item.email} className="flex flex-col gap-2 rounded-md border border-border bg-background p-3 sm:flex-row sm:items-center">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.email}</span>
                  <Button variant="outline" size="sm" onClick={() => copyAccessLink(item.invite_url)}>
                    <Copy className="h-4 w-4" aria-hidden="true" />
                    Скопировать ссылку
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {issuedNoEmailAccess && (
        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="space-y-2 p-4">
            <h2 className="font-semibold">Персональный доступ сотрудника</h2>
            <p className="text-sm text-muted-foreground">
              {issuedNoEmailAccess.learner_name}. PIN показывается только сейчас; передайте его отдельно от ссылки.
            </p>
            <p className="break-all text-sm">{issuedNoEmailAccess.access_url}</p>
            <p className="font-mono text-lg">PIN: {issuedNoEmailAccess.temporary_pin}</p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => void copyAccessLink(issuedNoEmailAccess.access_url)}>
                <Copy className="mr-2 h-4 w-4" aria-hidden="true" />
                Копировать ссылку
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={async () => {
                  await navigator.clipboard.writeText(issuedNoEmailAccess.temporary_pin);
                  toast.success('PIN скопирован');
                }}
              >
                <KeyRound className="mr-2 h-4 w-4" aria-hidden="true" />
                Копировать PIN
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Действует до {new Date(issuedNoEmailAccess.link_expires_at || issuedNoEmailAccess.expires_at || '').toLocaleString()}.
              {issuedNoEmailAccess.completion_window_minutes
                ? ` После первого входа на прохождение отводится ${issuedNoEmailAccess.completion_window_minutes} минут.`
                : ''}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* ── LEFT: course selector + enrolled users ─────── */}
        <Card>
          <CardContent className="p-4 space-y-4">
            <h2 className="font-semibold">{t('courses.title')}</h2>

            <SearchInput
              value={courseSearch}
              onChange={setCourseSearch}
              placeholder="Найти курс…"
            />

            <select
              aria-label="Курс для назначения"
              value={selectedCourse}
              onChange={(e) => {
                setAccessLinks([]);
                void fetchEnrollments(e.target.value);
              }}
              className="w-full border rounded-md px-3 py-2 text-sm"
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
                Ничего не найдено. Попробуйте короче запрос.
              </p>
            )}

            {selectedCourse && (
              <>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <h3 className="font-medium text-sm text-muted-foreground">
                    {t('courses.enrollments')}: {filteredEnrollments.length}
                    {filteredEnrollments.length !== enrollments.length &&
                      ` из ${enrollments.length}`}
                  </h3>
                  {/* Status filter — backend уже вернул все,
                     фильтруем UI-сайдом потому что дешевле. */}
                  <select
                    value={statusFilter}
                    onChange={(e) =>
                      setStatusFilter(e.target.value as StatusFilter)
                    }
                    className="text-xs border rounded-md px-2 py-1"
                    aria-label="Фильтр по статусу"
                  >
                    <option value="all">Все статусы</option>
                    <option value="enrolled">Записан</option>
                    <option value="in_progress">В процессе</option>
                    <option value="completed">Пройден</option>
                  </select>
                </div>

                {/* Search inside the enrolled table — when the
                   course has 50+ enrollees. */}
                {enrollments.length > 10 && (
                  <SearchInput
                    value={userSearch}
                    onChange={setUserSearch}
                    placeholder="Найти сотрудника в списке…"
                  />
                )}

                {filteredEnrollments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {enrollments.length === 0
                      ? t('courses.noCourses')
                      : 'Нет записей, подходящих под фильтр'}
                  </p>
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <th className="text-left p-2">{t('users.name')}</th>
                        <th className="text-left p-2">{t('courses.status')}</th>
                        <th className="text-left p-2">Источник</th>
                        <th className="text-left p-2">Доступ</th>
                        <th className="text-left p-2">Уведомление</th>
                        <th className="text-left p-2">Действие</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredEnrollments.map((e) => {
                        const u = usersById.get(e.user_id);
                        const sourceInfo = getAssignmentSourceInfo(e.source);
                        return (
                          <tr key={e.id} className="border-t align-top">
                            <td className="p-2 align-top text-sm">
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
                                  {e.user_id} (сотрудник не найден)
                                </span>
                              )}
                            </td>
                            <td className="p-2 align-top">
                              <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5">
                                <Badge
                                  className="text-sm font-normal leading-5"
                                  variant={STATUS_BADGE_VARIANT[e.status] || 'outline'}
                                >
                                  {STATUS_LABELS[e.status] || e.status}
                                </Badge>
                              </span>
                            </td>
                            <td className="p-2 align-top">
                              <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5" title={t(sourceInfo.descriptionKey)}>
                                <Badge className="text-sm font-normal leading-5" variant={sourceInfo.managedByRule ? 'secondary' : 'outline'}>
                                  {t(sourceInfo.labelKey)}
                                </Badge>
                              </span>
                              <p className="mt-1 max-w-56 text-xs text-muted-foreground">
                                {t(sourceInfo.descriptionKey)}
                              </p>
                            </td>
                            <td className="p-2 align-top">
                              <Button
                                data-testid="assignment-primary-line"
                                className="h-9 whitespace-nowrap text-sm leading-5"
                                variant="outline"
                                size="sm"
                                onClick={() => void handleAssignmentAccess(e, u)}
                              >
                                {u && !u.email
                                  ? accessStates[e.id]?.state === 'available' ? 'Перевыпустить доступ' : 'Создать доступ'
                                  : 'Получить ссылку'}
                              </Button>
                              {u && !u.email && accessStates[e.id]?.expires_at && (
                                <p className="mt-1 text-xs text-muted-foreground">
                                  Активен до {new Date(accessStates[e.id].expires_at!).toLocaleString()}
                                </p>
                              )}
                            </td>
                            <td className="p-2 align-top">
                              {e.notification_status ? (
                                <div className="space-y-1">
                                  <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5">
                                    <Badge className="text-sm font-normal leading-5" variant={e.notification_status === 'delivered' ? 'default' : e.notification_status === 'dead' ? 'outline' : 'secondary'}>
                                      {{ pending: 'Ожидает', claimed: 'Отправляется', retry: 'Повтор', delivered: 'Доставлено', dead: 'Не доставлено' }[e.notification_status]}
                                    </Badge>
                                  </span>
                                  {e.notification_error && <p className="text-xs text-muted-foreground">{e.notification_error}</p>}
                                  <Button variant="outline" size="sm" onClick={() => void resendNotification(e)}>Отправить повторно</Button>
                                </div>
                              ) : <span data-testid="assignment-primary-line" className="flex min-h-9 items-center text-sm leading-5 text-muted-foreground">Не требуется</span>}
                            </td>
                            <td className="p-2 align-top">
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
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </Table>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* ── RIGHT: available users to enroll ──────────── */}
        <Card>
          <CardContent className="p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Обучающиеся</h2>
              <Button
                onClick={handleEnroll}
                disabled={
                  !selectedCourse || selectedUsers.size === 0 || enrolling
                  || (deliveryMode === 'personal_link' && selectedUsers.size !== 1)
                }
              >
                {enrolling
                  ? t('common.loading')
                  : `Назначить (${selectedUsers.size})`}
              </Button>
            </div>
            <fieldset className="space-y-3 rounded-md border border-border p-3">
              <legend className="px-1 text-sm font-medium">Как сотрудник получит доступ</legend>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="delivery-mode"
                  value="email"
                  checked={deliveryMode === 'email'}
                  onChange={() => setDeliveryMode('email')}
                />
                <span><b>Email</b><span className="block text-xs text-muted-foreground">Отправим приглашение или уведомление на кадровый email.</span></span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="delivery-mode"
                  value="personal_link"
                  checked={deliveryMode === 'personal_link'}
                  onChange={() => setDeliveryMode('personal_link')}
                />
                <span><b>Персональная ссылка и PIN</b><span className="block text-xs text-muted-foreground">Подходит для телефона и не требует обычного входа или наличия email.</span></span>
              </label>
              {deliveryMode === 'personal_link' && (
                <div data-testid="personal-link-settings-grid" className="grid gap-3 sm:grid-cols-3">
                  <label data-testid="personal-link-field" className="grid grid-rows-[2.5rem_2.5rem_auto] gap-y-1 text-sm">
                    <span className="leading-5">Время на прохождение после первого входа, минут</span>
                    <Input
                      className="h-10"
                      type="number"
                      aria-label="Время на прохождение после первого входа, минут"
                      min={1}
                      max={1440}
                      value={completionWindowMinutes ?? ''}
                      placeholder="Без ограничения"
                      onChange={(event) => setCompletionWindowMinutes(event.target.value ? Number(event.target.value) : null)}
                    />
                    <span className="block text-xs text-muted-foreground">Таймер запускается, когда сотрудник впервые открыл назначение.</span>
                  </label>
                  <label data-testid="personal-link-field" className="grid grid-rows-[2.5rem_2.5rem_auto] gap-y-1 text-sm">
                    <span className="leading-5">Ссылка действительна, дней</span>
                    <Input
                      className="h-10"
                      type="number"
                      aria-label="Ссылка действительна, дней"
                      min={1}
                      max={31}
                      value={linkValidityDays}
                      onChange={(event) => setLinkValidityDays(Number(event.target.value))}
                    />
                    <span className="block text-xs text-muted-foreground">Это срок входа по ссылке, а не время прохождения курса.</span>
                  </label>
                  <label data-testid="personal-link-field" className="grid grid-rows-[2.5rem_2.5rem_auto] gap-y-1 text-sm">
                    <span className="leading-5">Завершить до (необязательно)</span>
                    <Input
                      className="h-10"
                      type="datetime-local"
                      aria-label="Завершить до"
                      value={dueAt}
                      onChange={(event) => setDueAt(event.target.value)}
                    />
                    <span className="block text-xs text-muted-foreground">Абсолютный крайний срок действует вместе с таймером после первого входа.</span>
                  </label>
                </div>
              )}
              {deliveryMode === 'personal_link' && selectedUsers.size > 1 && (
                <p className="text-sm text-warning" role="alert">
                  Для персональной ссылки выберите одного сотрудника: PIN показывается только один раз.
                </p>
              )}
            </fieldset>
            <p className="text-sm text-muted-foreground">
              {selectedCourse
                ? `Доступно: ${availableUsers.length} из ${tp('common.counts.learnerTotal', users.length)}`
                : 'Сначала выберите курс слева'}
            </p>
            <SearchInput
              value={userSearch}
              onChange={setUserSearch}
              placeholder="Найти обучающегося по имени, email или табельному…"
            />
            <div className="max-h-96 overflow-y-auto space-y-1">
              {availableUsers.length === 0 && users.length > 0 ? (
                <p className="text-xs text-muted-foreground p-2">
                  {selectedCourse
                    ? 'Все сотрудники уже записаны или не подходят под фильтр'
                    : 'Выберите курс слева, чтобы увидеть список'}
                </p>
              ) : (
                availableUsers.map((user) => (
                  <label
                    key={user.id}
                    className={`flex items-center gap-3 p-2 rounded cursor-pointer ${
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
                        {user.email || 'Email не указан'}
                        {user.personnel_number && ` · ${user.personnel_number}`}
                      </div>
                      {user.has_login_access === false && (
                        <div className="mt-1 text-xs font-medium text-warning">
                          После назначения будет создана ссылка доступа
                        </div>
                      )}
                      {deliveryMode === 'email' && !user.email?.trim() && (
                        <div className="mt-1 text-xs font-medium text-warning">
                          Для этого сотрудника выберите персональную ссылку и PIN
                        </div>
                      )}
                    </div>
                  </label>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="space-y-4 p-4">
          <div>
            <h2 className="font-semibold">Повторное обучение</h2>
            <p className="text-sm text-muted-foreground">
              Каждый запуск создаёт отдельный период обучения со своим прогрессом,
              попытками тестов, сроком и сертификатом. Поддерживаются опубликованные
              обычные курсы; SCORM пока недоступен для повторных циклов.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm">
              Курс
              <select className="mt-1 block min-w-52 rounded border bg-background px-2 py-1" value={recurringCourseId} onChange={(event) => setRecurringCourseId(event.target.value)}>
                <option value="">Выберите курс</option>
                {courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
              </select>
            </label>
            <label className="text-sm">
              Обучающийся
              <select className="mt-1 block min-w-52 rounded border bg-background px-2 py-1" value={recurringUserId} onChange={(event) => setRecurringUserId(event.target.value)}>
                <option value="">Выберите обучающегося</option>
                {users.map((learner) => <option key={learner.id} value={learner.id}>{learner.first_name} {learner.last_name}</option>)}
              </select>
            </label>
            <label className="text-sm">
              Периодичность, дней
              <input className="mt-1 block w-32 rounded border bg-background px-2 py-1" type="number" min={1} max={3660} value={cadenceDays} onChange={(event) => setCadenceDays(Number(event.target.value))} />
            </label>
            <label className="text-sm">
              Срок выполнения, дней
              <input className="mt-1 block w-32 rounded border bg-background px-2 py-1" type="number" min={0} max={365} value={dueDays} onChange={(event) => setDueDays(Number(event.target.value))} />
            </label>
            <Button variant="outline" onClick={() => void createRecurringRule()} disabled={savingRule || !recurringCourseId || !recurringUserId}>
              Сохранить черновик
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">Можно выбрать сотрудника, который уже проходил этот курс: черновик не меняет его текущее назначение.</p>
          <div className="space-y-2">
            {recurringRules.length === 0 ? (
              <p className="text-sm text-muted-foreground">Правил пока нет.</p>
            ) : recurringRules.map((rule) => {
              const course = courses.find((item) => item.id === rule.course_id);
              const learner = users.find((item) => item.id === rule.user_id);
              const occurrence = recurringOccurrences.find((item) => item.rule_id === rule.id);
              const occurrenceLabel = occurrence ? ({
                assigned: 'Назначено', overdue: 'Просрочено', completed: 'Завершено',
                completed_late: 'Завершено с опозданием', skipped: 'Пропущено',
              } as const)[occurrence.status] : null;
              return (
                <div key={rule.id} className="flex flex-wrap items-center justify-between gap-3 rounded border p-3">
                  <div>
                    <p className="text-sm font-medium">{course?.title || rule.course_id} · {learner ? `${learner.first_name} ${learner.last_name}` : rule.user_id}</p>
                    <p className="text-xs text-muted-foreground">Каждые {rule.cadence_days} дн., срок {rule.due_days} дн. · Следующий запуск: {rule.next_run_at ? new Date(rule.next_run_at).toLocaleString() : 'не запланирован'}</p>
                    {occurrence && <p className={`mt-1 text-xs ${occurrence.status === 'overdue' || occurrence.status === 'completed_late' ? 'font-medium text-destructive' : 'text-muted-foreground'}`}>
                      Последний период: {occurrenceLabel}. Срок: {new Date(occurrence.due_at).toLocaleString()}.
                      {occurrence.completed_at ? ` Завершено: ${new Date(occurrence.completed_at).toLocaleString()}.` : ''}
                    </p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{rule.status === 'draft' ? 'Черновик' : rule.status === 'active' ? 'Активно' : 'Остановлено'}</Badge>
                    {rule.status === 'active' && <Button size="sm" variant="outline" onClick={() => void deactivateRecurringRule(rule.id)}>Остановить</Button>}
                    {rule.status !== 'active' && <Button size="sm" onClick={() => void activateRecurringRule(rule.id)}>Запустить</Button>}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {dialog}
    </div>
  );
}
