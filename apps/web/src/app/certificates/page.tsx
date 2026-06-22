'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { CheckCircle2 } from 'lucide-react';

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
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchCertificates = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/certificates`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setCertificates(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchCertificates();
  }, [fetchCertificates]);

  const handleDownload = async (certId: string) => {
    const res = await fetch(`${API_URL}/v1/certificates/${certId}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `certificate-${certId}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
    }
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">{t('certificates.title')}</h1>

      {certificates.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-gray-400">
            {t('certificates.noCertificates')}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {certificates.map((cert) => (
            <Card key={cert.id}>
              <CardContent className="p-4 flex items-center justify-between">
                <div>
                  <div className="font-medium">{cert.certificate_number}</div>
                  <div className="text-sm text-gray-500">
                    {t('certificates.issuedAt')}: {new Date(cert.issued_at).toLocaleDateString('ru')}
                  </div>
                  {cert.expires_at && (
                    <div className="text-sm text-gray-400">
                      {t('certificates.expiresAt')}: {new Date(cert.expires_at).toLocaleDateString('ru')}
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Badge variant="outline">PDF</Badge>
                  <Button size="sm" onClick={() => handleDownload(cert.id)}>
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
    const res = await fetch(`${API_URL}/v1/certificates/verify/${number}`);
    if (res.ok) {
      setResult(await res.json());
    } else {
      setError(t('certificates.invalid'));
    }
  };

  return (
    <div className="flex gap-2">
      <input
        type="text"
        value={number}
        onChange={(e) => setNumber(e.target.value)}
        placeholder={t('certificates.verifyPlaceholder')}
        className="flex-1 border rounded px-3 py-2"
      />
      <Button onClick={handleVerify}>{t('certificates.verifyButton')}</Button>
      {result && (
        <div className="w-full mt-2 flex items-center gap-2 p-2 bg-green-50 rounded text-sm">
          <CheckCircle2 className="w-4 h-4 text-green-600" /> {t('certificates.valid')}. {result.user_name}, {result.course_title}
        </div>
      )}
      {error && (
        <div className="w-full mt-2 p-2 bg-red-50 rounded text-sm text-red-600">
          {error}
        </div>
      )}
    </div>
  );
}
