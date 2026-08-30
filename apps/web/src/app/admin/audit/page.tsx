'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { History, RefreshCw, Search } from 'lucide-react';
import { Button, Card, CardContent } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

type AuditEntry = {
  id: string;
  user_id: string | null;
  actor_email: string | null;
  actor_name: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
};

type Account = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
};

type UserListResponse = { users: Account[] };

function accountsFromAudit(entries: AuditEntry[]): Account[] {
  const byId = new Map<string, Account>();
  entries.forEach((entry) => {
    if (!entry.user_id || byId.has(entry.user_id)) return;
    const names = (entry.actor_name || '').trim().split(/\s+/).filter(Boolean);
    byId.set(entry.user_id, {
      id: entry.user_id,
      first_name: names[0] || null,
      last_name: names.slice(1).join(' ') || null,
      email: entry.actor_email,
    });
  });
  return Array.from(byId.values());
}

function mergeAccounts(entries: AuditEntry[], users: Account[]): Account[] {
  const byId = new Map(accountsFromAudit(entries).map((account) => [account.id, account]));
  users.forEach((account) => byId.set(account.id, account));
  return Array.from(byId.values()).sort((left, right) => accountLabel(left).localeCompare(accountLabel(right)));
}

const ACTION_LABELS: Record<string, string> = {
  employee_profile_updated: 'Изменены данные сотрудника',
  employee_terminated: 'Сотрудник уволен',
  'training_procedure.created': 'Создана процедура подтверждения',
  'training_procedure.updated': 'Изменена процедура подтверждения',
  'training_procedure.deleted': 'Удалён черновик процедуры',
  'training_procedure.activated': 'Активирована процедура подтверждения',
  'training_procedure.retired': 'Процедура выведена из действия',
  create: 'Создание',
  update: 'Изменение',
  delete: 'Удаление',
};

function accountLabel(account: Account) {
  return `${account.first_name || ''} ${account.last_name || ''}`.trim() || account.email || account.id;
}

function detailText(entry: AuditEntry) {
  if (entry.action === 'employee_profile_updated') {
    const fields = Array.isArray(entry.details?.changed_fields) ? entry.details?.changed_fields.join(', ') : '';
    return fields ? `Поля: ${fields}` : 'Профиль сохранён без изменения значений';
  }
  if (entry.action === 'employee_terminated') {
    return typeof entry.details?.reason === 'string' ? `Причина: ${entry.details.reason}` : 'Доступ сотрудника закрыт';
  }
  return entry.resource_id ? `ID объекта: ${entry.resource_id}` : '—';
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [actorId, setActorId] = useState('');
  const [action, setAction] = useState('');
  const [resourceType, setResourceType] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '500' });
      if (actorId) params.set('user_id', actorId);
      if (action) params.set('action', action);
      if (resourceType) params.set('resource_type', resourceType);
      if (startDate) params.set('start_date', new Date(`${startDate}T00:00:00`).toISOString());
      if (endDate) params.set('end_date', new Date(`${endDate}T23:59:59.999`).toISOString());
      const [logsResult, usersResult] = await Promise.allSettled([
        api.get<AuditEntry[]>(`/v1/audit/logs?${params.toString()}`),
        api.get<UserListResponse>('/v1/users?per_page=500'),
      ]);
      if (logsResult.status === 'rejected') throw logsResult.reason;
      const loadedEntries = logsResult.value.data;
      const loadedAccounts = usersResult.status === 'fulfilled' ? usersResult.value.data.users || [] : [];
      setEntries(loadedEntries);
      setAccounts(mergeAccounts(loadedEntries, loadedAccounts));
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Не удалось загрузить журнал действий');
    } finally {
      setLoading(false);
    }
  }, [action, actorId, endDate, resourceType, startDate]);

  useEffect(() => { void load(); }, [load]);

  const actionOptions = useMemo(
    () => Array.from(new Set(entries.map((entry) => entry.action))).sort(),
    [entries],
  );
  const resourceOptions = useMemo(
    () => Array.from(new Set(entries.map((entry) => entry.resource_type))).sort(),
    [entries],
  );

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold"><History className="h-6 w-6" /> Журнал действий</h1>
        <p className="mt-1 text-sm text-muted-foreground">Кто, когда и с какой учётной записи изменял данные компании. История увольнений не удаляется.</p>
      </div>

      <Card>
        <CardContent className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
          <label className="text-sm">Учётная запись
            <select value={actorId} onChange={(event) => setActorId(event.target.value)} className="mt-1 h-10 w-full rounded-md border bg-background px-3">
              <option value="">Все</option>
              {accounts.map((account) => <option key={account.id} value={account.id}>{accountLabel(account)}</option>)}
            </select>
          </label>
          <label className="text-sm">Тип действия
            <select value={action} onChange={(event) => setAction(event.target.value)} className="mt-1 h-10 w-full rounded-md border bg-background px-3">
              <option value="">Все</option>
              {actionOptions.map((item) => <option key={item} value={item}>{ACTION_LABELS[item] || item}</option>)}
            </select>
          </label>
          <label className="text-sm">Объект
            <select value={resourceType} onChange={(event) => setResourceType(event.target.value)} className="mt-1 h-10 w-full rounded-md border bg-background px-3">
              <option value="">Все</option>
              {resourceOptions.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="text-sm">С даты<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="mt-1 h-10 w-full rounded-md border bg-background px-3" /></label>
          <label className="text-sm">По дату<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="mt-1 h-10 w-full rounded-md border bg-background px-3" /></label>
          <Button className="mt-auto" onClick={() => void load()} disabled={loading}><Search className="mr-2 h-4 w-4" /> Применить</Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-sm text-muted-foreground"><RefreshCw className="mr-2 inline h-4 w-4 animate-spin" />Загрузка…</div>
          ) : entries.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">За выбранный период действий нет.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b bg-muted/40"><tr><th className="p-3">Дата и время</th><th className="p-3">Учётная запись</th><th className="p-3">Действие</th><th className="p-3">Объект</th><th className="p-3">Подробности</th></tr></thead>
                <tbody>
                  {entries.map((entry) => (
                    <tr key={entry.id} className="border-b last:border-0">
                      <td className="whitespace-nowrap p-3">{new Date(entry.created_at).toLocaleString('ru-RU')}</td>
                      <td className="p-3"><div className="font-medium">{entry.actor_name || 'Системное действие'}</div><div className="text-xs text-muted-foreground">{entry.actor_email || entry.user_id || '—'}</div></td>
                      <td className="p-3">{ACTION_LABELS[entry.action] || entry.action}</td>
                      <td className="p-3">{entry.resource_type}</td>
                      <td className="max-w-md p-3 text-muted-foreground">{detailText(entry)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
