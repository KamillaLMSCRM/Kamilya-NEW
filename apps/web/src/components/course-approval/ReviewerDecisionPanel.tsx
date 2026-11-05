'use client';

import { useEffect, useRef, useState } from 'react';
import { Button, Modal } from '@/components/ui';
import { submitReviewDecision, type ApprovalOutcome, type ReviewActivityState } from '@/lib/courseApproval';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { workspaceCopy } from '@/features/learning-workspace/copy';
import { WorkspacePanel } from '@/features/workspace-design';

interface DecisionProps {
  attemptId: string;
  activityState: ReviewActivityState;
  token?: string;
  snapshotLabel?: string;
  requestOutcome?: ApprovalOutcome;
  onSubmitted?: () => void;
  onReload?: () => void;
}

/** A new actor/attempt/snapshot gets a fresh form, without placing a token in a React key. */
export function ReviewerDecisionPanel(props: DecisionProps) {
  const identity = useRef({ attemptId: props.attemptId, token: props.token, snapshot: props.snapshotLabel, outcome: props.requestOutcome, epoch: 0 });
  const old = identity.current;
  if (old.attemptId !== props.attemptId || old.token !== props.token || old.snapshot !== props.snapshotLabel || old.outcome !== props.requestOutcome) {
    identity.current = { attemptId: props.attemptId, token: props.token, snapshot: props.snapshotLabel, outcome: props.requestOutcome, epoch: old.epoch + 1 };
  }
  return <DecisionForm key={identity.current.epoch} {...props} />;
}

function DecisionForm({ attemptId, activityState, token, snapshotLabel, requestOutcome = 'pending', onSubmitted, onReload }: DecisionProps) {
  const [reason, setReason] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<{ decision: 'approve' | 'return'; reason: string | null; acknowledged: boolean } | null>(null);
  const alive = useRef(true);
  const submitting = useRef(false);
  const { t, lang } = useT();
  const m = workspaceCopy(lang);
  const incomplete = activityState !== 'completed' && activityState !== 'decision_pending';
  const closed = requestOutcome !== 'pending' || conflict;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  function prepare(decision: 'approve' | 'return') {
    if (closed || busy) return;
    if (decision === 'return' && !reason.trim()) { toast.error(t('courseApproval.returnReason')); return; }
    if (decision === 'approve' && incomplete && !acknowledged) { toast.error(t('courseApproval.ackRequired')); return; }
    setError('');
    setPending({ decision, reason: decision === 'return' ? reason.trim() : null, acknowledged });
  }

  async function submit() {
    if (!pending || closed || submitting.current || !alive.current) return;
    const candidate = pending;
    submitting.current = true;
    setBusy(true);
    try {
      await submitReviewDecision(attemptId, candidate.decision, candidate.reason, candidate.acknowledged, token);
      if (!alive.current) return;
      setPending(null);
      toast.success(candidate.decision === 'approve' ? t('courseApproval.approve') : t('courseApproval.return'));
      onSubmitted?.();
    } catch (cause) {
      if (!alive.current) return;
      const status = typeof cause === 'object' && cause !== null && 'response' in cause
        ? (cause as { response?: { status?: number } }).response?.status : undefined;
      const message = status === 409 ? m.decisionScopeChanged : cause instanceof Error ? cause.message : t('courseApproval.retry');
      setConflict(status === 409);
      setError(message);
      setPending(null);
      toast.error(t('courseApproval.errorLoad'), { description: message });
    } finally {
      submitting.current = false;
      if (alive.current) setBusy(false);
    }
  }

  return <>
    <WorkspacePanel title={t('courseApproval.reviewDecision')} description={m.reviewHint} bodyClassName="space-y-5">
      {snapshotLabel && <p className="break-all rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs text-muted-foreground">{m.snapshot}: {snapshotLabel}</p>}
      {closed && <p role="status" className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm">{conflict ? m.decisionScopeChanged : m.blockedDecision}</p>}
      {incomplete && <label className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm"><input type="checkbox" className="mt-1" checked={acknowledged} disabled={closed || busy} onChange={(event) => setAcknowledged(event.target.checked)} /><span>{t('courseApproval.incompleteWarning')}</span></label>}
      <div className="grid min-w-0 gap-4 md:grid-cols-[minmax(0,1fr)_240px]">
        <label className="block min-w-0 space-y-2 text-sm font-medium"><span>{t('courseApproval.returnReason')}</span><textarea rows={4} value={reason} disabled={closed || busy} onChange={(event) => setReason(event.target.value)} placeholder={t('courseApproval.returnPlaceholder')} className="w-full rounded-xl border border-input bg-background px-4 py-3 text-sm leading-6 outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50" /></label>
        <p className="self-start rounded-xl border border-border bg-muted/30 p-4 text-xs leading-6 text-muted-foreground">{m.returnReason}</p>
      </div>
      {error && <div role="alert" className="space-y-3 rounded-lg border border-destructive/30 p-3 text-sm text-destructive"><p>{error}</p>{onReload && <Button type="button" variant="outline" size="sm" onClick={onReload}>{m.retry}</Button>}</div>}
      <div className="flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:justify-end [&_button]:min-h-11 [&_button]:whitespace-normal"><Button type="button" variant="outline" onClick={() => prepare('return')} disabled={busy || closed || !reason.trim()}>{t('courseApproval.return')}</Button><Button type="button" onClick={() => prepare('approve')} disabled={busy || closed}>{t('courseApproval.approve')}</Button></div>
    </WorkspacePanel>
    <Modal open={pending !== null} onClose={() => { if (!busy) setPending(null); }} dismissable={!busy} title={m.decisionQuestion} description={m.decisionHint}>
      <dl className="space-y-3 text-sm"><div><dt className="text-muted-foreground">{m.attempt}</dt><dd className="break-all font-mono text-xs">{attemptId}</dd></div>{snapshotLabel && <div><dt className="text-muted-foreground">{m.snapshot}</dt><dd className="break-all font-mono text-xs">{snapshotLabel}</dd></div>}<div><dt className="text-muted-foreground">{t('courseApproval.reviewDecision')}</dt><dd className="font-semibold">{pending?.decision === 'return' ? t('courseApproval.return') : t('courseApproval.approve')}</dd></div>{pending?.reason && <div><dt className="text-muted-foreground">{t('courseApproval.returnReason')}</dt><dd className="whitespace-pre-wrap break-words">{pending.reason}</dd></div>}</dl>
      <div className="mt-6 flex flex-wrap justify-end gap-2"><Button type="button" variant="outline" onClick={() => setPending(null)} disabled={busy}>{t('common.cancel')}</Button><Button type="button" onClick={() => void submit()} disabled={busy}>{busy ? t('common.saving') : m.confirmDecision}</Button></div>
    </Modal>
  </>;
}
