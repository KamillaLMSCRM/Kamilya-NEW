import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { buildTrainingLogBrowserHref, buildTrainingLogPageQuery } from '@/app/admin/training-log/query';
import type { StaffWorkspaceEmployee } from './StaffWorkspaceClient';

interface EmployeeEnrollment {
  user_id: string;
  enrollment_id: string;
  course_id: string;
  course_title: string;
  progress_percent: number;
  computed_status: 'assigned' | 'in_progress' | 'completed';
  assignment_due_at?: string | null;
  cycle_due_at?: string | null;
  deadline_state?: string;
  deadline_status?: string;
}

interface JournalPage { items: EmployeeEnrollment[]; total: number }

export function EmployeeLearning({ employee }: { employee: StaffWorkspaceEmployee }) {
  const [result, setResult] = useState<{ rows: EmployeeEnrollment[]; partial: boolean }>();
  const [error, setError] = useState(false);
  const search = employee.personnel_number || employee.full_name.trim().split(/\s+/).at(-1) || '';

  useEffect(() => {
    if (!search) return;
    const controller = new AbortController();
    const query = buildTrainingLogPageQuery({}, search, 50, 0);
    api.get<JournalPage>('/v1/admin/training-log?' + query, { signal: controller.signal })
      .then(({ data }) => {
        if (!controller.signal.aborted) setResult({
          rows: data.items.filter((row) => row.user_id === employee.id),
          partial: data.total > data.items.length,
        });
      })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [employee.id, search]);

  if (error || !search) return <p role="status" className="text-sm text-muted-foreground">Не удалось загрузить обучение сотрудника.</p>;
  if (!result) return <p role="status" className="text-sm text-muted-foreground">Загрузка обучения…</p>;

  const overdue = (row: EmployeeEnrollment) => row.computed_status !== 'completed' &&
    (row.deadline_state === 'overdue' || row.deadline_status === 'overdue');
  const labels = { assigned: 'Назначен', in_progress: 'В процессе', completed: 'Пройден' };
  const rows = [...result.rows].sort((a, b) => Number(overdue(b)) - Number(overdue(a)));
  return <div>
    <h4 className="mb-2 text-sm font-semibold">Назначенные курсы</h4>
    {!rows.length && !result.partial && <p className="text-sm text-muted-foreground">В журнале нет текущих назначений.</p>}
    <ul className="divide-y divide-border">{rows.slice(0, 6).map((row) => {
      const rawDeadline = row.assignment_due_at ?? row.cycle_due_at;
      const deadline = rawDeadline ? new Date(rawDeadline) : null;
      return <li key={row.enrollment_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0 text-sm [overflow-wrap:anywhere]">
          <Link className="font-medium text-primary hover:underline" href={buildTrainingLogBrowserHref({
            filters: { enrollment_id: row.enrollment_id, course_id: row.course_id }, search: '', returnTo: null,
          })}>{row.course_title}</Link>
          <p className="text-xs text-muted-foreground">{row.progress_percent}%{deadline && !Number.isNaN(deadline.getTime()) ? ' · до ' + deadline.toLocaleDateString('ru-RU') : ''}</p>
        </div>
        <span className={'rounded-md px-2 py-1 text-xs font-semibold ' + (overdue(row) ? 'bg-warning/10 text-warning' : 'bg-muted text-muted-foreground')}>
          {overdue(row) ? 'Просрочен' : labels[row.computed_status]}
        </span>
      </li>;
    })}</ul>
    {(result.partial || rows.length > 6) && <p className="text-xs text-muted-foreground">Здесь показана часть записей. Остальные можно найти в журнале.</p>}
  </div>;
}
