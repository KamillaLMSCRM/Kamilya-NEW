'use client';

import { useAuthStore } from '@/store/authStore';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui';
import { useT } from '@/i18n/useT';

export default function DashboardPage() {
  const { user } = useAuthStore();
  const { t } = useT();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t('dashboard.title')}</h1>
        <p className="text-gray-500">
          {t('dashboard.welcome')}, {user?.full_name || user?.firstName || 'Пользователь'}!
        </p>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>🎓 {t('nav.myDashboard')}</CardTitle>
          </CardHeader>
          <CardContent>
            <a href="/student" className="text-blue-600 hover:underline">
              {t('common.next')} →
            </a>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>📚 {t('nav.courses')}</CardTitle>
          </CardHeader>
          <CardContent>
            <a href="/courses" className="text-blue-600 hover:underline">
              {t('common.next')} →
            </a>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>🤖 {t('nav.aiGeneration')}</CardTitle>
          </CardHeader>
          <CardContent>
            <a href="/ai/generate" className="text-blue-600 hover:underline">
              {t('courses.createCourse')} →
            </a>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>📄 {t('nav.documents')}</CardTitle>
          </CardHeader>
          <CardContent>
            <a href="/documents" className="text-blue-600 hover:underline">
              {t('common.next')} →
            </a>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>🏅 {t('nav.certificates')}</CardTitle>
          </CardHeader>
          <CardContent>
            <a href="/certificates" className="text-blue-600 hover:underline">
              {t('common.next')} →
            </a>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>🔧 {t('nav.admin')}</CardTitle>
          </CardHeader>
          <CardContent>
            <a href="/admin" className="text-blue-600 hover:underline">
              {t('common.next')} →
            </a>
          </CardContent>
        </Card>
      </div>

      <div className="mt-4">
        <p className="text-gray-600">
          Загрузите документы для генерации AI-курсов,
          управляйте сотрудниками и отслеживайте прогресс обучения.
        </p>
      </div>
    </div>
  );
}
