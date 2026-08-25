"use client";

import { useCallback, useEffect, useState } from "react";
import { DatabaseZap, LockKeyhole } from "lucide-react";

import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
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

export default function TrainingRetentionPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role ?? "");
  const [items, setItems] = useState<RetentionPolicy[]>([]);
  const [loading, setLoading] = useState(true);

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

  if (role !== "methodologist") {
    return <Card><CardContent className="p-6"><h1 className="text-lg font-semibold">{t("trainingRetentionPage.accessDenied" as never)}</h1></CardContent></Card>;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header className="min-w-0">
        <h1 className="flex items-center gap-2 text-2xl font-semibold"><DatabaseZap className="h-6 w-6 shrink-0" aria-hidden="true" />{t("trainingRetentionPage.title" as never)}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t("trainingRetentionPage.subtitle" as never)}</p>
      </header>

      <div className="flex min-w-0 gap-3 border-l-4 border-primary bg-primary/5 px-4 py-3 text-sm" role="note">
        <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <p className="min-w-0">{t("trainingRetentionPage.readOnlyNotice" as never)}</p>
      </div>

      <Card className="min-w-0 overflow-hidden">
        <CardHeader><CardTitle className="text-base">{t("trainingRetentionPage.policies" as never)}</CardTitle></CardHeader>
        <CardContent className="p-0">
          {loading ? <p className="p-6 text-sm text-muted-foreground">{t("common.loading" as never)}</p> : items.length === 0 ? <p className="p-6 text-sm text-muted-foreground">{t("trainingRetentionPage.empty" as never)}</p> : <ul className="divide-y divide-border">{items.map((item) => {
            const years = item.retention_days % 365 === 0 ? item.retention_days / 365 : null;
            return <li key={item.id} className="min-w-0 p-5">
              <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{t(`trainingRetentionPage.types.${item.procedure_type}` as never)}</span>
                    <Badge variant={item.active ? "default" : "secondary"}>{item.active ? t("trainingRetentionPage.active" as never) : t("trainingRetentionPage.inactive" as never)}</Badge>
                  </div>
                  <p className="mt-2 text-lg font-semibold">{item.retention_days} {t("trainingRetentionPage.dayShort" as never)}{years ? <> · {years} {t("trainingRetentionPage.yearShort" as never)}</> : null}</p>
                  {(item.legal_basis || item.local_basis) && <p className="mt-2 break-words text-sm text-muted-foreground"><span className="font-medium text-foreground">{t("trainingRetentionPage.basis" as never)}:</span> {item.legal_basis || item.local_basis}</p>}
                </div>
              </div>
            </li>;
          })}</ul>}
        </CardContent>
      </Card>
    </div>
  );
}
