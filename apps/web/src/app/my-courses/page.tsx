'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { CheckCircle2 } from 'lucide-react';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';
import { safeResumeHref, studentDailyLearningCopy, type LearnerAssignment } from '@/features/student-daily-learning/nextAssignment';
import { AssignmentDetails } from '@/features/student-daily-learning/AssignmentDetails';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';

interface EnrolledCourse extends LearnerAssignment {
  description: string;
  status: string;
  enrollment_status: string;
  progress_percent: number;
  total_lessons: number;
  completed_lessons: number;
  enrolled_at: string;
}

export default function MyCoursesPage() {
  const user = useAuthStore((state) => state.user);
  const hasSession = useAuthStore((state) => Boolean(state.accessToken));
  return <ScopedMyCourses key={`${user?.user_id}:${user?.tenant_id}:${user?.role}:${hasSession}`} />;
}

function ScopedMyCourses() {
  const { t, tp } = useT();
  const lang = useLanguageStore((state) => state.lang);
  const copy = studentDailyLearningCopy[lang] ?? studentDailyLearningCopy.ru;
  const [courses, setCourses] = useState<EnrolledCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const [filter, setFilter] = useState<'all' | 'active' | 'completed'>('all');
  const hasSession = useAuthStore((state) => Boolean(state.accessToken));

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

  if (loading) return <WorkspacePage id="my-courses"><WorkspacePanel aria-busy="true"><p role="status">{t('common.loading')}</p></WorkspacePanel></WorkspacePage>;
  if (loadError) return (
    <WorkspacePage id="my-courses" title={t('student.enrolledCourses')}><WorkspacePanel bodyClassName="space-y-3" role="alert">
      <p>{t('common.loadFailed')}</p>
      <Button type="button" onClick={() => setRetryNonce((value) => value + 1)}>{t('common.retry')}</Button>
    </WorkspacePanel></WorkspacePage>
  );

  return (
    <WorkspacePage id="my-courses">
      <header className="flex min-w-0 flex-wrap items-start justify-between gap-5">
        <h1 className="min-w-0 break-words text-3xl font-semibold leading-tight tracking-tight">{t('student.enrolledCourses')}</h1>
      <WorkspaceToolbar aria-label={t('student.enrolledCourses')}>
        <div className="flex min-w-0 flex-wrap gap-2">
          {(['all', 'active', 'completed'] as const).map((f) => (
            <button
              key={f}
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={`min-h-11 px-4 py-2 text-sm rounded-xl transition-colors ${
                filter === f
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/70'
              }`}
            >
              {f === 'all' ? t('common.all') : f === 'active' ? t('student.inProgress') : t('student.completed')}
            </button>
          ))}
        </div>
      </WorkspaceToolbar>
      </header>

      {filteredCourses.length === 0 ? (
        <WorkspaceEmpty title={filter === 'all'
              ? t('student.noCourses')
              : filter === 'active'
              ? t('student.inProgress') + ' — ' + t('common.none')
               : t('student.completed') + ' — ' + t('common.none')} />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCourses.map((course, index) => (
            <WorkspacePanel key={course.enrollment_id || `${course.course_id}:${index}`} className="transition-shadow hover:shadow-md" bodyClassName="flex h-full flex-col">
                <div className="flex items-start justify-between mb-2">
                  <h2 className="break-words font-semibold">{course.title}</h2>
                  {course.enrollment_status === 'completed' && (
                    <Badge className="flex items-center gap-1 bg-success/15 text-success">
                      <CheckCircle2 className="w-3 h-3" />
                    </Badge>
                  )}
                </div>

                <p className="text-sm text-muted-foreground mb-3 line-clamp-2">{course.description}</p>
                <AssignmentDetails course={course} />

                <div className="mb-3">
                  <div className="flex justify-between text-xs text-muted-foreground mb-1">
                    <span>
                      {t('courses.lessonsCount', { done: course.completed_lessons, totalText: tp('common.counts.lessonTotal', course.total_lessons) })}
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
                  {course.can_resume === false ? <p role="status" className="text-sm text-muted-foreground">{copy.assignmentAccessRequired}</p> : <Link href={safeResumeHref(course)} className="flex-1">
                    <Button variant="outline" className="w-full" size="sm">
                      {course.enrollment_status === 'completed' ? t('courses.viewResult') : course.progress_percent === 0 ? t('courses.startCourse') : t('courses.continueCourse')}
                    </Button>
                  </Link>}
                  {course.enrollment_status === 'completed' && (
                    <Link href="/certificates">
                      <Button size="sm">{t('courses.viewCertificate')}</Button>
                    </Link>
                  )}
                </div>
            </WorkspacePanel>
          ))}
        </div>
      )}

    </WorkspacePage>
  );
}
