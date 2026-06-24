'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, Badge, Button } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { CheckCircle2, Clock, Play, BookOpen } from 'lucide-react';

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
      <h1 className="text-2xl font-bold text-warm-800 font-display">Мои тесты</h1>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-warm-800">{quizzes.length}</div>
            <div className="text-xs text-warm-400">Всего тестов</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-amber-500">{pending.length}</div>
            <div className="text-xs text-warm-400">Ожидают</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-emerald-500">{completed.length}</div>
            <div className="text-xs text-warm-400">Пройдено</div>
          </CardContent>
        </Card>
      </div>

      {/* Pending */}
      {pending.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-warm-800">Нужно пройти</h2>
          {pending.map((q) => (
            <Card key={q.quiz_id}>
              <CardContent className="p-4 flex items-center gap-4">
                <Clock className="w-5 h-5 text-amber-500" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-warm-800 truncate">{q.quiz_title}</div>
                  <div className="text-xs text-warm-400 flex items-center gap-1">
                    <BookOpen className="w-3 h-3" />
                    {q.module_title} → {q.lesson_title}
                  </div>
                  <div className="text-xs text-warm-400">
                    Порог: {q.pass_score}% · Дедлайн: {q.deferral_days} дн.
                  </div>
                </div>
                <Badge variant="outline">Ожидает</Badge>
                <a href={`/courses/quiz/${q.quiz_id}`}>
                  <Button size="sm">
                    <Play className="w-4 h-4 mr-1" /> Пройти
                  </Button>
                </a>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Completed */}
      {completed.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-warm-800">Пройденные</h2>
          {completed.map((q) => (
            <Card key={q.quiz_id}>
              <CardContent className="p-4 flex items-center gap-4">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-warm-800 truncate">{q.quiz_title}</div>
                  <div className="text-xs text-warm-400">
                    {q.module_title} → {q.lesson_title}
                  </div>
                  <div className="text-xs text-warm-400">
                    Пройден {q.completed_at ? new Date(q.completed_at).toLocaleDateString('ru-RU') : ''}
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
          <CardContent className="p-8 text-center text-warm-400">
            <p>У вас пока нет тестов.</p>
            <a href="/courses" className="text-blue-600 hover:underline text-sm mt-2 inline-block">
              Перейти к курсам
            </a>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
