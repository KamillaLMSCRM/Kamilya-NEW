'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Download, ExternalLink, FileCheck2, Loader2 } from 'lucide-react';

import { Badge, Button, Card, CardContent } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

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
    } catch {
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
      const res = await fetch(`${API_URL}/v1/certificates/${cert.id}/download`, {
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
      <div className="flex min-h-48 items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {t('common.loading')}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">{t('certificates.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('certificates.description')}</p>
      </div>

      {certificates.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 p-8 text-center">
            <FileCheck2 className="h-12 w-12 text-muted-foreground/50" aria-hidden="true" />
            <p className="max-w-md text-muted-foreground">{t('certificates.noCertificates')}</p>
            <Link href="/my-courses" className="text-sm font-medium text-primary hover:underline">
              {t('certificates.browseCourses')}
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {certificates.map((cert) => (
            <Card key={cert.id}>
              <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
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
                <div className="flex flex-col gap-2 sm:min-w-48">
                  <Link
                    href={`/verify/certificate/${encodeURIComponent(cert.certificate_number)}`}
                    className="inline-flex h-9 items-center justify-center rounded-md border border-input px-3 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    <ExternalLink className="mr-2 h-4 w-4" aria-hidden="true" />
                    {t('certificates.openVerification')}
                  </Link>
                  <Button
                    size="sm"
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
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <p className="text-sm text-muted-foreground">
        {t('certificates.publicVerificationHint')}{' '}
        <Link href="/verify/certificate" className="font-medium text-primary hover:underline">
          {t('certificates.verify')}
        </Link>
      </p>
    </div>
  );
}
