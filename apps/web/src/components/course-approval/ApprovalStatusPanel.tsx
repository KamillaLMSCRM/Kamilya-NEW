'use client';

import { useState } from 'react';
import { Badge, Button, Card, CardContent } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { cancelApprovalRequest, resendApprovalDelivery, revokeApprovalAccess, type ApprovalRequestSummary, type ReviewerAccessSecret } from '@/lib/courseApproval';

const TRANSIENT_ERRORS = ['provider_timeout', 'provider_unreachable', 'provider_rate_limited', 'provider_unavailable'];

export function ApprovalStatusPanel({ requests, onRefresh }: { requests: ApprovalRequestSummary[]; onRefresh?: () => void }) {
  const { t } = useT();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rotationId, setRotationId] = useState<string | null>(null);
  const [freshCredentials, setFreshCredentials] = useState<ReviewerAccessSecret[]>([]);

  async function action(requestId: string, kind: 'cancel' | 'revoke' | 'resend' | 'rotate') {
    setBusyId(requestId);
    try {
      if (kind === 'cancel') await cancelApprovalRequest(requestId);
      else if (kind === 'revoke') await revokeApprovalAccess(requestId);
      else {
        const result = await resendApprovalDelivery(requestId, kind === 'rotate');
        if (kind === 'rotate') setFreshCredentials(result.access_credentials);
      }
      onRefresh?.();
      toast.success(t(kind === 'cancel' ? 'courseApproval.cancelled' : kind === 'revoke' ? 'courseApproval.revoked' : kind === 'rotate' ? 'courseApproval.credentialsRotated' : 'courseApproval.deliveryRetried'));
    } catch { toast.error(t('courseApproval.errorLoad')); }
    finally { setBusyId(null); }
  }

  if (requests.length === 0) return <Card><CardContent className="p-5 text-sm text-muted-foreground">{t('courseApproval.noActiveRequests')}</CardContent></Card>;
  return <div className="space-y-3">
    {freshCredentials.length > 0 && <Card><CardContent className="space-y-2 p-4 text-sm"><p className="font-semibold">{t('courseApproval.credentialsRotated')}</p>{freshCredentials.map((credential) => <p key={credential.reviewer_id} className="break-all font-mono text-xs">{credential.access_url} · PIN: {credential.temporary_pin}</p>)}</CardContent></Card>}
    {requests.map((request) => {
      const rows = request.work_items || request.reviewers || [];
      const retryable = request.deliveries?.some((delivery) => delivery.status === 'failed' && TRANSIENT_ERRORS.includes(delivery.error_category || ''));
      return <Card key={request.request_id}><CardContent className="space-y-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold">{t('courseApproval.request')} {request.request_id.slice(0, 8)}</h3><p className="break-all text-xs text-muted-foreground">{t('courseApproval.revision')} {request.revision_number ? `#${request.revision_number}` : request.revision_id}{request.snapshot_sha256 ? ` · SHA-256 ${request.snapshot_sha256}` : ''}</p></div><Badge variant={request.outcome === 'approved' ? 'default' : 'outline'}>{request.outcome === 'changes_requested' ? t('courseApproval.changesRequested') : request.outcome === 'approved' ? t('courseApproval.approved') : request.outcome === 'cancelled' ? t('courseApproval.cancelled') : t('courseApproval.pending')}</Badge></div>
        <div className="grid gap-2 text-sm sm:grid-cols-3"><span>{t('courseApproval.delivery')}: {request.delivery_mode === 'email' ? t('courseApproval.email') : t('courseApproval.personalLink')}</span><span>{t('courseApproval.reviewerCount')}: {request.reviewer_ids?.length ?? request.reviewer_count ?? rows.length}</span><span>{t('courseApproval.deadline')}: {request.due_at ? new Date(request.due_at).toLocaleString() : t('courseApproval.notSet')}</span>{request.all_required_approved !== undefined && <span>{request.all_required_approved ? t('courseApproval.allRequiredApproved') : t('courseApproval.allRequiredPending')}</span>}</div>
        {rows.length > 0 && <div className="overflow-x-auto rounded border"><table className="min-w-[620px] w-full text-left text-xs"><caption className="sr-only">{t('courseApproval.reviewerStatus')}</caption><thead><tr className="border-b text-muted-foreground"><th className="p-2">{t('courseApproval.reviewer')}</th><th className="p-2">{t('courseApproval.delivery')}</th><th className="p-2">{t('courseApproval.access')}</th><th className="p-2">{t('courseApproval.activity')}</th><th className="p-2">{t('courseApproval.progress')}</th><th className="p-2">{t('courseApproval.outcome')}</th></tr></thead><tbody>{rows.map((reviewer) => <tr key={reviewer.reviewer_id || reviewer.id || reviewer.decision_at} className="border-b last:border-0"><td className="p-2 break-all">{reviewer.reviewer_id || reviewer.id || '—'}</td><td className="p-2">{reviewer.delivery_state || request.deliveries?.[0]?.status || '—'}</td><td className="p-2">{reviewer.access_state || '—'}</td><td className="p-2">{reviewer.activity_state || '—'}</td><td className="p-2">{reviewer.progress == null ? '—' : `${reviewer.progress}%`} · {reviewer.deadline_state || '—'}</td><td className="p-2">{reviewer.outcome || reviewer.decision || t('courseApproval.pending')}</td></tr>)}</tbody></table></div>}
        <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busyId === request.request_id || request.outcome !== 'pending'} onClick={() => void action(request.request_id, 'cancel')}>{t('courseApproval.cancelRequest')}</Button><Button size="sm" variant="outline" disabled={busyId === request.request_id || !retryable} onClick={() => void action(request.request_id, 'resend')}>{t('courseApproval.retryDelivery')}</Button><Button size="sm" variant="outline" disabled={busyId === request.request_id} onClick={() => { if (typeof window === 'undefined' || window.confirm(t('courseApproval.rotateConfirm'))) { setRotationId(request.request_id); void action(request.request_id, 'rotate').finally(() => setRotationId(null)); } }}>{rotationId === request.request_id ? t('courseApproval.sending') : t('courseApproval.rotateCredentials')}</Button><Button size="sm" variant="outline" disabled={busyId === request.request_id} onClick={() => void action(request.request_id, 'revoke')}>{t('courseApproval.revoke')}</Button></div>
      </CardContent></Card>;
    })}
  </div>;
}
