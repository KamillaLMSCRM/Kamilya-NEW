'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus, Save, Users } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import {
  cohortMemberPayload,
  cohortUserOptions,
  COHORT_MANAGER_ROLE,
  type UserListResponse,
} from './user-list-contract';

type Cohort = { id: string; name: string; description: string; member_count: number };
type Option = { id: string; name: string };
type Detail = Cohort & { user_ids: string[] };

export default function CohortsPage() {
  const { t, tp } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const canManage = role === COHORT_MANAGER_ROLE;
  const [items, setItems] = useState<Cohort[]>([]);
  const [users, setUsers] = useState<Option[]>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [loadState, setLoadState] = useState<'loading' | 'success' | 'error'>('loading');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [userIds, setUserIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!canManage) return;
    setLoadState('loading');
    try {
      const [cohorts, userList] = await Promise.all([
        api.get<Cohort[]>('/v1/cohorts'),
        api.get<UserListResponse>('/v1/users?per_page=500&include_students=true'),
      ]);
      setItems(cohorts.data);
      setUsers(cohortUserOptions(userList.data));
      setLoadState('success');
    } catch (error: unknown) {
      setLoadState('error');
      const apiError = error as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(t('cohorts.loadFailed'), { description: apiError.response?.data?.detail || apiError.message });
    }
  }, [canManage, t]);

  useEffect(() => { load(); }, [load]);

  const open = async (item: Cohort) => {
    try {
      const detail = await api.get<Detail>(`/v1/cohorts/${item.id}`);
      setSelected(detail.data);
      setName(detail.data.name);
      setDescription(detail.data.description);
      setUserIds(detail.data.user_ids);
    } catch (error: any) {
      toast.error(t('cohorts.loadFailed'), { description: error?.response?.data?.detail || error?.message });
    }
  };

  const resetEditor = () => {
    setSelected(null);
    setName('');
    setDescription('');
    setUserIds([]);
  };

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const response = await api.post<Cohort>('/v1/cohorts', { name: name.trim(), description });
      setItems((list) => [response.data, ...list]);
      setSelected({ ...response.data, user_ids: [] });
      toast.success(t('cohorts.created'));
    } catch (error: any) {
      toast.error(t('cohorts.saveFailed'), { description: error?.response?.data?.detail || error?.message });
    } finally {
      setSaving(false);
    }
  };

  const saveMembers = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await api.patch(`/v1/cohorts/${selected.id}`, { name: name.trim(), description });
      await api.put(`/v1/cohorts/${selected.id}/members`, cohortMemberPayload(userIds));
      await load();
      toast.success(t('cohorts.saved'));
    } catch (error: any) {
      toast.error(t('cohorts.saveFailed'), { description: error?.response?.data?.detail || error?.message });
    } finally {
      setSaving(false);
    }
  };

  const toggle = (id: string) => setUserIds((list) => list.includes(id) ? list.filter((item) => item !== id) : [...list, id]);

  if (!canManage) return <div className="space-y-2 p-6"><h1 className="text-2xl font-bold">{t('cohorts.title')}</h1><p className="text-sm text-muted-foreground">{t('learningPaths.forbidden')}</p></div>;
  if (loadState === 'loading') return <div className="p-6">{t('common.loading')}</div>;
  if (loadState === 'error') return <div className="space-y-3 p-6"><p className="text-sm text-destructive">{t('cohorts.loadFailed')}</p><Button variant="outline" onClick={load}>{t('common.retry')}</Button></div>;

  return <div className="mx-auto max-w-7xl space-y-6 p-6">
    <div>
      <h1 className="text-2xl font-bold">{t('cohorts.title')}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t('cohorts.subtitle')}</p>
      <p className="mt-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        {t('cohorts.audienceHint')}
      </p>
    </div>
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      <Card><CardContent className="space-y-3 p-4">
        <Button className="w-full gap-2" onClick={resetEditor}><Plus className="h-4 w-4" />{t('cohorts.new')}</Button>
        {items.map((item) => <button key={item.id} onClick={() => open(item)} className={`w-full rounded-lg border p-3 text-left ${selected?.id === item.id ? 'border-primary bg-primary/5' : 'border-border'}`}>
          <div className="truncate font-medium">{item.name}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {tp('common.counts.participant', item.member_count)}
          </div>
        </button>)}
        {!items.length && <p className="p-3 text-sm text-muted-foreground">{t('cohorts.empty')}</p>}
      </CardContent></Card>
      <Card><CardContent className="space-y-5 p-6">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 text-sm font-medium">{t('cohorts.name')}<Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t('cohorts.namePlaceholder')} /></label>
          <label className="space-y-2 text-sm font-medium">{t('cohorts.description')}<Input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        </div>
        {selected ? <>
          <Selector title={t('cohorts.members')} items={users} selected={userIds} onToggle={toggle} />
          <div className="flex justify-end"><Button variant="outline" onClick={saveMembers} disabled={saving} className="gap-2"><Save className="h-4 w-4" />{t('cohorts.save')}</Button></div>
        </> : <div className="flex justify-end"><Button onClick={create} disabled={saving || !name.trim()}>{t('cohorts.create')}</Button></div>}
      </CardContent></Card>
    </div>
  </div>;
}

function Selector({ title, items, selected, onToggle }: { title: string; items: Option[]; selected: string[]; onToggle: (id: string) => void }) {
  return <section><h2 className="mb-3 flex items-center gap-2 font-semibold"><Users className="h-4 w-4 text-primary" />{title}</h2><div className="grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">{items.map((item) => <label key={item.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3"><input type="checkbox" checked={selected.includes(item.id)} onChange={() => onToggle(item.id)} /><span className="truncate text-sm">{item.name}</span></label>)}</div></section>;
}
