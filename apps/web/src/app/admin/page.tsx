'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { ChevronRight } from 'lucide-react';

interface TenantStats {
  total_users: number;
  active_users: number;
  total_courses: number;
  published_courses: number;
  ai_generated_courses: number;
  total_enrollments: number;
  completed_enrollments: number;
  total_quizzes_taken: number;
  average_quiz_score: number;
  certificates_issued: number;
  documents_uploaded: number;
  storage_used_bytes: number;
}

interface UserItem {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface CourseItem {
  id: string;
  title: string;
  status: string;
  ai_generated: boolean;
  created_at: string;
  enrollment_count: number;
}

interface TrialUsageItem {
  used: number;
  limit: number | null;
  remaining: number | null;
}

interface TrialUsage {
  plan: string;
  status: string;
  trial_started_at: string | null;
  trial_ends_at: string | null;
  days_left: number | null;
  ai_courses: TrialUsageItem;
  jd_courses: TrialUsageItem;
  learners: TrialUsageItem;
  system_users: TrialUsageItem;
}

export default function AdminDashboardPage() {
  const { t } = useT();
  const [stats, setStats] = useState<TenantStats | null>(null);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [courses, setCourses] = useState<CourseItem[]>([]);
  const [trialUsage, setTrialUsage] = useState<TrialUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const [statsRes, usersRes, coursesRes, trialUsageRes] = await Promise.all([
        fetch(`${API_URL}/v1/admin/stats`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/v1/users?per_page=5`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/v1/courses`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/v1/admin/trial-usage`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);

      if (statsRes.ok) setStats(await statsRes.json());
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users || []);
      }
      if (coursesRes.ok) setCourses(await coursesRes.json());
      if (trialUsageRes.ok) setTrialUsage(await trialUsageRes.json());
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleExport = async (type: string) => {
    const res = await fetch(`${API_URL}/v1/admin/export/${type}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${type}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatLimit = (item: TrialUsageItem) => {
    if (item.limit == null) return `${item.used} / без лимита`;
    return `${item.used} / ${item.limit}`;
  };

  const trialItems = trialUsage ? [
    { label: 'AI-курс', value: formatLimit(trialUsage.ai_courses), left: trialUsage.ai_courses.remaining },
    { label: 'Курс по ДИ', value: formatLimit(trialUsage.jd_courses), left: trialUsage.jd_courses.remaining },
    { label: 'Обучающиеся', value: formatLimit(trialUsage.learners), left: trialUsage.learners.remaining },
    { label: 'Пользователи системы', value: formatLimit(trialUsage.system_users), left: trialUsage.system_users.remaining },
  ] : [];

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (!stats) return <div className="p-6">{t('common.error')}</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t('admin.title')}</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => handleExport('users')}>{t('admin.exportUsers')}</Button>
          <Button variant="outline" onClick={() => handleExport('courses')}>{t('admin.exportCourses')}</Button>
          <Button variant="outline" onClick={() => handleExport('quiz-results')}>{t('admin.exportQuizResults')}</Button>
        </div>
      </div>

      {trialUsage && (
        <Card>
          <CardContent className="p-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant={trialUsage.status === 'trial' ? 'secondary' : 'outline'}>
                    {trialUsage.plan}
                  </Badge>
                  <h2 className="text-lg font-semibold text-foreground">Trial и лимиты</h2>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  {trialUsage.trial_ends_at
                    ? `Осталось дней: ${trialUsage.days_left ?? 0}. До ${new Date(trialUsage.trial_ends_at).toLocaleDateString('ru')}.`
                    : 'Дата окончания trial не задана.'}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {trialItems.map((item) => (
                  <div key={item.label} className="rounded-xl border border-border bg-muted/30 px-3 py-2">
                    <div className="text-xs text-muted-foreground">{item.label}</div>
                    <div className="mt-1 text-base font-semibold text-foreground">{item.value}</div>
                    {item.left != null && (
                      <div className="text-xs text-muted-foreground">Осталось: {item.left}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-primary">{stats.total_users}</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.totalUsers')}</div>
            <div className="text-xs text-muted-foreground">{stats.active_users} {t('admin.stats.activeUsers')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-success">{stats.total_courses}</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.totalCourses')}</div>
            <div className="text-xs text-muted-foreground">{stats.published_courses} {t('admin.stats.published')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-warning">{stats.total_enrollments}</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.enrollments')}</div>
            <div className="text-xs text-muted-foreground">{stats.completed_enrollments} {t('admin.stats.completed')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-accent">{stats.certificates_issued}</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.certificates')}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{stats.ai_generated_courses}</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.aiGenerated')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{stats.total_quizzes_taken}</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.quizzesTaken')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{stats.average_quiz_score}%</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.averageScore')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{formatBytes(stats.storage_used_bytes)}</div>
            <div className="text-sm text-muted-foreground">{t('admin.stats.storage')}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>{t('admin.recentUsers')}</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <thead>
                <tr>
                   <th className="text-left p-2">{t('users.name')}</th>
                   <th className="text-left p-2">{t('users.email')}</th>
                   <th className="text-left p-2">{t('users.role')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-t">
                    <td className="p-2">{u.first_name} {u.last_name}</td>
                    <td className="p-2 text-muted-foreground">{u.email}</td>
                    <td className="p-2"><Badge variant="outline">{u.role}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="mt-3 space-y-2">
              <Link href="/admin/team" className="flex items-center gap-1 text-primary text-sm hover:underline">
                {t('nav.userManagement')} <ChevronRight className="w-4 h-4" />
              </Link>
              <Link href="/admin/staff?tab=import" className="flex items-center gap-1 text-primary text-sm hover:underline">
                {t('nav.staffSchedule')} <ChevronRight className="w-4 h-4" />
              </Link>
              <Link href="/admin/staff?tab=structure" className="flex items-center gap-1 text-primary text-sm hover:underline">
                {t('admin.staffStructure')} <ChevronRight className="w-4 h-4" />
              </Link>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('admin.recentCourses')}</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <thead>
                <tr>
                  <th className="text-left p-2">{t('admin.courses')}</th>
                  <th className="text-left p-2">{t('users.status')}</th>
                  <th className="text-left p-2">{t('courses.enrollments')}</th>
                </tr>
              </thead>
              <tbody>
                {courses.slice(0, 5).map((c) => (
                  <tr key={c.id} className="border-t">
                    <td className="p-2">{c.title}</td>
                    <td className="p-2">
                      <Badge variant={c.status === 'published' ? 'default' : 'outline'}>
                        {c.status}
                      </Badge>
                    </td>
                    <td className="p-2">{c.enrollment_count}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <a href="/courses" className="flex items-center gap-1 text-primary text-sm hover:underline mt-2 block">
              {t('admin.allCourses')} <ChevronRight className="w-4 h-4" />
            </a>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
