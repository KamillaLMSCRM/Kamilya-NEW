'use client';

/**
 * QuizAssignPanel — методолог выбирает сотрудников из tenant-списка,
 * задаёт дедлайн (опц.) и нажимает «Назначить». Под выбранным тестом
 * показывается текущий список назначений (с возможностью отменить).
 *
 * Требования:
 *   - GET /v1/users — список сотрудников (теперь teacher тоже имеет доступ)
 *   - GET /v1/quiz-assignments — текущие назначения в tenant
 *   - POST /v1/quiz-assignments — создать
 *   - DELETE /v1/quiz-assignments/{id} — отозвать
 *
 * Особенности:
 *   - В чекбокс-листе показываем только ещё НЕ назначенных этому тесту,
 *     чтобы случайно не дублировать (бэк и так skip-нет, но UX чище).
 *   - Поиск по ФИО / email для большого штата.
 *   - "Отозвать" доступно для assigned-статуса; для completed — скрыто
 *     (завершённый тест не имеет смысла отзывать — пусть остаётся в истории).
 */

import { useEffect, useMemo, useState, useCallback } from 'react';
import { Button, Card, CardContent, Badge } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Trash2, UserPlus, X } from 'lucide-react';
import {
  fetchAssignments,
  assignQuiz,
  removeAssignment,
} from './api';
import type { QuizAssignment } from './types';

interface UserLite {
  id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  role: string;
  is_active: boolean;
}

interface QuizAssignPanelProps {
  quizId: string;
  /** Optional: id of an object that should force a refresh when it changes. */
  refreshKey?: string | number;
}

const ROLE_FILTER = 'student'; // назначаем только студентам

export function QuizAssignPanel({ quizId, refreshKey }: QuizAssignPanelProps) {
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const { confirm, dialog } = useConfirm();
  const { t } = useT();

  const [users, setUsers] = useState<UserLite[]>([]);
  const [assignments, setAssignments] = useState<QuizAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [dueDate, setDueDate] = useState<string>('');

  const reload = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [usersRes, allAssignments] = await Promise.all([
        // Берём per_page=100, чтобы покрыть тенант целиком (тенант-лимит
        // обычно < 500 человек; если больше — добавим pagination позже).
        fetch(`${API_URL}/v1/users?per_page=100&is_active=true&role=${ROLE_FILTER}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetchAssignments(token),
      ]);
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users || []);
      }
      setAssignments(allAssignments);
    } catch (e) {
      toast.error(`${t('quizAssignments.loadError')}: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, t]);

  useEffect(() => {
    reload();
  }, [reload, refreshKey]);

  // Назначения для ЭТОГО теста
  const myAssignments = useMemo(
    () => assignments.filter((a) => a.quiz_id === quizId),
    [assignments, quizId]
  );

  // Список доступных для назначения (ещё не назначен этому тесту)
  const assignedUserIds = useMemo(
    () => new Set(myAssignments.map((a) => a.user_id)),
    [myAssignments]
  );

  const availableUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter((u) => {
      if (assignedUserIds.has(u.id)) return false;
      if (!q) return true;
      const fullName = `${u.first_name} ${u.last_name}`.toLowerCase();
      const email = (u.email ?? '').toLowerCase();
      return fullName.includes(q) || email.includes(q);
    });
  }, [users, assignedUserIds, search]);

  const toggleUser = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      availableUsers.forEach((u) => next.add(u.id));
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  const handleAssign = async () => {
    if (!token) return;
    if (selectedIds.size === 0) {
      toast.error(t('quizAssignments.selectAtLeastOne'));
      return;
    }
    setSubmitting(true);
    try {
      const result = await assignQuiz(token, {
        quiz_id: quizId,
        user_ids: Array.from(selectedIds),
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
      });
      const msg =
        result.skipped > 0
          ? t('quizAssignments.assignSuccessWithSkipped', {
              created: result.created,
              skipped: result.skipped,
            })
          : t('quizAssignments.assignSuccess', { count: result.created });
      toast.success(msg);
      setSelectedIds(new Set());
      setDueDate('');
      await reload();
    } catch (e) {
      toast.error(`Ошибка назначения: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (assignment: QuizAssignment) => {
    const ok = await confirm({
      title: t('quizAssignments.revokeConfirm', { name: assignment.user_name || assignment.user_id }),
      variant: 'danger',
      confirmLabel: t('quizAssignments.revoke'),
    });
    if (!ok) return;
    try {
      await removeAssignment(token!, assignment.id);
      toast.success(t('quizAssignments.revokeSuccess'));
      await reload();
    } catch (e) {
      toast.error(`${t('quizAssignments.revokeError')}: ${(e as Error).message}`);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          {t('quizAssignments.loading')}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* ─── Назначить ─── */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex items-center gap-2">
            <UserPlus size={16} className="text-primary" />
            <h4 className="font-semibold">{t('quizAssignments.assignHeading')}</h4>
            <Badge variant="secondary">
              {t('quizAssignments.availableCount', { count: availableUsers.length })}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('quizAssignments.search')}
              className="flex-1 min-w-[200px] rounded-md border border-input bg-background px-3 py-1.5 text-sm"
            />
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              title={t('quizAssignments.dueDate')}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={selectAllVisible}
              disabled={availableUsers.length === 0}
            >
              {t('quizAssignments.selectAll')}
            </Button>
            {selectedIds.size > 0 && (
              <Button size="sm" variant="ghost" onClick={clearSelection}>
                <X size={14} className="mr-1" />
                {t('quizAssignments.clearSelection', { count: selectedIds.size })}
              </Button>
            )}
            <Button size="sm" onClick={handleAssign} disabled={submitting || selectedIds.size === 0}>
              {submitting
                ? t('quizAssignments.assigning')
                : t('quizAssignments.assignButton', { count: selectedIds.size })}
            </Button>
          </div>

          {availableUsers.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              {users.length === 0
                ? t('quizAssignments.noStudents')
                : t('quizAssignments.allAssigned')}
            </p>
          ) : (
            <div className="max-h-[18rem] overflow-y-auto rounded border border-border/50 divide-y divide-border/40">
              {availableUsers.map((u) => {
                const checked = selectedIds.has(u.id);
                return (
                  <label
                    key={u.id}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-muted/40"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleUser(u.id)}
                      className="rounded"
                    />
                    <span className="flex-1">
                      {u.first_name} {u.last_name}
                    </span>
                    {u.email && (
                      <span className="text-xs text-muted-foreground">{u.email}</span>
                    )}
                  </label>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ─── Текущие назначения ─── */}
      <Card>
        <CardContent className="p-4 space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold">
              {t('quizAssignments.currentHeading')}{' '}
              <Badge variant="secondary" className="ml-1">{myAssignments.length}</Badge>
            </h4>
          </div>

          {myAssignments.length === 0 ? (
            <p className="text-sm text-muted-foreground py-3">
              {t('quizAssignments.noAssignments')}
            </p>
          ) : (
            <div className="divide-y divide-border/40 rounded border border-border/50">
              {myAssignments.map((a) => {
                const isDone = a.status === 'completed';
                const overdue =
                  !isDone &&
                  a.due_date &&
                  new Date(a.due_date) < new Date();
                const dueLocale = a.due_date
                  ? new Date(a.due_date).toLocaleDateString('ru-RU')
                  : null;
                return (
                  <div
                    key={a.id}
                    className="flex items-center gap-2 px-3 py-2 text-sm"
                  >
                    <span className="flex-1 truncate">
                      {a.user_name || a.user_id}
                    </span>
                    {dueLocale && (
                      <span className="text-xs text-muted-foreground">
                        {t('quizAssignments.dueOn', { date: dueLocale })}
                      </span>
                    )}
                    {isDone ? (
                      <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">
                        ✓ {t('quizAssignments.score', { percent: a.score_percent ?? 0 })}
                      </Badge>
                    ) : overdue ? (
                      <Badge variant="destructive">{t('quizAssignments.statusOverdue')}</Badge>
                    ) : (
                      <Badge variant="secondary">{t('quizAssignments.statusAssigned')}</Badge>
                    )}
                    {!isDone && (
                      <button
                        type="button"
                        title={t('quizAssignments.revoke')}
                        onClick={() => handleRevoke(a)}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
      {dialog}
    </div>
  );
}