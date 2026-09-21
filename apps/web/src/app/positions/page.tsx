"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  BriefcaseBusiness,
  ChevronRight,
  FileSpreadsheet,
  FileText,
  FileUp,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Upload,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { useT, type TranslationKey } from "@/i18n/useT";
import { toast } from "@/components/ui/Toast";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui";

interface Position {
  id: string;
  name: string;
  department: string | null;
  level: string;
  instruction_document_id: string | null;
  instruction_filename: string | null;
  instruction_embedding_status: string | null;
  course_ids: string[];
  employee_count: number;
  current_employee_count?: number;
  created_at: string | null;
}

interface AuditIssue {
  severity: "warning" | "suggestion" | "ok";
  message: string;
  suggestion?: string;
}

interface BulkItem {
  filename: string;
  name: string;
  department: string;
  level: string;
  responsibilities: string;
  requirements: string;
  error: string | null;
  issues: AuditIssue[];
  selected: boolean;
}

interface BulkResponse {
  items: Omit<BulkItem, "selected">[];
}

interface BulkCreateResponse {
  created: { index: number; id: string; name: string }[];
  failed: { index: number; name: string; error: string }[];
}

function instructionLabel(position: Position, t: (key: TranslationKey) => string): string {
  if (!position.instruction_document_id) return t("authenticatedUi.positions.instructionNotUploaded" as TranslationKey);
  const status = position.instruction_embedding_status;
  if (status === "failed" || status === "error") return t("authenticatedUi.positions.instructionProcessingError" as TranslationKey);
  if (status === "pending" || status === "processing") return t("authenticatedUi.positions.instructionProcessing" as TranslationKey);
  return t("authenticatedUi.positions.instructionUploaded" as TranslationKey);
}

function instructionVariant(position: Position): "default" | "secondary" | "destructive" | "outline" {
  if (!position.instruction_document_id) return "outline";
  if (position.instruction_embedding_status === "failed" || position.instruction_embedding_status === "error")
    return "destructive";
  if (position.instruction_embedding_status === "pending" || position.instruction_embedding_status === "processing")
    return "secondary";
  return "default";
}

export default function PositionsPage() {
  const { t, tp } = useT();
  const ui = useCallback(
    (key: string, params?: Record<string, string | number>) => t(key as TranslationKey, params),
    [t],
  );
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [level, setLevel] = useState("");
  const [bulkItems, setBulkItems] = useState<BulkItem[]>([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [showBulkPreview, setShowBulkPreview] = useState(false);
  const [bulkCreating, setBulkCreating] = useState(false);

  const fetchPositions = useCallback(async () => {
    setLoadError(null);
    try {
      const response = await api.get<Position[]>("/v1/positions");
      setPositions(Array.isArray(response.data) ? response.data : []);
    } catch {
      setLoadError(ui("authenticatedUi.positions.loadError"));
    } finally {
      setLoading(false);
    }
  }, [ui]);

  useEffect(() => {
    void fetchPositions();
  }, [fetchPositions]);

  const filteredPositions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return positions;
    return positions.filter((position) =>
      [position.name, position.department ?? "", position.level].some((value) =>
        value.toLocaleLowerCase().includes(normalized),
      ),
    );
  }, [positions, query]);

  const resetCreate = () => {
    setName("");
    setDepartment("");
    setLevel("");
    setShowCreate(false);
  };

  const handleCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      await api.post("/v1/positions", {
        name: name.trim(),
        department: department.trim(),
        level: level.trim(),
        responsibilities: "",
        requirements: "",
        course_ids: [],
      });
      toast.success(ui("authenticatedUi.positions.createSuccess"));
      resetCreate();
      await fetchPositions();
    } catch {
      toast.error(ui("authenticatedUi.positions.createError"));
    } finally {
      setCreating(false);
    }
  };

  const handleBulkAnalyze = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    if (files.length > 50) {
      setBulkError(ui("authenticatedUi.positions.bulkMaxFiles"));
      return;
    }
    setBulkLoading(true);
    setBulkError(null);
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    try {
      const response = await api.post<BulkResponse>("/v1/positions/bulk-analyze-jd", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const items = (response.data.items ?? []).map((item) => ({
        ...item,
        selected: !item.error && Boolean(item.name.trim()),
      }));
      setBulkItems(items);
      setShowBulkPreview(true);
    } catch {
      setBulkError(ui("authenticatedUi.positions.bulkAnalyzeError"));
    } finally {
      setBulkLoading(false);
    }
  };

  const selectedBulkItems = bulkItems.filter((item) => item.selected && !item.error && item.name.trim());

  const handleBulkCreate = async () => {
    if (!selectedBulkItems.length) return;
    setBulkCreating(true);
    try {
      const response = await api.post<BulkCreateResponse>("/v1/positions/bulk-create", {
        items: selectedBulkItems.map(
          ({ name: itemName, department: itemDepartment, level: itemLevel, responsibilities, requirements }) => ({
            name: itemName.trim(),
            department: itemDepartment.trim(),
            level: itemLevel.trim(),
            responsibilities,
            requirements,
            course_ids: [],
          }),
        ),
      });
      const failed = response.data.failed?.length ?? 0;
      toast.success(
        failed
          ? ui("authenticatedUi.positions.bulkCreateSuccessWithErrors", { created: response.data.created.length, failed })
          : ui("authenticatedUi.positions.bulkCreateSuccess", { created: response.data.created.length }),
      );
      setBulkItems([]);
      setShowBulkPreview(false);
      await fetchPositions();
    } catch {
      toast.error(ui("authenticatedUi.positions.bulkCreateError"));
    } finally {
      setBulkCreating(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
            <BriefcaseBusiness className="h-4 w-4" aria-hidden="true" />
            {ui("authenticatedUi.positions.eyebrow")}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{t("positions.title")}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {ui("authenticatedUi.positions.subtitle")}
          </p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
          <Button
            type="button"
            variant="outline"
            className="w-full gap-2 sm:w-auto"
            onClick={() => fileInputRef.current?.click()}
            disabled={bulkLoading}
          >
            {bulkLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-4 w-4" aria-hidden="true" />
            )}
            {ui("authenticatedUi.positions.uploadInstruction")}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.doc,.docx,.txt"
            className="sr-only"
            onChange={handleBulkAnalyze}
            aria-label={ui("authenticatedUi.positions.uploadInstructionAria")}
          />
          <Button type="button" className="w-full gap-2 sm:w-auto" onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t("positions.create")}
          </Button>
        </div>
      </header>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="relative block w-full sm:max-w-md">
          <span className="sr-only">{ui("authenticatedUi.positions.searchLabel")}</span>
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={ui("authenticatedUi.positions.searchPlaceholder")}
            className="pl-9"
          />
        </label>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>
            {ui("authenticatedUi.positions.resultCount", { filtered: filteredPositions.length, total: positions.length })}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => void fetchPositions()}
            aria-label={ui("authenticatedUi.positions.refresh")}
            title={ui("authenticatedUi.positions.refresh")}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {bulkError && (
        <div
          role="alert"
          className="flex items-start justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          <span>{bulkError}</span>
          <button
            type="button"
            className="rounded p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => setBulkError(null)}
            aria-label={ui("authenticatedUi.positions.closeMessage")}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}

      {loading ? (
        <Card>
          <CardContent className="flex min-h-52 items-center justify-center gap-3 text-sm text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
            {ui("authenticatedUi.positions.loading")}
          </CardContent>
        </Card>
      ) : loadError ? (
        <Card>
          <CardContent className="flex min-h-52 flex-col items-center justify-center gap-4 text-center">
            <p role="alert" className="text-sm text-destructive">
              {loadError}
            </p>
            <Button type="button" variant="outline" className="gap-2" onClick={() => void fetchPositions()}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              {ui("authenticatedUi.positions.retry")}
            </Button>
          </CardContent>
        </Card>
      ) : positions.length === 0 ? (
        <Card>
          <CardContent className="flex min-h-60 flex-col items-center justify-center gap-3 px-6 text-center">
            <BriefcaseBusiness className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
            <h2 className="text-lg font-medium">{ui("authenticatedUi.positions.emptyTitle")}</h2>
            <p className="max-w-md text-sm text-muted-foreground">
              {ui("authenticatedUi.positions.emptyDescription")}
            </p>
            <Button type="button" onClick={() => setShowCreate(true)} className="mt-2 gap-2">
              <Plus className="h-4 w-4" aria-hidden="true" />
              {ui("authenticatedUi.positions.create")}
            </Button>
          </CardContent>
        </Card>
      ) : filteredPositions.length === 0 ? (
        <Card>
          <CardContent className="flex min-h-40 items-center justify-center px-6 text-center text-sm text-muted-foreground">
            {ui("authenticatedUi.positions.noSearchResults")}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {filteredPositions.map((position) => (
            <Link
              key={position.id}
              href={`/positions/${position.id}`}
              className="group block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <Card className="transition-colors group-hover:border-primary/50 group-hover:bg-muted/20">
                <CardContent className="flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-center lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <h2 className="min-w-0 truncate text-base font-semibold text-foreground sm:text-lg">
                        {position.name}
                      </h2>
                      <Badge variant={instructionVariant(position)}>{instructionLabel(position, t)}</Badge>
                    </div>
                    <p className="mt-1 truncate text-sm text-muted-foreground">
                      {position.department || ui("authenticatedUi.positions.noDepartment")}
                      {position.level ? ` · ${position.level}` : ""}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span className="inline-flex items-center gap-1">
                        <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                        {tp('common.counts.course', position.course_ids?.length ?? 0)}
                      </span>
                      <span>
                        {tp(
                          'common.counts.employee',
                          position.current_employee_count ?? position.employee_count ?? 0
                        )}
                      </span>
                      {position.instruction_filename && (
                        <span className="inline-flex max-w-full items-center gap-1 truncate">
                          <FileUp className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          {position.instruction_filename}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="inline-flex shrink-0 items-center gap-2 text-sm font-medium text-primary">
                    {ui("authenticatedUi.positions.openCard")}
                    <ChevronRight
                      className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                      aria-hidden="true"
                    />
                  </span>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}

      {showCreate && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-position-title"
        >
          <Card className="max-h-[90vh] w-full overflow-auto rounded-b-none sm:max-w-xl sm:rounded-lg">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <h2 id="create-position-title" className="text-lg font-semibold">
                  {ui("authenticatedUi.positions.create")}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {ui("authenticatedUi.positions.createDescription")}
                </p>
              </div>
              <Button type="button" variant="ghost" size="icon" onClick={resetCreate} aria-label={ui("authenticatedUi.positions.close")}>
                <X className="h-5 w-5" aria-hidden="true" />
              </Button>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={handleCreate}>
                <div>
                  <label htmlFor="position-name" className="mb-1.5 block text-sm font-medium">
                    {ui("authenticatedUi.positions.name")}
                  </label>
                  <Input
                    id="position-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    required
                    autoFocus
                    placeholder={ui("authenticatedUi.positions.namePlaceholder")}
                  />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="position-department" className="mb-1.5 block text-sm font-medium">
                      {ui("authenticatedUi.positions.department")}
                    </label>
                    <Input
                      id="position-department"
                      value={department}
                      onChange={(event) => setDepartment(event.target.value)}
                      placeholder={ui("authenticatedUi.positions.departmentPlaceholder")}
                    />
                  </div>
                  <div>
                    <label htmlFor="position-level" className="mb-1.5 block text-sm font-medium">
                      {ui("authenticatedUi.positions.level")}
                    </label>
                    <Input
                      id="position-level"
                      value={level}
                      onChange={(event) => setLevel(event.target.value)}
                      placeholder={ui("authenticatedUi.positions.levelPlaceholder")}
                    />
                  </div>
                </div>
                <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                  <Button type="button" variant="outline" onClick={resetCreate}>
                    {ui("authenticatedUi.positions.cancel")}
                  </Button>
                  <Button type="submit" disabled={creating || !name.trim()} className="gap-2">
                    {creating && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}{ui("authenticatedUi.positions.create")}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {showBulkPreview && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="bulk-preview-title"
        >
          <Card className="max-h-[92vh] w-full overflow-auto rounded-b-none sm:max-w-3xl sm:rounded-lg">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <h2 id="bulk-preview-title" className="text-lg font-semibold">
                  {ui("authenticatedUi.positions.bulkPreviewTitle")}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {ui("authenticatedUi.positions.bulkPreviewDescription")}
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setShowBulkPreview(false)}
                aria-label={ui("authenticatedUi.positions.close")}
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />
                {ui("authenticatedUi.positions.selectedCount", { selected: selectedBulkItems.length, total: bulkItems.length })}
              </div>
              <div className="space-y-2">
                {bulkItems.map((item, index) => (
                  <label
                    key={`${item.filename}-${index}`}
                    className={`flex gap-3 rounded-md border p-3 ${item.error ? "border-destructive/30 bg-destructive/5" : "border-border"}`}
                  >
                    <input
                      type="checkbox"
                      checked={item.selected}
                      disabled={Boolean(item.error) || !item.name.trim()}
                      onChange={(event) =>
                        setBulkItems((current) =>
                          current.map((entry, entryIndex) =>
                            entryIndex === index ? { ...entry, selected: event.target.checked } : entry,
                          ),
                        )
                      }
                      className="mt-1 h-4 w-4 rounded border-input text-primary focus:ring-primary"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{item.name || item.filename}</span>
                        {item.error ? (
                          <Badge variant="destructive">{ui("authenticatedUi.positions.errorStatus")}</Badge>
                        ) : (
                          <Badge variant="default">{ui("authenticatedUi.positions.readyStatus")}</Badge>
                        )}
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {item.department || ui("authenticatedUi.positions.noDepartment")}
                        {item.level ? ` · ${item.level}` : ""} · {item.filename}
                      </span>
                      {item.error && <span className="mt-1 block text-sm text-destructive">{item.error}</span>}
                      {!item.error && item.issues?.length > 0 && (
                        <span className="mt-1 block text-xs text-warning">{ui("authenticatedUi.positions.aiIssues", { count: item.issues.length })}</span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
              <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowBulkPreview(false);
                    setBulkItems([]);
                  }}
                >
                  {ui("authenticatedUi.positions.cancel")}
                </Button>
                <Button
                  type="button"
                  disabled={bulkCreating || !selectedBulkItems.length}
                  onClick={() => void handleBulkCreate()}
                  className="gap-2"
                >
                  {bulkCreating && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}{ui("authenticatedUi.positions.createSelected", { count: selectedBulkItems.length })}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
