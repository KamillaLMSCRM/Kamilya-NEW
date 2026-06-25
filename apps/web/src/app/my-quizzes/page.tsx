'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Card, CardContent, Badge, Button } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { CheckCircle2, Clock, Play, BookOpen, Lock } from 'lucide-react';

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
  const { t } = useT();
  const [quizzes, setQuizzes] = useState<EnrolledQuiz[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/v1/quizzes/enrolled')
      .then((res) => setQuizzes(res.data || []))
      .finally(() => setLoading(false));
  }, []);

  const pending = quizzes.filter((q) => !q.passed);
  const completed = quizzes.filter((q) => q.passed);

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-foreground font-display">{t('student.myQuizzes')}</h1>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-foreground">{quizzes.length}</div>
            <div className="text-xs text-muted-foreground">{t('student.totalQuizzes')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-warning">{pending.length}</div>
            <div className="text-xs text-muted-foreground">{t('student.pendingQuizzes')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-success">{completed.length}</div>
            <div className="text-xs text-muted-foreground">{t('student.passedQuizzes')}</div>
          </CardContent>
        </Card>
      </div>

      {/* Pending */}
      {pending.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-foreground">{t('student.toComplete')}</h2>
          {pending.map((q) => (
            <Card key={q.quiz_id}>
              <CardContent className="p-4 flex items-center gap-4">
                {q.is_expired ? (
                  <Lock className="w-5 h-5 text-destructive" aria-hidden="true" />
                ) : (
                  <Clock className="w-5 h-5 text-warning" aria-hidden="true" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-foreground truncate">{q.quiz_title}</div>
                  <div className="text-xs text-muted-foreground flex items-center gap-1">
                    <BookOpen className="w-3 h-3" aria-hidden="true" />
                    {q.module_title} → {q.lesson_title}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t('quiz.passScore')}: {q.pass_score}% · {t('quiz.deferralDays')}: {q.deferral_days} {t('quiz.days')}
                    {q.attempts_count > 0 && ` · ${t('quiz.attempts')}: ${q.attempts_count}/${q.attempt_limit}`}
                  </div>
                  {q.is_expired && (
                    <div className="text-xs text-destructive mt-1">
                      {t('quiz.expiredHint', { days: q.deferral_days })}
                    </div>
                  )}
                </div>
                {q.is_expired ? (
                  <Badge variant="destructive">{t('quiz.expired')}</Badge>
                ) : (
                  <Badge variant="outline">{t('student.pendingBadge')}</Badge>
                )}
                {q.is_expired ? (
                  <Button size="sm" disabled aria-disabled="true" title={t('quiz.expiredHint', { days: q.deferral_days })}>
                    <Play className="w-4 h-4 mr-1" aria-hidden="true" /> {t('quiz.notAvailable')}
                  </Button>
                ) : (
                  <a href={`/courses/quiz/${q.quiz_id}`}>
                    <Button size="sm">
                      <Play className="w-4 h-4 mr-1" aria-hidden="true" /> {t('student.takeQuiz')}
                    </Button>
                  </a>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Completed */}
      {completed.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-foreground">{t('student.completedQuizzes')}</h2>
          {completed.map((q) => (
            <Card key={q.quiz_id}>
              <CardContent className="p-4 flex items-center gap-4">
                <CheckCircle2 className="w-5 h-5 text-success" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-foreground truncate">{q.quiz_title}</div>
                  <div className="text-xs text-muted-foreground">
                    {q.module_title} → {q.lesson_title}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t('student.passedOn')} {q.completed_at ? new Date(q.completed_at).toLocaleDateString('ru-RU') : ''}
                    {q.attempts_count > 0 && ` · ${t('quiz.attempts')}: ${q.attempts_count}`}
                  </div>
                </div>
                <Badge variant="default">{q.score_percent}%</Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {quizzes.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            <p>{t('student.noQuizzes') || 'У вас пока нет тестов.'}</p>
            <Link href="/courses" className="text-primary hover:underline text-sm mt-2 inline-block">
              {t('student.browseCourses')}
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
