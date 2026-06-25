'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { ChevronRight } from 'lucide-react';
import { api } from '@/lib/api';
import { toast } from '@/components/ui/Toast';

interface Stat {
  label: string;
  value: string | number;
  delta?: string;
  icon: React.ReactNode;
  color: string;
}

interface PipelineJob {
  id: string;
  status: string;
  course_title?: string;
  created_at: string;
}

export default function DashboardPage() {
  const { user } = useAuthStore();
  const { t } = useT();
  const [stats, setStats] = useState<{ totalCourses: number; publishedCourses: number; totalEnrollments: number; completedEnrollments: number } | null>(null);
  const [pipelineJobs, setPipelineJobs] = useState<PipelineJob[]>([]);
  const [recentCourses, setRecentCourses] = useState<any[]>([]);

  useEffect(() => {
    fetchStats();
    fetchPipeline();
    fetchRecentCourses();
  }, []);

  const fetchStats = async () => {
    try {
      const [coursesRes, enrollmentsRes] = await Promise.all([
        api.get('/v1/courses'),
        api.get('/v1/enrollments/stats').catch(() => null),
      ]);
      const courses = coursesRes.data;
      setStats({
        totalCourses: Array.isArray(courses) ? courses.length : 0,
        publishedCourses: Array.isArray(courses) ? courses.filter((c: any) => c.status === 'published').length : 0,
        totalEnrollments: enrollmentsRes?.data?.total ?? 0,
        completedEnrollments: enrollmentsRes?.data?.completed ?? 0,
      });
    } catch (err: any) {
      toast.error(t('common.loadFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    }
  };

  const fetchPipeline = async () => {
    try {
      const res = await api.get('/v1/ai/jobs');
      if (Array.isArray(res.data)) {
        setPipelineJobs(res.data.filter((j: any) => j.status !== 'completed').slice(0, 5));
      }
    } catch {}
  };

  const fetchRecentCourses = async () => {
    try {
      const res = await api.get('/v1/courses');
      if (Array.isArray(res.data)) {
        setRecentCourses(res.data.slice(0, 4));
      }
    } catch {}
  };

  const statCards: Stat[] = [
    {
      label: t('dashboard.totalCourses'),
      value: stats?.totalCourses ?? '—',
      delta: stats?.publishedCourses ? `${stats.publishedCourses} ${t('common.published')}` : undefined,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
        </svg>
      ),
      color: 'bg-primary/10 text-primary',
    },
    {
      label: t('dashboard.completedCourses'),
      value: stats?.completedEnrollments ?? '—',
      delta: stats?.totalEnrollments ? `${t('common.of')} ${stats.totalEnrollments} ${t('courses.enrollments')}` : undefined,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      ),
      color: 'bg-success/15 text-success',
    },
    {
      label: t('dashboard.aiGenerations'),
      value: pipelineJobs.length,
      delta: pipelineJobs.length > 0 ? t('dashboard.inProgress') : t('dashboard.queueEmpty'),
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4Z" />
          <circle cx="12" cy="15" r="2" />
        </svg>
      ),
      color: 'bg-accent/15 text-accent',
    },
    {
      label: t('dashboard.employees'),
      value: stats?.totalEnrollments ?? '—',
      delta: stats?.completedEnrollments
        ? t('dashboard.employeesDone', { count: stats.completedEnrollments })
        : undefined,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      ),
      color: 'bg-accent/15 text-accent-foreground',
    },
  ];

  const kanbanColumns = [
    { key: 'queued', label: t('dashboard.kanban.queued'), color: 'bg-muted-foreground/40' },
    { key: 'ingesting', label: t('dashboard.kanban.ingesting'), color: 'bg-accent' },
    { key: 'architecting', label: t('dashboard.kanban.architecting'), color: 'bg-primary' },
    { key: 'generating', label: t('dashboard.kanban.generating'), color: 'bg-info' },
    { key: 'reviewing', label: t('dashboard.kanban.reviewing'), color: 'bg-accent' },
  ];

  return (
    <div className="space-y-8">
      {/* Welcome */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground font-display">
            {t('dashboard.welcome')}, {user?.full_name?.split(' ')[0] || ''}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('dashboard.subtitle')}</p>
        </div>
        <Link
          href="/ai/generate"
          className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          {t('dashboard.newCourse')}
        </Link>
      </div>

      {/* Stat cards */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((stat, i) => (
          <div
            key={stat.label}
            className={`group relative rounded-2xl border border-border bg-card p-5 shadow-card hover:shadow-card-hover transition-all duration-300 animate-fade-up stagger-${i + 1}`}
            style={{ opacity: 0, animationFillMode: 'forwards' }}
          >
            <div className="flex items-start justify-between">
              <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${stat.color}`}>
                {stat.icon}
              </div>
            </div>
            <div className="mt-4">
              <div className="text-2xl font-bold text-foreground font-display">{stat.value}</div>
              <div className="text-sm text-muted-foreground mt-0.5">{stat.label}</div>
            </div>
            {stat.delta && (
              <div className="mt-2 text-[11px] text-muted-foreground">{stat.delta}</div>
            )}
          </div>
        ))}
      </div>

      {/* Kanban pipeline */}
      <div>
        <h2 className="text-lg font-bold text-foreground font-display mb-4">{t('dashboard.aiPipeline')}</h2>
        <div className="flex gap-4 overflow-x-auto pb-4">
          {kanbanColumns.map((col) => {
            const jobs = pipelineJobs.filter((j) => {
              if (col.key === 'queued') return j.status === 'queued';
              if (col.key === 'ingesting') return j.status === 'ingesting' || j.status === 'ingestion';
              if (col.key === 'architecting') return j.status === 'architecting' || j.status === 'architect';
              if (col.key === 'generating') return j.status === 'generating' || j.status === 'content_generation';
              if (col.key === 'reviewing') return j.status === 'reviewing' || j.status === 'review' || j.status === 'assessment';
              return false;
            });

            return (
              <div key={col.key} className="kanban-col">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
                  <span className={`h-2 w-2 rounded-full ${col.color}`} aria-hidden="true" />
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{col.label}</span>
                  <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                    {jobs.length}
                  </span>
                </div>
                <div className="scroll-inner">
                  {jobs.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                      {t('dashboard.kanban.empty')}
                    </div>
                  ) : (
                    jobs.map((job) => (
                      <div key={job.id} className="kanban-card">
                        <div className="text-sm font-medium text-foreground truncate">
                          {job.course_title || job.id.slice(0, 8)}
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          {new Date(job.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Recent courses */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-foreground font-display">{t('dashboard.lastCourses')}</h2>
          <Link href="/courses" className="flex items-center gap-1 text-sm text-primary hover:text-primary/80 transition-colors">
            {t('dashboard.allCourses')} <ChevronRight className="w-4 h-4" aria-hidden="true" />
          </Link>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {recentCourses.map((course) => (
            <Link
              key={course.id}
              href={`/courses/${course.id}`}
              className="group block rounded-2xl border border-border bg-card overflow-hidden shadow-card hover:shadow-card-hover transition-all duration-300 hover:-translate-y-1"
            >
              {/* Gradient header */}
              <div className="h-24 bg-gradient-to-br from-primary/20 via-primary/10 to-accent/10 p-4 flex items-end">
                <span className="text-xs font-medium text-primary bg-card/80 backdrop-blur-sm rounded-full px-2.5 py-1">
                  {course.status === 'published' ? t('courses.published') : t('courses.draft')}
                </span>
              </div>
              <div className="p-4">
                <h3 className="text-sm font-bold text-foreground group-hover:text-primary transition-colors truncate">
                  {course.title}
                </h3>
                {course.description && (
                  <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{course.description}</p>
                )}
              </div>
            </Link>
          ))}
          {recentCourses.length === 0 && (
            <div className="col-span-full rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              {t('dashboard.noCoursesHint')}{' '}
              <Link href="/ai/generate" className="text-primary hover:underline">
                {t('dashboard.aiGeneration')}
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
