'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Badge, Button } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { CheckCircle2, Clock, Play, BookOpen, Lock } from 'lucide-react';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceStat, WorkspaceToolbar } from '@/features/workspace-design';

interface EnrolledQuiz {
  quiz_id: string;
  quiz_title: string;
  lesson_title: string;
  module_title: string;
  course_id: string;
  pass_score: number;
  deferral_days: number;
  attempt_limit: number;
  score_percent: number | null;
  passed: boolean;
  completed_at: string | null;
  attempts_count: number;
  is_expired: boolean;
}

export default function MyQuizzesPage() {
  const { t, tp } = useT();
  const [quizzes, setQuizzes] = useState<EnrolledQuiz[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(false);
    api.get<EnrolledQuiz[]>('/v1/quizzes/enrolled')
      .then((res) => {
        if (active) setQuizzes(res.data || []);
      })
      .catch(() => {
        if (active) {
          setQuizzes([]);
          setLoadError(true);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [retryNonce]);

  const pending = quizzes.filter((q) => !q.passed);
  const completed = quizzes.filter((q) => q.passed);

  if (loading) return <WorkspacePage id="my-quizzes" title={t('student.myQuizzes')}><WorkspacePanel aria-busy="true"><p role="status">{t('common.loading')}</p></WorkspacePanel></WorkspacePage>;
  if (loadError) return (
    <WorkspacePage id="my-quizzes" title={t('student.myQuizzes')}><WorkspacePanel role="alert" bodyClassName="space-y-3">
      <p>{t('common.loadFailed')}</p>
      <Button type="button" onClick={() => setRetryNonce((value) => value + 1)}>{t('common.retry')}</Button>
    </WorkspacePanel></WorkspacePage>
  );

  return (
    <WorkspacePage id="my-quizzes" title={t('student.myQuizzes')} icon={<BookOpen />}>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        <WorkspaceStat label={t('student.totalQuizzes')} value={quizzes.length} />
        <WorkspaceStat label={t('student.pendingQuizzes')} value={pending.length} tone="warning" />
        <WorkspaceStat label={t('student.passedQuizzes')} value={completed.length} tone="success" />
      </div>

      {quizzes.length > 0 && <WorkspaceToolbar aria-label={t('student.myQuizzes')}>
        {pending.length > 0 && <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 text-sm font-medium hover:bg-muted" href="#pending-quizzes">{t('student.toComplete')}</a>}
        {completed.length > 0 && <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 text-sm font-medium hover:bg-muted" href="#completed-quizzes">{t('student.completedQuizzes')}</a>}
      </WorkspaceToolbar>}

      {/* Pending */}
      {pending.length > 0 && (
        <WorkspacePanel id="pending-quizzes" title={t('student.toComplete')} padded={false} bodyClassName="divide-y divide-border">
          {pending.map((q) => (
            <article key={q.quiz_id} className="flex min-w-0 flex-wrap items-start gap-4 p-5 sm:items-center sm:p-6">
                {q.is_expired ? (
                  <Lock className="w-5 h-5 text-destructive" aria-hidden="true" />
                ) : (
                  <Clock className="w-5 h-5 text-warning" aria-hidden="true" />
                )}
                <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                  <h3 className="break-words font-semibold text-foreground">{q.quiz_title}</h3>
                  <div className="mt-2 flex items-start gap-1 text-xs leading-5 text-muted-foreground">
                    <BookOpen className="w-3 h-3" aria-hidden="true" />
                    {q.module_title} → {q.lesson_title}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t('quiz.passScore')}: {q.pass_score}% · {t('quiz.deferralDays')}:{' '}
                    {tp('common.counts.day', q.deferral_days)}
                    {q.attempts_count > 0 && ` · ${t('quiz.attempts')}: ${q.attempts_count}/${q.attempt_limit}`}
                  </div>
                  {q.is_expired && (
                    <div className="text-xs text-destructive mt-1">
                      {t('quiz.expiredHint', {
                        daysText: tp('common.counts.day', q.deferral_days),
                      })}
                    </div>
                  )}
                </div>
                {q.is_expired ? (
                  <Badge variant="destructive">{t('quiz.expired')}</Badge>
                ) : (
                  <Badge variant="outline">{t('student.pendingBadge')}</Badge>
                )}
                {q.is_expired ? (
                  <Button
                    size="sm"
                    disabled
                    aria-disabled="true"
                    title={t('quiz.expiredHint', {
                      daysText: tp('common.counts.day', q.deferral_days),
                    })}
                  >
                    <Play className="w-4 h-4 mr-1" aria-hidden="true" /> {t('quiz.notAvailable')}
                  </Button>
                ) : (
                  <a href={`/courses/quiz/${q.quiz_id}`}>
                    <Button size="sm">
                      <Play className="w-4 h-4 mr-1" aria-hidden="true" /> {t('student.takeQuiz')}
                    </Button>
                  </a>
                )}
            </article>
          ))}
        </WorkspacePanel>
      )}

      {/* Completed */}
      {completed.length > 0 && (
        <WorkspacePanel id="completed-quizzes" title={t('student.completedQuizzes')} padded={false} bodyClassName="divide-y divide-border">
          {completed.map((q) => (
            <article key={q.quiz_id} className="flex min-w-0 flex-wrap items-center gap-4 p-5 sm:p-6">
                <CheckCircle2 className="w-5 h-5 text-success" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <h3 className="break-words font-semibold text-foreground">{q.quiz_title}</h3>
                  <div className="text-xs text-muted-foreground">
                    {q.module_title} → {q.lesson_title}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t('student.passedOn')} {q.completed_at ? new Date(q.completed_at).toLocaleDateString('ru-RU') : ''}
                    {q.attempts_count > 0 && ` · ${t('quiz.attempts')}: ${q.attempts_count}`}
                  </div>
                </div>
                <Badge variant="default">{q.score_percent == null ? '—' : `${q.score_percent}%`}</Badge>
            </article>
          ))}
        </WorkspacePanel>
      )}

      {quizzes.length === 0 && (
        <WorkspaceEmpty title={t('student.noQuizzes') || 'У вас пока нет тестов.'} icon={<BookOpen />} action={
            <Link href="/my-courses" className="text-primary hover:underline text-sm mt-2 inline-block">
              {t('student.browseCourses')}
            </Link>
        } />
      )}
    </WorkspacePage>
  );
}
