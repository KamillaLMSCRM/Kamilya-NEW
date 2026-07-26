"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, BriefcaseBusiness, Building2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, Button, Badge, SearchInput } from "@/components/ui";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useAuthStore } from "@/store/authStore";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/Toast";

const STAFF_RULES_OWNERS = new Set(["methodologist"]);

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
  type: "position" | "department";
  id: string;
}

async function fetchPositions(): Promise<PositionRow[]> {
  const response = await api.get("/v1/positions");
  return response.data;
}

async function fetchDepartments(): Promise<DepartmentRow[]> {
  const response = await api.get("/v1/departments");
  return response.data.departments.map((department: any) => ({
    id: department.id,
    name: department.name,
    slug: department.slug,
    course_ids: department.course_ids ?? [],
  }));
}

async function fetchCoursesLite(): Promise<CourseLite[]> {
  try {
    const response = await api.get("/v1/courses?per_page=100");
    return response.data?.items ?? response.data ?? [];
  } catch {
    return [];
  }
}

async function attachDepartmentCourse(
  departmentId: string,
  courseId: string,
  required: boolean,
): Promise<{ re_enrolled: number | null }> {
  const response = await api.post(`/v1/departments/${departmentId}/courses`, {
    course_id: courseId,
    required,
  });
  return { re_enrolled: response.data?.re_enrolled ?? null };
}

async function detachDepartmentCourse(departmentId: string, courseId: string): Promise<{ re_enrolled: number | null }> {
  const response = await api.delete(`/v1/departments/${departmentId}/courses/${courseId}`);
  return { re_enrolled: response.data?.re_enrolled ?? null };
}

export default function RulesTab() {
  const { confirm, dialog } = useConfirm();
  const role = useAuthStore((state) => state.user?.role ?? "");
  const isOwner = STAFF_RULES_OWNERS.has(role);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [departments, setDepartments] = useState<DepartmentRow[]>([]);
  const [courses, setCourses] = useState<CourseLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<ActivePanel | null>(null);
  const [mutating, setMutating] = useState(false);
  const [pickCourseId, setPickCourseId] = useState("");
  const [pickerSearch, setPickerSearch] = useState("");
  const [positionSearch, setPositionSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [positionRows, departmentRows, courseRows] = await Promise.all([
        fetchPositions().catch(() => []),
        fetchDepartments().catch(() => []),
        fetchCoursesLite(),
      ]);
      setPositions(positionRows);
      setDepartments(departmentRows);
      setCourses(courseRows);
    } catch (error: any) {
      const detail = error?.response?.data?.detail || "Не удалось загрузить правила";
      toast.error(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOwner) void load();
  }, [isOwner, load]);

  const activeDepartment =
    active?.type === "department" ? departments.find((department) => department.id === active.id) : undefined;
  const activePosition =
    active?.type === "position" ? positions.find((position) => position.id === active.id) : undefined;
  const activeCourses = useMemo(
    () => activeDepartment?.course_ids ?? [],
    [activeDepartment?.course_ids],
  );
  const activeLabel = activeDepartment?.name ?? activePosition?.name ?? "";
  const availableCourses = useMemo(() => {
    const attached = new Set(activeCourses);
    return courses
      .filter((course) => !attached.has(course.id))
      .filter((course) => course.title.toLowerCase().includes(pickerSearch.toLowerCase()));
  }, [activeCourses, courses, pickerSearch]);
  const filteredPositions = useMemo(() => {
    const query = positionSearch.trim().toLowerCase();
    if (!query) return positions;
    return positions.filter(
      (position) => position.name.toLowerCase().includes(query) || position.department.toLowerCase().includes(query),
    );
  }, [positions, positionSearch]);

  const handleAttach = async () => {
    if (!activeDepartment || !pickCourseId) return;
    setMutating(true);
    try {
      const result = await attachDepartmentCourse(activeDepartment.id, pickCourseId, true);
      toast.success(
        result.re_enrolled === null
          ? "Курс добавлен в правила отдела"
          : `Курс добавлен. Назначено: ${result.re_enrolled}`,
      );
      setPickCourseId("");
      setPickerSearch("");
      await load();
    } catch (error: any) {
      const detail = error?.response?.data?.detail || "Не удалось добавить курс";
      toast.error(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setMutating(false);
    }
  };

  const handleDetach = async (courseId: string) => {
    if (!activeDepartment) return;
    const accepted = await confirm({
      title: "Убрать курс из правил отдела?",
      message:
        "Курс перестанет входить в обязательное обучение отдела. Завершённые результаты сотрудников сохранятся.",
      variant: "danger",
      confirmLabel: "Убрать курс",
    });
    if (!accepted) return;
    setMutating(true);
    try {
      const result = await detachDepartmentCourse(activeDepartment.id, courseId);
      toast.success(
        result.re_enrolled === null ? "Курс убран из правил отдела" : `Курс убран. Затронуто: ${result.re_enrolled}`,
      );
      await load();
    } catch (error: any) {
      const detail = error?.response?.data?.detail || "Не удалось убрать курс";
      toast.error(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setMutating(false);
    }
  };

  if (!isOwner) {
    return (
      <Card>
        <CardContent className="space-y-2 p-6 text-center">
          <h3 className="text-lg font-bold">Нет доступа к правилам обучения</h3>
          <p className="text-sm text-muted-foreground">Эта вкладка доступна методологу.</p>
        </CardContent>
      </Card>
    );
  }

  if (loading && positions.length === 0 && departments.length === 0) {
    return <div className="p-6 text-muted-foreground">Загрузка правил...</div>;
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle className="text-base">Отделы</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {departments.length === 0 ? (
            <div className="px-4 py-3 text-sm text-muted-foreground">Нет отделов</div>
          ) : (
            <ul className="divide-y divide-border">
              {departments.map((department) => (
                <li key={department.id}>
                  <button
                    type="button"
                    onClick={() => setActive({ type: "department", id: department.id })}
                    className={`flex min-w-0 w-full items-center gap-2 px-4 py-3 text-left text-sm hover:bg-muted/40 ${active?.type === "department" && active.id === department.id ? "bg-primary/10 font-semibold" : ""}`}
                  >
                    <Building2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{department.name}</span>
                    <Badge variant="secondary">{department.course_ids.length}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
        <CardHeader>
          <CardTitle className="text-base">Должности</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {positions.length > 10 && (
            <div className="p-2">
              <SearchInput
                value={positionSearch}
                onChange={setPositionSearch}
                placeholder="Найти должность или отдел..."
              />
            </div>
          )}
          {filteredPositions.length === 0 ? (
            <div className="px-4 py-3 text-sm text-muted-foreground">Нет должностей</div>
          ) : (
            <ul className="max-h-96 divide-y divide-border overflow-y-auto">
              {filteredPositions.map((position) => (
                <li key={position.id}>
                  <button
                    type="button"
                    onClick={() => setActive({ type: "position", id: position.id })}
                    className={`flex min-w-0 w-full items-center gap-2 px-4 py-3 text-left text-sm hover:bg-muted/40 ${active?.type === "position" && active.id === position.id ? "bg-primary/10 font-semibold" : ""}`}
                  >
                    <BriefcaseBusiness className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{position.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">{position.department}</span>
                    </span>
                    <Badge variant="secondary">{position.course_ids.length}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        {!active ? (
          <CardContent className="p-6 text-sm text-muted-foreground">Выберите отдел или должность.</CardContent>
        ) : active.type === "position" && activePosition ? (
          <CardContent className="space-y-4 p-6">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <CardTitle className="flex items-center gap-2 text-base">
                  <BriefcaseBusiness className="h-4 w-4 shrink-0" />
                  Должность: {activePosition.name}
                </CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">
                  Связи должности с курсами редактируются в карточке должности.
                </p>
              </div>
              <Badge variant="secondary">{activePosition.course_ids.length} курсов</Badge>
            </div>
            <Link
              href={`/positions/${activePosition.id}?tab=training`}
              className="inline-flex max-w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
            >
              <span className="truncate">Открыть карточку должности</span>
              <ArrowRight className="h-4 w-4 shrink-0" />
            </Link>
          </CardContent>
        ) : (
          <>
            <CardHeader>
              <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                <Building2 className="h-4 w-4 shrink-0" />
                <span className="truncate">Правила отдела: {activeLabel}</span>
              </CardTitle>
              <p className="text-sm text-muted-foreground">Курсы отдела применяются к сотрудникам этого отдела.</p>
            </CardHeader>
            <CardContent className="space-y-4">
              {activeCourses.length === 0 ? (
                <p className="text-sm text-muted-foreground">В отделе пока нет правил обучения.</p>
              ) : (
                <ul className="divide-y divide-border rounded-md border">
                  {activeCourses.map((courseId) => {
                    const course = courses.find((item) => item.id === courseId);
                    return (
                      <li key={courseId} className="flex min-w-0 items-center gap-3 px-3 py-3 text-sm">
                        <span className="min-w-0 flex-1 truncate">{course?.title ?? courseId}</span>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={mutating}
                          onClick={() => void handleDetach(courseId)}
                          className="shrink-0 text-destructive hover:bg-destructive/10"
                        >
                          Убрать
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              )}
              <div className="space-y-2 border-t border-border pt-3">
                <SearchInput value={pickerSearch} onChange={setPickerSearch} placeholder="Найти курс..." />
                <div className="flex flex-col gap-2 sm:flex-row">
                  <select
                    value={pickCourseId}
                    onChange={(event) => setPickCourseId(event.target.value)}
                    disabled={mutating || availableCourses.length === 0}
                    className="min-w-0 flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="">{availableCourses.length ? "Выберите курс..." : "Нет доступных курсов"}</option>
                    {availableCourses.map((course) => (
                      <option key={course.id} value={course.id}>
                        {course.title}
                      </option>
                    ))}
                  </select>
                  <Button onClick={() => void handleAttach()} disabled={!pickCourseId || mutating} className="shrink-0">
                    Добавить
                  </Button>
                </div>
              </div>
            </CardContent>
          </>
        )}
        </Card>
      </div>
      {dialog}
    </>
  );
}
