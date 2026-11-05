'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Download, ExternalLink, FileCheck2, Loader2 } from 'lucide-react';

import { Badge, Button } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';

interface Certificate {
  id: string;
  course_id: string;
  certificate_number: string;
  issued_at: string;
  expires_at: string | null;
  status: 'active' | 'expired' | 'revoked';
  user_name: string;
  course_title: string;
}

export default function CertificatesPage() {
  const { t, lang } = useT();
  const [certificates, setCertificates] = useState<Certificate[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchCertificates = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/certificates`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Certificate request failed (${res.status})`);
      setCertificates(await res.json());
      setLoadError(false);
    } catch {
      setLoadError(true);
      toast.error(t('common.loadFailed') || 'Failed to load certificates');
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, t]);

  useEffect(() => {
    void fetchCertificates();
  }, [fetchCertificates]);

  const handleDownload = async (cert: Certificate) => {
    if (downloadingId) return;
    setDownloadingId(cert.id);
    try {
      const res = await fetch(`${API_URL}/v1/certificates/${cert.id}/download?direct=true`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (res.status === 404) {
          toast.error(t('certificates.invalid'));
        } else {
          toast.error(t('certificates.downloadFailed'));
        }
        return;
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `certificate-${cert.certificate_number}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      toast.success(t('certificates.downloaded'));
    } catch (e) {
      console.error('Certificate download failed', e);
      toast.error(t('certificates.downloadFailed'));
    } finally {
      setDownloadingId(null);
    }
  };

  const formatDate = (value: string) => new Intl.DateTimeFormat(lang).format(new Date(value));
  const statusLabel = (status: Certificate['status']) => {
    if (status === 'active') return t('certificateVerification.active');
    if (status === 'expired') return t('certificateVerification.expired');
    return t('certificateVerification.revoked');
  };

  if (loading) {
    return (
      <WorkspacePage id="certificates" title={t('certificates.title')}><WorkspacePanel aria-busy="true" bodyClassName="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {t('common.loading')}
      </WorkspacePanel></WorkspacePage>
    );
  }

  return (
    <WorkspacePage id="certificates" title={t('certificates.title')} description={t('certificates.description')} icon={<FileCheck2 />}>
      <WorkspaceToolbar>
        <p className="min-w-0 flex-1 text-sm leading-6 text-muted-foreground">{t('certificates.publicVerificationHint')}</p>
        <Link href="/verify/certificate" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border px-4 text-sm font-medium text-primary hover:bg-muted"><ExternalLink className="h-4 w-4 shrink-0" aria-hidden="true" />{t('certificates.verify')}</Link>
      </WorkspaceToolbar>

      {loadError ? <WorkspacePanel role="alert" bodyClassName="space-y-3"><p>{t('common.loadFailed')}</p><Button variant="outline" onClick={() => { setLoading(true); void fetchCertificates(); }}>{t('common.retry')}</Button></WorkspacePanel> : certificates.length === 0 ? (
        <WorkspaceEmpty title={t('certificates.noCertificates')} icon={<FileCheck2 />} action={
            <Link href="/my-courses" className="text-sm font-medium text-primary hover:underline">
              {t('certificates.browseCourses')}
            </Link>
        } />
      ) : (
        <WorkspacePanel padded={false} bodyClassName="divide-y divide-border">
          {certificates.map((cert) => (
            <article key={cert.id} className="grid min-w-0 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(12rem,auto)] sm:p-6">
                <div className="min-w-0 border-l-4 border-primary/25 pl-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="break-words text-base font-semibold">
                      {cert.course_title || t('certificates.courseFallback')}
                    </h2>
                    <Badge
                      variant={cert.status === 'revoked' ? 'destructive' : 'outline'}
                      className={
                        cert.status === 'active'
                          ? 'border-success/40 bg-success/10 text-success'
                          : cert.status === 'expired'
                            ? 'border-warning/50 bg-warning/10 text-warning-foreground'
                            : undefined
                      }
                    >
                      {statusLabel(cert.status)}
                    </Badge>
                  </div>
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {cert.certificate_number}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
                    <span>{t('certificates.issuedAt')}: {formatDate(cert.issued_at)}</span>
                    {cert.expires_at && (
                      <span>{t('certificates.expiresAt')}: {formatDate(cert.expires_at)}</span>
                    )}
                  </div>
                </div>
                <div className="flex min-w-0 flex-wrap items-start gap-2 lg:max-w-xs lg:flex-col lg:items-stretch">
                  <Link
                    href={`/verify/certificate/${encodeURIComponent(cert.certificate_number)}`}
                    className="inline-flex min-h-11 items-center justify-center rounded-xl border border-input px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    <ExternalLink className="mr-2 h-4 w-4" aria-hidden="true" />
                    {t('certificates.openVerification')}
                  </Link>
                  <Button
                    className="min-h-11"
                    onClick={() => handleDownload(cert)}
                    disabled={downloadingId === cert.id}
                  >
                    {downloadingId === cert.id ? (
                      <Loader2 className="w-4 h-4 mr-1 animate-spin" aria-hidden="true" />
                    ) : (
                      <Download className="w-4 h-4 mr-1" aria-hidden="true" />
                    )}
                    {t('common.download')}
                  </Button>
                </div>
            </article>
          ))}
        </WorkspacePanel>
      )}

    </WorkspacePage>
  );
}
