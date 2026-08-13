'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock3, Download, Mail, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { api } from '@/lib/api';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';

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

export function EvidenceConfirmationPanel({
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
  const [downloading, setDownloading] = useState(false);

  const loadEvent = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get<LearnerEvidenceEvent>(`/v1/training-evidence/events/mine/${eventId}`);
      setEvent(response.data);
      setConfirmed(response.data.confirmation_status === 'confirmed');
    } catch (requestError: any) {
      setError(requestError?.response?.data?.message || t('evidenceConfirmation.errors.load'));
    } finally {
      setLoading(false);
    }
  }, [eventId, t]);

  useEffect(() => {
    void loadEvent();
  }, [loadEvent]);

  const requestCode = async () => {
    setRequesting(true);
    setError(null);
    try {
      const response = await api.post<{ challenge_id: string; expires_in: number; retry_after?: number | null }>(
        `/v1/training-evidence/step-up/events/${eventId}/request`,
        {},
      );
      setChallengeId(response.data.challenge_id);
      setRetryAfter(response.data.retry_after ?? null);
    } catch (requestError: any) {
      setError(requestError?.response?.data?.message || t('evidenceConfirmation.errors.request'));
    } finally {
      setRequesting(false);
    }
  };

  const verifyCode = async () => {
    if (!challengeId || !/^\d{6}$/.test(code)) return;
    setVerifying(true);
    setError(null);
    try {
      await api.post(`/v1/training-evidence/step-up/events/${eventId}/verify`, {
        challenge_id: challengeId,
        code,
      });
      setConfirmed(true);
      setChallengeId(null);
      setCode('');
      await loadEvent();
      onConfirmed?.();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.message || t('evidenceConfirmation.errors.verify'));
    } finally {
      setVerifying(false);
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
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `kamilya-training-evidence-${eventId}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (requestError: any) {
      setError(requestError?.response?.data?.message || 'Не удалось скачать подтверждение прохождения.');
    } finally {
      setDownloading(false);
    }
  };

  const title = event?.procedure_title || activityTitle;
  const statement = event?.confirmation_statement;
  const version = event?.release_version ?? event?.confirmation_object_version;
  const statusText = confirmed
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
      <Card aria-busy="true">
        <CardContent className="flex items-center gap-3 p-5 text-sm text-muted-foreground">
          <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t('evidenceConfirmation.loading')}
        </CardContent>
      </Card>
    );
  }

  if (error && !event) {
    return (
      <Card className="border-destructive/30">
        <CardContent className="space-y-3 p-5">
          <div className="flex items-start gap-3 text-sm text-destructive" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
          <Button type="button" variant="outline" onClick={() => void loadEvent()}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            {t('common.retry')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={confirmed ? 'border-success/40 bg-success/5' : 'border-primary/30'}>
      <CardHeader className="pb-3">
        <div className="flex items-start gap-3">
          <div className="rounded-full bg-primary/10 p-2 text-primary" aria-hidden="true">
            {confirmed ? <CheckCircle2 className="h-5 w-5 text-success" /> : <ShieldCheck className="h-5 w-5" />}
          </div>
          <div className="min-w-0">
            <CardTitle className="text-lg">{t('evidenceConfirmation.title')}</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{t('evidenceConfirmation.subtitle')}</p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{t('evidenceConfirmation.activity')}</dt>
            <dd className="mt-1 font-medium text-foreground">{title}</dd>
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

        {statement ? (
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
          {confirmed ? <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" /> : <Clock3 className="h-4 w-4 text-warning" aria-hidden="true" />}
          <span className={confirmed ? 'text-success' : 'text-muted-foreground'}>{statusText}</span>
        </div>

        <div className="rounded-md border border-border bg-muted/30 p-4">
          <p className="text-sm text-muted-foreground">
            Скачайте индивидуальное подтверждение прохождения. Его можно распечатать,
            подписать вручную и передать в головной офис.
          </p>
          <Button
            className="mt-3"
            type="button"
            variant="outline"
            onClick={() => void downloadEvidence()}
            disabled={downloading}
          >
            <Download className="mr-2 h-4 w-4" aria-hidden="true" />
            {downloading ? 'Подготовка PDF…' : 'Скачать подтверждение прохождения'}
          </Button>
        </div>

        {!confirmed && learnerEmail && (
          <div className="space-y-3 rounded-md border border-border p-4">
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
          </div>
        )}

        {!confirmed && !learnerEmail && (
          <div className="rounded-md border border-border p-4 text-sm text-muted-foreground">
            Электронное подтверждение недоступно, потому что у сотрудника нет email. Скачайте PDF,
            подпишите его вручную и передайте в головной офис; зафиксированный системой результат
            прохождения при этом сохраняется.
          </div>
        )}

        {confirmed && actionButtons}
      </CardContent>
    </Card>
  );
}
