'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';

interface EnrolledCourse {
  course_id: string;
  title: string;
  description: string;
  status: string;
  progress_percent: number;
  total_lessons: number;
  completed_lessons: number;
  enrolled_at: string;
  thumbnail_url: string | null;
}

interface DashboardData {
  user_id: string;
  full_name: string;
  enrolled_courses: EnrolledCourse[];
  total_courses: number;
  completed_courses: number;
  total_progress_percent: number;
  certificates_count: number;
}

export default function StudentDashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const token = useAuthStore((s) => s.token);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchDashboard = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/student/dashboard`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setDashboard(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  if (loading) return <div className="p-6">Загрузка...</div>;
  if (!dashboard) return <div className="p-6">Ошибка загрузки</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Мой дашборд</h1>
        <p className="text-gray-500">Добро пожаловать, {dashboard.full_name || 'Студент'}!</p>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-blue-600">{dashboard.total_courses}</div>
            <div className="text-sm text-gray-500">Курсов</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-green-600">{dashboard.completed_courses}</div>
            <div className="text-sm text-gray-500">Завершено</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-orange-600">{dashboard.total_progress_percent}%</div>
            <div className="text-sm text-gray-500">Общий прогресс</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-purple-600">{dashboard.certificates_count}</div>
            <div className="text-sm text-gray-500">Сертификатов</div>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-4">Мои курсы</h2>
        {dashboard.enrolled_courses.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-center text-gray-400">
              Вы пока не записаны ни на один курс
            </CardContent>
          </Card>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {dashboard.enrolled_courses.map((course) => (
              <Card key={course.course_id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="font-medium line-clamp-2">{course.title}</h3>
                    {course.progress_percent === 100 ? (
                      <Badge variant="default" className="bg-green-100 text-green-700">✓</Badge>
                    ) : null}
                  </div>

                  <p className="text-sm text-gray-500 mb-3 line-clamp-2">{course.description}</p>

                  <div className="mb-3">
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>{course.completed_lessons}/{course.total_lessons} уроков</span>
                      <span>{course.progress_percent}%</span>
                    </div>
                    <div className="h-2 bg-gray-200 rounded">
                      <div
                        className="h-2 bg-blue-600 rounded transition-all"
                        style={{ width: `${course.progress_percent}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <a href={`/courses/${course.course_id}`} className="flex-1">
                      <Button variant="outline" className="w-full" size="sm">
                        {course.progress_percent === 0 ? 'Начать' : 'Продолжить'}
                      </Button>
                    </a>
                    {course.progress_percent === 100 && (
                      <a href={`/courses/${course.course_id}/certificate`}>
                        <Button size="sm">Сертификат</Button>
                      </a>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
