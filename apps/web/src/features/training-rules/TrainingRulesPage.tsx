"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Building2, GraduationCap, Plus, Trash2 } from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";
import { useT } from "@/i18n/useT";
import { useAuthStore } from "@/store/authStore";
import { toast } from "@/components/ui/Toast";

type Scope = "organization" | "department" | "position";
type Operation = "attach" | "detach";

interface Course {
  id: string;
  title: string;
  status: string;
}

interface OrganizationRule {
  course_id: string;
}

interface Department {
  id: string;
  name: string;
  slug: string;
  course_ids: string[];
}

interface Position {
  id: string;
  name: string;
  department: string | null;
  course_ids: string[];
  employee_count?: number;
}

interface RulePreview {
  affected_employees: number;
  enrollments_to_add: number;
  in_progress_to_remove: number;
  protected_completed: number;
  protected_other_sources: number;
}

interface PendingMutation {
  scope: Exclude<Scope, "position">;
  operation: Operation;
  courseId: string;
  departmentId?: string;
  preview: RulePreview;
}

const SCOPES: Scope[] = ["organization", "department", "position"];

function courseList(data: unknown): Course[] {
  const raw = Array.isArray(data) ? data : (data as { items?: unknown[] } | null)?.items;
  return Array.isArray(raw)
    ? raw.filter((item): item is Course => Boolean(item && typeof item === "object" && "id" in item && "title" in item))
    : [];
}

export default function TrainingRulesPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role ?? "");
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryScope = searchParams.get("scope");
  const queryDepartmentId = searchParams.get("department_id");
  const [scope, setScope] = useState<Scope>(() => {
    return SCOPES.includes(queryScope as Scope) ? (queryScope as Scope) : "organization";
  });
  const [courses, setCourses] = useState<Course[]>([]);
  const [organizationRules, setOrganizationRules] = useState<OrganizationRule[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [departmentId, setDepartmentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [pending, setPending] = useState<PendingMutation | null>(null);
  const { confirm, dialog } = useConfirm();

  useEffect(() => {
    setScope(SCOPES.includes(queryScope as Scope) ? (queryScope as Scope) : "organization");
  }, [queryScope]);

  const setScopeFromUrl = (nextScope: Scope) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("scope", nextScope);
    router.replace(`/training-rules?${params.toString()}`);
    setScope(nextScope);
    setPending(null);
  };

  const load = useCallback(async () => {
    if (role !== "methodologist") return;
    setLoading(true);
    try {
      const [courseResponse, organizationResponse, departmentResponse, positionResponse] = await Promise.all([
        api.get("/v1/courses?per_page=100"),
        api.get<{ rules: OrganizationRule[] }>("/v1/training-rules/organization"),
        api.get<{ departments: Department[] }>("/v1/departments"),
        api.get<Position[]>("/v1/positions"),
      ]);
      setCourses(courseList(courseResponse.data));
      setOrganizationRules(organizationResponse.data.rules ?? []);
      const nextDepartments = departmentResponse.data.departments ?? [];
      setDepartments(nextDepartments);
      setPositions(positionResponse.data ?? []);
      setDepartmentId((current) => {
        if (queryDepartmentId && nextDepartments.some((item) => item.id === queryDepartmentId)) {
          return queryDepartmentId;
        }
        return current || nextDepartments[0]?.id || "";
      });
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("trainingRulesPage.loadError"));
    } finally {
      setLoading(false);
    }
  }, [queryDepartmentId, role, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedDepartment = departments.find((item) => item.id === departmentId);
  const courseById = useMemo(() => new Map(courses.map((course) => [course.id, course])), [courses]);
  const attachedCourseIds = scope === "organization" ? organizationRules.map((rule) => rule.course_id) : selectedDepartment?.course_ids ?? [];
  const availableCourses = courses.filter(
    (course) => course.status === "published" && !attachedCourseIds.includes(course.id),
  );

  const requestPreview = async (operation: Operation, courseId: string) => {
    setPreviewing(true);
    try {
      const body = {
        scope,
        operation,
        course_id: courseId,
        ...(scope === "department" ? { department_id: departmentId } : {}),
      };
      const response = await api.post<RulePreview>("/v1/training-rules/preview", body);
      setPending({
        scope: scope as Exclude<Scope, "position">,
        operation,
        courseId,
        departmentId,
        preview: response.data,
      });
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("trainingRulesPage.previewError"));
      throw error;
    } finally {
      setPreviewing(false);
    }
  };

  const confirmMutation = async () => {
    if (!pending) return;
    const accepted = await confirm({
      title: pending.operation === "detach" ? t("trainingRulesPage.confirmDetachTitle") : t("trainingRulesPage.confirmAttachTitle"),
      message: t("trainingRulesPage.confirmMessage"),
      variant: pending.operation === "detach" ? "danger" : "warning",
      confirmLabel: pending.operation === "detach" ? t("trainingRulesPage.detach") : t("trainingRulesPage.attach"),
    });
    if (!accepted) return;

    setMutating(true);
    try {
      if (pending.scope === "organization") {
        if (pending.operation === "attach") {
          await api.post("/v1/training-rules/organization", { course_id: pending.courseId, required: true });
        } else {
          await api.delete(`/v1/training-rules/organization/${pending.courseId}`);
        }
      } else if (pending.operation === "attach") {
        await api.post(`/v1/departments/${pending.departmentId}/courses`, { course_id: pending.courseId, required: true });
      } else {
        await api.delete(`/v1/departments/${pending.departmentId}/courses/${pending.courseId}`);
      }
      setPending(null);
      await load();
      toast.success(t("trainingRulesPage.saved"));
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("trainingRulesPage.saveError"));
    } finally {
      setMutating(false);
    }
  };

  if (role !== "methodologist") {
    return <Card><CardContent className="p-6"><h2 className="text-lg font-semibold">{t("trainingRulesPage.accessDenied")}</h2><p className="mt-1 text-sm text-muted-foreground">{t("trainingRulesPage.methodologistOnly")}</p></CardContent></Card>;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold"><GraduationCap className="h-6 w-6 shrink-0" aria-hidden="true" />{t("trainingRulesPage.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("trainingRulesPage.subtitle")}</p>
      </header>

      <div className="flex min-w-0 flex-wrap gap-2" role="tablist" aria-label={t("trainingRulesPage.scopeLabel")}>
        {SCOPES.map((item) => (
          <button key={item} type="button" role="tab" aria-selected={scope === item} onClick={() => setScopeFromUrl(item)} className={`min-h-10 rounded-md border px-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${scope === item ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted"}`}>
            {t(`trainingRulesPage.scopes.${item}` as never)}
          </button>
        ))}
      </div>

      {loading ? <p className="text-sm text-muted-foreground">{t("trainingRulesPage.loading")}</p> : scope === "position" ? (
        <PositionOverview positions={positions} t={t} />
      ) : (
        <RuleEditor
          scope={scope}
          courses={courses}
          courseById={courseById}
          availableCourses={availableCourses}
          attachedCourseIds={attachedCourseIds}
          departments={departments}
          departmentId={departmentId}
          setDepartmentId={setDepartmentId}
          selectedDepartment={selectedDepartment}
          pending={pending}
          previewing={previewing}
          mutating={mutating}
          onPreview={requestPreview}
          onConfirm={confirmMutation}
          onCancelPreview={() => setPending(null)}
          t={t}
        />
      )}
      {dialog}
    </div>
  );
}

function PositionOverview({ positions, t }: { positions: Position[]; t: (key: any, params?: any) => string }) {
  return <Card><CardHeader><CardTitle>{t("trainingRulesPage.positionOverview")}</CardTitle></CardHeader><CardContent>
    {positions.length === 0 ? <p className="text-sm text-muted-foreground">{t("trainingRulesPage.noPositions")}</p> : <ul className="divide-y divide-border">{positions.map((position) => <li key={position.id} className="flex min-w-0 items-center gap-3 py-3"><Building2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" /><span className="min-w-0 flex-1"><span className="block truncate font-medium" title={position.name}>{position.name}</span><span className="block truncate text-xs text-muted-foreground" title={position.department ?? ""}>{position.department || t("trainingRulesPage.noDepartment")}</span></span><Badge variant="secondary">{position.course_ids.length}</Badge><Link href={`/positions/${position.id}?tab=training`} className="inline-flex shrink-0 items-center gap-1 text-sm text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("trainingRulesPage.openPosition")}<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link></li>)}</ul>}
  </CardContent></Card>;
}

function RuleEditor({ scope, courseById, availableCourses, attachedCourseIds, departments, departmentId, setDepartmentId, pending, previewing, mutating, onPreview, onConfirm, onCancelPreview, t }: any) {
  const [courseId, setCourseId] = useState("");
  const isDepartment = scope === "department";
  return <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
    <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><Building2 className="h-5 w-5" aria-hidden="true" />{isDepartment ? t("trainingRulesPage.departmentRules") : t("trainingRulesPage.organizationRules")}</CardTitle></CardHeader><CardContent className="space-y-4">
      {isDepartment && <label className="block space-y-1"><span className="text-sm font-medium">{t("trainingRulesPage.department")}</span><select value={departmentId} onChange={(event) => { setDepartmentId(event.target.value); onCancelPreview(); }} className="w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{departments.map((department: Department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>}
      <div className="space-y-2"><p className="text-sm font-medium">{t("trainingRulesPage.attachedCourses")}</p>{attachedCourseIds.length === 0 ? <p className="text-sm text-muted-foreground">{t("trainingRulesPage.empty")}</p> : <ul className="divide-y divide-border rounded-md border">{attachedCourseIds.map((id: string) => <li key={id} className="flex min-w-0 items-center gap-2 px-3 py-3"><span className="min-w-0 flex-1 truncate" title={courseById.get(id)?.title ?? id}>{courseById.get(id)?.title ?? id}</span><Button type="button" size="sm" variant="outline" disabled={mutating || previewing} onClick={() => void onPreview("detach", id)} className="shrink-0 text-destructive"><Trash2 className="h-4 w-4" aria-hidden="true" /><span className="sr-only">{t("trainingRulesPage.detach")}</span></Button></li>)}</ul>}</div>
      <div className="space-y-2 border-t border-border pt-4"><label className="text-sm font-medium" htmlFor="training-rule-course">{t("trainingRulesPage.addCourse")}</label><div className="flex min-w-0 flex-col gap-2 sm:flex-row"><select id="training-rule-course" value={courseId} onChange={(event) => setCourseId(event.target.value)} disabled={mutating || previewing || availableCourses.length === 0} className="min-w-0 flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><option value="">{availableCourses.length ? t("trainingRulesPage.selectCourse") : t("trainingRulesPage.noAvailableCourses")}</option>{availableCourses.map((course: Course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select><Button type="button" disabled={!courseId || mutating || previewing || (isDepartment && !departmentId)} onClick={async () => { try { await onPreview("attach", courseId); setCourseId(""); } catch { /* Error is shown by the page-level handler. */ } }}><Plus className="h-4 w-4" aria-hidden="true" />{previewing ? t("trainingRulesPage.previewing") : t("trainingRulesPage.attach")}</Button></div></div>
    </CardContent></Card>
    <PreviewPanel pending={pending} mutating={mutating} onConfirm={onConfirm} onCancel={onCancelPreview} t={t} />
  </div>;
}

function PreviewPanel({ pending, mutating, onConfirm, onCancel, t }: { pending: PendingMutation | null; mutating: boolean; onConfirm: () => void; onCancel: () => void; t: (key: any, params?: any) => string }) {
  if (!pending) return <Card className="min-w-0 overflow-hidden"><CardContent className="flex min-h-48 min-w-0 items-center justify-center p-6 text-center text-sm text-muted-foreground"><span className="min-w-0 max-w-full break-words">{t("trainingRulesPage.previewEmpty")}</span></CardContent></Card>;
  const rows: Array<[string, number]> = [["affected_employees", pending.preview.affected_employees], ["enrollments_to_add", pending.preview.enrollments_to_add], ["in_progress_to_remove", pending.preview.in_progress_to_remove], ["protected_completed", pending.preview.protected_completed], ["protected_other_sources", pending.preview.protected_other_sources]];
  return <Card className="border-warning/40"><CardHeader><CardTitle className="text-base">{t("trainingRulesPage.previewTitle")}</CardTitle><p className="text-sm text-muted-foreground">{t("trainingRulesPage.previewSubtitle")}</p></CardHeader><CardContent className="space-y-4"><dl className="grid gap-2 sm:grid-cols-2">{rows.map(([key, value]) => <div key={key} className="flex min-w-0 items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2 text-sm"><dt className="min-w-0 truncate" title={t(`trainingRulesPage.preview.${key}` as never)}>{t(`trainingRulesPage.preview.${key}` as never)}</dt><dd className="font-semibold">{value}</dd></div>)}</dl><div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="outline" onClick={onCancel} disabled={mutating}>{t("common.cancel")}</Button><Button type="button" variant={pending.operation === "detach" ? "destructive" : "default"} onClick={onConfirm} disabled={mutating}>{pending.operation === "detach" ? t("trainingRulesPage.confirmDetach") : t("trainingRulesPage.confirmAttach")}</Button></div></CardContent></Card>;
}
