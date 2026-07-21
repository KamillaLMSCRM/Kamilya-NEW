'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card,
  CardContent,
  Button,
  Badge,
  Table,
  SearchInput,
} from '@/components/ui';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

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
}

interface Enrollment {
  id: string;
  user_id: string;
  course_id: string;
  status: string; // 'enrolled' | 'in_progress' | 'completed'
  source: 'manual' | 'position' | 'department' | string;
  enrolled_at: string;
}

// UI-фильтры по статусу (frontend-side, потому что /courses/{id}/enrollments
// возвращает все записи разом — фильтрация дешевле клиентом).
type StatusFilter = 'all' | 'enrolled' | 'in_progress' | 'completed';

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
const SOURCE_LABELS: Record<string, string> = {
  manual: 'Вручную',
  position: 'Должность',
  department: 'Отдел',
};

// ── component ─────────────────────────────────────────────

export default function EnrollmentsPage() {
  const { t } = useT();
  const { confirm, dialog } = useConfirm();
  const [courses, setCourses] = useState<Course[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedCourse, setSelectedCourse] = useState<string>('');
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [enrolling, setEnrolling] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set());
  const token = useAuthStore((s) => s.accessToken);
  const userRole = useAuthStore((s) => s.user?.role);
  const canManageAssignments = userRole === 'methodologist';
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  // ── фильтры (UI-side) ──────────────────────────────────
  const [userSearch, setUserSearch] = useState('');
  const [courseSearch, setCourseSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

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
        setCourses(Array.isArray(data) ? data : []);
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

  const fetchEnrollments = async (courseId: string) => {
    setSelectedCourse(courseId);
    setSelectedUsers(new Set());
    setStatusFilter('all'); // сброс при смене курса
    if (!token || !courseId) return;
    const res = await fetch(`${API_URL}/v1/courses/${courseId}/enrollments`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) setEnrollments(await res.json());
  };

  const handleEnroll = async () => {
    if (!selectedCourse || selectedUsers.size === 0) return;
    setEnrolling(true);
    try {
      const res = await fetch(`${API_URL}/v1/courses/${selectedCourse}/enrollments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ user_ids: Array.from(selectedUsers) }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail || 'Assignment failed');
      }
      const created = await res.json();
      if (Array.isArray(created) && created.length > 0) {
        toast.success(`Назначено обучающихся: ${created.length}`);
      } else {
        toast.info('Новых назначений нет: выбранные обучающиеся уже назначены или недоступны');
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
    if (enrollment.source !== 'manual') {
      toast.info('Это назначение управляется правилами отдела или должности');
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

  // Записи на курс (левая таблица) — фильтруем по статусу и поиску
  // по ФИО/email/табельному.
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
      <h1 className="text-2xl font-bold">
        Обучающиеся — назначения на курсы
      </h1>

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
              value={selectedCourse}
              onChange={(e) => fetchEnrollments(e.target.value)}
              className="w-full border rounded-md px-3 py-2 text-sm"
            >
              <option value="">
                {t('courses.status')}: {t('common.all')} (
                {filteredCourses.length})
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
                        <th className="text-left p-2">Действие</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredEnrollments.map((e) => {
                        const u = usersById.get(e.user_id);
                        return (
                          <tr key={e.id} className="border-t">
                            <td className="p-2 text-sm">
                              {u ? (
                                <>
                                  <div className="font-medium">
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
                            <td className="p-2">
                              <Badge
                                variant={STATUS_BADGE_VARIANT[e.status] || 'outline'}
                              >
                                {STATUS_LABELS[e.status] || e.status}
                              </Badge>
                            </td>
                            <td className="p-2">
                              <Badge variant={e.source === 'manual' ? 'outline' : 'secondary'}>
                                {SOURCE_LABELS[e.source] || e.source}
                              </Badge>
                            </td>
                            <td className="p-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleUnenroll(e)}
                                disabled={e.source !== 'manual'}
                              >
                                {e.source === 'manual' ? t('common.delete') : 'Через правила'}
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
                }
              >
                {enrolling
                  ? t('common.loading')
                  : `${t('courses.enrollments')} (${selectedUsers.size})`}
              </Button>
            </div>
            <p className="text-sm text-muted-foreground">
              {selectedCourse
                ? `Доступно обучающихся: ${availableUsers.length} из ${users.length}`
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
                        {user.email}
                        {user.personnel_number && ` · ${user.personnel_number}`}
                      </div>
                    </div>
                  </label>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {dialog}
    </div>
  );
}
