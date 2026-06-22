'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

interface JobDescription {
  id: string;
  title: string;
  department: string;
  position: string;
  status: string;
  created_at: string;
  course_id: string | null;
}

export default function JobDescriptionsPage() {
  const { t } = useT();
  const [jds, setJds] = useState<JobDescription[]>([]);
  const [loading, setLoading] = useState(true);
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchJDs = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/job-descriptions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setJds(data.items || data || []);
      }
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchJDs();
  }, [fetchJDs]);

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Job Descriptions</h1>
        <Button onClick={() => window.location.href = '/ai/generate'}>
          + {t('common.create')} JD
        </Button>
      </div>

      {jds.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            Нет job descriptions. Создайте первую через AI генерацию!
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {jds.map((jd) => (
            <Card key={jd.id} className="hover:shadow-md transition-shadow">
              <CardContent className="p-4 flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h3 className="font-medium">{jd.title}</h3>
                    <Badge variant={jd.status === 'active' ? 'default' : 'outline'}>
                      {jd.status}
                    </Badge>
                  </div>
                  <div className="text-sm text-gray-500 mt-1">
                    {jd.department} · {jd.position}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    {t('common.create')}: {new Date(jd.created_at).toLocaleDateString('ru')}
                  </div>
                </div>
                <div className="flex gap-2">
                  {jd.course_id ? (
                    <a href={`/courses/${jd.course_id}`}>
                      <Button variant="outline" size="sm">{t('courses.editCourse')}</Button>
                    </a>
                  ) : (
                    <Button size="sm" disabled>Курс не создан</Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
