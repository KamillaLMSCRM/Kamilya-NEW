'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { CheckCircle2, Download, Loader2 } from 'lucide-react';
import Link from 'next/link';

interface Certificate {
  id: string;
  course_id: string;
  certificate_number: string;
  issued_at: string;
  expires_at: string | null;
}

export default function CertificatesPage() {
  const { t } = useT();
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
      if (res.ok) setCertificates(await res.json());
    } catch {
      toast.error(t('common.loadFailed') || 'Failed to load certificates');
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, t]);

  useEffect(() => {
    fetchCertificates();
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
          toast.error(t('common.saveFailed') || 'Download failed');
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
      toast.success(t('toast.courseCompleted') || 'Downloaded');
    } catch (e) {
      console.error('Certificate download failed', e);
      toast.error(t('common.saveFailed') || 'Download failed');
    } finally {
      setDownloadingId(null);
    }
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">{t('certificates.title')}</h1>

      {certificates.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 p-8 text-center">
            <CheckCircle2 className="h-12 w-12 text-muted-foreground/50" aria-hidden="true" />
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
              <CardContent className="p-4 flex items-center justify-between">
                <div>
                  <div className="font-medium">{cert.certificate_number}</div>
                  <div className="text-sm text-muted-foreground">
                    {t('certificates.issuedAt')}: {new Date(cert.issued_at).toLocaleDateString('ru')}
                  </div>
                  {cert.expires_at && (
                    <div className="text-sm text-muted-foreground">
                      {t('certificates.expiresAt')}: {new Date(cert.expires_at).toLocaleDateString('ru')}
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Badge variant="outline">PDF</Badge>
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

      <div className="mt-8">
        <h2 className="text-lg font-semibold mb-4">{t('certificates.verify')}</h2>
        <Card>
          <CardContent className="p-4">
            <VerifyCertificateForm />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function VerifyCertificateForm() {
  const { t } = useT();
  const [number, setNumber] = useState('');
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const handleVerify = async () => {
    setError('');
    setResult(null);
    if (!number.trim()) return;
    const res = await fetch(`${API_URL}/v1/certificates/verify/${encodeURIComponent(number.trim())}`);
    if (res.ok) {
      setResult(await res.json());
    } else {
      setError(t('certificates.invalid'));
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t('certificates.verifyHint')}</p>
      <div className="flex flex-col gap-2 sm:flex-row">
      <input
        type="text"
        value={number}
        onChange={(e) => setNumber(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') handleVerify(); }}
        placeholder={t('certificates.verifyPlaceholder')}
        className="flex-1 border rounded px-3 py-2"
      />
      <Button onClick={handleVerify} disabled={!number.trim()}>{t('certificates.verifyButton')}</Button>
      </div>
      {result && (
        <div className="w-full mt-2 flex items-center gap-2 p-2 bg-success/10 rounded text-sm">
          <CheckCircle2 className="w-4 h-4 text-success" /> {t('certificates.valid')}. {result.user_name}, {result.course_title}
        </div>
      )}
      {error && (
        <div className="w-full mt-2 p-2 bg-destructive/10 rounded text-sm text-destructive">
          {error}
        </div>
      )}
    </div>
  );
}
