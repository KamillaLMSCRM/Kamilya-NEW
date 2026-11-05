'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock3, Download, Mail, RefreshCw, ShieldCheck, Upload } from 'lucide-react';
import { Button, Input } from '@/components/ui';
import { api } from '@/lib/api';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { getLearnerWorkspaceCopy } from '@/features/learner-workspace/copy';
import { useLanguageStore } from '@/store/languageStore';
import { WorkspacePanel } from '@/features/workspace-design';

export interface LearnerEvidenceEvent {
  id: string;
  enrollment_id: string | null;
  content_release_id: string | null;
  procedure_type: string;
  record_type: string;
  related_event_id: string | null;
  occurred_at: string;
  created_at: string;
  confirmation_status: 'not_required' | 'pending' | 'confirmed';
  // Keep fields nullable because the API deliberately allows absent release metadata.
  procedure_title?: string | null;
  release_version?: number | null;
  release_sha256?: string | null;
  confirmation_statement?: string | null;
  confirmation_object_version?: string | null;
}

interface LearnerSignedCopyLedger {
  status: 'awaiting_return' | 'uploaded_pending_review' | 'accepted' | 'replacement_requested';
  scans: Array<{
    id: string;
    original_filename: string;
    status: 'uploaded_pending_review' | 'accepted' | 'replacement_requested';
    latest_review_reason?: string | null;
  }>;
}

const MAX_SIGNED_COPY_BYTES = 10 * 1024 * 1024;
const SIGNED_COPY_TYPES = new Set(['application/pdf', 'image/jpeg', 'image/png']);

interface EvidenceConfirmationPanelProps {
  eventId: string;
  activityTitle: string;
  activityKind: 'course' | 'quiz';
  continueHref?: string;
  continueLabel?: string;
  resultHref?: string;
  resultLabel?: string;
  onConfirmed?: () => void;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('ru-RU');
}

function procedureLabel(type: string, activityKind: EvidenceConfirmationPanelProps['activityKind'], t: ReturnType<typeof useT>['t']) {
  if (type === 'knowledge_check' || activityKind === 'quiz') return t('evidenceConfirmation.procedureQuiz');
  if (type === 'training' || activityKind === 'course') return t('evidenceConfirmation.procedureCourse');
  return type;
}

export function EvidenceConfirmationPanel(props: EvidenceConfirmationPanelProps) {
  const actor = useAuthStore((state) => state.user);
  const token = useAuthStore((state) => state.accessToken);
  const sessionEpoch = useAuthStore((state) => state.sessionEpoch);
  const scope = JSON.stringify([props.eventId, props.activityKind, actor?.user_id, actor?.tenant_id, actor?.role,
    actor?.impersonated_by, actor?.impersonated_role, Boolean(token), sessionEpoch]);
  return <ScopedEvidenceConfirmationPanel key={scope} {...props} />;
}

function ScopedEvidenceConfirmationPanel({
  eventId,
  activityTitle,
  activityKind,
  continueHref,
  continueLabel,
  resultHref,
  resultLabel,
  onConfirmed,
}: EvidenceConfirmationPanelProps) {
  const { t } = useT();
  const lang = useLanguageStore((state) => state.lang);
  const m = getLearnerWorkspaceCopy(lang);
  const learnerEmail = useAuthStore((state) => state.user?.email ?? null);
  const [event, setEvent] = useState<LearnerEvidenceEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [retryAfter, setRetryAfter] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [downloading, setDownloading] = useState(false);
  const [signedCopyLedger, setSignedCopyLedger] = useState<LearnerSignedCopyLedger | null>(null);
  const [signedCopyLoading, setSignedCopyLoading] = useState(false);
  const [signedCopyUploading, setSignedCopyUploading] = useState(false);
  const [signedCopyError, setSignedCopyError] = useState<string | null>(null);

  const loadSignedCopies = useCallback(async () => {
    if (activityKind !== 'course') return;
    setSignedCopyLoading(true);
    setSignedCopyError(null);
    try {
      const response = await api.get<LearnerSignedCopyLedger>(
        `/v1/training-evidence/events/mine/${eventId}/signed-scans`,
      );
      if (!alive.current) return;
      setSignedCopyLedger(response.data);
    } catch (requestError: any) {
      if (!alive.current) return;
      setSignedCopyError(requestError?.response?.data?.message || t('evidenceConfirmation.signedCopyLoadFailed'));
    } finally {
      if (alive.current) setSignedCopyLoading(false);
    }
  }, [activityKind, eventId, t]);

  const loadEvent = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get<LearnerEvidenceEvent>(`/v1/training-evidence/events/mine/${eventId}`);
      if (!alive.current) return;
      if (response.data.id !== eventId
        || response.data.procedure_type !== (activityKind === 'quiz' ? 'knowledge_check' : 'training')
        || !['pending', 'confirmed', 'not_required'].includes(response.data.confirmation_status)) throw new Error(t('evidenceConfirmation.errors.load'));
      setEvent(response.data);
      setConfirmed(response.data.confirmation_status === 'confirmed');
    } catch (requestError: any) {
      if (!alive.current) return;
      setError(requestError?.response?.data?.message || t('evidenceConfirmation.errors.load'));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [eventId, activityKind, t]);

  useEffect(() => {
    void loadEvent();
  }, [loadEvent]);

  useEffect(() => {
    void loadSignedCopies();
  }, [loadSignedCopies]);

  const uploadSignedCopy = async (file: File) => {
    if (!alive.current || signedCopyUploading) return;
    if (!SIGNED_COPY_TYPES.has(file.type) || file.size <= 0 || file.size > MAX_SIGNED_COPY_BYTES) {
      setSignedCopyError(t('evidenceConfirmation.signedCopyInvalid'));
      return;
    }
    setSignedCopyUploading(true);
    setSignedCopyError(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      await api.post(`/v1/training-evidence/events/mine/${eventId}/signed-scans`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (!alive.current) return;
      await loadSignedCopies();
    } catch (requestError: any) {
      if (!alive.current) return;
      setSignedCopyError(requestError?.response?.data?.message || t('evidenceConfirmation.signedCopyUploadFailed'));
    } finally {
      if (alive.current) setSignedCopyUploading(false);
    }
  };

  const requestCode = async () => {
    if (!alive.current || requesting || event?.confirmation_status !== 'pending') return;
    setRequesting(true);
    setError(null);
    try {
      const response = await api.post<{ challenge_id: string; expires_in: number; retry_after?: number | null }>(
        `/v1/training-evidence/step-up/events/${eventId}/request`,
        {},
      );
      if (!alive.current) return;
      setChallengeId(response.data.challenge_id);
      setRetryAfter(response.data.retry_after ?? null);
    } catch (requestError: any) {
      if (!alive.current) return;
      setError(requestError?.response?.data?.message || t('evidenceConfirmation.errors.request'));
    } finally {
      if (alive.current) setRequesting(false);
    }
  };

  const verifyCode = async () => {
    if (!alive.current || verifying || event?.confirmation_status !== 'pending' || !challengeId || !/^\d{6}$/.test(code)) return;
    setVerifying(true);
    setError(null);
    try {
      await api.post(`/v1/training-evidence/step-up/events/${eventId}/verify`, {
        challenge_id: challengeId,
        code,
      });
      if (!alive.current) return;
      setConfirmed(true);
      setChallengeId(null);
      setCode('');
      await loadEvent();
      if (!alive.current) return;
      onConfirmed?.();
    } catch (requestError: any) {
      if (!alive.current) return;
      setError(requestError?.response?.data?.message || t('evidenceConfirmation.errors.verify'));
    } finally {
      if (alive.current) setVerifying(false);
    }
  };

  const downloadEvidence = async () => {
    setDownloading(true);
    setError(null);
    try {
      const response = await api.get<Blob>(
        `/v1/training-evidence/events/mine/${eventId}/export`,
        { params: { format: 'pdf' }, responseType: 'blob' },
      );
      if (!alive.current) return;
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `kamilya-training-evidence-${eventId}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (requestError: any) {
      if (!alive.current) return;
      setError(requestError?.response?.data?.message || t('evidenceConfirmation.downloadFailed'));
    } finally {
      if (alive.current) setDownloading(false);
    }
  };

  const title = event?.procedure_title || activityTitle;
  const statement = event?.confirmation_statement;
  const version = event?.release_version ?? event?.confirmation_object_version;
  const notRequired = event?.confirmation_status === 'not_required';
  const statusText = notRequired ? m.confirmationNotRequired : confirmed
    ? t('evidenceConfirmation.status.confirmed')
    : t('evidenceConfirmation.status.pending');

  const actionButtons = useMemo(() => (
    <div className="flex flex-wrap gap-2">
      {continueHref && (
        <a href={continueHref}>
          <Button type="button">{continueLabel || t('evidenceConfirmation.continue')}</Button>
        </a>
      )}
      {resultHref && (
        <a href={resultHref}>
          <Button type="button" variant="outline">{resultLabel || t('evidenceConfirmation.result')}</Button>
        </a>
      )}
    </div>
  ), [continueHref, continueLabel, resultHref, resultLabel, t]);

  if (loading) {
    return (
      <WorkspacePanel aria-busy="true" bodyClassName="flex items-center gap-3 text-sm text-muted-foreground" role="status">
          <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t('evidenceConfirmation.loading')}
      </WorkspacePanel>
    );
  }

  if (error && !event) {
    return (
      <WorkspacePanel className="border-destructive/30" bodyClassName="space-y-4">
          <div className="flex items-start gap-3 text-sm text-destructive" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
          <Button type="button" variant="outline" onClick={() => void loadEvent()}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            {t('common.retry')}
          </Button>
      </WorkspacePanel>
    );
  }

  return (
    <WorkspacePanel className={confirmed ? 'border-success/40' : 'border-primary/30'}
      title={<span className="flex items-start gap-3"><span className="rounded-xl bg-primary/10 p-2 text-primary" aria-hidden="true">{confirmed ? <CheckCircle2 className="h-5 w-5 text-success" /> : <ShieldCheck className="h-5 w-5" />}</span><span className="min-w-0 break-words pt-1">{notRequired ? m.confirmationNotRequired : t('evidenceConfirmation.title')}</span></span>}
      description={notRequired ? m.noConfirmationHint : confirmed ? t('evidenceConfirmation.status.confirmed') : t('evidenceConfirmation.subtitle')}
      bodyClassName="space-y-6 [&_button]:h-auto [&_button]:min-h-11 [&_button]:py-2 [&_button]:whitespace-normal">
        <dl className="grid gap-5 rounded-xl border border-border bg-muted/20 p-4 text-sm sm:grid-cols-2 sm:p-5">
          <div>
            <dt className="text-muted-foreground">{t('evidenceConfirmation.activity')}</dt>
             <dd className="mt-1 break-words font-medium text-foreground">{title}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t('evidenceConfirmation.procedure')}</dt>
            <dd className="mt-1 font-medium text-foreground">{procedureLabel(event?.procedure_type || '', activityKind, t)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t('evidenceConfirmation.date')}</dt>
            <dd className="mt-1 font-medium text-foreground">{event ? formatDate(event.occurred_at) : '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t('evidenceConfirmation.release')}</dt>
            <dd className="mt-1 break-all font-mono text-xs text-foreground">
              {version || event?.content_release_id || t('evidenceConfirmation.releaseUnavailable')}
            </dd>
          </div>
          {event?.release_sha256 && (
            <div className="sm:col-span-2">
              <dt className="text-muted-foreground">{t('evidenceConfirmation.releaseHash')}</dt>
              <dd className="mt-1 break-all font-mono text-xs text-foreground">{event.release_sha256}</dd>
            </div>
          )}
        </dl>

        {notRequired ? <p className="text-sm text-muted-foreground">{m.noConfirmationHint}</p> : statement ? (
          <div className="rounded-md border border-border bg-muted/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t('evidenceConfirmation.statement')}</p>
            <p className="mt-2 text-sm leading-6 text-foreground">{statement}</p>
          </div>
        ) : (
          <div className="rounded-md border border-warning/30 bg-warning/10 p-4 text-sm text-foreground">
            {t('evidenceConfirmation.statementUnavailable')}
          </div>
        )}

        <div className="flex items-center gap-2 text-sm" role="status">
          {confirmed || notRequired ? <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" /> : <Clock3 className="h-4 w-4 text-warning" aria-hidden="true" />}
          <span className={confirmed ? 'text-success' : 'text-muted-foreground'}>{statusText}</span>
        </div>

        <div className="grid min-w-0 items-start gap-4 xl:grid-cols-2">
        <section className="rounded-xl border border-border p-5">
          <p className="text-sm text-muted-foreground">
            {t('evidenceConfirmation.pdfDescription')}
          </p>
          <Button
            className="mt-3"
            type="button"
            variant="outline"
            onClick={() => void downloadEvidence()}
            disabled={downloading}
          >
            <Download className="mr-2 h-4 w-4" aria-hidden="true" />
            {downloading ? t('evidenceConfirmation.downloadingPdf') : t('evidenceConfirmation.downloadPdf')}
          </Button>
        </section>

        {activityKind === 'course' && (
          <section className="min-w-0 space-y-3 rounded-xl border border-border p-5">
            <div>
              <p className="text-sm font-medium text-foreground">{t('evidenceConfirmation.signedCopy')}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {t('evidenceConfirmation.signedCopyHint')}
              </p>
            </div>
            <div className="text-sm" role="status">
              {signedCopyLoading && !signedCopyLedger
                ? t('evidenceConfirmation.signedCopyLoading')
                : signedCopyLedger?.status === 'accepted'
                  ? t('evidenceConfirmation.signedCopyAccepted')
                  : signedCopyLedger?.status === 'uploaded_pending_review'
                    ? t('evidenceConfirmation.signedCopyPending')
                    : signedCopyLedger?.status === 'replacement_requested'
                      ? t('evidenceConfirmation.signedCopyReplace', { reason: signedCopyLedger.scans.at(-1)?.latest_review_reason || t('evidenceConfirmation.signedCopyReason') })
                      : t('evidenceConfirmation.signedCopyMissing')}
            </div>
            <label className="inline-flex min-h-11 cursor-pointer items-center rounded-xl border border-input px-3 py-2 text-sm font-medium hover:bg-accent focus-within:ring-2 focus-within:ring-ring">
              {signedCopyUploading ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
              {signedCopyUploading ? t('evidenceConfirmation.signedCopyUploading') : t('evidenceConfirmation.signedCopyUpload')}
              <input
                type="file"
                className="sr-only"
                accept="application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png"
                disabled={signedCopyUploading}
                onChange={(uploadEvent) => {
                  const file = uploadEvent.target.files?.[0];
                  uploadEvent.target.value = '';
                  if (file) void uploadSignedCopy(file);
                }}
              />
            </label>
            <p className="text-xs text-muted-foreground">{t('evidenceConfirmation.signedCopyFormats')}</p>
            {signedCopyError && <p className="text-sm text-destructive" role="alert">{signedCopyError}</p>}
          </section>
        )}
        </div>

        {error && (confirmed || notRequired || !learnerEmail) && <p className="text-sm text-destructive" role="alert">{error}</p>}

        {!confirmed && !notRequired && learnerEmail && (
          <section className="min-w-0 space-y-4 rounded-xl border border-primary/25 bg-primary/5 p-5 sm:p-6">
            <p className="text-sm text-muted-foreground">{t('evidenceConfirmation.explanation')}</p>
            {!challengeId ? (
              <Button type="button" onClick={() => void requestCode()} disabled={requesting || retryAfter !== null}>
                <Mail className="mr-2 h-4 w-4" aria-hidden="true" />
                {requesting ? t('evidenceConfirmation.requesting') : t('evidenceConfirmation.requestCode')}
              </Button>
            ) : (
              <div className="space-y-3">
                <label htmlFor={`evidence-code-${eventId}`} className="block text-sm font-medium text-foreground">
                  {t('evidenceConfirmation.codeLabel')}
                </label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Input
                    id={`evidence-code-${eventId}`}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    pattern="[0-9]{6}"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                    aria-describedby={`evidence-code-help-${eventId}`}
                    className="max-w-xs font-mono text-lg tracking-[0.3em]"
                  />
                  <Button type="button" onClick={() => void verifyCode()} disabled={verifying || code.length !== 6}>
                    {verifying ? t('evidenceConfirmation.verifying') : t('evidenceConfirmation.confirm')}
                  </Button>
                </div>
                <p id={`evidence-code-help-${eventId}`} className="text-xs text-muted-foreground">
                  {t('evidenceConfirmation.codeHelp')}
                </p>
              </div>
            )}
            {retryAfter !== null && <p className="text-xs text-muted-foreground">{t('evidenceConfirmation.retryAfter', { seconds: retryAfter })}</p>}
            {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          </section>
        )}

        {!confirmed && !notRequired && !learnerEmail && (
          <div className="rounded-md border border-border p-4 text-sm text-muted-foreground">
            {t('evidenceConfirmation.noEmailFallback')}
          </div>
        )}

        {(continueHref || resultHref) && <footer className="border-t border-border pt-5 [&_button]:min-h-11 [&_button]:whitespace-normal">{actionButtons}</footer>}
    </WorkspacePanel>
  );
}
