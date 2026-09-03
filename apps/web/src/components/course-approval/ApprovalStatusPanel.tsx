'use client';

import { useState } from 'react';
import { Badge, Button, Card, CardContent, Modal } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { cancelApprovalRequest, resendApprovalDelivery, revokeApprovalAccess, type ApprovalRequestSummary, type ReviewerAccessSecret } from '@/lib/courseApproval';

const TRANSIENT_ERRORS = ['provider_timeout', 'provider_unreachable', 'provider_rate_limited', 'provider_unavailable'];
type ConfirmationKind = 'cancel' | 'rotate';

export function ApprovalStatusPanel({ requests, onRefresh }: { requests: ApprovalRequestSummary[]; onRefresh?: () => void }) {
  const { t } = useT();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ kind: ConfirmationKind; requestId: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [cancelledIds, setCancelledIds] = useState<Set<string>>(() => new Set());
  const [freshCredentials, setFreshCredentials] = useState<ReviewerAccessSecret[]>([]);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copyFailed, setCopyFailed] = useState(false);

  async function copySecret(value: string, key: string) {
    try {
      if (!navigator.clipboard) throw new Error('clipboard-unavailable');
      await navigator.clipboard.writeText(value);
      setCopiedKey(key);
      setCopyFailed(false);
    } catch {
      const area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', 'true');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try {
        if (!document.execCommand('copy')) throw new Error('copy-failed');
        setCopiedKey(key);
        setCopyFailed(false);
      } catch {
        setCopyFailed(true);
      } finally {
        document.body.removeChild(area);
      }
    }
  }

  async function action(requestId: string, kind: 'cancel' | 'revoke' | 'resend' | 'rotate') {
    setBusyId(requestId);
    setActionError(null);
    try {
      if (kind === 'cancel') {
        await cancelApprovalRequest(requestId);
        setCancelledIds((current) => new Set(current).add(requestId));
      } else if (kind === 'revoke') {
        await revokeApprovalAccess(requestId);
      } else {
        const result = await resendApprovalDelivery(requestId, kind === 'rotate');
        if (kind === 'rotate') setFreshCredentials(result.access_credentials);
      }
      setConfirm(null);
      onRefresh?.();
      toast.success(t(kind === 'cancel' ? 'courseApproval.cancelled' : kind === 'revoke' ? 'courseApproval.revoked' : kind === 'rotate' ? 'courseApproval.credentialsRotated' : 'courseApproval.deliveryRetried'));
    } catch (error) {
      const message = error instanceof Error ? error.message : t('courseApproval.errorLoad');
      setActionError(message);
      toast.error(t('courseApproval.errorLoad'), { description: message });
    } finally {
      setBusyId(null);
    }
  }

  function requestConfirmation(kind: ConfirmationKind, requestId: string) {
    setActionError(null);
    setConfirm({ kind, requestId });
  }

  if (requests.length === 0) return <Card><CardContent className="p-5 text-sm text-muted-foreground">{t('courseApproval.noActiveRequests')}</CardContent></Card>;
  const confirmedRequest = confirm ? requests.find((request) => request.request_id === confirm.requestId) : undefined;

  return <>
    {confirm && confirmedRequest && <Modal open onClose={() => { if (!busyId) { setConfirm(null); setActionError(null); } }} title={confirm.kind === 'cancel' ? t('courseApproval.cancelConfirmTitle') : t('courseApproval.rotateCredentials')} description={confirm.kind === 'cancel' ? t('courseApproval.cancelConfirmDescription') : t('courseApproval.rotateConfirm')} dismissable={false} closeOnBackdrop={false}>
      <div className="space-y-4">
        {actionError && <p role="alert" className="break-words rounded border border-destructive/40 p-3 text-sm text-destructive">{actionError}</p>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={() => { setConfirm(null); setActionError(null); }} disabled={busyId === confirm.requestId}>{t('courseApproval.cancel')}</Button>
          <Button type="button" onClick={() => void action(confirm.requestId, confirm.kind)} disabled={busyId === confirm.requestId}>{busyId === confirm.requestId ? t('courseApproval.sending') : confirm.kind === 'cancel' ? t('courseApproval.confirmCancel') : t('courseApproval.confirmRotate')}</Button>
        </div>
      </div>
    </Modal>}
    <Modal open={freshCredentials.length > 0} onClose={() => { setFreshCredentials([]); setCopiedKey(null); setCopyFailed(false); }} title={t('courseApproval.credentialsTitle')} description={t('courseApproval.credentialsWarning')} dismissable={false} closeOnBackdrop={false}>
      <section aria-label={t('courseApproval.credentialsTitle')} className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm">
        <p className="font-semibold">{t('courseApproval.credentialsOneTime')}</p>
        {freshCredentials.map((credential) => <div key={credential.reviewer_id} className="space-y-2 rounded border bg-background p-3">
          <div className="flex flex-wrap items-center gap-2"><code className="min-w-0 flex-1 break-all text-xs">{credential.access_url}</code><Button type="button" size="sm" variant="outline" onClick={() => void copySecret(credential.access_url, `${credential.reviewer_id}:url`)}>{t('courseApproval.copyUrl')}</Button></div>
          <div className="flex flex-wrap items-center gap-2"><code className="break-all font-mono">{credential.temporary_pin}</code><Button type="button" size="sm" variant="outline" onClick={() => void copySecret(credential.temporary_pin, `${credential.reviewer_id}:pin`)}>{t('courseApproval.copyPin')}</Button></div>
          {copiedKey?.startsWith(`${credential.reviewer_id}:`) && <span role="status" className="break-words text-xs text-emerald-700">{t('courseApproval.copied')}</span>}
        </div>)}
        {copyFailed && <p role="alert" className="break-words text-xs text-destructive">{t('courseApproval.copyFailed')}</p>}
        <Button type="button" className="w-full" onClick={() => { setFreshCredentials([]); setCopiedKey(null); setCopyFailed(false); }}>{t('courseApproval.credentialsAcknowledge')}</Button>
      </section>
    </Modal>
    <div className="space-y-3">
      {requests.map((request) => {
        const rows = request.work_items || request.reviewers || [];
        const effectiveOutcome = cancelledIds.has(request.request_id) ? 'cancelled' : request.outcome;
        const retryable = request.deliveries?.some((delivery) => delivery.status === 'failed' && TRANSIENT_ERRORS.includes(delivery.error_category || ''));
        return <Card key={request.request_id}><CardContent className="space-y-3 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold">{t('courseApproval.request')} {request.request_id.slice(0, 8)}</h3><p className="break-all text-xs text-muted-foreground">{t('courseApproval.revision')} {request.revision_number ? `#${request.revision_number}` : request.revision_id}{request.snapshot_sha256 ? ` · SHA-256 ${request.snapshot_sha256}` : ''}</p></div><Badge variant={effectiveOutcome === 'approved' ? 'default' : 'outline'}>{effectiveOutcome === 'changes_requested' ? t('courseApproval.changesRequested') : effectiveOutcome === 'approved' ? t('courseApproval.approved') : effectiveOutcome === 'cancelled' ? t('courseApproval.cancelled') : t('courseApproval.pending')}</Badge></div>
          <div className="grid gap-2 text-sm sm:grid-cols-3"><span>{t('courseApproval.delivery')}: {request.delivery_mode === 'email' ? t('courseApproval.email') : t('courseApproval.personalLink')}</span><span>{t('courseApproval.reviewerCount')}: {request.reviewer_ids?.length ?? request.reviewer_count ?? rows.length}</span><span>{t('courseApproval.deadline')}: {request.due_at ? new Date(request.due_at).toLocaleString() : t('courseApproval.notSet')}</span>{request.all_required_approved !== undefined && <span>{request.all_required_approved ? t('courseApproval.allRequiredApproved') : t('courseApproval.allRequiredPending')}</span>}</div>
          {rows.length > 0 && <div className="overflow-x-auto rounded border"><table className="min-w-[620px] w-full text-left text-xs"><caption className="sr-only">{t('courseApproval.reviewerStatus')}</caption><thead><tr className="border-b text-muted-foreground"><th className="p-2">{t('courseApproval.reviewer')}</th><th className="p-2">{t('courseApproval.delivery')}</th><th className="p-2">{t('courseApproval.access')}</th><th className="p-2">{t('courseApproval.activity')}</th><th className="p-2">{t('courseApproval.progress')}</th><th className="p-2">{t('courseApproval.outcome')}</th></tr></thead><tbody>{rows.map((reviewer) => <tr key={reviewer.reviewer_id || reviewer.id || reviewer.decision_at} className="border-b last:border-0"><td className="p-2 break-all">{reviewer.reviewer_id || reviewer.id || '—'}</td><td className="p-2">{reviewer.delivery_state || request.deliveries?.[0]?.status || '—'}</td><td className="p-2">{reviewer.access_state || '—'}</td><td className="p-2">{reviewer.activity_state || '—'}</td><td className="p-2">{reviewer.progress == null ? '—' : `${reviewer.progress}%`} · {reviewer.deadline_state || '—'}</td><td className="p-2">{reviewer.outcome || reviewer.decision || t('courseApproval.pending')}</td></tr>)}</tbody></table></div>}
          <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={busyId === request.request_id || effectiveOutcome !== 'pending'} onClick={() => requestConfirmation('cancel', request.request_id)}>{t('courseApproval.cancelRequest')}</Button><Button type="button" size="sm" variant="outline" disabled={busyId === request.request_id || !retryable} onClick={() => void action(request.request_id, 'resend')}>{t('courseApproval.retryDelivery')}</Button><Button type="button" size="sm" variant="outline" disabled={busyId === request.request_id || effectiveOutcome === 'cancelled'} onClick={() => requestConfirmation('rotate', request.request_id)}>{t('courseApproval.rotateCredentials')}</Button><Button type="button" size="sm" variant="outline" disabled={busyId === request.request_id || effectiveOutcome === 'cancelled'} onClick={() => void action(request.request_id, 'revoke')}>{t('courseApproval.revoke')}</Button></div>
        </CardContent></Card>;
      })}
    </div>
  </>;
}
