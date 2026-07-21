'use client';

/**
 * CompanyCoursesTab — вкладка «Курсы компании» в /admin/staff
 *
 * Реализует уровень 1 (company-wide) привязки курсов по ТЗ §1.1:
 * «Уровень 1 реализуется через привязку курса ко всем отделам».
 *
 * Бэкенд:
 *   GET    /v1/departments                       — список отделов тенанта с course_ids
 *   GET    /v1/courses                           — каталог курсов
 *   POST   /v1/departments/attach-courses-all     — batch attach
 *   DELETE /v1/departments/detach-courses-all    — batch detach
 *
 * Логика UI:
 *   - tenant-wide set = пересечение course_ids всех отделов тенанта
 *   - если 0 отделов в тенанте — показываем «сначала создайте отделы»
 *   - если в каталоге 0 курсов — «сначала создайте курс»
 *   - иначе — список tenant-wide + picker для добавления
 *
 * Caveat (TZ §1.1): при создании нового отдела методолог должен вернуться
 * сюда и нажать «Привязать» снова, чтобы новый отдел унаследовал общие
 * курсы. Это задокументировано в самом UI.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, Button, Badge, Table, SearchInput } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { api } from '@/lib/api';
import { toast } from '@/components/ui/Toast';

// ── RBAC — те же владельцы, что у RulesTab (ADR-0012) ───────

const COMPANY_COURSES_OWNERS = new Set([
  'methodologist',
  'admin',
  'org_admin',
  'superadmin',
]);

// ── типы ─────────────────────────────────────────────────────

interface Course {
  id: string;
  title: string;
  status: string;
}

interface Department {
  id: string;
  name: string;
  slug: string;
  parent_id: string | null;
  course_ids: string[];
}

interface DepartmentsListResponse {
  departments: Department[];
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
  const [pickerSearch, setPickerSearch] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Tenant-wide set = пересечение course_ids по всем отделам.
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
      // Загружаем параллельно. Если один из запросов падает —
      // показываем только то, что получилось (не блокируем UI).
      const [deptRes, courseRes] = await Promise.allSettled([
        api.get('/v1/departments'),
        // Большой per_page чтобы получить все курсы разом (каталог
        // тенанта — десятки курсов, не тысячи).
        api.get('/v1/courses?per_page=100'),
      ]);
      if (deptRes.status === 'fulfilled') {
        const data: DepartmentsListResponse = deptRes.value.data || { departments: [] };
        setDepartments(data.departments || []);
      } else {
        // Не critical: picker всё равно будет работать, просто
        // покажем предупреждение.
        console.warn('Failed to load departments:', deptRes.reason);
        toast.error('Не удалось загрузить список отделов');
        setDepartments([]);
      }
      if (courseRes.status === 'fulfilled') {
        // /v1/courses возвращает массив напрямую, не объект.
        const data = courseRes.value.data;
        setAllCourses(Array.isArray(data) ? data : []);
      } else {
        console.warn('Failed to load courses:', courseRes.reason);
        toast.error('Не удалось загрузить каталог курсов');
        setAllCourses([]);
      }
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
        { course_ids: Array.from(picked), required: true },
      );
      toast.success(
        `Курсы добавлены в ${res.data.departments_affected} ${pluralize(
          res.data.departments_affected,
          'отдел',
          'отдела',
          'отделов',
        )}. Новые записи на курс созданы для ${res.data.enrollments_added} сотрудников.`,
      );
      setPickerOpen(false);
      setPicked(new Set());
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Не удалось добавить курсы';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDetach = async (courseId: string, title: string) => {
    if (
      !confirm(
        `Снять курс «${title}» со всех отделов?\n\n` +
          `Курс перестанет быть обязательным для сотрудников, которые ещё не начали его проходить. ` +
          `Те, кто уже прошёл, сохранят сертификат.`,
      )
    )
      return;
    setSubmitting(true);
    try {
      const res = await api.delete<AttachAllResponse>(
        '/v1/departments/detach-courses-all',
        { data: { course_ids: [courseId] } },
      );
      toast.success(
        `Курс снят с ${res.data.departments_affected} ${pluralize(
          res.data.departments_affected,
          'отдела',
          'отделов',
          'отделов',
        )}.`,
      );
      await load();
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 404) {
        toast.info('Этот курс уже не привязан ни к одному отделу');
      } else {
        toast.error(typeof detail === 'string' ? detail : 'Не удалось снять курс');
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
          <h3 className="text-lg font-bold text-foreground">Раздел недоступен</h3>
          <p className="text-sm text-muted-foreground">
            «Курсы компании» — раздел для администратора и методолога. Студенты проходят
            курсы, не настраивая их.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (loading) {
    return <div className="p-6 text-muted-foreground">Загружаю…</div>;
  }

  // ── Empty states: три честных сценария ─────────────────────

  if (departments.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-center space-y-3">
          <div className="text-4xl">🏢</div>
          <h3 className="text-lg font-bold text-foreground">Сначала создайте отделы</h3>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Чтобы назначить курс сразу всем сотрудникам, нужна оргструктура.
            Загрузите штатное расписание из Excel на вкладке «Импорт» — отделы
            создадутся автоматически. После этого вернитесь сюда.
          </p>
          <p className="text-xs text-muted-foreground">
            Это ограничение текущей версии. В следующем релизе появится единая
            настройка «обязательные курсы для всей компании» без привязки к отделам.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (allCourses.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-center space-y-3">
          <div className="text-4xl">📚</div>
          <h3 className="text-lg font-bold text-foreground">В каталоге пока нет ни одного курса</h3>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Сначала создайте курс в разделе «Курсы» (например, «Техника безопасности» или
            «Охрана труда»). После этого он появится здесь и вы сможете назначить его всем
            отделам одним кликом.
          </p>
        </CardContent>
      </Card>
    );
  }

  // ── Normal state: есть отделы И есть курсы ─────────────────

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>🏢 Курсы для всей компании</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-foreground space-y-2">
          <p>
            Курсы из этого списка получает <strong>каждый новый сотрудник</strong> —
            независимо от должности и отдела. Это обязательные курсы для всей
            компании (например, вводный инструктаж по охране труда).
          </p>
          <p className="text-muted-foreground text-xs">
            <strong>Важно:</strong> если вы создадите новый отдел, его сотрудники
            не получат эти курсы автоматически. После создания отдела вернитесь
            сюда и заново добавьте нужные курсы — это займёт один клик.
          </p>
          <p className="text-muted-foreground text-xs">
            Сейчас привязано: {departments.length}{' '}
            {pluralize(departments.length, 'отдел', 'отдела', 'отделов')} ·{' '}
            {tenantWideCourses.length} обязательных курсов.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Обязательные для всех</CardTitle>
            <Button onClick={() => setPickerOpen((p) => !p)} disabled={submitting}>
              {pickerOpen ? 'Отмена' : '+ Добавить курс'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {tenantWideCourses.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground text-center">
              Пока ни одного курса. Нажмите «+ Добавить курс», чтобы назначить
              обязательный курс сразу всем отделам.
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
                        Снять с компании
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {pickerOpen && (
        <Card>
          <CardHeader>
            <CardTitle>Выберите курс для всей компании</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Курс будет добавлен во все {departments.length}{' '}
              {pluralize(departments.length, 'отдел', 'отдела', 'отделов')} сразу.
              Сотрудники получат его автоматически при следующем входе.
            </p>
            <SearchInput
              value={pickerSearch}
              onChange={setPickerSearch}
              placeholder="Найти курс по названию…"
            />
            <div className="max-h-80 overflow-y-auto border border-border rounded-md divide-y divide-border">
              {allCourses
                .filter((c) => !tenantWideCourseIds.has(c.id))
                .filter((c) =>
                  pickerSearch
                    ? c.title.toLowerCase().includes(pickerSearch.toLowerCase())
                    : true,
                )
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
              {allCourses
                .filter((c) => !tenantWideCourseIds.has(c.id))
                .filter((c) =>
                  pickerSearch
                    ? c.title.toLowerCase().includes(pickerSearch.toLowerCase())
                    : true,
                ).length === 0 && (
                <div className="p-4 text-sm text-muted-foreground text-center">
                  {pickerSearch
                    ? 'По вашему запросу ничего не найдено'
                    : 'Все курсы уже добавлены в обязательные для компании.'}
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setPickerOpen(false);
                  setPicked(new Set());
                  setPickerSearch('');
                }}
                disabled={submitting}
              >
                Отмена
              </Button>
              <Button onClick={handleAttach} disabled={picked.size === 0 || submitting}>
                {submitting
                  ? 'Добавляю…'
                  : `Добавить во все отделы (${picked.size})`}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────

function pluralize(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}
