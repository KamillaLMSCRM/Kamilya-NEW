"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, Eye, FileCheck2, LockKeyhole, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, DateInput, Input } from "@/components/ui";
import { toast } from "@/components/ui/Toast";
import { useT } from "@/i18n/useT";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";

type ProcedureType = "acknowledgement" | "internal_attestation" | "admission_decision";
type ProcedureStatus = "draft" | "active" | "retired";
type ConfirmationMethod = "manual_record" | "email_otp";

interface Procedure {
  id: string;
  tenant_id: string;
  code: string;
  version: number;
  title: string;
  description: string;
  procedure_type: ProcedureType;
  status: ProcedureStatus;
  approval_reference: string | null;
  approval_date: string | null;
  approved_by_name: string | null;
  legal_basis: string | null;
  local_basis: string | null;
  confirmation_method: ConfirmationMethod;
  retention_class: string | null;
  retention_days: number | null;
  commission_snapshot_rules: Record<string, unknown> | null;
  authorized_decision_rules: Record<string, unknown> | null;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  activated_at: string | null;
  retired_at: string | null;
}

interface ProcedureForm {
  code: string;
  version: string;
  title: string;
  description: string;
  procedure_type: ProcedureType;
  confirmation_method: ConfirmationMethod;
  approval_reference: string;
  approval_date: string;
  approved_by_name: string;
  legal_basis: string;
  local_basis: string;
  retention_class: string;
  retention_days: string;
  commission_members: string;
  commission_quorum: string;
  commission_decision_record: string;
  decision_authority: string;
  decision_record: string;
  decision_effective_date: string;
}

const EMPTY_FORM: ProcedureForm = {
  code: "",
  version: "1",
  title: "",
  description: "",
  procedure_type: "acknowledgement",
  confirmation_method: "manual_record",
  approval_reference: "",
  approval_date: "",
  approved_by_name: "",
  legal_basis: "",
  local_basis: "",
  retention_class: "",
  retention_days: "",
  commission_members: "",
  commission_quorum: "",
  commission_decision_record: "",
  decision_authority: "",
  decision_record: "",
  decision_effective_date: "",
};

const RETENTION_CLASSES = [
  "training-results",
  "knowledge-checks",
  "acknowledgements",
  "work-admission",
  "other",
] as const;
const RETENTION_PERIODS = ["365", "1095", "1825", "3650", "7300"] as const;

function generatedProcedureCode() {
  return `procedure-${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
}

function formFromProcedure(item: Procedure): ProcedureForm {
  const commission = item.commission_snapshot_rules ?? {};
  const decision = item.authorized_decision_rules ?? {};
  return {
    code: item.code,
    version: String(item.version),
    title: item.title,
    description: item.description,
    procedure_type: item.procedure_type,
    confirmation_method: item.confirmation_method,
    approval_reference: item.approval_reference ?? "",
    approval_date: item.approval_date ?? "",
    approved_by_name: item.approved_by_name ?? "",
    legal_basis: item.legal_basis ?? "",
    local_basis: item.local_basis ?? "",
    retention_class: item.retention_class ?? "",
    retention_days: item.retention_days ? String(item.retention_days) : "",
    commission_members: String(commission.members ?? ""),
    commission_quorum: String(commission.quorum ?? ""),
    commission_decision_record: String(commission.decision_record ?? ""),
    decision_authority: String(decision.authority ?? ""),
    decision_record: String(decision.decision_record ?? ""),
    decision_effective_date: String(decision.effective_date ?? ""),
  };
}

function toPayload(form: ProcedureForm) {
  return {
    code: form.code.trim() || generatedProcedureCode(),
    version: Number(form.version),
    title: form.title.trim(),
    description: form.description.trim(),
    procedure_type: form.procedure_type,
    confirmation_method: form.confirmation_method,
    approval_reference: form.approval_reference.trim() || null,
    approval_date: form.approval_date || null,
    approved_by_name: form.approved_by_name.trim() || null,
    legal_basis: form.legal_basis.trim() || null,
    local_basis: form.local_basis.trim() || null,
    retention_class: form.retention_class.trim() || null,
    retention_days: form.retention_days ? Number(form.retention_days) : null,
    commission_snapshot_rules:
      form.procedure_type === "internal_attestation"
        ? { members: form.commission_members.trim(), quorum: form.commission_quorum.trim(), decision_record: form.commission_decision_record.trim() }
        : null,
    authorized_decision_rules:
      form.procedure_type === "admission_decision"
        ? { authority: form.decision_authority.trim(), decision_record: form.decision_record.trim(), effective_date: form.decision_effective_date.trim() }
        : null,
  };
}

export default function TrainingProceduresPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role ?? "");
  const [items, setItems] = useState<Procedure[]>([]);
  const [form, setForm] = useState<ProcedureForm>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (role !== "methodologist") return;
    setLoading(true);
    try {
      const response = await api.get<{ items: Procedure[] }>("/v1/training-procedures");
      setItems(response.data.items ?? []);
    } catch (error: any) {
      toast.error(typeof error?.response?.data?.detail === "string" ? error.response.data.detail : t("trainingProceduresPage.loadError"));
    } finally {
      setLoading(false);
    }
  }, [role, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const updateForm = (field: keyof ProcedureForm, value: string) => setForm((current) => ({ ...current, [field]: value }));
  const isEditing = editingId !== null;
  const selected = useMemo(() => items.find((item) => item.id === editingId) ?? null, [editingId, items]);
  const readOnly = Boolean(selected && selected.status !== "draft");

  const save = async () => {
    setSaving(true);
    try {
      if (editingId) await api.patch(`/v1/training-procedures/${editingId}`, toPayload(form));
      else await api.post("/v1/training-procedures", toPayload(form));
      toast.success(t("trainingProceduresPage.saved"));
      setEditingId(null);
      setForm(EMPTY_FORM);
      await load();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("trainingProceduresPage.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const action = async (item: Procedure, operation: "activate" | "retire" | "delete") => {
    if (operation === "delete" && !window.confirm(t("trainingProceduresPage.deleteConfirm"))) return;
    setSaving(true);
    try {
      if (operation === "delete") await api.delete(`/v1/training-procedures/${item.id}`);
      else await api.post(`/v1/training-procedures/${item.id}/${operation}`);
      toast.success(t("trainingProceduresPage.saved"));
      if (editingId === item.id) {
        setEditingId(null);
        setForm(EMPTY_FORM);
      }
      await load();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      const missing = detail?.missing_fields;
      toast.error(Array.isArray(missing) ? `${t("trainingProceduresPage.activationIncomplete")}: ${missing.join(", ")}` : typeof detail === "string" ? detail : t("trainingProceduresPage.saveError"));
    } finally {
      setSaving(false);
    }
  };

  if (role !== "methodologist") {
    return <Card><CardContent className="p-6"><h1 className="text-lg font-semibold">{t("trainingProceduresPage.accessDenied")}</h1><p className="mt-1 text-sm text-muted-foreground">{t("trainingProceduresPage.methodologistOnly")}</p></CardContent></Card>;
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><FileCheck2 className="h-6 w-6 shrink-0" aria-hidden="true" />{t("trainingProceduresPage.title")}</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t("trainingProceduresPage.subtitle")}</p>
        </div>
        <Button type="button" onClick={() => { setEditingId(null); setForm(EMPTY_FORM); }} disabled={saving} className="shrink-0"><Plus className="h-4 w-4" aria-hidden="true" />{t("trainingProceduresPage.newProcedure")}</Button>
      </header>

      <div className="flex min-w-0 gap-3 border-l-4 border-warning bg-warning/10 px-4 py-3 text-sm text-foreground" role="note">
        <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        <p className="min-w-0">{t("trainingProceduresPage.evidenceBoundary")}</p>
      </div>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <Card className="min-w-0 overflow-hidden">
          <CardHeader><CardTitle className="text-base">{t("trainingProceduresPage.catalog")}</CardTitle></CardHeader>
          <CardContent className="p-0">
            {loading ? <p className="p-6 text-sm text-muted-foreground">{t("common.loading")}</p> : items.length === 0 ? <p className="p-6 text-sm text-muted-foreground">{t("trainingProceduresPage.empty")}</p> : <ul className="divide-y divide-border">{items.map((item) => <li key={item.id} className={`min-w-0 p-4 ${editingId === item.id ? "bg-primary/5" : ""}`}>
              <div className="flex min-w-0 items-start gap-3"><div className="min-w-0 flex-1"><div className="flex min-w-0 flex-wrap items-center gap-2"><span className="truncate font-medium" title={item.title}>{item.title}</span><Badge variant={item.status === "active" ? "default" : "secondary"}>{t(`trainingProceduresPage.status.${item.status}` as never)}</Badge></div><p className="mt-1 break-words text-xs text-muted-foreground">{item.code} v{item.version} · {t(`trainingProceduresPage.types.${item.procedure_type}` as never)}</p></div><Button type="button" variant="outline" size="sm" disabled={saving} onClick={() => { setEditingId(item.id); setForm(formFromProcedure(item)); }} aria-label={item.status === "draft" ? t("trainingProceduresPage.edit") : t("common.open")} title={item.status === "draft" ? t("trainingProceduresPage.edit") : t("common.open")}>{item.status === "draft" ? <Pencil className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}</Button></div>
              <div className="mt-3 flex min-w-0 flex-wrap gap-2">{item.status === "draft" && <Button type="button" size="sm" onClick={() => void action(item, "activate")} disabled={saving}><CheckCircle2 className="h-4 w-4" aria-hidden="true" />{t("trainingProceduresPage.activate")}</Button>}{item.status === "active" && <Button type="button" size="sm" variant="outline" onClick={() => void action(item, "retire")} disabled={saving}><RotateCcw className="h-4 w-4" aria-hidden="true" />{t("trainingProceduresPage.retire")}</Button>}{item.status === "draft" && <Button type="button" size="sm" variant="ghost" onClick={() => void action(item, "delete")} disabled={saving} aria-label={t("common.delete")} title={t("common.delete")}><Trash2 className="h-4 w-4" aria-hidden="true" /></Button>}</div>
            </li>)}</ul>}
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader><CardTitle className="text-base">{isEditing ? t("trainingProceduresPage.editTitle") : t("trainingProceduresPage.createTitle")}</CardTitle><p className="text-sm text-muted-foreground">{t("trainingProceduresPage.formHint")}</p></CardHeader>
          <CardContent className="space-y-4">
            <fieldset disabled={readOnly || saving} className="space-y-4">
            <Field label={t("trainingProceduresPage.name")}><Input value={form.title} onChange={(event) => updateForm("title", event.target.value)} /></Field>
            <Field label={t("trainingProceduresPage.type")}><select className="min-h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.procedure_type} onChange={(event) => updateForm("procedure_type", event.target.value as ProcedureType)} disabled={isEditing}><option value="acknowledgement">{t("trainingProceduresPage.types.acknowledgement")}</option><option value="internal_attestation">{t("trainingProceduresPage.types.internal_attestation")}</option><option value="admission_decision">{t("trainingProceduresPage.types.admission_decision")}</option></select></Field>
            <Field label={t("trainingProceduresPage.description")}><textarea className="min-h-20 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.description} onChange={(event) => updateForm("description", event.target.value)} /></Field>
            <div className="grid min-w-0 gap-4 sm:grid-cols-2"><Field label={t("trainingProceduresPage.confirmationMethod")}><select className="min-h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.confirmation_method} onChange={(event) => updateForm("confirmation_method", event.target.value as ConfirmationMethod)}><option value="manual_record">{t("trainingProceduresPage.confirmations.manual_record")}</option><option value="email_otp">{t("trainingProceduresPage.confirmations.email_otp")}</option></select></Field><Field label={t("trainingProceduresPage.retentionClass")}><select className="min-h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.retention_class} onChange={(event) => updateForm("retention_class", event.target.value)}><option value="">{t("trainingProceduresPage.chooseOption")}</option>{form.retention_class && !RETENTION_CLASSES.includes(form.retention_class as typeof RETENTION_CLASSES[number]) && <option value={form.retention_class}>{form.retention_class}</option>}{RETENTION_CLASSES.map((item) => <option key={item} value={item}>{t(`trainingProceduresPage.retentionClasses.${item}` as never)}</option>)}</select></Field></div>
            <Field label={t("trainingProceduresPage.retentionPeriod")}><select className="min-h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.retention_days} onChange={(event) => updateForm("retention_days", event.target.value)}><option value="">{t("trainingProceduresPage.chooseOption")}</option>{form.retention_days && !RETENTION_PERIODS.includes(form.retention_days as typeof RETENTION_PERIODS[number]) && <option value={form.retention_days}>{form.retention_days} {t("trainingProceduresPage.days")}</option>}{RETENTION_PERIODS.map((days) => <option key={days} value={days}>{t(`trainingProceduresPage.retentionPeriods.${days}` as never)}</option>)}</select></Field>
            <details className="rounded-md border border-border bg-muted/20 p-3" open={isEditing && readOnly}>
              <summary className="cursor-pointer text-sm font-semibold">{t("trainingProceduresPage.additionalSettings")}</summary>
              <div className="mt-4 space-y-4">
                <p className="text-xs text-muted-foreground">{t("trainingProceduresPage.additionalSettingsHint")}</p>
                <div className="grid min-w-0 gap-4 sm:grid-cols-2"><Field label={t("trainingProceduresPage.code")}><Input value={form.code} disabled={isEditing} placeholder={t("trainingProceduresPage.codeAuto")} onChange={(event) => updateForm("code", event.target.value)} /></Field><Field label={t("trainingProceduresPage.version")}><Input type="number" min={1} value={form.version} disabled={isEditing} onChange={(event) => updateForm("version", event.target.value)} /></Field></div>
                <div className="grid min-w-0 gap-4 sm:grid-cols-2"><Field label={t("trainingProceduresPage.approvalReference")}><Input value={form.approval_reference} onChange={(event) => updateForm("approval_reference", event.target.value)} /></Field><Field label={t("trainingProceduresPage.approvalDate")}><DateInput value={form.approval_date} onChange={(value) => updateForm("approval_date", value)} /></Field></div>
                <Field label={t("trainingProceduresPage.approvedBy")}><Input value={form.approved_by_name} onChange={(event) => updateForm("approved_by_name", event.target.value)} /></Field>
                <div className="grid min-w-0 gap-4 sm:grid-cols-2"><Field label={t("trainingProceduresPage.legalBasis")}><textarea className="min-h-20 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.legal_basis} onChange={(event) => updateForm("legal_basis", event.target.value)} /></Field><Field label={t("trainingProceduresPage.localBasis")}><textarea className="min-h-20 w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.local_basis} onChange={(event) => updateForm("local_basis", event.target.value)} /></Field></div>
                {form.procedure_type === "internal_attestation" && <RuleFields title={t("trainingProceduresPage.commissionRules")} fields={[["commission_members", t("trainingProceduresPage.commissionMembers")], ["commission_quorum", t("trainingProceduresPage.commissionQuorum")], ["commission_decision_record", t("trainingProceduresPage.decisionRecord")]]} form={form} updateForm={updateForm} />}
                {form.procedure_type === "admission_decision" && <RuleFields title={t("trainingProceduresPage.authorizedRules")} fields={[["decision_authority", t("trainingProceduresPage.authority")], ["decision_record", t("trainingProceduresPage.decisionRecord")], ["decision_effective_date", t("trainingProceduresPage.effectiveDate")]]} form={form} updateForm={updateForm} />}
              </div>
            </details>
            </fieldset>
            <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4"><Button type="button" variant="outline" onClick={() => { setEditingId(null); setForm(EMPTY_FORM); }}>{readOnly ? t("common.close") : t("common.cancel")}</Button>{!readOnly && <Button type="button" onClick={() => void save()} disabled={saving || !form.title}>{saving ? t("common.saving") : t("common.save")}</Button>}</div>
            {selected?.status === "retired" && <p className="text-xs text-muted-foreground">{t("trainingProceduresPage.retiredHint")}</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block min-w-0 space-y-1"><span className="text-sm font-medium">{label}</span>{children}</label>;
}

function RuleFields({ title, fields, form, updateForm }: { title: string; fields: Array<[keyof ProcedureForm, string]>; form: ProcedureForm; updateForm: (field: keyof ProcedureForm, value: string) => void }) {
  return <fieldset className="space-y-3 rounded-md border border-border p-3"><legend className="px-1 text-sm font-semibold">{title}</legend>{fields.map(([field, label]) => <Field key={field} label={label}><Input value={form[field]} onChange={(event) => updateForm(field, event.target.value)} /></Field>)}</fieldset>;
}
