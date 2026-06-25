'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, Button, Badge, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { CheckCircle2, Trash2, UserPlus } from 'lucide-react';

interface Quiz {
  id: string;
  title: string;
}

interface User {
  id: string;
  full_name: string;
  role: string;
}

interface Assignment {
  id: string;
  quiz_id: string;
  quiz_title: string;
  user_id: string;
  user_name: string;
  status: string;
  score_percent: number | null;
  due_date: string | null;
  completed_at: string | null;
  created_at: string;
}

export default function QuizAssignPage() {
  const { t } = useT();
    const { confirm, dialog } = useConfirm();
  const token = useAuthStore((s) => s.accessToken);
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [selectedQuiz, setSelectedQuiz] = useState('');
  const [selectedUsers, setSelectedUsers] = useState<string[]>([]);
  const [dueDate, setDueDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [assigning, setAssigning] = useState(false);

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const [quizzesRes, usersRes, assignmentsRes] = await Promise.all([
        api.get('/v1/quizzes'),
        api.get('/v1/users'),
        api.get('/v1/quiz-assignments'),
      ]);
      setQuizzes(quizzesRes.data || []);
        setUsers((usersRes.data || []).filter((u: User) => u.role !== 'superadmin' && u.role !== 'admin'));
        setAssignments(assignmentsRes.data || []);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleAssign = async () => {
    if (!selectedQuiz || selectedUsers.length === 0) return;
    setAssigning(true);
    try {
      const res = await api.post('/v1/quiz-assignments', {
        quiz_id: selectedQuiz,
        user_ids: selectedUsers,
        due_date: dueDate || null,
      });
      toast.success(
        t('toast.positionAssigned'),
        { description: `Назначено: ${res.data.created}, пропущено: ${res.data.skipped}` }
      );
      setSelectedUsers([]);
      fetchData();
    } catch (err: any) {
      toast.error(t('common.saveFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    } finally {
      setAssigning(false);
    }
  };

  const handleDelete = async (id: string) => {
        const ok = await confirm({
      title: t('dialogs.confirmDeleteAssignment'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    await api.delete(`/v1/quiz-assignments/${id}`);
    fetchData();
  };

  const toggleUser = (id: string) => {
    setSelectedUsers(prev => prev.includes(id) ? prev.filter(u => u !== id) : [...prev, id]);
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Назначение тестов сотрудникам</h1>

      {/* Assign form */}
      <Card>
        <CardContent className="p-4 space-y-4">
          <h3 className="font-semibold flex items-center gap-2">
            <UserPlus className="w-5 h-5" /> Назначить тест
          </h3>

          <div>
            <label className="text-sm text-muted-foreground mb-1 block">Тест</label>
            <select
              value={selectedQuiz}
              onChange={(e) => setSelectedQuiz(e.target.value)}
              className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary"
            >
              <option value="">Выберите тест</option>
              {quizzes.map(q => (
                <option key={q.id} value={q.id}>{q.title}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-sm text-muted-foreground mb-1 block">Сотрудники ({selectedUsers.length} выбрано)</label>
            <div className="max-h-48 overflow-y-auto border border-border rounded-xl p-2 space-y-1">
              {users.length === 0 && (
                <p className="text-sm text-muted-foreground">Нет сотрудников</p>
              )}
              {users.map(u => (
                <label
                  key={u.id}
                  className={`flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-colors ${
                    selectedUsers.includes(u.id) ? 'bg-primary/5 border border-primary/20' : 'hover:bg-muted'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedUsers.includes(u.id)}
                    onChange={() => toggleUser(u.id)}
                    className="h-4 w-4 rounded border-border text-primary"
                  />
                  <span className="text-sm">{u.full_name}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="text-sm text-muted-foreground mb-1 block">Срок сдачи (опционально)</label>
            <Input
              type="datetime-local"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
            />
          </div>

          <Button
            onClick={handleAssign}
            disabled={!selectedQuiz || selectedUsers.length === 0 || assigning}
          >
            {assigning ? 'Назначение...' : `Назначить (${selectedUsers.length})`}
          </Button>
        </CardContent>
      </Card>

      {/* Existing assignments */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <h3 className="font-semibold">Текущие назначения ({assignments.length})</h3>
          {assignments.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет назначений</p>
          ) : (
            <div className="space-y-2">
              {assignments.map(a => (
                <div key={a.id} className="flex items-center gap-3 p-3 rounded-xl border border-border">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">{a.quiz_title}</div>
                    <div className="text-xs text-muted-foreground">{a.user_name}</div>
                  </div>
                  <Badge variant={a.status === 'completed' ? 'default' : 'outline'}>
                    {a.status === 'completed' ? `${a.score_percent}%` : a.status}
                  </Badge>
                  {a.due_date && (
                    <span className="text-xs text-muted-foreground">
                      до {new Date(a.due_date).toLocaleDateString('ru-RU')}
                    </span>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(a.id)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
{dialog}
    </div>
  );
}
