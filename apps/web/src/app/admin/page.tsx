'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

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

export default function AdminDashboardPage() {
  const { t } = useT();
  const [stats, setStats] = useState<TenantStats | null>(null);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [courses, setCourses] = useState<CourseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const [statsRes, usersRes, coursesRes] = await Promise.all([
        fetch(`${API_URL}/v1/admin/stats`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/v1/users?per_page=5`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/v1/courses`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);

      if (statsRes.ok) setStats(await statsRes.json());
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users || []);
      }
      if (coursesRes.ok) setCourses(await coursesRes.json());
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

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (!stats) return <div className="p-6">{t('common.error')}</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t('admin.title')}</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => handleExport('users')}>{t('admin.exportUsers')}</Button>
          <Button variant="outline" onClick={() => handleExport('courses')}>{t('admin.exportCourses')}</Button>
          <Button variant="outline" onClick={() => handleExport('enrollments')}>{t('admin.exportEnrollments')}</Button>
          <Button variant="outline" onClick={() => handleExport('quiz-results')}>{t('admin.exportQuizResults')}</Button>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-blue-600">{stats.total_users}</div>
            <div className="text-sm text-gray-500">{t('admin.stats.totalUsers')}</div>
            <div className="text-xs text-gray-400">{stats.active_users} {t('admin.stats.activeUsers')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-green-600">{stats.total_courses}</div>
            <div className="text-sm text-gray-500">{t('admin.stats.totalCourses')}</div>
            <div className="text-xs text-gray-400">{stats.published_courses} {t('admin.stats.published')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-orange-600">{stats.total_enrollments}</div>
            <div className="text-sm text-gray-500">{t('admin.stats.enrollments')}</div>
            <div className="text-xs text-gray-400">{stats.completed_enrollments} {t('admin.stats.completed')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-purple-600">{stats.certificates_issued}</div>
            <div className="text-sm text-gray-500">{t('admin.stats.certificates')}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{stats.ai_generated_courses}</div>
            <div className="text-sm text-gray-500">{t('admin.stats.aiGenerated')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{stats.total_quizzes_taken}</div>
            <div className="text-sm text-gray-500">{t('admin.stats.quizzesTaken')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{stats.average_quiz_score}%</div>
            <div className="text-sm text-gray-500">{t('admin.stats.averageScore')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">{formatBytes(stats.storage_used_bytes)}</div>
            <div className="text-sm text-gray-500">{t('admin.stats.storage')}</div>
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
                    <td className="p-2 text-gray-500">{u.email}</td>
                    <td className="p-2"><Badge variant="outline">{u.role}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <a href="/admin/users" className="text-blue-600 text-sm hover:underline mt-2 block">
              {t('admin.allUsers')} →
            </a>
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
                  <th className="text-left p-2">Название</th>
                  <th className="text-left p-2">Статус</th>
                  <th className="text-left p-2">Записей</th>
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
            <a href="/courses" className="text-blue-600 text-sm hover:underline mt-2 block">
              {t('admin.allCourses')} →
            </a>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
