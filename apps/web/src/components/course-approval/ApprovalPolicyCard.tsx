'use client';

import { useState } from 'react';
import { CheckCircle2, LoaderCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui';
import { configureApprovalPolicy } from '@/lib/courseApproval';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';

export interface ApprovalPolicyCardProps {
  courseId: string;
  initialRequiresApproval?: boolean;
  canConfigure?: boolean;
}

export function ApprovalPolicyCard({ courseId, initialRequiresApproval = false, canConfigure = true }: ApprovalPolicyCardProps) {
  const [enabled, setEnabled] = useState(initialRequiresApproval);
  const [saving, setSaving] = useState(false);
  const { t } = useT();

  async function handleChange(next: boolean) {
    setSaving(true);
    try {
      const policy = await configureApprovalPolicy(courseId, next);
      setEnabled(policy.requires_approval);
      toast.success(next ? t('courseApproval.policyLabel') : t('courseApproval.policyTitle'));
    } catch {
      toast.error(t('courseApproval.errorLoad'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h2 className="text-base font-semibold">{t('courseApproval.policyTitle')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t('courseApproval.policyHint')}</p>
        </div>
        <label className="flex min-h-11 items-start gap-3 rounded-lg border p-3">
          <input type="checkbox" className="mt-1 h-4 w-4" checked={enabled} disabled={!canConfigure || saving} onChange={(event) => void handleChange(event.target.checked)} />
          <span className="min-w-0">
            <span className="block font-medium">{t('courseApproval.policyLabel')}</span>
            <span className="mt-1 block text-xs text-muted-foreground">{t('courseApproval.policySnapshot')}</span>
          </span>
          {saving && <LoaderCircle className="ml-auto mt-0.5 h-4 w-4 animate-spin" aria-label="Сохранение" />}
        </label>
        {enabled && <p className="flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> {t('courseApproval.policyAllRequired')}</p>}
      </CardContent>
    </Card>
  );
}
