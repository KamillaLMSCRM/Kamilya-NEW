'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';

interface Certificate {
  id: string;
  course_id: string;
  certificate_number: string;
  issued_at: string;
  expires_at: string | null;
}

export default function CertificatesPage() {
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

  if (loading) return <div className="p-6">Загрузка...</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Мои сертификаты</h1>

      {certificates.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-gray-400">
            У вас пока нет сертификатов. Завершите курсы, чтобы получить сертификат!
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
                    Выдан: {new Date(cert.issued_at).toLocaleDateString('ru')}
                  </div>
                  {cert.expires_at && (
                    <div className="text-sm text-gray-400">
                      Действителен до: {new Date(cert.expires_at).toLocaleDateString('ru')}
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Badge variant="outline">PDF</Badge>
                  <Button size="sm" onClick={() => handleDownload(cert.id)}>
                    Скачать
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="mt-8">
        <h2 className="text-lg font-semibold mb-4">Проверить сертификат</h2>
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
      setError('Сертификат не найден');
    }
  };

  return (
    <div className="flex gap-2">
      <input
        type="text"
        value={number}
        onChange={(e) => setNumber(e.target.value)}
        placeholder="Номер сертификата (KML-2026-XXXXXX)"
        className="flex-1 border rounded px-3 py-2"
      />
      <Button onClick={handleVerify}>Проверить</Button>
      {result && (
        <div className="w-full mt-2 p-2 bg-green-50 rounded text-sm">
          ✓ Сертификат действителен. Выдан: {result.user_name}, Курс: {result.course_title}
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
