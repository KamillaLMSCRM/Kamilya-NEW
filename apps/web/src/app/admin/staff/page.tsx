"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { BookOpenCheck, Building2, ChevronDown, ChevronRight, FileText, GraduationCap, Network, Search, Upload, Users, X } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from "@/components/ui";
import { useAuthStore } from "@/store/authStore";
import { useT } from "@/i18n/useT";
import { toast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { formatKzPhone, isCompleteKzPhone } from "@/lib/kzPhone";
import { ApplyRulesProgress } from "@/components/ui/ApplyRulesProgress";

interface DepartmentOption {
  id: string;
  name: string;
}

interface PositionOption {
  id: string;
  name: string;
  department: string | null;
  department_id: string | null;
}

type ImportProposalAction = "create" | "update" | "move" | "skip" | "conflict" | string;

interface ImportProposalRow {
  id?: string;
  row_number?: number;
  name?: string;
  full_name?: string;
  branch_name?: string;
  department_name?: string;
  position_name?: string;
  personnel_number?: string | null;
  message?: string;
  blocking?: boolean;
  action?: ImportProposalAction;
  confidence?: number | string | null;
  confidence_label?: string | null;
  evidence?: string[] | string | null;
  parent_name?: string | null;
  source_sheet?: string | null;
  [key: string]: unknown;
}

interface ImportSessionResponse {
  id: string;
  state: string;
  mode: string;
  source_file_name: string;
  source_file_sha256: string;
  source_format: string;
  workbook_analysis?: Record<string, unknown> | null;
  mapping_json?: Record<string, string> | null;
  proposal?: {
    branches?: ImportProposalRow[];
    departments?: ImportProposalRow[];
    positions?: ImportProposalRow[];
    staff?: ImportProposalRow[];
    conflicts?: ImportProposalRow[];
    summary?: Record<string, number>;
    [key: string]: unknown;
  } | null;
  proposal_revision: string | null;
  expires_at?: string | null;
  result_summary?: Record<string, number | string> | null;
  mapping_id?: string | null;
}

interface ProposalCorrectionPayload {
  kind: "branch" | "department" | "position" | "staff";
  external_key: string;
  name?: string;
  branch_external_key?: string;
  department_external_key?: string;
  position_external_key?: string;
}

interface AdaptiveParserSummary {
  raw_columns: string[];
  suggested_mapping: Record<string, string>;
  missing_required_columns: string[];
  selected_sheet?: string | null;
  header_row?: number | null;
}

function getAdaptiveParserSummary(session: ImportSessionResponse | null): AdaptiveParserSummary {
  const parser = session?.workbook_analysis?.parser;
  if (!parser || typeof parser !== "object") {
    return { raw_columns: [], suggested_mapping: {}, missing_required_columns: [] };
  }
  const value = parser as Record<string, unknown>;
  return {
    raw_columns: Array.isArray(value.raw_columns) ? value.raw_columns.filter((item): item is string => typeof item === "string") : [],
    suggested_mapping: value.suggested_mapping && typeof value.suggested_mapping === "object" ? value.suggested_mapping as Record<string, string> : {},
    missing_required_columns: Array.isArray(value.missing_required_columns) ? value.missing_required_columns.filter((item): item is string => typeof item === "string") : [],
    selected_sheet: typeof value.selected_sheet === "string" ? value.selected_sheet : null,
    header_row: typeof value.header_row === "number" ? value.header_row : null,
  };
}

interface OrganizationUnitNode {
  id: string;
  name: string;
  unit_type: "branch" | "department" | string;
  parent_id?: string | null;
  is_active?: boolean;
  departments?: OrganizationUnitNode[];
  children?: OrganizationUnitNode[];
  positions?: StructurePosition[];
  employee_count?: number;
  position_count?: number;
}

const STAFF_FIELDS = [
  { key: "personnel_number", label: "Табельный номер", required: true },
  { key: "first_name", label: "Имя", required: true },
  { key: "last_name", label: "Фамилия", required: true },
  { key: "full_name", label: "ФИО (вместо имени и фамилии)", required: false },
  { key: "branch", label: "Филиал", required: false },
  { key: "department", label: "Отдел", required: false },
  { key: "position", label: "Должность", required: true },
  { key: "email", label: "Email", required: false },
  { key: "phone", label: "Телефон", required: false },
  { key: "hire_date", label: "Дата приёма", required: false },
] as const;

export default function AdminStaffPage() {
  const { t, tp } = useT();
  const router = useRouter();
  const search = useSearchParams();

  // URL-backed tabs keep refresh, Back/Forward and copied links stable.
  type Tab = "import" | "structure";
  const queryTab = search?.get("tab");
  const normalisedTab: string | null = queryTab;
  // Студенту вкладки «Импорт» и «Структура» не нужны — он
  // потребитель контента, ничего не настраивает (см. ADR-0012).
  // Страница /admin/staff — это методологический surface. Если
  // зашёл студент — показываем понятное «нет доступа».
  const userRole = useAuthStore((s) => s.user?.role ?? "");
  const isStaffOwnersRole = userRole === "methodologist";
  const initialTab: Tab = normalisedTab === "import" ? "import" : "structure";
  const [tab, setTab] = useState<Tab>(initialTab);

  useEffect(() => {
    if (queryTab === "rules") {
      router.replace("/training-rules?scope=department");
      return;
    }
    if (queryTab === "company" || queryTab === "company-courses") {
      router.replace("/training-rules?scope=organization");
      return;
    }
    setTab(queryTab === "import" ? "import" : "structure");
  }, [queryTab, router]);

  const selectTab = (nextTab: Tab) => {
    const params = new URLSearchParams(search?.toString());
    params.set("tab", nextTab);
    router.replace(`/staff?${params.toString()}`);
  };

  const [manualOpen, setManualOpen] = useState(false);
  const [manualSaving, setManualSaving] = useState(false);
  const [manualOptionsLoading, setManualOptionsLoading] = useState(false);
  const [departmentOptions, setDepartmentOptions] = useState<DepartmentOption[]>([]);
  const [positionOptions, setPositionOptions] = useState<PositionOption[]>([]);
  const [structureRefreshKey, setStructureRefreshKey] = useState(0);
  const [manualForm, setManualForm] = useState({
    personnel_number: "",
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    department_id: "",
    position_id: "",
    department: "",
    position: "",
  });
  // Manual staff creation can start the async apply-rules task.
  const [applyTaskId, setApplyTaskId] = useState<string | null>(null);
  const [selectedMappingId, setSelectedMappingId] = useState<string>("");
  const [adaptiveFile, setAdaptiveFile] = useState<File | null>(null);
  const [adaptiveSession, setAdaptiveSession] = useState<ImportSessionResponse | null>(null);
  const [adaptiveStep, setAdaptiveStep] = useState(0);
  const [adaptiveLoading, setAdaptiveLoading] = useState(false);
  const [adaptiveCommitting, setAdaptiveCommitting] = useState(false);
  const [adaptiveMappingLoading, setAdaptiveMappingLoading] = useState(false);
  const [adaptiveMapping, setAdaptiveMapping] = useState<Record<string, string>>({});
  const [adaptiveSheetName, setAdaptiveSheetName] = useState("");
  const [adaptiveMode, setAdaptiveMode] = useState<"ADD_OR_UPDATE" | "FULL_RECONCILIATION">("ADD_OR_UPDATE");
  const adaptiveFileInputRef = useRef<HTMLInputElement>(null) as React.MutableRefObject<HTMLInputElement | null>;

  const fetchSavedMappings = useCallback(async () => {
    try {
      const res = await api.get("/v1/admin/staff/import/mappings");
      const defaultMapping = (res.data || []).find((mapping: { is_default?: boolean }) => mapping.is_default);
      if (defaultMapping?.id) setSelectedMappingId((current) => current || defaultMapping.id);
    } catch {
      // A missing saved default does not block adaptive analysis.
    }
  }, []);

  useEffect(() => {
    fetchSavedMappings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const adaptiveBase = (id: string) => `/v1/admin/staff/import/sessions/${id}`;

  const adaptiveError = (error: any, fallback: string) => {
    const detail = error?.response?.data?.detail;
    return typeof detail === "string" ? detail : detail?.message || fallback;
  };

  const handleAdaptiveAnalyze = async () => {
    if (!adaptiveFile) return;
    setAdaptiveLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", adaptiveFile);
      formData.append("idempotency_key", crypto.randomUUID());
      formData.append("mode", adaptiveMode);
      if (Object.keys(adaptiveMapping).length > 0) {
        formData.append("mapping_json", JSON.stringify(adaptiveMapping));
      } else if (selectedMappingId) {
        formData.append("mapping_id", selectedMappingId);
      }
      if (adaptiveSheetName) formData.append("sheet_name", adaptiveSheetName);
      const response = await api.post<ImportSessionResponse>(
        "/v1/admin/staff/import/sessions/analyze",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setAdaptiveSession(response.data);
      const parser = getAdaptiveParserSummary(response.data);
      setAdaptiveMapping(response.data.mapping_json || parser.suggested_mapping);
      setAdaptiveSheetName(parser.selected_sheet || "");
      setAdaptiveStep(response.data.state === "needs_mapping" ? 2 : 1);
      window.sessionStorage.setItem("kamilya-adaptive-import-session-id", response.data.id);
      toast.success("Файл разобран. Ничего ещё не изменено.");
    } catch (error) {
      toast.error(adaptiveError(error, "Не удалось разобрать файл"));
    } finally {
      setAdaptiveLoading(false);
    }
  };

  const refreshAdaptiveSession = async () => {
    if (!adaptiveSession) return;
    try {
      const response = await api.get<ImportSessionResponse>(adaptiveBase(adaptiveSession.id));
      setAdaptiveSession(response.data);
      const parser = getAdaptiveParserSummary(response.data);
      setAdaptiveMapping((current) => Object.keys(current).length > 0 ? current : response.data.mapping_json || parser.suggested_mapping);
      setAdaptiveSheetName((current) => current || parser.selected_sheet || "");
    } catch (error) {
      toast.error(adaptiveError(error, "Не удалось обновить анализ"));
    }
  };

  const handleAdaptiveMappingSubmit = async () => {
    if (!adaptiveSession) return;
    const parser = getAdaptiveParserSummary(adaptiveSession);
    const hasName = Boolean(adaptiveMapping.full_name) || Boolean(adaptiveMapping.first_name && adaptiveMapping.last_name);
    const hasOrganizationUnit = Boolean(adaptiveMapping.branch || adaptiveMapping.department);
    const required = ["personnel_number", "position"];
    if (!hasName || !hasOrganizationUnit || required.some((field) => !adaptiveMapping[field])) {
      toast.error("Сопоставьте табельный номер, филиал или отдел, должность и ФИО (или имя и фамилию).");
      return;
    }
    if (parser.raw_columns.length > 0 && Object.values(adaptiveMapping).some((column) => !parser.raw_columns.includes(column))) {
      toast.error("В сопоставлении есть колонка, которой нет в выбранном листе.");
      return;
    }
    setAdaptiveMappingLoading(true);
    try {
      const response = await api.post<ImportSessionResponse>(`${adaptiveBase(adaptiveSession.id)}/mapping`, {
        mapping_json: adaptiveMapping,
        sheet_name: adaptiveSheetName || null,
      });
      setAdaptiveSession(response.data);
      setAdaptiveStep(response.data.state === "needs_mapping" ? 2 : 3);
      toast.success("Сопоставление сохранено. Предложение обновлено.");
    } catch (error) {
      toast.error(adaptiveError(error, "Не удалось сохранить сопоставление"));
    } finally {
      setAdaptiveMappingLoading(false);
    }
  };

  const handleAdaptiveApprove = async () => {
    if (!adaptiveSession || !adaptiveSession.proposal_revision) return;
    const fullReconciliation = adaptiveSession.mode === "FULL_RECONCILIATION";
    if (fullReconciliation && !window.confirm("Полная сверка может отметить отсутствующих в файле сотрудников. Продолжить только после проверки списка?")) {
      return;
    }
    setAdaptiveLoading(true);
    try {
      const response = await api.post<ImportSessionResponse>(`${adaptiveBase(adaptiveSession.id)}/approve`, {
        revision: adaptiveSession.proposal_revision,
        full_reconciliation_confirmation: fullReconciliation,
      });
      setAdaptiveSession(response.data);
      setAdaptiveStep(4);
      toast.success("Изменения подтверждены. Теперь можно применить их.");
    } catch (error) {
      toast.error(adaptiveError(error, "Подтверждение заблокировано конфликтами"));
    } finally {
      setAdaptiveLoading(false);
    }
  };

  const handleAdaptiveCorrections = async (corrections: ProposalCorrectionPayload[]) => {
    if (!adaptiveSession?.proposal_revision) return;
    setAdaptiveLoading(true);
    try {
      const response = await api.post<ImportSessionResponse>(`${adaptiveBase(adaptiveSession.id)}/corrections`, {
        revision: adaptiveSession.proposal_revision,
        corrections,
      });
      setAdaptiveSession(response.data);
      setAdaptiveStep(3);
      toast.success("Исправления сохранены. Проверьте обновлённое предложение.");
    } catch (error: any) {
      toast.error(adaptiveError(error, "Не удалось сохранить исправления структуры"));
    } finally {
      setAdaptiveLoading(false);
    }
  };

  const handleAdaptiveCommit = async () => {
    if (!adaptiveSession || !adaptiveSession.proposal_revision) return;
    setAdaptiveCommitting(true);
    try {
      const response = await api.post<ImportSessionResponse>(`${adaptiveBase(adaptiveSession.id)}/commit`, {
        revision: adaptiveSession.proposal_revision,
      });
      setAdaptiveSession(response.data);
      setAdaptiveStep(5);
      window.sessionStorage.removeItem("kamilya-adaptive-import-session-id");
      setStructureRefreshKey((value) => value + 1);
      toast.success("Структура и сотрудники обновлены.");
    } catch (error) {
      toast.error(adaptiveError(error, "Не удалось применить подтверждённые изменения"));
    } finally {
      setAdaptiveCommitting(false);
    }
  };

  const resetAdaptive = () => {
    setAdaptiveFile(null);
    setAdaptiveSession(null);
    setAdaptiveStep(0);
    setAdaptiveMapping({});
    setAdaptiveSheetName("");
    window.sessionStorage.removeItem("kamilya-adaptive-import-session-id");
    if (adaptiveFileInputRef.current) adaptiveFileInputRef.current.value = "";
  };

  useEffect(() => {
    const sessionId = window.sessionStorage.getItem("kamilya-adaptive-import-session-id");
    if (!sessionId || adaptiveSession) return;
    let active = true;
    api.get<ImportSessionResponse>(`/v1/admin/staff/import/sessions/${sessionId}`)
      .then((response) => {
        if (!active) return;
        const restored = response.data;
        const parser = getAdaptiveParserSummary(restored);
        setAdaptiveSession(restored);
        setAdaptiveMapping(restored.mapping_json || parser.suggested_mapping);
        setAdaptiveSheetName(parser.selected_sheet || "");
        setAdaptiveStep(restored.state === "needs_mapping" ? 2 : restored.state === "committed" ? 5 : restored.state === "approved" ? 4 : 3);
      })
      .catch(() => {
        if (active) window.sessionStorage.removeItem("kamilya-adaptive-import-session-id");
      });
    return () => {
      active = false;
    };
  }, [adaptiveSession]);

  useEffect(() => {
    if (!manualOpen || !isStaffOwnersRole) return;

    let active = true;
    setManualOptionsLoading(true);
    Promise.all([
      api.get<{ departments: DepartmentOption[] }>("/v1/departments"),
      api.get<PositionOption[]>("/v1/positions"),
    ])
      .then(([departmentsResponse, positionsResponse]) => {
        if (!active) return;
        setDepartmentOptions(departmentsResponse.data.departments ?? []);
        setPositionOptions(positionsResponse.data ?? []);
      })
      .catch((error: any) => {
        if (!active) return;
        const detail = error?.response?.data?.detail;
        toast.error(
          typeof detail === "string"
            ? detail
            : detail?.message || t("staffPage.manualHierarchyLoadError"),
        );
      })
      .finally(() => {
        if (active) setManualOptionsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [manualOpen, isStaffOwnersRole, t]);

  const handleManualChange = (field: keyof typeof manualForm, value: string) => {
    setManualForm((current) => ({ ...current, [field]: value }));
  };

  const resetManualForm = () => {
    setManualForm({
      personnel_number: "",
      first_name: "",
      last_name: "",
      email: "",
      phone: "",
      department_id: "",
      position_id: "",
      department: "",
      position: "",
    });
  };

  const closeManualModal = () => {
    setManualOpen(false);
    resetManualForm();
  };

  const handleManualCreate = async () => {
    const requiredFields: Array<keyof typeof manualForm> = [
      "personnel_number",
      "first_name",
      "last_name",
    ];
    const hierarchyMissing =
      (!manualForm.department_id && !manualForm.department.trim()) ||
      (!manualForm.position_id && !manualForm.position.trim());
    if (requiredFields.some((field) => !manualForm[field].trim()) || hierarchyMissing) {
      toast.error("Заполните табельный номер, имя, фамилию, отдел и должность");
      return;
    }
    if (manualForm.phone && !isCompleteKzPhone(manualForm.phone)) {
      toast.error(t("staffPage.manualPhoneInvalid"));
      return;
    }

    setManualSaving(true);
    try {
      const payload = {
        personnel_number: manualForm.personnel_number.trim(),
        first_name: manualForm.first_name.trim(),
        last_name: manualForm.last_name.trim(),
        email: manualForm.email.trim() || undefined,
        phone: manualForm.phone.trim() || undefined,
        department_id: manualForm.department_id || undefined,
        position_id: manualForm.position_id || undefined,
        department: manualForm.department_id ? undefined : manualForm.department.trim(),
        position: manualForm.position_id ? undefined : manualForm.position.trim(),
      };
      const res = await api.post("/v1/admin/staff/manual", payload);
      const r = res.data;
      toast.success(r.created > 0 ? t("staffPage.manualAdded") : t("staffPage.manualUpdated"));
      setApplyTaskId(r.apply_rules_task_id ?? null);
      setStructureRefreshKey((value) => value + 1);
      selectTab("structure");
      setManualOpen(false);
      resetManualForm();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || "Не удалось добавить сотрудника";
      toast.error(typeof detail === "string" ? detail : detail.message || JSON.stringify(detail));
    } finally {
      setManualSaving(false);
    }
  };

  const selectedDepartment = departmentOptions.find(
    (department) => department.id === manualForm.department_id,
  );
  const filteredPositionOptions = positionOptions.filter(
    (position) =>
      position.department_id === manualForm.department_id ||
      (!position.department_id &&
        Boolean(selectedDepartment) &&
        (position.department || "").trim().toLocaleLowerCase() ===
          selectedDepartment!.name.trim().toLocaleLowerCase()),
  );

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-5 sm:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground"><Users className="h-6 w-6 shrink-0" aria-hidden="true" />{t("staffPage.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("staffPage.subtitle")}</p>
      </div>

      {!isStaffOwnersRole ? (
        // Student hit /admin/staff (maybe via stale link). Очищаем
        // объяснение, не показываем UI. ADR-0012: студенты не
        // настраивают ничего ни в одном из доменов.
        <Card>
          <CardContent className="p-6 text-center space-y-2">
            <Users className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
            <h3 className="text-lg font-bold text-foreground">{t("staffPage.accessDenied")}</h3>
            <p className="text-sm text-muted-foreground">{t("staffPage.methodologistOnly")}</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-muted-foreground">
              Сотрудников можно загрузить файлом или добавить вручную.
            </div>
            <Button type="button" onClick={() => setManualOpen(true)}>
              + Добавить сотрудника
            </Button>
          </div>

          {manualOpen && (
            <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 sm:items-center">
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="manual-employee-title"
                className="w-full max-w-2xl rounded-xl bg-card p-6 shadow-xl"
              >
                <div className="mb-5 flex items-start justify-between gap-4">
                  <div>
                    <h2 id="manual-employee-title" className="text-xl font-bold text-foreground">Новый сотрудник</h2>
                    <p className="mt-1 text-sm text-muted-foreground">{t("staffPage.manualRuleInheritance")}</p>
                  </div>
                  <button
                    type="button"
                    onClick={closeManualModal}
                    className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={t("common.close")}
                    title={t("common.close")}
                  >
                    <X className="h-5 w-5" aria-hidden="true" />
                  </button>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-sm font-medium">Табельный номер *</span>
                    <input
                      value={manualForm.personnel_number}
                      onChange={(e) => handleManualChange("personnel_number", e.target.value)}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                      placeholder="Например, 0001"
                    />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-medium">Email</span>
                    <input
                      type="email"
                      value={manualForm.email}
                      onChange={(e) => handleManualChange("email", e.target.value)}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                      placeholder="employee@company.kz"
                    />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-medium">Имя *</span>
                    <input
                      value={manualForm.first_name}
                      onChange={(e) => handleManualChange("first_name", e.target.value)}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                      placeholder="Имя"
                    />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-medium">Фамилия *</span>
                    <input
                      value={manualForm.last_name}
                      onChange={(e) => handleManualChange("last_name", e.target.value)}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                      placeholder="Фамилия"
                    />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-medium">Отдел *</span>
                    <select
                      value={manualForm.department_id}
                      onChange={(e) =>
                        setManualForm((current) => ({
                          ...current,
                          department_id: e.target.value,
                          department: "",
                          position_id: "",
                          position: "",
                        }))
                      }
                      disabled={manualOptionsLoading}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                    >
                      <option value="">{t("staffPage.manualNewDepartment")}</option>
                      {departmentOptions.map((department) => (
                        <option key={department.id} value={department.id}>
                          {department.name}
                        </option>
                      ))}
                    </select>
                    {!manualForm.department_id && (
                      <input
                        value={manualForm.department}
                        onChange={(e) => handleManualChange("department", e.target.value)}
                        className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                        placeholder={t("staffPage.manualDepartmentName")}
                      />
                    )}
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-medium">Должность *</span>
                    <select
                      value={manualForm.position_id}
                      onChange={(e) =>
                        setManualForm((current) => ({
                          ...current,
                          position_id: e.target.value,
                          position: "",
                        }))
                      }
                      disabled={manualOptionsLoading || !manualForm.department_id}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                    >
                      <option value="">{t("staffPage.manualNewPosition")}</option>
                      {filteredPositionOptions.map((position) => (
                        <option key={position.id} value={position.id}>
                          {position.name}
                        </option>
                      ))}
                    </select>
                    {!manualForm.position_id && (
                      <input
                        value={manualForm.position}
                        onChange={(e) => handleManualChange("position", e.target.value)}
                        className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                        placeholder={t("staffPage.manualPositionName")}
                      />
                    )}
                  </label>
                  <label className="space-y-1 md:col-span-2">
                    <span className="text-sm font-medium">Телефон</span>
                    <input
                      type="tel"
                      value={manualForm.phone}
                      onChange={(e) => handleManualChange("phone", formatKzPhone(e.target.value))}
                      inputMode="tel"
                      autoComplete="tel"
                      maxLength={18}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
                      placeholder="+7 (777) 000-00-00"
                    />
                  </label>
                </div>

                <div className="mt-6 flex justify-end gap-2">
                  <Button type="button" variant="outline" onClick={closeManualModal}>
                    Отмена
                  </Button>
                  <Button type="button" onClick={handleManualCreate} disabled={manualSaving}>
                    {manualSaving ? "Сохраняю…" : "Добавить"}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* ADR-0011 + ADR-0012: import and structure are one URL-backed workspace. */}
          <div role="tablist" className="flex border-b border-border">
            <button
              role="tab"
              aria-selected={tab === "import"}
              onClick={() => selectTab("import")}
              className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors ${
                tab === "import"
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Upload className="h-4 w-4" aria-hidden="true" />{t("staffPage.tabs.import")}
            </button>
            <button
              role="tab"
              aria-selected={tab === "structure"}
              onClick={() => selectTab("structure")}
              className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors ${
                tab === "structure"
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Network className="h-4 w-4" aria-hidden="true" />{t("staffPage.tabs.structure")}
            </button>
          </div>

          {applyTaskId && <ApplyRulesProgress taskId={applyTaskId} />}

          {tab === "import" && (
            <div className="space-y-6">
              <AdaptiveImportFlow
                file={adaptiveFile}
                session={adaptiveSession}
                step={adaptiveStep}
                mode={adaptiveMode}
                loading={adaptiveLoading}
                committing={adaptiveCommitting}
                mappingLoading={adaptiveMappingLoading}
                mapping={adaptiveMapping}
                sheetName={adaptiveSheetName}
                inputRef={adaptiveFileInputRef}
                onModeChange={setAdaptiveMode}
                onFileChange={(file) => {
                  setAdaptiveFile(file);
                  setAdaptiveSession(null);
                  setAdaptiveStep(0);
                }}
                onAnalyze={handleAdaptiveAnalyze}
                onMappingChange={setAdaptiveMapping}
                onSheetNameChange={setAdaptiveSheetName}
                onSubmitMapping={handleAdaptiveMappingSubmit}
                onRefresh={refreshAdaptiveSession}
                onCorrectProposal={handleAdaptiveCorrections}
                onApprove={handleAdaptiveApprove}
                onCommit={handleAdaptiveCommit}
                onReset={resetAdaptive}
              />
            </div>
          )}

          {tab === "structure" && <StructureTab refreshKey={structureRefreshKey} />}
        </>
      )}
    </div>
  );
}

function proposalRows(session: ImportSessionResponse | null, key: "branches" | "departments" | "positions" | "staff" | "conflicts") {
  const rows = session?.proposal?.[key];
  return Array.isArray(rows) ? rows : [];
}

function rowEvidence(row: ImportProposalRow) {
  if (row.message) return row.message;
  if (Array.isArray(row.evidence)) {
    return row.evidence.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") return String((item as { claim?: string; message?: string }).claim || (item as { message?: string }).message || "Подтверждение источником");
      return String(item);
    }).join(" · ");
  }
  return typeof row.evidence === "string" ? row.evidence : "Нет дополнительных пояснений";
}

function rowConfidence(row: ImportProposalRow) {
  if (row.confidence_label) return row.confidence_label;
  if (typeof row.confidence === "number") return `${Math.round(row.confidence * 100)}%`;
  return row.confidence || "—";
}

function AdaptiveImportFlow({
  file,
  session,
  step,
  mode,
  loading,
  committing,
  mappingLoading,
  mapping,
  sheetName,
  inputRef,
  onModeChange,
  onFileChange,
  onAnalyze,
  onMappingChange,
  onSheetNameChange,
  onSubmitMapping,
  onRefresh,
  onCorrectProposal,
  onApprove,
  onCommit,
  onReset,
}: {
  file: File | null;
  session: ImportSessionResponse | null;
  step: number;
  mode: "ADD_OR_UPDATE" | "FULL_RECONCILIATION";
  loading: boolean;
  committing: boolean;
  mappingLoading: boolean;
  mapping: Record<string, string>;
  sheetName: string;
  inputRef: React.MutableRefObject<HTMLInputElement | null>;
  onModeChange: (mode: "ADD_OR_UPDATE" | "FULL_RECONCILIATION") => void;
  onFileChange: (file: File | null) => void;
  onAnalyze: () => void;
  onMappingChange: (mapping: Record<string, string>) => void;
  onSheetNameChange: (sheetName: string) => void;
  onSubmitMapping: () => void;
  onRefresh: () => void;
  onCorrectProposal: (corrections: ProposalCorrectionPayload[]) => Promise<void>;
  onApprove: () => void;
  onCommit: () => void;
  onReset: () => void;
}) {
  const branchRows = useMemo(() => proposalRows(session, "branches"), [session]);
  const departmentRows = useMemo(() => proposalRows(session, "departments"), [session]);
  const positionRows = useMemo(() => proposalRows(session, "positions"), [session]);
  const staffRows = useMemo(() => proposalRows(session, "staff"), [session]);
  const conflicts = useMemo(() => proposalRows(session, "conflicts"), [session]);
  const summary = session?.proposal?.summary || session?.result_summary || {};
  const blocking = conflicts.some((row) => row.blocking === true) || session?.state === "needs_correction";
  const approvalReady = session?.state === "ready_for_approval";
  const steps = ["Файл", "Сопоставление", "Предложение", "Подтверждение", "Готово"];
  const [proposalEditing, setProposalEditing] = useState(false);
  const [proposalDraft, setProposalDraft] = useState<{
    branches: ImportProposalRow[];
    departments: ImportProposalRow[];
    positions: ImportProposalRow[];
    staff: ImportProposalRow[];
  }>({ branches: [], departments: [], positions: [], staff: [] });

  useEffect(() => {
    setProposalDraft({
      branches: branchRows.map((row) => ({ ...row })),
      departments: departmentRows.map((row) => ({ ...row })),
      positions: positionRows.map((row) => ({ ...row })),
      staff: staffRows.map((row) => ({ ...row })),
    });
    setProposalEditing(false);
  }, [branchRows, departmentRows, positionRows, session?.proposal_revision, staffRows]);

  const updateDraft = (kind: keyof typeof proposalDraft, index: number, patch: Partial<ImportProposalRow>) => {
    setProposalDraft((current) => ({
      ...current,
      [kind]: current[kind].map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row),
    }));
  };

  const submitProposalCorrections = async () => {
    const corrections: ProposalCorrectionPayload[] = [];
    proposalDraft.branches.forEach((row) => {
      if (typeof row.external_key === "string") corrections.push({ kind: "branch", external_key: row.external_key, name: String(row.branch_name || "").trim() });
    });
    proposalDraft.departments.forEach((row) => {
      if (typeof row.external_key === "string") corrections.push({ kind: "department", external_key: row.external_key, name: String(row.department_name || "").trim(), branch_external_key: String(row.branch_external_key || "legacy:root") });
    });
    proposalDraft.positions.forEach((row) => {
      if (typeof row.external_key === "string") corrections.push({ kind: "position", external_key: row.external_key, name: String(row.position_name || "").trim(), branch_external_key: String(row.branch_external_key || "legacy:root"), department_external_key: String(row.department_external_key || "legacy:root") });
    });
    proposalDraft.staff.forEach((row) => {
      if (typeof row.external_key === "string") corrections.push({ kind: "staff", external_key: row.external_key, branch_external_key: String(row.branch_external_key || "legacy:root"), department_external_key: String(row.department_external_key || "legacy:root"), position_external_key: String(row.position_external_key || "") });
    });
    if (corrections.some((item) => !item.external_key || ("name" in item && !item.name) || (item.kind === "staff" && !item.position_external_key))) {
      toast.error("Заполните названия и связи всех элементов предложения.");
      return;
    }
    await onCorrectProposal(corrections);
  };

  return (
    <Card data-testid="adaptive-import-flow">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-3">
          <span>Адаптивная загрузка штатки</span>
          <Badge variant="secondary">Новый безопасный сценарий</Badge>
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Система сама разберёт формат файла, покажет предполагаемые филиалы, отделы и сотрудников. До вашего подтверждения данные не меняются.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        <ol className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5" aria-label="Шаги импорта">
          {steps.map((label, index) => (
            <li key={label} className={`rounded-md border px-2 py-2 ${step >= index + 1 ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"}`}>
              <span className="font-semibold">{index + 1}. </span>{label}
            </li>
          ))}
        </ol>

        {!session && (
          <div className="space-y-4 rounded-lg border border-border bg-muted/20 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={(element) => {
                  inputRef.current = element;
                }}
                type="file"
                accept=".xls,.xlsx,.csv"
                className="sr-only"
                aria-label="Выбрать файл штатного расписания для анализа"
                onChange={(event) => onFileChange(event.target.files?.[0] || null)}
              />
              <Button type="button" variant="outline" onClick={() => inputRef.current?.click()}>
                Выбрать файл для анализа
              </Button>
              <span className="text-sm text-muted-foreground">{file?.name || "Файл не выбран"}</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-sm">
                <span className="font-medium">Режим загрузки</span>
                <select
                  aria-label="Режим загрузки"
                  value={mode}
                  onChange={(event) => onModeChange(event.target.value as "ADD_OR_UPDATE" | "FULL_RECONCILIATION")}
                  className="w-full rounded-md border border-border bg-background px-3 py-2"
                >
                  <option value="ADD_OR_UPDATE">Добавить или обновить найденное</option>
                  <option value="FULL_RECONCILIATION" disabled>Полная сверка — готовится (автоматического удаления нет)</option>
                </select>
              </label>
              <div className="rounded-md border border-primary/20 bg-primary/5 p-3 text-xs text-muted-foreground">
                Сначала появится предложение структуры. Можно загрузить даже привычный старый Excel — методисту не нужно заранее приводить его к шаблону.
              </div>
            </div>
            <Button type="button" onClick={onAnalyze} disabled={!file || loading}>
              {loading ? "Анализирую…" : "Запустить анализ файла"}
            </Button>
          </div>
        )}

        {session && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-muted/20 p-3 text-sm">
              <div>
                <strong>{session.source_file_name}</strong>
                <span className="ml-2 text-muted-foreground">Формат: {session.source_format} · Статус: {session.state}</span>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={onRefresh}>Обновить анализ</Button>
            </div>

            {session.workbook_analysis && (() => {
              const parser = getAdaptiveParserSummary(session);
              const fullNameMapped = Boolean(mapping.full_name);
              const requiredMissing = [
                !mapping.personnel_number && "Табельный номер",
                !mapping.branch && !mapping.department && "Филиал или отдел",
                !mapping.position && "Должность",
                !fullNameMapped && !(mapping.first_name && mapping.last_name) && "ФИО или Имя + Фамилия",
              ].filter(Boolean) as string[];
              const needsMapping = session.state === "needs_mapping" || parser.missing_required_columns.length > 0;
              return (
                <div className="rounded-md border border-border p-3 text-sm">
                  <h3 className="font-semibold">1–2. Что найдено в файле</h3>
                  <p className="mt-1 text-muted-foreground">
                    Листы и заголовки проанализированы автоматически. Исходный файл не изменяется.
                  </p>
                  <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
                    <div className="rounded bg-muted/50 p-2"><span className="text-muted-foreground">Колонок найдено</span><strong className="ml-1">{parser.raw_columns.length}</strong></div>
                    <div className="rounded bg-muted/50 p-2"><span className="text-muted-foreground">Лист</span><strong className="ml-1">{sheetName || parser.selected_sheet || "по умолчанию"}</strong></div>
                    <div className="rounded bg-muted/50 p-2"><span className="text-muted-foreground">Строка заголовка</span><strong className="ml-1">{parser.header_row || "—"}</strong></div>
                  </div>

                  {needsMapping ? (
                    <div className="mt-4 rounded-md border border-warning/40 bg-warning/10 p-3">
                      <h4 className="font-semibold text-warning">Нужно сопоставить колонки</h4>
                      <p className="mt-1 text-xs text-muted-foreground">Выберите, какая колонка исходного файла означает каждое поле. После сохранения система продолжит анализ этой же сессии.</p>
                      {parser.missing_required_columns.length > 0 && <p className="mt-2 text-xs text-destructive">Не распознано автоматически: {parser.missing_required_columns.join(", ")}</p>}
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        {STAFF_FIELDS.map((field) => {
                          const required = field.required && !(fullNameMapped && (field.key === "first_name" || field.key === "last_name"));
                          return (
                            <label key={field.key} className="space-y-1">
                              <span className="text-xs font-semibold text-muted-foreground">{field.label}{required ? " *" : ""}</span>
                              <select
                                aria-label={field.label}
                                value={mapping[field.key] || ""}
                                onChange={(event) => {
                                  const next = { ...mapping };
                                  if (event.target.value) next[field.key] = event.target.value;
                                  else delete next[field.key];
                                  onMappingChange(next);
                                }}
                                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                              >
                                <option value="">Не использовать</option>
                                {parser.raw_columns.map((column) => <option key={`${field.key}-${column}`} value={column}>{column}</option>)}
                              </select>
                            </label>
                          );
                        })}
                      </div>
                      {requiredMissing.length > 0 && <p className="mt-2 text-xs text-destructive">Обязательные поля: {requiredMissing.join(", ")}</p>}
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Button type="button" onClick={onSubmitMapping} disabled={mappingLoading || requiredMissing.length > 0}>{mappingLoading ? "Сохраняю…" : "Сохранить сопоставление и продолжить"}</Button>
                        {parser.selected_sheet && <label className="text-xs text-muted-foreground">Лист: <select value={sheetName || parser.selected_sheet} onChange={(event) => onSheetNameChange(event.target.value)} className="rounded border border-border bg-background px-2 py-1"><option value={parser.selected_sheet}>{parser.selected_sheet}</option></select></label>}
                      </div>
                    </div>
                  ) : (
                    <div className="mt-3 rounded border border-success/30 bg-success/5 p-2 text-xs text-muted-foreground">Сопоставление полей распознано. Проверьте предложенную структуру ниже.</div>
                  )}
                </div>
              );
            })()}

            <div className="rounded-md border border-border p-3">
              <h3 className="font-semibold">3. Предлагаемая структура</h3>
              <p className="mt-1 text-sm text-muted-foreground">Проверьте, что строки филиалов не попали в отделы, а отделы находятся внутри правильного филиала.</p>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                {[["Филиалы", branchRows.length], ["Отделы", departmentRows.length], ["Должности", positionRows.length], ["Сотрудники", staffRows.length], ["Конфликты", conflicts.length]].map(([label, count]) => (
                  <div key={String(label)} className="rounded bg-muted/50 p-2 text-center"><div className="text-lg font-bold">{count}</div><div className="text-xs text-muted-foreground">{label}</div></div>
                ))}
              </div>
              <div className="mt-4 max-h-80 overflow-auto rounded border border-border">
                {[...branchRows.map((row) => ({ ...row, _kind: "Филиал" })), ...departmentRows.map((row) => ({ ...row, _kind: "Отдел" })), ...positionRows.map((row) => ({ ...row, _kind: "Должность" })), ...staffRows.map((row) => ({ ...row, _kind: "Сотрудник" }))].map((row, index) => (
                  <div key={row.id || `${row._kind}-${index}`} className="grid gap-1 border-b border-border px-3 py-2 text-xs sm:grid-cols-[100px_1fr_100px_1.5fr]">
                    <span className="font-semibold">{row._kind}</span>
                    <span>{row.full_name || row.branch_name || row.department_name || row.position_name || row.name || row.personnel_number || "—"}</span>
                    <span className="text-muted-foreground">{row.action || "—"} · {rowConfidence(row)}</span>
                    <span className="text-muted-foreground">{rowEvidence(row)}</span>
                  </div>
                ))}
              </div>
              {session.state !== "approved" && session.state !== "committed" && (
                <div className="mt-4 rounded-md border border-primary/30 bg-primary/5 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h4 className="text-sm font-semibold">Исправить предложение до подтверждения</h4>
                      <p className="text-xs text-muted-foreground">Можно переименовать филиал или отдел и исправить связи. Исходный Excel менять не нужно.</p>
                    </div>
                    <Button type="button" variant="outline" size="sm" onClick={() => setProposalEditing((value) => !value)}>
                      {proposalEditing ? "Скрыть редактор" : "Редактировать структуру"}
                    </Button>
                  </div>
                  {proposalEditing && (
                    <div className="mt-3 max-h-[60vh] space-y-4 overflow-y-auto pr-1">
                      {proposalDraft.branches.length > 0 && <fieldset className="space-y-2"><legend className="text-sm font-semibold">Филиалы</legend>{proposalDraft.branches.map((row, index) => <label key={String(row.external_key)} className="block text-xs"><span className="text-muted-foreground">Название филиала</span><input aria-label={`Название филиала ${index + 1}`} value={String(row.branch_name || "")} onChange={(event) => updateDraft("branches", index, { branch_name: event.target.value })} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm" /></label>)}</fieldset>}

                      {proposalDraft.departments.length > 0 && <fieldset className="space-y-2"><legend className="text-sm font-semibold">Отделы</legend>{proposalDraft.departments.map((row, index) => <div key={String(row.external_key)} className="grid gap-2 rounded border border-border bg-background p-2 sm:grid-cols-2"><label className="text-xs"><span className="text-muted-foreground">Название отдела</span><input aria-label={`Название отдела ${index + 1}`} value={String(row.department_name || "")} onChange={(event) => updateDraft("departments", index, { department_name: event.target.value })} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm" /></label><label className="text-xs"><span className="text-muted-foreground">Филиал</span><select aria-label={`Филиал отдела ${index + 1}`} value={String(row.branch_external_key || "legacy:root")} onChange={(event) => updateDraft("departments", index, { branch_external_key: event.target.value })} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"><option value="legacy:root">Без филиала (старый формат)</option>{proposalDraft.branches.map((branch) => <option key={String(branch.external_key)} value={String(branch.external_key)}>{String(branch.branch_name)}</option>)}</select></label></div>)}</fieldset>}

                      {proposalDraft.positions.length > 0 && <fieldset className="space-y-2"><legend className="text-sm font-semibold">Должности</legend>{proposalDraft.positions.map((row, index) => <div key={String(row.external_key)} className="grid gap-2 rounded border border-border bg-background p-2 sm:grid-cols-2"><label className="text-xs"><span className="text-muted-foreground">Название должности</span><input aria-label={`Название должности ${index + 1}`} value={String(row.position_name || "")} onChange={(event) => updateDraft("positions", index, { position_name: event.target.value })} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm" /></label><label className="text-xs"><span className="text-muted-foreground">Отдел или прямое подчинение филиалу</span><select aria-label={`Подразделение должности ${index + 1}`} value={String(row.department_external_key || "legacy:root")} onChange={(event) => { const departmentKey = event.target.value; const department = proposalDraft.departments.find((item) => item.external_key === departmentKey); updateDraft("positions", index, { department_external_key: departmentKey, branch_external_key: department?.branch_external_key || row.branch_external_key || "legacy:root" }); }} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"><option value="legacy:root">Непосредственно в филиале</option>{proposalDraft.departments.map((department) => <option key={String(department.external_key)} value={String(department.external_key)}>{String(department.department_name)}</option>)}</select></label></div>)}</fieldset>}

                      {proposalDraft.staff.length > 0 && <fieldset className="space-y-2"><legend className="text-sm font-semibold">Сотрудники</legend>{proposalDraft.staff.map((row, index) => <div key={String(row.external_key)} className="grid items-end gap-2 rounded border border-border bg-background p-2 sm:grid-cols-2"><div className="text-sm"><span className="block font-medium">{String(row.first_name || "")} {String(row.last_name || "")}</span><span className="text-xs text-muted-foreground">Табельный № {String(row.personnel_number || "—")}</span></div><label className="text-xs"><span className="text-muted-foreground">Должность</span><select aria-label={`Должность сотрудника ${index + 1}`} value={String(row.position_external_key || "")} onChange={(event) => { const positionKey = event.target.value; const position = proposalDraft.positions.find((item) => item.external_key === positionKey); updateDraft("staff", index, { position_external_key: positionKey, branch_external_key: position?.branch_external_key || "legacy:root", department_external_key: position?.department_external_key || "legacy:root" }); }} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"><option value="">Выберите должность</option>{proposalDraft.positions.map((position) => <option key={String(position.external_key)} value={String(position.external_key)}>{String(position.position_name)}</option>)}</select></label></div>)}</fieldset>}

                      <div className="sticky bottom-0 flex justify-end gap-2 border-t border-border bg-card py-3"><Button type="button" variant="outline" onClick={() => setProposalEditing(false)}>Отмена</Button><Button type="button" onClick={submitProposalCorrections} disabled={loading}>{loading ? "Сохраняю…" : "Сохранить исправления"}</Button></div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {blocking && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive" role="alert">
                <strong>Нужно разобрать конфликты до подтверждения.</strong>
                <ul className="mt-2 list-disc pl-5">{conflicts.filter((row) => row.blocking !== false).map((row, index) => <li key={row.id || index}>{rowEvidence(row) || row.name || "Неоднозначная строка"}</li>)}</ul>
              </div>
            )}

            <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
              <Button type="button" variant="outline" onClick={onReset}>Выбрать другой файл</Button>
              <Button type="button" variant="outline" onClick={onApprove} disabled={loading || blocking || !approvalReady}>
                {loading ? "Подтверждаю…" : "Подтвердить предложение"}
              </Button>
              <Button type="button" onClick={onCommit} disabled={committing || session.state !== "approved" || !session.proposal_revision}>
                {committing ? "Применяю…" : "Применить подтверждённые изменения"}
              </Button>
            </div>
            {session.state === "committed" && (
              <div className="rounded-md border border-success/40 bg-success/10 p-3 text-sm text-success" role="status">
                Импорт завершён. Результат зафиксирован, повторная отправка того же файла безопасна.
              </div>
            )}
            <p className="text-xs text-muted-foreground">Ревизия предложения: {session.proposal_revision}. Подтверждение не выполняет удаление сотрудников.</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Structure tab ────────────────────────────────────────────────────

interface StructureEmployee {
  id: string;
  full_name: string;
  personnel_number: string | null;
  is_active: boolean;
}

interface StructurePosition {
  id: string;
  name: string;
  department: string;
  department_slug: string | null;
  employee_count: number;
  employees: StructureEmployee[];
}

interface StructureDepartment {
  id: string | null;
  name: string;
  slug: string;
  position_count: number;
  employee_count: number;
  positions: StructurePosition[];
  branch_id?: string | null;
  branch_name?: string | null;
}

interface StructureBranch {
  id: string;
  name: string;
  department_count: number;
  employee_count: number;
  positions: StructurePosition[];
  departments: StructureDepartment[];
}

interface StructureResponse {
  departments: StructureDepartment[];
  branches: StructureBranch[];
  unassignedPositions: StructurePosition[];
  summary: {
    total_employees: number;
    total_branches?: number;
    total_departments: number;
    total_positions: number;
  };
}

function normaliseStructureResponse(raw: any): StructureResponse {
  if (Array.isArray(raw?.branches)) {
    const toDepartment = (node: any, branch: any): StructureDepartment => ({
      id: node.id,
      name: node.name,
      slug: node.slug || node.id,
      position_count: node.position_count ?? node.positions?.length ?? 0,
      employee_count: node.employee_count ?? 0,
      positions: Array.isArray(node.positions) ? node.positions : [],
      branch_id: branch?.id ?? null,
      branch_name: branch?.name ?? null,
    });
    const toBranch = (branch: any): StructureBranch => ({
      id: branch.id,
      name: branch.name,
      departments: (branch.departments || branch.children || [])
        .filter((node: any) => node.unit_type === "department" || !node.unit_type)
        .map((node: any) => toDepartment(node, branch)),
      positions: Array.isArray(branch.positions) ? branch.positions : [],
      department_count: branch.department_count ?? (branch.children || []).length ?? 0,
      employee_count: branch.employee_count ?? 0,
    });
    const branches: StructureBranch[] = raw.branches.map(toBranch);
    const legacyDepartments: StructureDepartment[] = (raw.legacy_roots || []).map((node: any) => toDepartment(node, null));
    return {
      departments: [...legacyDepartments, ...(Array.isArray(raw.departments) ? raw.departments : [])],
      branches,
      unassignedPositions: Array.isArray(raw.unassigned_legacy_positions) ? raw.unassigned_legacy_positions : [],
      summary: {
        total_employees: raw.summary?.total_employees ?? branches.reduce((sum, branch) => sum + branch.employee_count, 0),
        total_branches: raw.summary?.total_branches ?? raw.branches.length,
        total_departments: raw.summary?.total_departments ?? branches.reduce((sum, branch) => sum + branch.department_count, 0) + legacyDepartments.length,
        total_positions: raw.summary?.total_positions ?? branches.reduce((sum, branch) => sum + branch.positions.length + branch.departments.reduce((inner, department) => inner + department.position_count, 0), 0),
      },
    };
  }
  // Compatibility response from /admin/staff/structure: root rows are kept
  // as legacy departments and are never silently relabelled as branches.
  return {
    departments: Array.isArray(raw?.departments) ? raw.departments : [],
    branches: [],
    unassignedPositions: [],
    summary: {
      total_employees: raw?.summary?.total_employees ?? 0,
      total_branches: 0,
      total_departments: raw?.summary?.total_departments ?? raw?.departments?.length ?? 0,
      total_positions: raw?.summary?.total_positions ?? 0,
    },
  };
}

function StructureTab({ refreshKey = 0 }: { refreshKey?: number }) {
  const { t, tp } = useT();
  const [data, setData] = useState<StructureResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [expandedDepts, setExpandedDepts] = useState<Set<string>>(new Set());
  const [expandedPositions, setExpandedPositions] = useState<Set<string>>(new Set());
  const [expandedBranches, setExpandedBranches] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [unitModal, setUnitModal] = useState<{ type: "branch" | "department"; parentId?: string; parentName?: string; unitId?: string } | null>(null);
  const [unitName, setUnitName] = useState("");
  const [unitSaving, setUnitSaving] = useState(false);

  // Keep modal form state scoped to the modal lifecycle. Otherwise a cancelled
  // rename can leak its old name into the next "Добавить ..." dialog.
  const closeUnitModal = useCallback(() => {
    if (unitSaving) return;
    setUnitModal(null);
    setUnitName("");
  }, [unitSaving]);

  useEffect(() => {
    if (!unitModal) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeUnitModal();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeUnitModal, unitModal]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    (async () => {
      try {
        try {
          const res = await api.get("/v1/organization-units/tree");
          if (!cancelled) setData(normaliseStructureResponse(res.data));
        } catch {
          // The old structure endpoint remains a read-compatible fallback.
          const res = await api.get("/v1/admin/staff/structure");
          if (!cancelled) setData(normaliseStructureResponse(res.data));
        }
      } catch {
        if (!cancelled) {
          setData(null);
          setLoadError(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshKey, retryKey]);

  const createUnit = async () => {
    const name = unitName.trim();
    if (!unitModal || !name) return;
    setUnitSaving(true);
    try {
      if (unitModal.unitId) {
        await api.patch(`/v1/organization-units/${unitModal.unitId}`, { name });
        toast.success("Название обновлено");
      } else {
        await api.post("/v1/organization-units", {
          name,
          unit_type: unitModal.type,
          parent_id: unitModal.parentId || null,
        });
        toast.success(unitModal.type === "branch" ? "Филиал добавлен" : "Отдел добавлен");
      }
      setUnitModal(null);
      setUnitName("");
      setRetryKey((value) => value + 1);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : detail?.message || "Не удалось создать подразделение");
    } finally {
      setUnitSaving(false);
    }
  };

  const archiveUnit = async (unitId: string, name: string) => {
    if (!window.confirm(`Архивировать «${name}»? Подразделение с активными отделами или должностями архивировать нельзя.`)) return;
    try {
      await api.post(`/v1/organization-units/${unitId}/archive`, { reason: "Архивировано методистом через раздел структуры" });
      toast.success("Подразделение архивировано");
      setRetryKey((value) => value + 1);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Не удалось архивировать подразделение");
    }
  };

  const toggleDept = (slug: string) => {
    setExpandedDepts((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  const togglePosition = (positionId: string) => {
    setExpandedPositions((prev) => {
      const next = new Set(prev);
      if (next.has(positionId)) next.delete(positionId);
      else next.add(positionId);
      return next;
    });
  };

  const filteredDepartments = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return data.departments;

    return data.departments.flatMap((department) => {
      if (department.name.toLocaleLowerCase().includes(needle)) return [department];
      const positions = department.positions.filter((position) => {
        if (position.name.toLocaleLowerCase().includes(needle)) return true;
        return position.employees.some((employee) =>
          `${employee.full_name} ${employee.personnel_number ?? ""}`.toLocaleLowerCase().includes(needle),
        );
      });
      return positions.length > 0 ? [{ ...department, positions }] : [];
    });
  }, [data, query]);

  const filteredBranches = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return data.branches;
    return data.branches
      .map((branch) => {
        const positions = branch.positions.filter((position) =>
          position.name.toLocaleLowerCase().includes(needle) ||
          position.employees.some((employee) => `${employee.full_name} ${employee.personnel_number ?? ""}`.toLocaleLowerCase().includes(needle)),
        );
        const departments = branch.departments.filter((department) =>
          department.name.toLocaleLowerCase().includes(needle) ||
          department.positions.some((position) => position.name.toLocaleLowerCase().includes(needle) || position.employees.some((employee) => `${employee.full_name} ${employee.personnel_number ?? ""}`.toLocaleLowerCase().includes(needle))),
        );
        return { ...branch, positions, departments };
      })
      .filter((branch) => branch.name.toLocaleLowerCase().includes(needle) || branch.positions.length > 0 || branch.departments.length > 0);
  }, [data, query]);

  if (loading) {
    return <div className="p-6 text-muted-foreground">Загружаю структуру…</div>;
  }
  if (loadError) {
    return (
      <div
        role="alert"
        className="flex flex-col items-center gap-4 rounded-md border border-destructive/30 bg-destructive/5 p-6 text-center"
      >
        <div>
          <p className="font-medium text-foreground">{t("staffPage.structureLoadError")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t("staffPage.retryHint")}</p>
        </div>
        <Button type="button" variant="outline" onClick={() => setRetryKey((value) => value + 1)}>
          Повторить
        </Button>
      </div>
    );
  }
  if (!data || (data.departments.length === 0 && data.branches.length === 0 && data.unassignedPositions.length === 0)) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <p>{t("staffPage.structureEmpty")}</p>
        <p className="text-sm mt-2">{t("staffPage.structureEmptyHint")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-primary/10 p-3 text-center">
          <div className="text-2xl font-bold text-primary">{data.summary.total_employees}</div>
          <div className="text-xs text-primary">Сотрудников</div>
        </div>
        <div className="rounded-lg bg-accent/10 p-3 text-center">
        <div className="text-2xl font-bold text-accent">{data.summary.total_branches ?? data.branches.length}</div>
          <div className="text-xs text-accent">Филиалов</div>
        </div>
        <div className="rounded-lg bg-warning/10 p-3 text-center">
          <div className="text-2xl font-bold text-warning">{data.summary.total_departments}</div>
          <div className="text-xs text-warning">Отделов</div>
        </div>
        <div className="rounded-lg bg-muted p-3 text-center">
          <div className="text-2xl font-bold text-foreground">{data.summary.total_positions}</div>
          <div className="text-xs text-foreground">Должностей</div>
        </div>
      </div>

      <div className="flex justify-end">
        <Button type="button" onClick={() => setUnitModal({ type: "branch" })}>+ Добавить филиал</Button>
      </div>

      <Link
        href="/training-log"
        className="inline-flex min-h-10 items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <FileText className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{t("staffPage.openTrainingLog")}</span>
      </Link>

      <label className="relative block w-full sm:max-w-md">
        <span className="sr-only">Поиск по структуре</span>
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Найти сотрудника, должность или отдел…"
          aria-label="Поиск по структуре"
          className="w-full rounded-md border border-border bg-background px-9 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </label>

      {filteredDepartments.length === 0 && filteredBranches.length === 0 && (
        <div className="rounded-md border border-border p-6 text-center text-sm text-muted-foreground">
          Поиск не дал результатов.
        </div>
      )}

      {filteredBranches.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Филиалы</CardTitle>
            <p className="text-sm text-muted-foreground">Отделы, должности и сотрудники находятся внутри филиала. Добавление филиала не создаёт сотрудников автоматически.</p>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border">
              {filteredBranches.map((branch) => {
                const open = expandedBranches.has(branch.id) || query.trim().length > 0;
                return (
                  <li key={branch.id}>
                    <div className="flex flex-wrap items-center gap-2 px-4 py-3">
                      <button type="button" onClick={() => setExpandedBranches((current) => { const next = new Set(current); if (next.has(branch.id)) next.delete(branch.id); else next.add(branch.id); return next; })} aria-expanded={open} className="flex min-w-0 flex-[1_1_16rem] items-center gap-3 text-left">
                        {open ? <ChevronDown className="h-4 w-4" aria-hidden="true" /> : <ChevronRight className="h-4 w-4" aria-hidden="true" />}
                        <Building2 className="h-4 w-4 text-primary" aria-hidden="true" />
                        <span className="min-w-0 truncate font-semibold">{branch.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">{branch.department_count} отделов · {branch.employee_count} сотрудников</span>
                      </button>
                      <Button type="button" variant="outline" size="sm" onClick={() => setUnitModal({ type: "department", parentId: branch.id, parentName: branch.name })}>+ Добавить отдел</Button>
                      <Button type="button" variant="ghost" size="sm" onClick={() => { setUnitName(branch.name); setUnitModal({ type: "branch", unitId: branch.id }); }}>Переименовать</Button>
                      <Button type="button" variant="ghost" size="sm" onClick={() => archiveUnit(branch.id, branch.name)}>Архивировать</Button>
                    </div>
                    {open && <ul className="divide-y divide-border bg-muted/20">
                      {branch.positions.length === 0 && branch.departments.length === 0 && <li className="px-12 py-3 text-xs text-muted-foreground">В филиале пока нет отделов и должностей</li>}
                      {branch.positions.map((pos) => {
                        const positionOpen = expandedPositions.has(pos.id) || query.trim().length > 0;
                        return (
                          <li key={pos.id} className="px-4 py-3 pl-12">
                            <div className="flex min-w-0 items-start gap-3">
                              <button
                                type="button"
                                onClick={() => togglePosition(pos.id)}
                                aria-expanded={positionOpen}
                                className="flex min-w-0 flex-1 items-start gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              >
                                {positionOpen ? (
                                  <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                                ) : (
                                  <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                                )}
                                <span className="min-w-0">
                                  <span className="block truncate text-sm font-medium text-foreground">{pos.name}</span>
                                  <span className="mt-0.5 block text-xs text-muted-foreground">{tp('common.counts.employee', pos.employee_count)}</span>
                                </span>
                              </button>
                              <Link
                                href={`/positions/${pos.id}?tab=training`}
                                className="shrink-0 rounded-sm text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              >
                                Профиль и обучение
                              </Link>
                            </div>
                            {positionOpen && pos.employees.length > 0 && (
                              <ul className="mt-2 space-y-1 pl-6">
                                {pos.employees.map((emp) => (
                                  <li key={emp.id} className="flex min-w-0 items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-background">
                                    <span className={emp.is_active ? "min-w-0 text-base font-semibold text-primary" : "min-w-0 text-base font-semibold text-muted-foreground line-through"}>
                                      {emp.full_name}
                                      {emp.personnel_number && <span className="ml-2 whitespace-nowrap text-xs font-normal text-muted-foreground">· {emp.personnel_number}</span>}
                                    </span>
                                    {emp.is_active && (
                                      <Link
                                        href={`/assignments?user_id=${emp.id}`}
                                        className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium text-primary hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                      >
                                        <GraduationCap className="h-4 w-4" aria-hidden="true" />
                                        <span className="hidden sm:inline">Назначить обучение</span>
                                        <span className="sm:hidden">Назначить</span>
                                      </Link>
                                    )}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </li>
                        );
                      })}
                      {branch.departments.map((department) => <li key={department.id || department.slug} className="flex flex-wrap items-center justify-between gap-3 px-12 py-3">
                        <span><span className="block text-sm font-medium">{department.name}</span><span className="text-xs text-muted-foreground">{department.position_count} должностей · {department.employee_count} сотрудников</span></span>
                        {department.id && <span className="flex flex-wrap items-center gap-2"><Link href={`/training-rules?scope=department&department_id=${department.id}`} className="text-xs text-primary hover:underline">Обязательные курсы</Link><Button type="button" variant="ghost" size="sm" onClick={() => { setUnitName(department.name); setUnitModal({ type: "department", unitId: department.id || undefined, parentId: branch.id, parentName: branch.name }); }}>Переименовать</Button><Button type="button" variant="ghost" size="sm" onClick={() => department.id && archiveUnit(department.id, department.name)}>Архивировать</Button></span>}
                      </li>)}
                    </ul>}
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}

      {unitModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div role="dialog" aria-modal="true" aria-labelledby="unit-dialog-title" className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
            <div className="flex items-start justify-between gap-3"><div><h2 id="unit-dialog-title" className="text-lg font-bold">{unitModal.unitId ? "Переименовать подразделение" : unitModal.type === "branch" ? "Новый филиал" : "Новый отдел"}</h2><p className="mt-1 text-sm text-muted-foreground">{unitModal.parentName ? `В филиале «${unitModal.parentName}»` : "Филиал верхнего уровня"}</p></div><button type="button" aria-label="Закрыть" onClick={closeUnitModal} disabled={unitSaving}><X className="h-5 w-5" /></button></div>
            <label className="mt-5 block space-y-1 text-sm"><span className="font-medium">Название</span><input autoFocus value={unitName} onChange={(event) => setUnitName(event.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2" placeholder={unitModal.type === "branch" ? "Например, Филиал Павлодар" : "Например, Отдел внутреннего контроля"} /></label>
            <div className="mt-5 flex justify-end gap-2"><Button type="button" variant="outline" onClick={closeUnitModal} disabled={unitSaving}>Отмена</Button><Button type="button" onClick={createUnit} disabled={!unitName.trim() || unitSaving}>{unitSaving ? "Сохраняю…" : unitModal.unitId ? "Сохранить" : "Создать"}</Button></div>
          </div>
        </div>
      )}

      {/* Department tree */}
      {filteredDepartments.length > 0 && <Card>
        <CardHeader><CardTitle>Совместимые отделы</CardTitle><p className="text-sm text-muted-foreground">Это данные старого формата, сохранённые без автоматического переименования в филиалы.</p></CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y divide-border">
            {filteredDepartments.map((dept) => {
              const isOpen = expandedDepts.has(dept.slug) || query.trim().length > 0;
              return (
                <li key={dept.slug}>
                  <div className="flex min-w-0 items-center gap-2 px-4 py-3 hover:bg-muted/40 transition-colors">
                    <button
                      type="button"
                      onClick={() => toggleDept(dept.slug)}
                      aria-expanded={isOpen}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-bold text-primary">
                        <Building2 className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-foreground">{dept.name}</span>
                        <span className="block text-xs text-muted-foreground">
                          {tp('common.counts.position', dept.position_count)} ·{' '}
                          {tp('common.counts.employee', dept.employee_count)}
                        </span>
                      </span>
                    </button>
                    {dept.id && (
                      <Link
                        href={`/training-rules?scope=department&department_id=${dept.id}`}
                        className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium text-foreground hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <BookOpenCheck className="h-4 w-4" aria-hidden="true" />
                        <span className="hidden sm:inline">Обязательные курсы</span>
                      </Link>
                    )}
                  </div>
                  {isOpen && (
                    <ul className="bg-muted/30 divide-y divide-border">
                      {dept.positions.length === 0 && (
                        <li className="px-4 py-3 pl-14 text-xs text-muted-foreground italic">Нет должностей</li>
                      )}
                      {dept.positions.map((pos) => {
                        const positionOpen = expandedPositions.has(pos.id) || query.trim().length > 0;
                        return (
                        <li key={pos.id} className="px-4 py-3 pl-14">
                          <div className="flex min-w-0 items-start gap-3">
                            <button
                              type="button"
                              onClick={() => togglePosition(pos.id)}
                              aria-expanded={positionOpen}
                              className="flex min-w-0 flex-1 items-start gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {positionOpen ? (
                                <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                              ) : (
                                <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                              )}
                              <span className="min-w-0">
                                <span className="block truncate text-sm font-medium text-foreground">{pos.name}</span>
                                <span className="mt-0.5 block text-xs text-muted-foreground">
                                  {tp('common.counts.employee', pos.employee_count)}
                                </span>
                              </span>
                            </button>
                            <Link
                              href={`/positions/${pos.id}?tab=training`}
                              className="shrink-0 rounded-sm text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              Профиль и обучение
                            </Link>
                          </div>
                          {positionOpen && pos.employees.length > 0 && (
                            <ul className="mt-2 space-y-1 pl-6">
                              {pos.employees.map((emp) => (
                                <li key={emp.id} className="flex min-w-0 items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-background">
                                  <span
                                    className={
                                      emp.is_active
                                        ? "min-w-0 text-base font-semibold text-primary"
                                        : "min-w-0 text-base font-semibold text-muted-foreground line-through"
                                    }
                                  >
                                    {emp.full_name}
                                    {emp.personnel_number && (
                                      <span className="ml-2 whitespace-nowrap text-xs font-normal text-muted-foreground">
                                        · {emp.personnel_number}
                                      </span>
                                    )}
                                  </span>
                                  {emp.is_active && (
                                    <Link
                                      href={`/assignments?user_id=${emp.id}`}
                                      className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium text-primary hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                    >
                                      <GraduationCap className="h-4 w-4" aria-hidden="true" />
                                      <span className="hidden sm:inline">Назначить обучение</span>
                                      <span className="sm:hidden">Назначить</span>
                                    </Link>
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                        </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>}

      {data.unassignedPositions.length > 0 && <Card>
        <CardHeader><CardTitle>Требуют распределения</CardTitle><p className="text-sm text-muted-foreground">Должности старого формата, для которых нельзя безопасно определить филиал или отдел. Они не потеряны и показаны отдельно.</p></CardHeader>
        <CardContent className="space-y-2">{data.unassignedPositions.map((position) => <div key={position.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-warning/30 bg-warning/5 p-3"><div><span className="block text-sm font-medium">{position.name}</span><span className="text-xs text-muted-foreground">Исходное подразделение: {position.department || "не указано"}</span></div><span className="text-xs text-muted-foreground">{position.employee_count} сотрудников</span></div>)}</CardContent>
      </Card>}
    </div>
  );
}
