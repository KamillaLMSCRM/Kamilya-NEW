'use client';

/**
 * CompanyCoursesTab — вкладка «Курсы компании» в /admin/staff
 *
 * Реализует уровень 1 (tenant-wide) привязки курсов по TZ §1.1:
 * «Уровень 1 реализуется через привязку курса ко всем отделам
 * одним action'ом в UI (batch-INSERT в department_courses)».
 *
 * Бэкенд (см. /v1/departments/attach-courses-all и
 * /v1/departments/detach-courses-all, добавленные 2026-06-30 в
 * рамках Epic по TZ_COURSE_ASSIGNMENT_ACCESS_v1.md):
 *
 *   POST   /v1/departments/attach-courses-all
 *          body: { course_ids: [uuid, ...], required: true }
 *          → 200 { departments_affected, enrollments_added, ... }
 *
 *   DELETE /v1/departments/detach-courses-all
 *          body: { course_ids: [uuid, ...] }
 *          → 200 (или 404 если ни один курс не был привязан)
 *
 * UI:
 *   1. Список «курсы компании» — те, что привязаны ко всем отделам.
 *      Загружается через /v1/departments (для каждого берём course_ids),
 *      пересечение = tenant-wide.
 *   2. Кнопка «+ Добавить курс компании» — multi-select picker из
 *      /v1/courses, по submit дёргает attach-courses-all.
 *   3. Кнопка «× убрать» напротив каждого — detach-courses-all.
 *
 * Caveat (TZ §1.1): при создании нового отдела методолог должен
 * не забыть привязать к нему «общие» курсы через эту вкладку.
 * v1.1 может ввести явный tenant_courses, если это станет
 * источником ошибок.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, Button, Badge, Table } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { api } from '@/lib/api';
import { toast } from '@/components/ui/Toast';

// ── RBAC — same owners as RulesTab (ADR-0012) ────────────────

const COMPANY_COURSES_OWNERS = new Set([
  'methodologist',
  'teacher',
  'admin',
  'org_admin',
  'superadmin',
]);

// ── types ─────────────────────────────────────────────────────

interface Course {
  id: string;
  title: string;
  status: string;
}

interface Department {
  id: string;
  name: string;
  slug: string;
  course_ids: string[];
}

interface AttachAllResponse {
  departments_affected: number;
  enrollments_added: number;
  enrollments_removed: number;
  courses_processed: number;
}

export default function CompanyCoursesTab() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const userRole = useAuthStore((s) => s.user?.role ?? '');
  const isOwner = COMPANY_COURSES_OWNERS.has(userRole);

  const [departments, setDepartments] = useState<Department[]>([]);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  // Course IDs attached to EVERY department in the tenant =
  // "tenant-wide" (level 1) courses. We compute by intersection.
  const tenantWideCourseIds = useMemo(() => {
    if (departments.length === 0) return new Set<string>();
    const [first, ...rest] = departments;
    const intersection = new Set(first.course_ids);
    for (const d of rest) {
      for (const cid of Array.from(intersection)) {
        if (!d.course_ids.includes(cid)) intersection.delete(cid);
      }
    }
    return intersection;
  }, [departments]);

  // Map id → title for nice display
  const courseById = useMemo(() => {
    const m = new Map<string, Course>();
    for (const c of allCourses) m.set(c.id, c);
    return m;
  }, [allCourses]);

  const tenantWideCourses = useMemo(() => {
    return Array.from(tenantWideCourseIds)
      .map((id) => courseById.get(id))
      .filter((c): c is Course => Boolean(c))
      .sort((a, b) => a.title.localeCompare(b.title, 'ru'));
  }, [tenantWideCourseIds, courseById]);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    try {
      const [deptRes, courseRes] = await Promise.all([
        api.get('/v1/departments'),
        api.get('/v1/courses'),
      ]);
      setDepartments(deptRes.data || []);
      setAllCourses(courseRes.data || []);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Не удалось загрузить';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAttach = async () => {
    if (picked.size === 0) return;
    setSubmitting(true);
    try {
      const res = await api.post<AttachAllResponse>(
        '/v1/departments/attach-courses-all',
        { course_ids: Array.from(picked), required: true }
      );
      toast.success(
        `Привязано к ${res.data.departments_affected} отделам, ` +
          `+${res.data.enrollments_added} enrollments`
      );
      setPickerOpen(false);
      setPicked(new Set());
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Не удалось привязать';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDetach = async (courseId: string, title: string) => {
    if (
      !confirm(
        `Снять курс «${title}» со ВСЕХ отделов?\n` +
          `Будет удалён из привязки каждого отдела. ` +
          `In-progress enrollments будут удалены, completed — останутся в истории.`
      )
    )
      return;
    setSubmitting(true);
    try {
      const res = await api.delete<AttachAllResponse>(
        '/v1/departments/detach-courses-all',
        { data: { course_ids: [courseId] } }
      );
      toast.success(
        `Снято с ${res.data.departments_affected} отделов, ` +
          `-${res.data.enrollments_removed} enrollments`
      );
      await load();
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 404) {
        // Already detached — not really an error from the user's POV.
        toast.info('Курс уже был снят со всех отделов');
      } else {
        toast.error(typeof detail === 'string' ? detail : 'Не удалось снять');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const togglePicked = (id: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (!isOwner) {
    return (
      <Card>
        <CardContent className="p-6 text-center space-y-2">
          <div className="text-4xl">🚫</div>
          <h3 className="text-lg font-bold text-foreground">Нет доступа</h3>
          <p className="text-sm text-muted-foreground">
            Вкладка «Курсы компании» доступна администратору и методологу.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (loading) {
    return <div className="p-6 text-muted-foreground">Загружаю курсы компании...</div>;
  }

  return (
    <div className="space-y-4">
      {/* Header card explaining level-1 semantics */}
      <Card>
        <CardHeader>
          <CardTitle>🏢 Курсы компании (уровень 1)</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-foreground space-y-2">
          <p>
            Курсы из этого списка привязаны ко <strong>всем</strong> отделам
            тенанта. Каждый новый сотрудник автоматически получает их в
            обязательные курсы.
          </p>
          <p className="text-muted-foreground text-xs">
            <strong>Подсказка:</strong> при создании нового отдела методолог должен
            вернуться сюда и заново нажать «Привязать», чтобы новый отдел
            унаследовал общие курсы. (В v1.1 планируется явная таблица
            <code className="mx-1">tenant_courses</code>.)
          </p>
          <p className="text-muted-foreground text-xs">
            Всего отделов: <strong>{departments.length}</strong> · Курсов в каталоге:{' '}
            <strong>{allCourses.length}</strong> · Курсов уровня 1:{' '}
            <strong>{tenantWideCourses.length}</strong>
          </p>
        </CardContent>
      </Card>

      {/* Tenant-wide courses list */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Привязаны ко всем отделам</CardTitle>
            <Button onClick={() => setPickerOpen((p) => !p)} disabled={submitting}>
              {pickerOpen ? 'Отмена' : '+ Добавить'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {tenantWideCourses.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground text-center">
              Нет курсов уровня 1. Нажмите «+ Добавить», чтобы привязать
              курс сразу ко всем отделам.
            </div>
          ) : (
            <Table>
              <thead className="bg-muted">
                <tr>
                  <th className="text-left p-2">Курс</th>
                  <th className="text-left p-2">Статус</th>
                  <th className="text-right p-2">Действие</th>
                </tr>
              </thead>
              <tbody>
                {tenantWideCourses.map((c) => (
                  <tr key={c.id} className="border-t">
                    <td className="p-2 text-sm font-medium">{c.title}</td>
                    <td className="p-2">
                      <Badge variant={c.status === 'published' ? 'default' : 'outline'}>
                        {c.status}
                      </Badge>
                    </td>
                    <td className="p-2 text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDetach(c.id, c.title)}
                        disabled={submitting}
                      >
                        × Снять
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Course picker */}
      {pickerOpen && (
        <Card>
          <CardHeader>
            <CardTitle>Выберите курсы для привязки ко всем отделам</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="max-h-80 overflow-y-auto border border-border rounded-md divide-y divide-border">
              {allCourses
                .filter((c) => !tenantWideCourseIds.has(c.id))
                .sort((a, b) => a.title.localeCompare(b.title, 'ru'))
                .map((c) => (
                  <label
                    key={c.id}
                    className={`flex items-center gap-3 px-3 py-2 cursor-pointer ${
                      picked.has(c.id) ? 'bg-primary/10' : 'hover:bg-muted'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={picked.has(c.id)}
                      onChange={() => togglePicked(c.id)}
                      className="rounded"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium">{c.title}</div>
                      <div className="text-xs text-muted-foreground">
                        <Badge variant={c.status === 'published' ? 'default' : 'outline'}>
                          {c.status}
                        </Badge>
                      </div>
                    </div>
                  </label>
                ))}
              {allCourses.filter((c) => !tenantWideCourseIds.has(c.id)).length === 0 && (
                <div className="p-4 text-sm text-muted-foreground text-center">
                  Все курсы уже привязаны ко всем отделам.
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setPickerOpen(false);
                  setPicked(new Set());
                }}
                disabled={submitting}
              >
                Отмена
              </Button>
              <Button onClick={handleAttach} disabled={picked.size === 0 || submitting}>
                {submitting
                  ? 'Привязываю...'
                  : `Привязать ко всем отделам (${picked.size})`}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
