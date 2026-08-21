'use client';

import { FormEvent, useState } from 'react';
import { AlertTriangle, CheckCircle2, LifeBuoy, Send } from 'lucide-react';
import { api } from '@/lib/api';
import { useT } from '@/i18n/useT';
import { Button, Input, Modal } from '@/components/ui';

const SUPPORT_EMAIL = 'support@kml.kz';
const CATEGORIES = ['access', 'technical', 'learning', 'staff', 'billing', 'other'] as const;
type SupportCategory = (typeof CATEGORIES)[number];

interface SupportRequestResult {
  id: string;
  reference: string;
  delivery_status: 'pending' | 'sent' | 'deferred' | 'failed';
  created_at: string;
}

export function SupportRequestDialog() {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<SupportCategory>('technical');
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);
  const [result, setResult] = useState<SupportRequestResult | null>(null);

  const reset = () => {
    setCategory('technical');
    setSubject('');
    setMessage('');
    setError(false);
    setResult(null);
  };

  const close = () => {
    if (submitting) return;
    setOpen(false);
    if (result) reset();
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (subject.trim().length < 3 || message.trim().length < 10) return;
    setSubmitting(true);
    setError(false);
    try {
      const currentPath = `${window.location.pathname}${window.location.search}`.slice(0, 500);
      const response = await api.post<SupportRequestResult>('/v1/support/requests', {
        category,
        subject: subject.trim(),
        message: message.trim(),
        current_path: currentPath,
      });
      setResult(response.data);
    } catch {
      setError(true);
    } finally {
      setSubmitting(false);
    }
  };

  const fallbackSubject = encodeURIComponent(
    result ? `${result.reference}: ${subject.trim()}` : subject.trim() || t('support.defaultEmailSubject')
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-border px-2.5 text-sm font-medium text-muted-foreground transition-colors hover:border-primary/30 hover:bg-primary/5 hover:text-primary sm:px-3"
        aria-label={t('support.open')}
        title={t('support.open')}
      >
        <LifeBuoy className="h-4 w-4" aria-hidden="true" />
        <span className="hidden lg:inline">{t('support.open')}</span>
      </button>

      <Modal
        open={open}
        onClose={close}
        title={result ? t('support.successTitle') : t('support.title')}
        description={result ? undefined : t('support.description')}
        dismissable={!submitting}
        className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-xl"
      >
        {result ? (
          <div className="space-y-5">
            <div className="flex gap-3 rounded-xl border border-success/25 bg-success/10 p-4 text-success">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-medium">{t('support.successMessage')}</p>
                <p className="mt-1 font-mono text-sm">{result.reference}</p>
              </div>
            </div>
            {result.delivery_status !== 'sent' && (
              <div className="flex gap-3 rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-foreground">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
                <div>
                  <p>{t('support.deliveryDeferred')}</p>
                  <a
                    href={`mailto:${SUPPORT_EMAIL}?subject=${fallbackSubject}`}
                    className="mt-2 inline-block font-medium text-primary underline underline-offset-4"
                  >
                    {SUPPORT_EMAIL}
                  </a>
                </div>
              </div>
            )}
            <Button type="button" className="w-full" onClick={close}>
              {t('support.close')}
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <label className="block space-y-1.5 text-sm font-medium text-foreground">
              <span>{t('support.category')}</span>
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value as SupportCategory)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
              >
                {CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {t(`support.categories.${value}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1.5 text-sm font-medium text-foreground">
              <span>{t('support.subject')}</span>
              <Input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                minLength={3}
                maxLength={160}
                placeholder={t('support.subjectPlaceholder')}
                required
              />
            </label>
            <label className="block space-y-1.5 text-sm font-medium text-foreground">
              <span>{t('support.message')}</span>
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                minLength={10}
                maxLength={4000}
                rows={7}
                placeholder={t('support.messagePlaceholder')}
                className="flex w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                required
              />
            </label>
            <p className="text-xs text-muted-foreground">{t('support.privacyHint')}</p>
            {error && (
              <div role="alert" className="rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {t('support.submitError')}{' '}
                <a href={`mailto:${SUPPORT_EMAIL}?subject=${fallbackSubject}`} className="font-medium underline underline-offset-4">
                  {SUPPORT_EMAIL}
                </a>
              </div>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" onClick={close} disabled={submitting}>
                {t('support.cancel')}
              </Button>
              <Button
                type="submit"
                disabled={submitting || subject.trim().length < 3 || message.trim().length < 10}
                className="gap-2"
              >
                <Send className="h-4 w-4" aria-hidden="true" />
                {submitting ? t('support.submitting') : t('support.submit')}
              </Button>
            </div>
          </form>
        )}
      </Modal>
    </>
  );
}
