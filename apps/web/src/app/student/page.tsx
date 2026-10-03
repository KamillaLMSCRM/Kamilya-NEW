'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import Link from 'next/link';
import { CheckCircle2, PlayCircle } from 'lucide-react';
import { useLanguageStore } from '@/store/languageStore';
import { assignmentSourceLabel, formatAssignmentDueAt, safeResumeHref, selectNextAssignment, studentDailyLearningCopy } from '@/features/student-daily-learning/nextAssignment';

interface EnrolledCourse {
  enrollment_id?: string;
  course_id: string;
  can_resume?: boolean;
  title: string;
  description: string;
  status: string;
  enrollment_status: string;
  delivery_type: 'native' | 'scorm';
  progress_percent: number;
  total_lessons: number;
  completed_lessons: number;
  enrolled_at: string;
  thumbnail_url: string | null;
  assignment_due_at: string | null;
  assignment_source: string | null;
  resume_href: string | null;
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
  const { t, tp } = useT();
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const token = useAuthStore((s) => s.accessToken);
  const lang = useLanguageStore((s) => s.lang);
  const copy = studentDailyLearningCopy[lang] ?? studentDailyLearningCopy.ru;
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  useEffect(() => {
    if (!token) {
      setDashboard(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setLoadError(false);
    setDashboard(null);
    fetch(`${API_URL}/v1/student/dashboard`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    }).then(async (res) => {
      if (!res.ok) throw new Error('dashboard_request_failed');
      const data = await res.json();
      if (active) setDashboard(data);
    }).catch((error: unknown) => {
      if (active && !(error instanceof DOMException && error.name === 'AbortError')) {
        setLoadError(true);
        setDashboard(null);
      }
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, API_URL, retryNonce]);

  const retry = useCallback(() => {
    // Updating a stable retry nonce reruns the authenticated, abortable fetch.
    setRetryNonce((value) => value + 1);
  }, []);

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (!dashboard) return loadError ? (
    <div className="p-6 space-y-3" role="alert">
      <p>{copy.loadError}</p>
      <Button onClick={retry}>{copy.retry}</Button>
    </div>
  ) : <div className="p-6">{t('common.error')}</div>;

  const nextCourse = selectNextAssignment(dashboard.enrolled_courses);
  const nextDueLabel = nextCourse ? formatAssignmentDueAt(nextCourse.assignment_due_at, lang) : null;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t('student.title')}</h1>
        <p className="text-muted-foreground">{t('dashboard.welcome')}, {dashboard.full_name || t('student.learnerFallback')}!</p>
      </div>

      {nextCourse && (
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-primary">{t('student.resumeTitle')}</p>
              <h2 className="mt-1 break-words text-lg font-semibold text-foreground">{nextCourse.title}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {nextCourse.progress_percent >= 100 ? copy.remainingSteps : t('student.resumeDescription', { percent: nextCourse.progress_percent })}
              </p>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {nextDueLabel && (
                  <span>{copy.due}: {nextDueLabel}</span>
                )}
                {nextDueLabel && Date.parse(nextCourse.assignment_due_at ?? '') < Date.now() && (
                  <span className="font-medium text-destructive">{copy.overdue}</span>
                )}
                {assignmentSourceLabel(nextCourse.assignment_source, lang) && (
                  <span>{copy.source}: {assignmentSourceLabel(nextCourse.assignment_source, lang)}</span>
                )}
              </div>
            </div>
            <Link href={safeResumeHref(nextCourse)} className="shrink-0">
              <Button className="gap-2"><PlayCircle className="h-4 w-4" aria-hidden="true" />{nextCourse.progress_percent === 0 ? t('courses.startCourse') : t('courses.continueCourse')}</Button>
            </Link>
          </CardContent>
        </Card>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-primary">{dashboard.total_courses}</div>
            <div className="text-sm text-muted-foreground">{t('courses.title')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-success">{dashboard.completed_courses}</div>
            <div className="text-sm text-muted-foreground">{t('student.completed')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-warning">{dashboard.total_progress_percent}%</div>
            <div className="text-sm text-muted-foreground">{t('dashboard.overallProgress')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-bold text-accent">{dashboard.certificates_count}</div>
            <div className="text-sm text-muted-foreground">{t('dashboard.certificatesCount')}</div>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-4">{t('student.enrolledCourses')}</h2>
        {dashboard.enrolled_courses.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
              <p className="text-muted-foreground">{t('student.noCourses')}</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {dashboard.enrolled_courses.map((course, index) => (
              <Card key={course.enrollment_id || `${course.course_id}:${index}`} className="hover:shadow-md transition-shadow">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="font-medium line-clamp-2">{course.title}</h3>
                    {course.enrollment_status === 'completed' ? (
                      <Badge variant="default" className="flex items-center gap-1 bg-success/15 text-success">
                        <CheckCircle2 className="w-3 h-3" />
                      </Badge>
                    ) : null}
                  </div>

                  <p className="text-sm text-muted-foreground mb-3 line-clamp-2">{course.description}</p>

                  <div className="mb-3">
                    <div className="flex justify-between text-xs text-muted-foreground mb-1">
                      <span>
                        {t('courses.lessonsCount', {
                          done: course.completed_lessons,
                          totalText: tp('common.counts.lessonTotal', course.total_lessons),
                        })}
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
                    {course.can_resume === false ? (
                      <p className="text-sm text-muted-foreground" role="status">{copy.assignmentAccessRequired}</p>
                    ) : (
                      <Link href={`/courses/${course.course_id}`} className="flex-1">
                        <Button variant="outline" className="w-full" size="sm">
                          {course.enrollment_status === 'completed'
                            ? t('courses.viewResult')
                            : course.progress_percent === 0
                              ? t('courses.startCourse')
                              : t('courses.continueCourse')}
                        </Button>
                      </Link>
                    )}
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
    </div>
  );
}
