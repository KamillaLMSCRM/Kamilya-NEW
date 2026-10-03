'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Card, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { CheckCircle2 } from 'lucide-react';
import { api } from '@/lib/api';

interface EnrolledCourse {
  course_id: string;
  title: string;
  description: string;
  status: string;
  enrollment_status: string;
  progress_percent: number;
  total_lessons: number;
  completed_lessons: number;
  enrolled_at: string;
}

export default function MyCoursesPage() {
  const { t, tp } = useT();
  const [courses, setCourses] = useState<EnrolledCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const [filter, setFilter] = useState<'all' | 'active' | 'completed'>('all');
  const token = useAuthStore((s) => s.accessToken);
  const hasSession = Boolean(token);

  const fetchCourses = useCallback(async (isActive: () => boolean) => {
    if (!hasSession) {
      if (isActive()) {
        setCourses([]);
        setLoadError(false);
        setLoading(false);
      }
      return;
    }
    setLoading(true);
    setLoadError(false);
    try {
      const response = await api.get<{ enrolled_courses?: EnrolledCourse[] }>('/v1/student/dashboard');
      if (isActive()) setCourses(response.data.enrolled_courses || []);
    } catch {
      if (isActive()) {
        setCourses([]);
        setLoadError(true);
      }
    } finally {
      if (isActive()) setLoading(false);
    }
  }, [hasSession]);

  useEffect(() => {
    let active = true;
    void fetchCourses(() => active);
    return () => { active = false; };
  }, [fetchCourses, retryNonce]);

  const filteredCourses = courses.filter((c) => {
    if (filter === 'active') return c.enrollment_status !== 'completed';
    if (filter === 'completed') return c.enrollment_status === 'completed';
    return true;
  });

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (loadError) return (
    <div className="space-y-3 p-6" role="alert">
      <p>{t('common.loadFailed')}</p>
      <Button type="button" onClick={() => setRetryNonce((value) => value + 1)}>{t('common.retry')}</Button>
    </div>
  );

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
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/70'
              }`}
            >
              {f === 'all' ? t('common.all') : f === 'active' ? t('student.inProgress') : t('student.completed')}
            </button>
          ))}
        </div>
      </div>

      {filteredCourses.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
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
                  {course.enrollment_status === 'completed' && (
                    <Badge className="flex items-center gap-1 bg-success/15 text-success">
                      <CheckCircle2 className="w-3 h-3" />
                    </Badge>
                  )}
                </div>

                <p className="text-sm text-muted-foreground mb-3 line-clamp-2">{course.description}</p>

                <div className="mb-3">
                  <div className="flex justify-between text-xs text-muted-foreground mb-1">
                    <span>
                      {course.completed_lessons} из {tp('common.counts.lessonTotal', course.total_lessons)}
                    </span>
                    <span>{course.progress_percent}%</span>
                  </div>
                  <div className="h-2 bg-muted rounded">
                    <div
                      className="h-2 bg-primary rounded transition-all"
                      style={{ width: `${course.progress_percent}%` }}
                    />
                  </div>
                </div>

                <div className="flex gap-2">
                  <Link href={`/courses/${course.course_id}`} className="flex-1">
                    <Button variant="outline" className="w-full" size="sm">
                      {course.progress_percent === 0 ? t('courses.startCourse') : t('courses.continueCourse')}
                    </Button>
                  </Link>
                  {course.enrollment_status === 'completed' && (
                    <Link href="/certificates">
                      <Button size="sm">{t('courses.viewCertificate')}</Button>
                    </Link>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
            )}

    </div>
  );}
