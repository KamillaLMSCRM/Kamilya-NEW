'use client';

import { FormEvent, useEffect, useState } from 'react';
import { AlertTriangle, ArrowLeft, CheckCircle2, Loader2, Search, ShieldCheck, XCircle } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { Button, Input } from '@/components/ui';
import { useT } from '@/i18n/useT';
import {
  fetchCertificateVerification,
  formatVerificationDate,
  getCertificateVerificationPath,
  normalizeCertificateNumber,
  type CertificateVerification,
} from './verification';

type LookupState = 'idle' | 'loading' | 'result' | 'not-found' | 'network-error';

interface VerificationPanelProps {
  initialNumber?: string;
}

function statusStyles(status: CertificateVerification['status']): {
  className: string;
  Icon: typeof CheckCircle2;
} {
  if (status === 'active') return { className: 'border-success/40 bg-success/10 text-success', Icon: CheckCircle2 };
  if (status === 'expired') return { className: 'border-warning/50 bg-warning/10 text-warning-foreground', Icon: AlertTriangle };
  return { className: 'border-destructive/40 bg-destructive/10 text-destructive', Icon: XCircle };
}

export default function VerificationPanel({ initialNumber }: VerificationPanelProps) {
  const { t, lang } = useT();
  const router = useRouter();
  const [number, setNumber] = useState(initialNumber ? normalizeCertificateNumber(initialNumber) : '');
  const [result, setResult] = useState<CertificateVerification | null>(null);
  const [state, setState] = useState<LookupState>(initialNumber ? 'loading' : 'idle');

  const verify = async (rawNumber: string) => {
    const normalized = normalizeCertificateNumber(rawNumber);
    if (!normalized) return;
    setNumber(normalized);
    setResult(null);
    setState('loading');
    try {
      const response = await fetchCertificateVerification(normalized);
      if (!response) {
        setState('not-found');
        return;
      }
      setResult(response);
      setState('result');
    } catch {
      setState('network-error');
    }
  };

  useEffect(() => {
    if (!initialNumber) return;
    void verify(initialNumber);
    // The number route is intentionally looked up once on entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialNumber]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = normalizeCertificateNumber(number);
    if (!normalized) return;
    if (!initialNumber) {
      router.push(getCertificateVerificationPath(normalized));
      return;
    }
    void verify(normalized);
  };

  const backToLanding = () => router.push('/verify/certificate');
  const styles = result ? statusStyles(result.status) : null;
  const StatusIcon = styles?.Icon;

  return (
    <main className="min-h-screen bg-background px-4 py-10 sm:px-6 sm:py-16">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-md bg-primary/10 text-primary">
            <ShieldCheck className="h-6 w-6" aria-hidden="true" />
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">Kamilya LMS</p>
            <h1 className="text-2xl font-bold text-foreground sm:text-3xl">{t('certificateVerification.title')}</h1>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-5 shadow-sm sm:p-8">
          <p className="max-w-2xl text-sm text-muted-foreground sm:text-base">{t('certificateVerification.description')}</p>
          <form onSubmit={submit} className="mt-6 space-y-3">
            <label htmlFor="public-certificate-number" className="block text-sm font-medium">
              {t('certificateVerification.numberLabel')}
            </label>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Input
                id="public-certificate-number"
                name="certificate_number"
                autoComplete="off"
                inputMode="text"
                value={number}
                onChange={(event) => setNumber(event.target.value.toUpperCase())}
                placeholder={t('certificateVerification.placeholder')}
                className="min-h-11 flex-1"
              />
              <Button type="submit" className="min-h-11 gap-2 sm:min-w-32" disabled={!number.trim() || state === 'loading'}>
                {state === 'loading' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Search className="h-4 w-4" aria-hidden="true" />}
                {state === 'loading' ? t('certificateVerification.checking') : t('certificateVerification.verify')}
              </Button>
            </div>
          </form>

          {state === 'loading' && (
            <p className="mt-6 flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t('certificateVerification.checking')}
            </p>
          )}

          {state === 'not-found' && (
            <div className="mt-6 flex flex-col gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive" role="alert">
              <span>{t('certificateVerification.notFound')}</span>
              <Button type="button" variant="outline" className="min-h-11 w-fit" onClick={() => void verify(number)}>
                <Search className="mr-2 h-4 w-4" aria-hidden="true" />
                {t('certificateVerification.retry')}
              </Button>
            </div>
          )}

          {state === 'network-error' && (
            <div className="mt-6 flex flex-col gap-3 rounded-md border border-warning/50 bg-warning/10 p-4 text-sm" role="alert">
              <span>{t('certificateVerification.networkError')}</span>
              <Button type="button" variant="outline" className="min-h-11 w-fit" onClick={() => void verify(number)}>
                <Search className="mr-2 h-4 w-4" aria-hidden="true" />
                {t('certificateVerification.retry')}
              </Button>
            </div>
          )}

          {result && styles && StatusIcon && (
            <section className={`mt-6 rounded-md border p-5 ${styles.className}`} aria-live="polite" aria-label={t(`certificateVerification.${result.status}` as never)}>
              <div className="flex items-start gap-3">
                <StatusIcon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
                <div className="min-w-0">
                  <h2 className="font-semibold">{t(`certificateVerification.${result.status}` as never)}</h2>
                  <dl className="mt-4 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                    <div><dt className="opacity-75">{t('certificateVerification.certificateNumber')}</dt><dd className="mt-0.5 break-all font-medium">{result.certificate_number}</dd></div>
                    <div><dt className="opacity-75">{t('certificateVerification.organization')}</dt><dd className="mt-0.5 break-words font-medium">{result.organization_name}</dd></div>
                    <div><dt className="opacity-75">{t('certificateVerification.issuedTo')}</dt><dd className="mt-0.5 break-words font-medium">{result.user_name}</dd></div>
                    <div><dt className="opacity-75">{t('certificateVerification.course')}</dt><dd className="mt-0.5 break-words font-medium">{result.course_title}</dd></div>
                    <div><dt className="opacity-75">{t('certificateVerification.issuedAt')}</dt><dd className="mt-0.5 font-medium">{formatVerificationDate(result.issued_at, lang)}</dd></div>
                    <div><dt className="opacity-75">{t('certificateVerification.expiresAt')}</dt><dd className="mt-0.5 font-medium">{result.expires_at ? formatVerificationDate(result.expires_at, lang) : t('certificateVerification.noExpiry')}</dd></div>
                  </dl>
                  {result.status === 'revoked' && result.revoked_reason && (
                    <p className="mt-4 border-t border-current/20 pt-3 text-sm"><strong>{t('certificateVerification.revokedReason')}:</strong> {result.revoked_reason}</p>
                  )}
                </div>
              </div>
            </section>
          )}

          {initialNumber && (
            <Button type="button" variant="link" className="mt-5 min-h-11 gap-2 px-0" onClick={backToLanding}>
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              {t('certificateVerification.back')}
            </Button>
          )}
        </div>
      </div>
    </main>
  );
}
