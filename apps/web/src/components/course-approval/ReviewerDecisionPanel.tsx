'use client';

import { useState } from 'react';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { submitReviewDecision, type ReviewActivityState } from '@/lib/courseApproval';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';

export function ReviewerDecisionPanel({ attemptId, activityState, token, onSubmitted }: { attemptId: string; activityState: ReviewActivityState; token?: string; onSubmitted?: () => void }) {
  const [reason, setReason] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const { t } = useT();
  const incomplete = activityState !== 'completed';
  async function submit(decision: 'approve' | 'return') {
    if (decision === 'return' && !reason.trim()) { toast.error(t('courseApproval.returnReason')); return; }
    if (decision === 'approve' && incomplete && !acknowledged) { toast.error(t('courseApproval.ackRequired')); return; }
    setBusy(true);
    try { await submitReviewDecision(attemptId, decision, decision === 'return' ? reason.trim() : null, acknowledged, token); toast.success(decision === 'approve' ? t('courseApproval.approve') : t('courseApproval.return')); onSubmitted?.(); }
    catch (error) { toast.error(t('courseApproval.errorLoad'), { description: error instanceof Error ? error.message : t('courseApproval.retry') }); }
    finally { setBusy(false); }
  }
  return <Card><CardContent className="space-y-4 p-5"><div><h2 className="text-lg font-semibold">{t('courseApproval.reviewDecision')}</h2><p className="mt-1 text-sm text-muted-foreground">{t('courseApproval.decisionHint')}</p></div>{incomplete && <label className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"><input type="checkbox" className="mt-1" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>{t('courseApproval.incompleteWarning')}</span></label>}<label className="block space-y-2 text-sm font-medium">{t('courseApproval.returnReason')}<Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t('courseApproval.returnPlaceholder')} /></label><div className="flex flex-col gap-2 sm:flex-row sm:justify-end"><Button variant="outline" onClick={() => void submit('return')} disabled={busy}>{t('courseApproval.return')}</Button><Button onClick={() => void submit('approve')} disabled={busy}>{t('courseApproval.approve')}</Button></div></CardContent></Card>;
}
