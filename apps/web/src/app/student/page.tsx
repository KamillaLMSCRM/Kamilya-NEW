'use client';

import { useState, useEffect, useCallback } from 'react';
import { Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import Link from 'next/link';
import { CheckCircle2, PlayCircle } from 'lucide-react';
import { useLanguageStore } from '@/store/languageStore';
import { assignmentSourceLabel, formatAssignmentDueAt, safeResumeHref, selectNextAssignment, studentDailyLearningCopy } from '@/features/student-daily-learning/nextAssignment';
import { AssignmentDetails } from '@/features/student-daily-learning/AssignmentDetails';
import { getLearnerWorkspaceCopy } from '@/features/learner-workspace/copy';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceStat } from '@/features/workspace-design';

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
  const token = useAuthStore((state) => state.accessToken);
  const user = useAuthStore((state) => state.user);
  return <ScopedStudentDashboard key={`${token}:${user?.user_id}:${user?.tenant_id}:${user?.role}`} />;
}

function ScopedStudentDashboard() {
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

  if (loading) return <WorkspacePage id="student" title={t('student.title')}><WorkspacePanel aria-busy="true"><p role="status">{t('common.loading')}</p></WorkspacePanel></WorkspacePage>;
  if (!dashboard) return loadError ? (
    <WorkspacePage id="student" title={t('student.title')}><WorkspacePanel role="alert" bodyClassName="space-y-3">
      <p>{copy.loadError}</p>
      <Button onClick={retry}>{copy.retry}</Button>
    </WorkspacePanel></WorkspacePage>
  ) : <WorkspacePage id="student" title={t('student.title')}><WorkspaceEmpty title={t('common.error')} /></WorkspacePage>;

  const nextCourse = selectNextAssignment(dashboard.enrolled_courses);
  const nextDueLabel = nextCourse ? formatAssignmentDueAt(nextCourse.assignment_due_at, lang) : null;

  return (
    <WorkspacePage id="student" title={t('student.title')} description={<>{t('dashboard.welcome')}, {dashboard.full_name || t('student.learnerFallback')}!</>} icon={<PlayCircle />}>

      {nextCourse && (
        <WorkspacePanel className="overflow-hidden border-primary/25" bodyClassName="flex flex-col gap-5 border-l-4 border-primary bg-primary/5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-primary">{getLearnerWorkspaceCopy(lang).next}</p>
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
        </WorkspacePanel>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <WorkspaceStat label={t('courses.title')} value={dashboard.total_courses} />
        <WorkspaceStat label={t('student.completed')} value={dashboard.completed_courses} tone="success" />
        <WorkspaceStat label={t('dashboard.overallProgress')} value={dashboard.total_progress_percent == null ? null : `${dashboard.total_progress_percent}%`} />
        <WorkspaceStat label={t('dashboard.certificatesCount')} value={dashboard.certificates_count} />
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-4">{t('student.enrolledCourses')}</h2>
        {dashboard.enrolled_courses.length === 0 ? (
          <WorkspaceEmpty title={t('student.noCourses')} icon={<PlayCircle />} />
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {dashboard.enrolled_courses.map((course, index) => (
              <WorkspacePanel key={course.enrollment_id || `${course.course_id}:${index}`} className="transition-shadow hover:shadow-md" bodyClassName="h-full">
                <article className="flex h-full min-w-0 flex-col">
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="min-w-0 break-words font-semibold">{course.title}</h3>
                    {course.enrollment_status === 'completed' ? (
                      <Badge variant="default" className="flex items-center gap-1 bg-success/15 text-success">
                        <CheckCircle2 className="w-3 h-3" />
                      </Badge>
                    ) : null}
                  </div>

                  <p className="text-sm text-muted-foreground mb-3 line-clamp-2">{course.description}</p>
                  <AssignmentDetails course={course} />

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

                  <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-border pt-4 [&_button]:h-auto [&_button]:min-h-11 [&_button]:py-2 [&_button]:whitespace-normal">
                    {course.can_resume === false ? (
                      <p className="text-sm text-muted-foreground" role="status">{copy.assignmentAccessRequired}</p>
                    ) : (
                      <Link href={safeResumeHref(course)} className="flex-1">
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
                </article>
              </WorkspacePanel>
            ))}
          </div>
        )}
      </div>
    </WorkspacePage>
  );
}
