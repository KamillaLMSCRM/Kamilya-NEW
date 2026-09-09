'use client';

import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, LoaderCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui';
import { configureApprovalPolicy, getApprovalPolicy } from '@/lib/courseApproval';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';

export interface ApprovalPolicyCardProps {
  courseId: string;
  /** Legacy callers may pass this, but the server readback is authoritative. */
  initialRequiresApproval?: boolean;
  canConfigure?: boolean;
}

export function ApprovalPolicyCard({ courseId, canConfigure = true }: ApprovalPolicyCardProps) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);
  const generationRef = useRef(0);
  const { t } = useT();

  useEffect(() => {
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    setEnabled(null);
    setLoadError(false);
    setSaving(false);
    void getApprovalPolicy(courseId)
      .then((policy) => {
        if (generationRef.current === generation) setEnabled(policy.requires_approval);
      })
      .catch(() => {
        if (generationRef.current === generation) setLoadError(true);
      });
  }, [courseId, reload]);

  async function handleChange(next: boolean) {
    if (enabled === null || saving) return;
    const generation = generationRef.current;
    setSaving(true);
    try {
      const policy = await configureApprovalPolicy(courseId, next);
      if (generationRef.current !== generation) return;
      setEnabled(policy.requires_approval);
      toast.success(next ? t('courseApproval.policyLabel') : t('courseApproval.policyTitle'));
    } catch {
      if (generationRef.current !== generation) return;
      toast.error(t('courseApproval.errorLoad'));
    } finally {
      if (generationRef.current === generation) setSaving(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h2 className="text-base font-semibold">{t('courseApproval.policyTitle')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t('courseApproval.policyHint')}</p>
        </div>
        {enabled !== null ? (
          <label className="flex min-h-11 items-start gap-3 rounded-lg border p-3">
            <input type="checkbox" className="mt-1 h-4 w-4" checked={enabled} disabled={!canConfigure || saving} onChange={(event) => void handleChange(event.target.checked)} />
            <span className="min-w-0">
              <span className="block font-medium">{t('courseApproval.policyLabel')}</span>
              <span className="mt-1 block text-xs text-muted-foreground">{t('courseApproval.policySnapshot')}</span>
            </span>
            {saving && <LoaderCircle className="ml-auto mt-0.5 h-4 w-4 animate-spin" aria-label="Сохранение" />}
          </label>
        ) : loadError ? (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 p-3 text-xs text-destructive">
            <span>{t('courseApproval.errorLoad')}</span>
            <button type="button" className="font-medium underline" onClick={() => setReload((value) => value + 1)}>{t('common.retry')}</button>
          </div>
        ) : (
          <div role="status" className="flex items-center gap-2 rounded-lg border p-3 text-xs text-muted-foreground">
            <LoaderCircle className="h-4 w-4 animate-spin" aria-label="Сохранение" />
            {t('common.loading')}
          </div>
        )}
        {enabled === true && <p className="flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> {t('courseApproval.policyAllRequired')}</p>}
      </CardContent>
    </Card>
  );
}
