'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Card, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { CheckCircle2, ChevronRight } from 'lucide-react';

interface EnrolledCourse {
  course_id: string;
  title: string;
  description: string;
  status: string;
  progress_percent: number;
  total_lessons: number;
  completed_lessons: number;
  enrolled_at: string;
}

export default function MyCoursesPage() {
  const { t } = useT();
  const [courses, setCourses] = useState<EnrolledCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'active' | 'completed'>('all');
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchCourses = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/student/dashboard`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setCourses(data.enrolled_courses || []);
      }
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  const filteredCourses = courses.filter((c) => {
    if (filter === 'active') return c.progress_percent < 100;
    if (filter === 'completed') return c.progress_percent === 100;
    return true;
  });

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t('student.enrolledCourses')}</h1>
        <div className="flex gap-2">
          {(['all', 'active', 'completed'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                filter === f
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {f === 'all' ? t('common.all') : f === 'active' ? t('student.inProgress') : t('student.completed')}
            </button>
          ))}
        </div>
      </div>

      {filteredCourses.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            {filter === 'all'
              ? t('student.noCourses')
              : filter === 'active'
              ? t('student.inProgress') + ' — ' + t('common.none')
              : t('student.completed') + ' — ' + t('common.none')}
          </CardContent>
        </Card>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCourses.map((course) => (
            <Card key={course.course_id} className="hover:shadow-md transition-shadow">
              <CardContent className="p-4">
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-medium line-clamp-2">{course.title}</h3>
                  {course.progress_percent === 100 && (
                    <Badge className="flex items-center gap-1 bg-green-100 text-green-700">
                      <CheckCircle2 className="w-3 h-3" />
                    </Badge>
                  )}
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
                      {course.progress_percent === 0 ? t('courses.startCourse') : t('courses.continueCourse')}
                    </Button>
                  </a>
                  {course.progress_percent === 100 && (
                    <a href={`/courses/${course.course_id}/certificate`}>
                      <Button size="sm">{t('courses.viewCertificate')}</Button>
                    </a>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
            )}

      {/* Browse available courses for self-enrollment */}
      <div className="mt-8 pt-6 border-t">
        <h2 className="text-lg font-semibold mb-4">{t('courses.browse')} <ChevronRight className="inline w-4 h-4" /></h2>
        <Link href="/courses">
          <Button variant="outline">{t('courses.viewAll')}</Button>
        </Link>
      </div>
    </div>
  );}
