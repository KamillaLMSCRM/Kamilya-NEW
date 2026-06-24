'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, Badge, Button } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { CheckCircle2, Clock, AlertCircle, Play } from 'lucide-react';

interface QuizAssignment {
  id: string;
  quiz_id: string;
  quiz_title: string;
  status: string;
  score_percent: number | null;
  due_date: string | null;
  completed_at: string | null;
  created_at: string;
}

export default function MyQuizzesPage() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const [assignments, setAssignments] = useState<QuizAssignment[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAssignments = useCallback(async () => {
    if (!token) return;
    try {
      const res = await api.get('/v1/quiz-assignments/my');
      setAssignments(res.data || []);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { fetchAssignments(); }, [fetchAssignments]);

  const getStatusBadge = (a: QuizAssignment) => {
    if (a.status === 'completed') {
      return (
        <Badge variant={a.score_percent && a.score_percent >= 80 ? 'default' : 'destructive'}>
          {a.score_percent}%
        </Badge>
      );
    }
    if (a.due_date && new Date(a.due_date) < new Date()) {
      return <Badge variant="destructive">Просрочен</Badge>;
    }
    return <Badge variant="outline">Ожидает</Badge>;
  };

  const getStatusIcon = (a: QuizAssignment) => {
    if (a.status === 'completed') {
      return <CheckCircle2 className="w-5 h-5 text-emerald-500" />;
    }
    if (a.due_date && new Date(a.due_date) < new Date()) {
      return <AlertCircle className="w-5 h-5 text-red-500" />;
    }
    return <Clock className="w-5 h-5 text-warm-400" />;
  };

  const pending = assignments.filter(a => a.status !== 'completed');
  const completed = assignments.filter(a => a.status === 'completed');

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-warm-800 font-display">Мои тесты</h1>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-warm-800">{assignments.length}</div>
            <div className="text-xs text-warm-400">Всего</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold text-primary">{pending.length}</div>
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
          {pending.map(a => (
            <Card key={a.id}>
              <CardContent className="p-4 flex items-center gap-4">
                {getStatusIcon(a)}
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-warm-800 truncate">{a.quiz_title}</div>
                  {a.due_date && (
                    <div className="text-xs text-warm-400">
                      Срок: {new Date(a.due_date).toLocaleDateString('ru-RU')}
                    </div>
                  )}
                </div>
                {getStatusBadge(a)}
                <a href={`/courses/quiz/${a.quiz_id}`}>
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
          {completed.map(a => (
            <Card key={a.id}>
              <CardContent className="p-4 flex items-center gap-4">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-warm-800 truncate">{a.quiz_title}</div>
                  <div className="text-xs text-warm-400">
                    Пройден {a.completed_at ? new Date(a.completed_at).toLocaleDateString('ru-RU') : ''}
                  </div>
                </div>
                {getStatusBadge(a)}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {assignments.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-warm-400">
            Вам пока не назначено ни одного теста
          </CardContent>
        </Card>
      )}
    </div>
  );
}
