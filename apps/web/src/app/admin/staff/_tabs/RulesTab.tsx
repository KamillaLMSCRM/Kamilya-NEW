'use client';

/**
 * RulesTab — «Правила» в /admin/staff
 *
 * См. ADR-0012 — ролевая модель admin vs methodologist. Владение
 * этой вкладкой:
 *
 *   methodologist  — основной владелец (управляет
 *                              контентом штатки и правилами привязок)
 *   admin / org_admin         — могут редактировать для удобства
 *   superadmin                — платформенный bypass
 *   student                   — ЗАПРЕЩЕНО (ничего не настраивает)
 *
 * Под капотом дёргает эндпоинты B1c:
 *
 *   POST   /v1/positions/{id}/courses
 *   DELETE /v1/positions/{id}/courses/{cid}
 *   POST   /v1/departments/{id}/courses
 *   DELETE /v1/departments/{id}/courses/{cid}
 *
 * Все мутации идемпотентны на бэке и возвращают текущее
 * состояние объекта + счётчик `re_enrolled` (сколько
 * enrollment-строк фактически было материализовано ядром
 * `recompute_enrollments`).
 *
 * MVP без drag-drop. Действия:
 *   1. Выбрать должность или отдел в левом списке
 *   2. Справа — список привязанных курсов с галочкой «обязательный»
 *      и кнопкой «× убрать»
 *   3. Под списком — select «+ добавить курс» (только из
 *      неподключённых)
 *   4. После мутации — toast с числом «привязано, материализовано
 *      N enrollments» + автоматический перезагрузка списков
 *
 * B2b (drag-drop) и B2d (страница /admin/positions/[id]) идут
 * следующими сессиями.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, Button, Badge, SearchInput } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { api } from '@/lib/api';
import { toast } from '@/components/ui/Toast';

// ── RBAC — ADR-0012 ──────────────────────────────────────────────

// Владелец learning-content domain. Methodologist и methodologist здесь
// равнозначны (см. ADR-0012 §1). Admin для удобства (он же хозяин
// tenant'а), superadmin — платформенный bypass.
const STAFF_RULES_OWNERS = new Set([
  'methodologist',
  'admin',
  'org_admin',
  'superadmin',
]);

// ── types ─────────────────────────────────────────────────────────

interface PositionRow {
  id: string;
  name: string;
  department: string;
  course_ids: string[];
}

interface DepartmentRow {
  id: string;
  name: string;
  slug: string;
  course_ids: string[];
}

interface CourseLite {
  id: string;
  title: string;
}

interface ActivePanel {
  type: 'position' | 'department';
  id: string;
}

// ── API helpers ──────────────────────────────────────────────────

async function fetchPositions(): Promise<PositionRow[]> {
  const r = await api.get('/v1/positions');
  return r.data;
}

async function fetchDepartments(): Promise<DepartmentRow[]> {
  const r = await api.get('/v1/admin/staff/structure');
  // Map structure dept → our slim shape. `course_ids` filled in
  // by a separate call below because structure endpoint doesn't
  // list courses per position/department (it lists employee counts).
  return r.data.departments.map((d: any) => ({
    id: d.id ?? d.slug, // legacy departments can have null id
    name: d.name,
    slug: d.slug,
    course_ids: [],
  }));
}

// Нет GET /v1/departments/{id}/courses — показываем hint в UI и
// оставляем массив пустым. B2d epic добавит endpoint.
// Список курсов ограничен 100 на страницу в бэке (`Query(20, ge=1,
// le=100)` в `courses/router.py`). Берём больше не нужно — для B2
// хватит опубликованных + draft, перебирать 200+ не планируется. Если
// понадобится больше, добавим пагинацию в следующей итерации.
async function fetchCoursesLite(): Promise<CourseLite[]> {
  try {
    const r = await api.get('/v1/courses?per_page=100');
    return r.data?.items ?? r.data ?? [];
  } catch {
    return [];
  }
}

async function attachCourse(
  panel: ActivePanel,
  courseId: string,
  required: boolean,
): Promise<{ re_enrolled: number | null }> {
  const url =
    panel.type === 'position'
      ? `/v1/positions/${panel.id}/courses`
      : `/v1/departments/${panel.id}/courses`;
  const r = await api.post(url, { course_id: courseId, required });
  return { re_enrolled: r.data?.re_enrolled ?? null };
}

async function detachCourse(panel: ActivePanel, courseId: string): Promise<{ re_enrolled: number | null }> {
  const url =
    panel.type === 'position'
      ? `/v1/positions/${panel.id}/courses/${courseId}`
      : `/v1/departments/${panel.id}/courses/${courseId}`;
  const r = await api.delete(url);
  return { re_enrolled: r.data?.re_enrolled ?? null };
}

// ── component ────────────────────────────────────────────────────

export default function RulesTab() {
  const user = useAuthStore((s) => s.user);
  const role = user?.role ?? '';
  const isOwner = STAFF_RULES_OWNERS.has(role);

  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [departments, setDepartments] = useState<DepartmentRow[]>([]);
  const [courses, setCourses] = useState<CourseLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<ActivePanel | null>(null);
  const [mutating, setMutating] = useState(false);
  const [pickCourseId, setPickCourseId] = useState('');
  // Поиск в левой колонке (отделы + должности) и в picker'е курсов.
  const [pickerSearch, setPickerSearch] = useState('');
  const [posSearch, setPosSearch] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pos, deps, coursesList] = await Promise.all([
        fetchPositions().catch((e) => {
          console.error('positions fetch failed:', e?.response?.status, e?.response?.data);
          return [];
        }),
        fetchDepartments().catch((e) => {
          console.error('departments fetch failed:', e?.response?.status, e?.response?.data);
          return [];
        }),
        fetchCoursesLite(),
      ]);

      setPositions(pos);
      setDepartments(deps);
      setCourses(coursesList);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Не удалось загрузить правила';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOwner) load();
  }, [load, isOwner]);

  // Active panel's current course list (live).
  const activeCourses = useMemo(() => {
    if (!active) return [];
    if (active.type === 'position') {
      const p = positions.find((x) => x.id === active.id);
      return p?.course_ids ?? [];
    }
    const d = departments.find((x) => x.id === active.id);
    return d?.course_ids ?? [];
  }, [active, positions, departments]);

  const activeLabel = useMemo(() => {
    if (!active) return '';
    if (active.type === 'position') {
      const p = positions.find((x) => x.id === active.id);
      return p ? `${p.department} · ${p.name}` : '';
    }
    const d = departments.find((x) => x.id === active.id);
    return d?.name ?? '';
  }, [active, positions, departments]);

  const availableCourses = useMemo(() => {
    const set = new Set(activeCourses);
    return courses.filter((c) => !set.has(c.id));
  }, [courses, activeCourses]);

  // Фильтрация списка курсов в picker'е по подстроке.
  const filteredAvailableCourses = useMemo(() => {
    if (!pickerSearch) return availableCourses;
    const q = pickerSearch.toLowerCase();
    return availableCourses.filter((c) => c.title.toLowerCase().includes(q));
  }, [availableCourses, pickerSearch]);

  // Фильтрация списка должностей (левая колонка) по подстроке.
  const filteredPositions = useMemo(() => {
    if (!posSearch) return positions;
    const q = posSearch.toLowerCase();
    return positions.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.department || '').toLowerCase().includes(q),
    );
  }, [positions, posSearch]);

  const handleAttach = async () => {
    if (!active || !pickCourseId) return;
    setMutating(true);
    try {
      const { re_enrolled } = await attachCourse(active, pickCourseId, true);
      toast.success(
        re_enrolled !== null
          ? `Привязано. Зачислено: ${re_enrolled}`
          : 'Привязано',
      );
      setPickCourseId('');
      setPickerSearch('');
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Ошибка привязки';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setMutating(false);
    }
  };

  const handleDetach = async (courseId: string) => {
    if (!active) return;
    if (!confirm('Убрать курс из правила? У выполнивших обучение запись сохранится.')) return;
    setMutating(true);
    try {
      const { re_enrolled } = await detachCourse(active, courseId);
      toast.success(
        re_enrolled !== null
          ? `Убрано. Затронуто enrollments: ${re_enrolled}`
          : 'Убрано',
      );
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Ошибка удаления';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setMutating(false);
    }
  };

  // ── RBAC gate ──────────────────────────────────────────────────

  if (!isOwner) {
    return (
      <Card>
        <CardContent className="p-6 text-center space-y-2">
          <div className="text-4xl">🚫</div>
          <h3 className="text-lg font-bold text-foreground">
            Нет доступа к вкладке «Правила»
          </h3>
          <p className="text-sm text-muted-foreground">
            Вкладка предназначена для методолога и администратора тенанта.
            Переключитесь на соответствующий аккаунт или обратитесь к
            администратору для назначения прав.
          </p>
          <p className="text-[11px] text-muted-foreground pt-2">
            Роли: methodologist, admin, org_admin, superadmin.
            См. <code className="text-foreground">docs/adr/0012-rbac-admin-vs-methodologist.md</code>.
          </p>
        </CardContent>
      </Card>
    );
  }

  // ── render ──────────────────────────────────────────────────────

  if (loading && positions.length === 0 && departments.length === 0) {
    return <div className="p-6 text-muted-foreground">Загружаю правила…</div>;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {/* Left — picker */}
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle className="text-base">🏢 Отделы</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {departments.length === 0 ? (
            <div className="px-4 py-3 text-xs text-muted-foreground">Нет отделов</div>
          ) : (
            <ul className="divide-y divide-border">
              {departments.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => setActive({ type: 'department', id: d.id })}
                    className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-muted/40 ${
                      active?.type === 'department' && active.id === d.id
                        ? 'bg-primary/10 font-semibold'
                        : ''
                    }`}
                  >
                    <span className="flex-1 truncate">{d.name}</span>
                    <Badge variant="secondary">{d.course_ids.length}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>

        <CardHeader>
          <CardTitle className="text-base">🧑‍💼 Должности</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {positions.length === 0 ? (
            <div className="px-4 py-3 text-xs text-muted-foreground">Нет должностей</div>
          ) : (
            <>
              {/* Поиск по должностям — при >10 должностях скроллить
                 список в search-инпуте удобнее, чем глазами. */}
              {positions.length > 10 && (
                <div className="p-2">
                  <SearchInput
                    value={posSearch}
                    onChange={setPosSearch}
                    placeholder="Найти должность или отдел…"
                  />
                </div>
              )}
              {filteredPositions.length === 0 ? (
                <div className="px-4 py-3 text-xs text-muted-foreground">
                  Ничего не найдено по «{posSearch}»
                </div>
              ) : (
                <ul className="divide-y divide-border max-h-96 overflow-y-auto">
                  {filteredPositions.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => setActive({ type: 'position', id: p.id })}
                        className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-muted/40 ${
                          active?.type === 'position' && active.id === p.id
                            ? 'bg-primary/10 font-semibold'
                            : ''
                        }`}
                      >
                        <span className="flex-1 min-w-0">
                          <div className="truncate">{p.name}</div>
                          <div className="text-[11px] text-muted-foreground truncate">
                            {p.department}
                          </div>
                        </span>
                        <Badge variant="secondary">{p.course_ids.length}</Badge>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Right — active panel */}
      <Card className="lg:col-span-2">
        {!active ? (
          <CardContent className="p-6 text-sm text-muted-foreground">
            Выберите отдел или должность слева, чтобы увидеть привязанные курсы.
          </CardContent>
        ) : (
          <>
            <CardHeader>
              <CardTitle className="text-base">
                {active.type === 'position' ? '👤 Должность: ' : '🏢 Отдел: '}
                {activeLabel}
              </CardTitle>
              {active.type === 'department' && (
                <p className="text-xs text-muted-foreground">
                  ⚠️ Список курсов отдела пока не отображается: в API нет GET /v1/departments/{'{id}'}/courses.
                  Можно добавлять — мутация работает, привязка появится в БД.
                </p>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              {activeCourses.length === 0 ? (
                <p className="text-sm text-muted-foreground italic">
                  Нет привязанных курсов
                </p>
              ) : (
                <ul className="divide-y divide-border rounded-lg border">
                  {activeCourses.map((cid) => {
                    const c = courses.find((x) => x.id === cid);
                    return (
                      <li
                        key={cid}
                        className="flex items-center gap-3 px-3 py-2 text-sm"
                      >
                        <span className="flex-1 min-w-0">
                          <div className="truncate font-medium">
                            {c?.title ?? cid}
                          </div>
                          {c === undefined && (
                            <div className="text-[11px] text-muted-foreground">
                              (курс не загружен — попробуйте обновить)
                            </div>
                          )}
                        </span>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={mutating}
                          onClick={() => handleDetach(cid)}
                          className="text-destructive hover:bg-destructive/10"
                        >
                          × убрать
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              )}

              {/* Add course — кастомный picker с поиском вместо
                 native <select>: при >20 курсах скролл неудобен, а
                 мобильные браузеры вообще плохо поддерживают. */}
              <div className="pt-2 border-t border-border space-y-2">
                <SearchInput
                  value={pickerSearch}
                  onChange={setPickerSearch}
                  placeholder="Найти курс по названию…"
                />
                <div className="flex flex-col sm:flex-row gap-2">
                  <select
                    value={pickCourseId}
                    onChange={(e) => setPickCourseId(e.target.value)}
                    disabled={mutating || filteredAvailableCourses.length === 0}
                    className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
                    size={Math.min(6, Math.max(1, filteredAvailableCourses.length))}
                  >
                    {filteredAvailableCourses.length === 0 ? (
                      <option value="">
                        {availableCourses.length === 0
                          ? 'Нет доступных курсов'
                          : 'По вашему запросу ничего не найдено'}
                      </option>
                    ) : (
                      <>
                        <option value="">+ добавить курс…</option>
                        {filteredAvailableCourses.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.title}
                          </option>
                        ))}
                      </>
                    )}
                  </select>
                  <Button
                    onClick={handleAttach}
                    disabled={!pickCourseId || mutating}
                  >
                    {mutating ? '…' : 'Привязать'}
                  </Button>
                </div>
              </div>
            </CardContent>
          </>
        )}
      </Card>
    </div>
  );
}
