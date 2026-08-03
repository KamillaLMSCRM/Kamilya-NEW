"use client";

import { useCallback, useEffect, useState } from "react";
import { DatabaseZap, LockKeyhole, Play, Plus, RotateCcw, Trash2 } from "lucide-react";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui";
import { toast } from "@/components/ui/Toast";
import { useT } from "@/i18n/useT";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";

type ProcedureType = "acknowledgement" | "training" | "knowledge_check" | "internal_attestation" | "admission_decision";

interface RetentionPolicy {
  id: string;
  procedure_type: ProcedureType;
  retention_days: number;
  legal_basis: string | null;
  local_basis: string | null;
  active: boolean;
}

interface PurgeResult {
  dry_run: boolean;
  roots_scanned: number;
  eligible_roots: number;
  purged_roots: number;
  purged_events: number;
  purged_confirmations: number;
  purged_hold_history: number;
  purged_shares: number;
  reason_counts: Record<string, number>;
}

const TYPES: ProcedureType[] = ["acknowledgement", "training", "knowledge_check", "internal_attestation", "admission_decision"];

const emptyForm = {
  procedure_type: "training" as ProcedureType,
  retention_days: "1825",
  legal_basis: "",
  local_basis: "",
  active: false,
};

export default function TrainingRetentionPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role ?? "");
  const [items, setItems] = useState<RetentionPolicy[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [purging, setPurging] = useState(false);
  const [execute, setExecute] = useState(false);
  const [token, setToken] = useState("");
  const [reauthPassword, setReauthPassword] = useState("");
  const [result, setResult] = useState<PurgeResult | null>(null);

  const load = useCallback(async () => {
    if (role !== "methodologist") return;
    setLoading(true);
    try {
      const response = await api.get<{ items: RetentionPolicy[] }>("/v1/training-retention/policies");
      setItems(response.data.items ?? []);
    } catch {
      toast.error(t("trainingRetentionPage.loadError" as never));
    } finally {
      setLoading(false);
    }
  }, [role, t]);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    if (!form.legal_basis.trim() && !form.local_basis.trim()) {
      toast.error(t("trainingRetentionPage.basisRequired" as never));
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form, retention_days: Number(form.retention_days), legal_basis: form.legal_basis.trim() || null, local_basis: form.local_basis.trim() || null };
      if (editingId) await api.patch(`/v1/training-retention/policies/${editingId}`, payload);
      else await api.post("/v1/training-retention/policies", payload);
      toast.success(t("trainingRetentionPage.saved" as never));
      setEditingId(null);
      setForm(emptyForm);
      await load();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("trainingRetentionPage.saveError" as never));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item: RetentionPolicy) => {
    if (!window.confirm(t("trainingRetentionPage.deleteConfirm" as never))) return;
    setSaving(true);
    try {
      await api.delete(`/v1/training-retention/policies/${item.id}`);
      toast.success(t("trainingRetentionPage.deleted" as never));
      await load();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("trainingRetentionPage.saveError" as never));
    } finally {
      setSaving(false);
    }
  };

  const runPurge = async () => {
    if (execute && token !== "PURGE_TRAINING_EVIDENCE") {
      toast.error(t("trainingRetentionPage.confirmationRequired" as never));
      return;
    }
    if (execute && !window.confirm(t("trainingRetentionPage.irreversibleConfirm" as never))) return;
    setPurging(true);
    try {
      const response = await api.post<PurgeResult>("/v1/training-retention/purge", {
        dry_run: !execute,
        confirmation_token: execute ? token : null,
        reauth_password: execute ? reauthPassword : null,
        max_roots: 100,
      });
      setResult(response.data);
      const messageKey = execute ? "trainingRetentionPage.purgeComplete" : "trainingRetentionPage.previewComplete";
      toast.success(t(messageKey as never));
      if (execute) await load();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("trainingRetentionPage.purgeError" as never));
    } finally {
      setPurging(false);
    }
  };

  if (role !== "methodologist") {
    return <Card><CardContent className="p-6"><h1 className="text-lg font-semibold">{t("trainingRetentionPage.accessDenied" as never)}</h1></CardContent></Card>;
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><DatabaseZap className="h-6 w-6 shrink-0" aria-hidden="true" />{t("trainingRetentionPage.title" as never)}</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t("trainingRetentionPage.subtitle" as never)}</p>
        </div>
        <Button type="button" onClick={() => { setEditingId(null); setForm(emptyForm); }} disabled={saving}><Plus className="h-4 w-4" aria-hidden="true" />{t("trainingRetentionPage.newPolicy" as never)}</Button>
      </header>

      <div className="flex min-w-0 gap-3 border-l-4 border-warning bg-warning/10 px-4 py-3 text-sm" role="note">
        <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        <p className="min-w-0">{t("trainingRetentionPage.warning" as never)}</p>
      </div>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Card className="min-w-0 overflow-hidden">
          <CardHeader><CardTitle className="text-base">{t("trainingRetentionPage.policies" as never)}</CardTitle></CardHeader>
          <CardContent className="p-0">
            {loading ? <p className="p-6 text-sm text-muted-foreground">{t("common.loading" as never)}</p> : items.length === 0 ? <p className="p-6 text-sm text-muted-foreground">{t("trainingRetentionPage.empty" as never)}</p> : <ul className="divide-y divide-border">{items.map((item) => <li key={item.id} className="min-w-0 p-4">
              <div className="flex min-w-0 items-start gap-3"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="font-medium">{t(`trainingRetentionPage.types.${item.procedure_type}` as never)}</span><Badge variant={item.active ? "default" : "secondary"}>{item.active ? t("trainingRetentionPage.active" as never) : t("trainingRetentionPage.inactive" as never)}</Badge></div><p className="mt-1 text-sm text-muted-foreground">{t("trainingRetentionPage.days" as never)}: {item.retention_days}</p></div><Button type="button" variant="outline" size="sm" onClick={() => { setEditingId(item.id); setForm({ procedure_type: item.procedure_type, retention_days: String(item.retention_days), legal_basis: item.legal_basis ?? "", local_basis: item.local_basis ?? "", active: item.active }); }} aria-label={t("trainingRetentionPage.edit" as never)}><RotateCcw className="h-4 w-4" aria-hidden="true" /></Button>{!item.active && <Button type="button" variant="ghost" size="icon" onClick={() => void remove(item)} aria-label={t("common.delete" as never)}><Trash2 className="h-4 w-4" aria-hidden="true" /></Button>}</div>
              <p className="mt-2 break-words text-xs text-muted-foreground">{item.legal_basis || item.local_basis}</p>
            </li>)}</ul>}
          </CardContent>
        </Card>

        <Card className="min-w-0"><CardHeader><CardTitle className="text-base">{editingId ? t("trainingRetentionPage.editTitle" as never) : t("trainingRetentionPage.createTitle" as never)}</CardTitle></CardHeader><CardContent className="space-y-4">
          <label className="block space-y-1"><span className="text-sm font-medium">{t("trainingRetentionPage.procedureType" as never)}</span><select className="min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.procedure_type} disabled={Boolean(editingId)} onChange={(event) => setForm({ ...form, procedure_type: event.target.value as ProcedureType })}>{TYPES.map((type) => <option key={type} value={type}>{t(`trainingRetentionPage.types.${type}` as never)}</option>)}</select></label>
          <label className="block space-y-1"><span className="text-sm font-medium">{t("trainingRetentionPage.days" as never)}</span><Input type="number" min={1} max={36500} value={form.retention_days} onChange={(event) => setForm({ ...form, retention_days: event.target.value })} /></label>
          <label className="block space-y-1"><span className="text-sm font-medium">{t("trainingRetentionPage.legalBasis" as never)}</span><textarea className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.legal_basis} onChange={(event) => setForm({ ...form, legal_basis: event.target.value })} /></label>
          <label className="block space-y-1"><span className="text-sm font-medium">{t("trainingRetentionPage.localBasis" as never)}</span><textarea className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.local_basis} onChange={(event) => setForm({ ...form, local_basis: event.target.value })} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={(event) => setForm({ ...form, active: event.target.checked })} />{t("trainingRetentionPage.activePolicy" as never)}</label>
          <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4"><Button type="button" variant="outline" onClick={() => { setEditingId(null); setForm(emptyForm); }}>{t("common.cancel" as never)}</Button><Button type="button" onClick={() => void save()} disabled={saving}>{saving ? t("common.saving" as never) : t("common.save" as never)}</Button></div>
        </CardContent></Card>
      </div>

      <Card><CardHeader><CardTitle className="text-base">{t("trainingRetentionPage.purgeTitle" as never)}</CardTitle><p className="text-sm text-muted-foreground">{t("trainingRetentionPage.purgeHint" as never)}</p></CardHeader><CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3"><Button type="button" variant="outline" onClick={() => void runPurge()} disabled={purging}><Play className="h-4 w-4" aria-hidden="true" />{purging ? t("trainingRetentionPage.running" as never) : t("trainingRetentionPage.preview" as never)}</Button><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={execute} onChange={(event) => { setExecute(event.target.checked); setResult(null); setToken(""); setReauthPassword(""); }} />{t("trainingRetentionPage.enableExecute" as never)}</label></div>
        {execute && <div className="max-w-xl space-y-3"><p className="text-sm font-medium text-destructive">{t("trainingRetentionPage.irreversible" as never)}</p><label className="block space-y-1"><span className="text-sm font-medium">{t("trainingRetentionPage.confirmationToken" as never)}</span><Input value={token} onChange={(event) => setToken(event.target.value)} placeholder="PURGE_TRAINING_EVIDENCE" autoComplete="off" /></label><label className="block space-y-1"><span className="text-sm font-medium">{t("trainingRetentionPage.reauthPassword" as never)}</span><Input type="password" value={reauthPassword} onChange={(event) => setReauthPassword(event.target.value)} autoComplete="current-password" /></label><p className="text-xs text-muted-foreground">{t("trainingRetentionPage.reauthHint" as never)}</p></div>}
        {execute && <Button type="button" variant="destructive" onClick={() => void runPurge()} disabled={purging || token !== "PURGE_TRAINING_EVIDENCE" || !reauthPassword}>{t("trainingRetentionPage.execute" as never)}</Button>}
        {result && <div className="grid gap-3 rounded-md border border-border bg-muted/30 p-4 text-sm sm:grid-cols-4"><div><b>{result.roots_scanned}</b><span className="ml-1">{t("trainingRetentionPage.scanned" as never)}</span></div><div><b>{result.eligible_roots}</b><span className="ml-1">{t("trainingRetentionPage.eligible" as never)}</span></div><div><b>{result.purged_events}</b><span className="ml-1">{t("trainingRetentionPage.events" as never)}</span></div><div><b>{result.purged_shares}</b><span className="ml-1">{t("trainingRetentionPage.shares" as never)}</span></div><div className="sm:col-span-4 text-xs text-muted-foreground">{Object.entries(result.reason_counts).map(([key, value]) => `${key}: ${value}`).join(" · ")}</div></div>}
      </CardContent></Card>
    </div>
  );
}
