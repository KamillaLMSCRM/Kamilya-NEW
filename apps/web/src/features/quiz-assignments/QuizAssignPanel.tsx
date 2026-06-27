'use client';

/**
 * QuizAssignPanel — назначение теста сотрудникам ИЛИ должностям.
 *
 * Режимы:
 *   - «Сотрудники» (по умолчанию): выбор конкретных людей из tenant-листа.
 *   - «Должности»: выбор должностей — backend разворачивает в user_ids.
 *     Удобно для "назначить всем кассирам" (30+ человек).
 *
 * Под выбранным тестом показывается текущий список назначений с
 * возможностью отозвать (assigned → deleted). Завершённые тесты
 * остаются в истории (отзывать нельзя — тест уже пройден).
 *
 * Edge cases:
 *   - tenant без студентов → объясняем что надо добавить в «Пользователи»
 *   - tenant без должностей → вкладка «Должности» показывает empty-state
 *   - пагинация /v1/users: если total > per_page, подгружаем все страницы
 *     последовательно (тенант <500 чел обычно, но >100 уже возможно)
 *   - назначения по должностям: бэк отдаёт summary с users_skipped
 *     (уже назначены) и positions_not_found — мы это показываем в toast
 */

import { useEffect, useMemo, useState, useCallback } from 'react';
import { Button, Card, CardContent, Badge } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import {
  Trash2,
  UserPlus,
  Briefcase,
  X,
  Mail,
  Users,
  ChevronRight,
} from 'lucide-react';
import {
  fetchAssignments,
  assignQuiz,
  assignQuizByPositions,
  removeAssignment,
} from './api';
import type { PositionLite, QuizAssignment } from './types';

interface UserLite {
  id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  role: string;
  is_active: boolean;
  position_id: string | null;
}

interface QuizAssignPanelProps {
  quizId: string;
  refreshKey?: string | number;
}

type Mode = 'users' | 'positions';

export function QuizAssignPanel({ quizId, refreshKey }: QuizAssignPanelProps) {
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const { confirm, dialog } = useConfirm();
  const { t } = useT();

  const [mode, setMode] = useState<Mode>('users');

  // Shared state
  const [assignments, setAssignments] = useState<QuizAssignment[]>([]);
  const [loadingAssignments, setLoadingAssignments] = useState(true);
  const [dueDate, setDueDate] = useState<string>('');
  const [submitting, setSubmitting] = useState(false);

  // Users mode
  const [users, setUsers] = useState<UserLite[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Positions mode
  const [positions, setPositions] = useState<PositionLite[]>([]);
  const [loadingPositions, setLoadingPositions] = useState(false);
  const [selectedPositions, setSelectedPositions] = useState<Set<string>>(new Set());

  // Load assignments (shared between both modes)
  const reloadAssignments = useCallback(async () => {
    if (!token) return;
    setLoadingAssignments(true);
    try {
      setAssignments(await fetchAssignments(token));
    } catch (e) {
      toast.error(`${t('quizAssignments.loadError')}: ${(e as Error).message}`);
    } finally {
      setLoadingAssignments(false);
    }
  }, [token, t]);

  // Load users with pagination. The endpoint supports per_page up to 500
  // (raised from 100 in this commit). Most legal-entity tenants are
  // <300 employees, so 2 requests is the worst case. We don't loop
  // beyond page 10 just in case.
  const reloadUsers = useCallback(async () => {
    if (!token) return;
    setLoadingUsers(true);
    try {
      const PAGE_SIZE = 200;
      const MAX_PAGES = 10;
      let page = 1;
      let total = 0;
      const collected: UserLite[] = [];

      while (page <= MAX_PAGES) {
        const res = await fetch(
          `${API_URL}/v1/users?page=${page}&per_page=${PAGE_SIZE}&is_active=true&role=student`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (!res.ok) {
          const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          throw new Error(detail.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        collected.push(...(data.users as UserLite[]));
        total = data.total;
        if (collected.length >= total || (data.users as UserLite[]).length < PAGE_SIZE) {
          break;
        }
        page += 1;
      }

      setUsers(collected);
      setUsersTotal(total);
    } catch (e) {
      toast.error(`${t('quizAssignments.loadError')}: ${(e as Error).message}`);
    } finally {
      setLoadingUsers(false);
    }
  }, [token, API_URL, t]);

  // Load positions (no pagination — typically <50 per tenant)
  const reloadPositions = useCallback(async () => {
    if (!token) return;
    setLoadingPositions(true);
    try {
      const res = await fetch(`${API_URL}/v1/positions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(detail.detail || `HTTP ${res.status}`);
      }
      const data: PositionLite[] = await res.json();
      setPositions(data);
    } catch (e) {
      toast.error(`${t('quizAssignments.loadError')}: ${(e as Error).message}`);
    } finally {
      setLoadingPositions(false);
    }
  }, [token, API_URL, t]);

  useEffect(() => {
    reloadAssignments();
  }, [reloadAssignments, refreshKey]);
  useEffect(() => {
    if (mode === 'users') reloadUsers();
    else reloadPositions();
  }, [mode, reloadUsers, reloadPositions]);

  // Assignments for THIS quiz
  const myAssignments = useMemo(
    () => assignments.filter((a) => a.quiz_id === quizId),
    [assignments, quizId]
  );

  // Users already assigned to this quiz (shown in the "available" list as
  // a small greyed-out hint so the methodologist knows the dedup is working)
  const assignedUserIds = useMemo(
    () => new Set(myAssignments.map((a) => a.user_id)),
    [myAssignments]
  );

  // Users available to assign — filtered by search, not already assigned
  const availableUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter((u) => {
      if (q) {
        const fullName = `${u.first_name} ${u.last_name}`.toLowerCase();
        const email = (u.email ?? '').toLowerCase();
        if (!fullName.includes(q) && !email.includes(q)) return false;
      }
      return true;
    });
  }, [users, search]);

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

  const togglePosition = (id: string) => {
    setSelectedPositions((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleAssignUsers = async () => {
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
      await Promise.all([reloadAssignments(), reloadUsers()]);
    } catch (e) {
      toast.error(`${t('quizAssignments.assignError')}: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAssignPositions = async () => {
    if (!token) return;
    if (selectedPositions.size === 0) {
      toast.error(t('quizAssignments.selectAtLeastOnePosition'));
      return;
    }
    setSubmitting(true);
    try {
      const summary = await assignQuizByPositions(token, {
        quiz_id: quizId,
        position_ids: Array.from(selectedPositions),
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
      });
      const parts: string[] = [];
      parts.push(t('quizAssignments.assignSuccess', { count: summary.users_assigned }));
      if (summary.users_skipped > 0) {
        parts.push(t('quizAssignments.alreadyAssigned', { count: summary.users_skipped }));
      }
      if (summary.positions_not_found.length > 0) {
        parts.push(t('quizAssignments.positionsNotFound', { count: summary.positions_not_found.length }));
      }
      toast.success(parts.join(' · '));
      setSelectedPositions(new Set());
      setDueDate('');
      await reloadAssignments();
    } catch (e) {
      toast.error(`${t('quizAssignments.assignError')}: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (assignment: QuizAssignment) => {
    const ok = await confirm({
      title: t('quizAssignments.revokeConfirm', { name: assignment.user_name || assignment.user_email || assignment.user_id }),
      variant: 'danger',
      confirmLabel: t('quizAssignments.revoke'),
    });
    if (!ok) return;
    try {
      await removeAssignment(token!, assignment.id);
      toast.success(t('quizAssignments.revokeSuccess'));
      await reloadAssignments();
    } catch (e) {
      toast.error(`${t('quizAssignments.revokeError')}: ${(e as Error).message}`);
    }
  };

  // Copy invite info for users who don't have an account yet — their
  // email is on file (added by HR via invitations module) but they
  // haven't accepted. The methodologist can't really "assign" them
  // until they exist as users; we surface this clearly.
  const pendingUsers = useMemo(
    () => users.filter((u) => !u.is_active || !u.email),
    [users]
  );

  if (loadingAssignments && assignments.length === 0) {
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
          <div className="flex items-center gap-2 flex-wrap">
            <UserPlus size={16} className="text-primary" />
            <h4 className="font-semibold">{t('quizAssignments.assignHeading')}</h4>
            {mode === 'users' && (
              <Badge variant="secondary">
                {t('quizAssignments.availableCount', {
                  count: availableUsers.length - assignedUserIds.size,
                })}
                {usersTotal > 0 && usersTotal !== users.length ? ` / ${usersTotal}` : ''}
              </Badge>
            )}
            {mode === 'positions' && (
              <Badge variant="secondary">
                {t('quizAssignments.selectedPositions', { count: selectedPositions.size })}
              </Badge>
            )}
          </div>

          {/* Mode toggle — Users vs Positions. Two workflows with different
              ergonomics: handpick individuals vs "all cashiers". The toggle
              is a thin button row, not a heavy tab strip, to keep the
              construction-page dense layout intact. */}
          <div className="inline-flex rounded-md border border-border/60 bg-muted/40 p-0.5 text-sm">
            <button
              type="button"
              className={`inline-flex items-center gap-1.5 px-3 py-1 rounded ${
                mode === 'users' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setMode('users')}
            >
              <Users size={14} />
              {t('quizAssignments.modeUsers')}
            </button>
            <button
              type="button"
              className={`inline-flex items-center gap-1.5 px-3 py-1 rounded ${
                mode === 'positions' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setMode('positions')}
            >
              <Briefcase size={14} />
              {t('quizAssignments.modePositions')}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {mode === 'users' && (
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('quizAssignments.search')}
                className="flex-1 min-w-[200px] rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              />
            )}
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              title={t('quizAssignments.dueDate')}
            />
            {mode === 'users' && availableUsers.length > 0 && (
              <>
                <Button size="sm" variant="outline" onClick={selectAllVisible}>
                  {t('quizAssignments.selectAll')}
                </Button>
                {selectedIds.size > 0 && (
                  <Button size="sm" variant="ghost" onClick={clearSelection}>
                    <X size={14} className="mr-1" />
                    {t('quizAssignments.clearSelection', { count: selectedIds.size })}
                  </Button>
                )}
                <Button
                  size="sm"
                  onClick={handleAssignUsers}
                  disabled={submitting || selectedIds.size === 0}
                >
                  {submitting
                    ? t('quizAssignments.assigning')
                    : t('quizAssignments.assignButton', { count: selectedIds.size })}
                </Button>
              </>
            )}
            {mode === 'positions' && positions.length > 0 && (
              <>
                {selectedPositions.size > 0 && (
                  <Button size="sm" variant="ghost" onClick={() => setSelectedPositions(new Set())}>
                    <X size={14} className="mr-1" />
                    {t('quizAssignments.clearSelection', { count: selectedPositions.size })}
                  </Button>
                )}
                <Button
                  size="sm"
                  onClick={handleAssignPositions}
                  disabled={submitting || selectedPositions.size === 0}
                >
                  {submitting
                    ? t('quizAssignments.assigning')
                    : t('quizAssignments.assignByPositionsButton', {
                        count: selectedPositions.size,
                      })}
                </Button>
              </>
            )}
          </div>

          {/* Pending users warning. Если есть сотрудники с пустым email
              или неактивные — напоминаем что они не получат тест. */}
          {mode === 'users' && pendingUsers.length > 0 && (
            <div className="rounded-md border border-amber-300/60 bg-amber-50/40 dark:bg-amber-950/20 px-3 py-2 text-xs flex items-start gap-2">
              <Mail size={14} className="text-amber-600 mt-0.5 shrink-0" />
              <div>
                <div className="font-medium text-amber-900 dark:text-amber-200">
                  {t('quizAssignments.pendingUsersTitle', { count: pendingUsers.length })}
                </div>
                <div className="text-amber-800/80 dark:text-amber-300/80">
                  {t('quizAssignments.pendingUsersHint')}
                </div>
              </div>
            </div>
          )}

          {/* USERS mode body */}
          {mode === 'users' && (
            loadingUsers ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t('quizAssignments.loading')}
              </p>
            ) : availableUsers.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {users.length === 0
                  ? t('quizAssignments.noStudents')
                  : t('quizAssignments.allAssigned')}
              </p>
            ) : (
              <div className="max-h-[18rem] overflow-y-auto rounded border border-border/50 divide-y divide-border/40">
                {availableUsers.map((u) => {
                  const checked = selectedIds.has(u.id);
                  const alreadyAssigned = assignedUserIds.has(u.id);
                  return (
                    <label
                      key={u.id}
                      className={`flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-muted/40 ${
                        alreadyAssigned ? 'opacity-50' : ''
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={alreadyAssigned}
                        onChange={() => toggleUser(u.id)}
                        className="rounded"
                      />
                      <span className="flex-1">
                        {u.first_name} {u.last_name}
                        {alreadyAssigned && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            ({t('quizAssignments.alreadyAssignedShort')})
                          </span>
                        )}
                      </span>
                      {u.email && (
                        <span className="text-xs text-muted-foreground">{u.email}</span>
                      )}
                    </label>
                  );
                })}
              </div>
            )
          )}

          {/* POSITIONS mode body */}
          {mode === 'positions' && (
            loadingPositions ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t('quizAssignments.loading')}
              </p>
            ) : positions.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t('quizAssignments.noPositions')}
              </p>
            ) : (
              <div className="rounded border border-border/50 divide-y divide-border/40">
                {positions.map((p) => {
                  const checked = selectedPositions.has(p.id);
                  return (
                    <label
                      key={p.id}
                      className="flex items-center gap-2 px-3 py-2 text-sm cursor-pointer hover:bg-muted/40"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => togglePosition(p.id)}
                        className="rounded"
                      />
                      <Briefcase size={14} className="text-muted-foreground" />
                      <span className="flex-1">
                        <span className="font-medium">{p.name}</span>
                        {p.department && (
                          <span className="text-muted-foreground text-xs ml-2">
                            {p.department}
                          </span>
                        )}
                      </span>
                      <Badge variant="outline">
                        <Users size={10} className="mr-1" />
                        {p.employee_count ?? 0}
                      </Badge>
                      <ChevronRight size={14} className="text-muted-foreground/50" />
                    </label>
                  );
                })}
              </div>
            )
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
                      {a.user_name || a.user_email || a.user_id}
                      {a.position_name && (
                        <span className="text-xs text-muted-foreground ml-2">
                          · {a.position_name}
                        </span>
                      )}
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