'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, Eye, Loader2, RefreshCw, Save } from 'lucide-react';

import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';

const CANONICAL_VERIFICATION_URL = 'https://app.kml.kz/verify/certificate';

interface CertificateSettings {
  organization_name: string;
  signer_name: string;
  signer_title: string;
  validity_months: number | null;
  footer_note: string;
  verification_base_url: string;
  show_verification_url: boolean;
}

const defaults: CertificateSettings = {
  organization_name: 'Kamilya LMS',
  signer_name: '',
  signer_title: '',
  validity_months: null,
  footer_note: '',
  verification_base_url: CANONICAL_VERIFICATION_URL,
  show_verification_url: true,
};

function normalizeSettings(value: Partial<CertificateSettings>): CertificateSettings {
  return {
    ...defaults,
    ...value,
    verification_base_url: CANONICAL_VERIFICATION_URL,
  };
}

function errorMessage(error: unknown, fallback: string): string {
  const responseDetail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return responseDetail || (error instanceof Error ? error.message : fallback);
}

export default function CertificateSettingsPage() {
  const { t } = useT();
  const [settings, setSettings] = useState<CertificateSettings>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await api.get<Partial<CertificateSettings>>('/v1/certificates/settings');
        if (!cancelled) setSettings(normalizeSettings(res.data));
      } catch (err) {
        toast.error(t('certificateSettings.loadFailed'), {
          description: errorMessage(err, t('common.loadFailed')),
        });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const replacePreviewUrl = useCallback((nextUrl: string | null) => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = nextUrl;
    setPreviewUrl(nextUrl);
  }, []);

  const generatePreview = useCallback(async (
    nextSettings: CertificateSettings,
    signal?: AbortSignal,
  ): Promise<string | null> => {
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const response = await api.post<Blob>('/v1/certificates/settings/preview', {
        settings: { ...nextSettings, verification_base_url: CANONICAL_VERIFICATION_URL },
        sample_user_name: t('certificateSettings.sampleUser'),
        sample_course_title: t('certificateSettings.sampleCourse'),
      }, { responseType: 'blob', signal });
      const nextUrl = URL.createObjectURL(response.data);
      replacePreviewUrl(nextUrl);
      return nextUrl;
    } catch (err) {
      if (signal?.aborted) return null;
      setPreviewError(errorMessage(err, t('certificateSettings.previewFailed')));
      return null;
    } finally {
      if (!signal?.aborted) setPreviewLoading(false);
    }
  }, [replacePreviewUrl, t]);

  useEffect(() => {
    if (loading) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void generatePreview(settings, controller.signal);
    }, 500);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [generatePreview, loading, settings]);

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  const update = <K extends keyof CertificateSettings>(key: K, value: CertificateSettings[K]) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        ...settings,
        verification_base_url: CANONICAL_VERIFICATION_URL,
        validity_months: settings.validity_months && settings.validity_months > 0
          ? settings.validity_months
          : null,
      };
      const res = await api.put<Partial<CertificateSettings>>('/v1/certificates/settings', payload);
      setSettings(normalizeSettings(res.data));
      toast.success(t('certificateSettings.saved'));
    } catch (err) {
      toast.error(t('certificateSettings.saveFailed'), {
        description: errorMessage(err, t('common.saveFailed')),
      });
    } finally {
      setSaving(false);
    }
  };

  const downloadPreview = async () => {
    const url = previewUrl || await generatePreview(settings);
    if (!url) return;
    const link = document.createElement('a');
    link.href = url;
    link.download = 'certificate-preview.pdf';
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t('certificateSettings.title')}</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('certificateSettings.description')}</p>
        </div>
        <Button onClick={save} disabled={saving || loading} className="min-h-11 gap-2">
          <Save className="h-4 w-4" aria-hidden="true" />
          {saving ? t('certificateSettings.saving') : t('common.save')}
        </Button>
      </div>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">{t('certificateSettings.issuerTitle')}</CardTitle>
            <p className="text-sm text-muted-foreground">{t('certificateSettings.issuerDescription')}</p>
          </CardHeader>
          <CardContent className="space-y-5">
            {loading ? (
              <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-muted-foreground" aria-live="polite">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                {t('common.loading')}
              </div>
            ) : (
              <>
                <div>
                  <label htmlFor="certificate-organization" className="mb-2 block text-sm font-medium">
                    {t('certificateSettings.organization')}
                  </label>
                  <Input
                    id="certificate-organization"
                    name="organization_name"
                    autoComplete="organization"
                    maxLength={160}
                    value={settings.organization_name}
                    onChange={(event) => update('organization_name', event.target.value)}
                    placeholder={t('certificateSettings.organizationPlaceholder')}
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="certificate-signer-name" className="mb-2 block text-sm font-medium">
                      {t('certificateSettings.signer')}
                    </label>
                    <Input
                      id="certificate-signer-name"
                      name="signer_name"
                      autoComplete="name"
                      maxLength={120}
                      value={settings.signer_name}
                      onChange={(event) => update('signer_name', event.target.value)}
                      placeholder={t('certificateSettings.signerPlaceholder')}
                    />
                  </div>
                  <div>
                    <label htmlFor="certificate-signer-title" className="mb-2 block text-sm font-medium">
                      {t('certificateSettings.signerTitle')}
                    </label>
                    <Input
                      id="certificate-signer-title"
                      name="signer_title"
                      maxLength={120}
                      value={settings.signer_title}
                      onChange={(event) => update('signer_title', event.target.value)}
                      placeholder={t('certificateSettings.signerTitlePlaceholder')}
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="certificate-validity" className="mb-2 block text-sm font-medium">
                    {t('certificateSettings.validity')}
                  </label>
                  <Input
                    id="certificate-validity"
                    name="validity_months"
                    type="number"
                    min={0}
                    max={120}
                    inputMode="numeric"
                    value={settings.validity_months ?? ''}
                    onChange={(event) => update('validity_months', event.target.value ? Number(event.target.value) : null)}
                    placeholder={t('certificateSettings.noExpiry')}
                  />
                </div>

                <div className="rounded-md border border-border bg-muted/30 p-4">
                  <p className="text-sm font-medium">{t('certificateSettings.verificationTitle')}</p>
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {CANONICAL_VERIFICATION_URL}/{'{certificate_number}'}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">{t('certificateSettings.verificationDescription')}</p>
                </div>

                <label className="flex min-h-11 items-center gap-3 rounded-md border border-border p-3 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.show_verification_url}
                    onChange={(event) => update('show_verification_url', event.target.checked)}
                    className="h-4 w-4 rounded border-border text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  {t('certificateSettings.showVerificationUrl')}
                </label>

                <div>
                  <label htmlFor="certificate-footer-note" className="mb-2 block text-sm font-medium">
                    {t('certificateSettings.footerNote')}
                  </label>
                  <textarea
                    id="certificate-footer-note"
                    name="footer_note"
                    maxLength={300}
                    value={settings.footer_note}
                    onChange={(event) => update('footer_note', event.target.value)}
                    rows={3}
                    className="min-h-24 w-full rounded-md border border-border bg-card px-3 py-2.5 text-sm outline-none transition-colors focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring"
                    placeholder={t('certificateSettings.footerPlaceholder')}
                  />
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
            <div>
              <CardTitle className="flex items-center gap-2 text-xl">
                <Eye className="h-5 w-5 text-primary" aria-hidden="true" />
                {t('certificateSettings.previewTitle')}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">{t('certificateSettings.previewDescription')}</p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => void generatePreview(settings)}
              disabled={previewLoading || loading}
              aria-label={t('certificateSettings.refreshPreview')}
              title={t('certificateSettings.refreshPreview')}
            >
              <RefreshCw className={previewLoading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} aria-hidden="true" />
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="overflow-hidden rounded-md border border-border bg-muted/30" style={{ aspectRatio: '297 / 210' }} aria-busy={previewLoading}>
              {previewUrl ? (
                <iframe title={t('certificateSettings.previewTitle')} src={previewUrl} className="h-full w-full border-0" />
              ) : (
                <div className="flex h-full min-h-48 items-center justify-center p-6 text-center text-sm text-muted-foreground" aria-live="polite">
                  {previewLoading ? (
                    <span className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />{t('certificateSettings.previewLoading')}</span>
                  ) : (
                    t('certificateSettings.previewUnavailable')
                  )}
                </div>
              )}
            </div>
            {previewError && (
              <div className="flex flex-col gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive" role="alert">
                <span>{previewError}</span>
                <Button type="button" variant="outline" className="w-fit min-h-11" onClick={() => void generatePreview(settings)}>
                  <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
                  {t('common.retry')}
                </Button>
              </div>
            )}
            <Button type="button" variant="outline" className="min-h-11 w-full gap-2" onClick={() => void downloadPreview()} disabled={previewLoading || loading}>
              <Download className="h-4 w-4" aria-hidden="true" />
              {t('certificateSettings.downloadPreview')}
            </Button>
            <p className="text-xs text-muted-foreground">{t('certificateSettings.previewSample')}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
