'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus, Save, Users } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Input } from '@/components/ui';
import { WorkspacePage, WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';
import { toast } from '@/components/ui/Toast';
import {
  cohortMemberPayload,
  cohortUserOptions,
  COHORT_MANAGER_ROLE,
  type UserListResponse,
} from './user-list-contract';

type Cohort = { id: string; name: string; description: string; member_count: number; responsible_user_id: string | null; responsible_user_name: string | null };
type Option = { id: string; name: string };
type Detail = Cohort & { user_ids: string[] };

export default function CohortsPage() {
  const { t, tp } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const canManage = role === COHORT_MANAGER_ROLE;
  const [items, setItems] = useState<Cohort[]>([]);
  const [users, setUsers] = useState<Option[]>([]);
  const [methodologists, setMethodologists] = useState<Option[]>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [loadState, setLoadState] = useState<'loading' | 'success' | 'error'>('loading');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [userIds, setUserIds] = useState<string[]>([]);
  const [responsibleUserId, setResponsibleUserId] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!canManage) return;
    setLoadState('loading');
    try {
      const [cohorts, userList, methodologistList] = await Promise.all([
        api.get<Cohort[]>('/v1/cohorts'),
        api.get<UserListResponse>('/v1/users?per_page=500&role=student&is_active=true'),
        api.get<UserListResponse>('/v1/users?per_page=500&role=methodologist&is_active=true'),
      ]);
      setItems(cohorts.data);
      setUsers(cohortUserOptions(userList.data));
      setMethodologists(cohortUserOptions(methodologistList.data, 'methodologist'));
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
      setResponsibleUserId(detail.data.responsible_user_id || '');
      const eligibleUserIds = new Set(users.map((item) => item.id));
      setUserIds(detail.data.user_ids.filter((id) => eligibleUserIds.has(id)));
    } catch (error: any) {
      toast.error(t('cohorts.loadFailed'), { description: error?.response?.data?.detail || error?.message });
    }
  };

  const resetEditor = () => {
    setSelected(null);
    setName('');
    setDescription('');
    setUserIds([]);
    setResponsibleUserId('');
  };

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const response = await api.post<Cohort>('/v1/cohorts', {
        name: name.trim(),
        description,
        responsible_user_id: responsibleUserId || null,
      });
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
      await api.patch(`/v1/cohorts/${selected.id}`, {
        name: name.trim(),
        description,
        responsible_user_id: responsibleUserId || null,
      });
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

  if (!canManage) return <WorkspacePage id="cohorts" title={t('cohorts.title')} icon={<Users />} className="p-6"><WorkspacePanel><p className="text-sm text-muted-foreground">{t('learningPaths.forbidden')}</p></WorkspacePanel></WorkspacePage>;
  if (loadState === 'loading') return <WorkspacePage id="cohorts" title={t('cohorts.title')} icon={<Users />} className="p-6"><WorkspacePanel><p role="status" className="py-8 text-center text-sm text-muted-foreground">{t('common.loading')}</p></WorkspacePanel></WorkspacePage>;
  if (loadState === 'error') return <WorkspacePage id="cohorts" title={t('cohorts.title')} icon={<Users />} className="p-6"><WorkspacePanel bodyClassName="space-y-4"><p role="alert" className="text-sm text-destructive">{t('cohorts.loadFailed')}</p><Button variant="outline" onClick={load}>{t('common.retry')}</Button></WorkspacePanel></WorkspacePage>;

  return <WorkspacePage id="cohorts" title={t('cohorts.title')} description={t('cohorts.subtitle')} icon={<Users />} className="mx-auto max-w-7xl px-4 py-6 sm:px-6" actions={<Button className="gap-2" onClick={resetEditor}><Plus className="h-4 w-4" aria-hidden="true" />{t('cohorts.new')}</Button>}>
    <WorkspaceToolbar>
      <p className="text-xs leading-5 text-muted-foreground">
        {t('cohorts.audienceHint')}
      </p>
    </WorkspaceToolbar>
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(240px,0.35fr)_minmax(0,1fr)]">
      <WorkspacePanel title={t('cohorts.title')} bodyClassName="space-y-3 max-h-[36rem] overflow-y-auto">
        {items.map((item) => <button key={item.id} onClick={() => open(item)} aria-pressed={selected?.id === item.id} className={`w-full rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected?.id === item.id ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'}`}>
          <div className="break-words font-medium">{item.name}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {tp('common.counts.participant', item.member_count)}
          </div>
          {item.responsible_user_name && <div className="mt-1 truncate text-xs text-primary">{t('cohorts.responsible')}: {item.responsible_user_name}</div>}
        </button>)}
        {!items.length && <p className="p-3 text-sm text-muted-foreground">{t('cohorts.empty')}</p>}
      </WorkspacePanel>
      <div className="min-w-0 space-y-5">
      <WorkspacePanel title={selected?.name || t('cohorts.new')} bodyClassName="space-y-5">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 text-sm font-medium">{t('cohorts.name')}<Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t('cohorts.namePlaceholder')} /></label>
          <label className="space-y-2 text-sm font-medium">{t('cohorts.description')}<Input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        </div>
        <label className="block space-y-2 text-sm font-medium">
          {t('cohorts.responsible')}
          <select value={responsibleUserId} onChange={(event) => setResponsibleUserId(event.target.value)} className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">
            <option value="">{t('cohorts.responsibleNone')}</option>
            {methodologists.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <span className="block text-xs font-normal text-muted-foreground">{t('cohorts.responsibleHint')}</span>
        </label>
      </WorkspacePanel>
        {selected ? <WorkspacePanel title={t('cohorts.members')} bodyClassName="space-y-5">
          <Selector title={t('cohorts.members')} items={users} selected={userIds} onToggle={toggle} />
          <div className="flex justify-end border-t border-border pt-4"><Button onClick={saveMembers} disabled={saving} className="gap-2"><Save className="h-4 w-4" aria-hidden="true" />{t('cohorts.save')}</Button></div>
        </WorkspacePanel> : <div className="flex justify-end"><Button onClick={create} disabled={saving || !name.trim()}>{t('cohorts.create')}</Button></div>}
      </div>
    </div>
  </WorkspacePage>;
}

function Selector({ title, items, selected, onToggle }: { title: string; items: Option[]; selected: string[]; onToggle: (id: string) => void }) {
  return <div role="group" aria-label={title} className="grid max-h-80 gap-2 overflow-y-auto sm:grid-cols-2">{items.map((item) => <label key={item.id} className={`flex min-w-0 cursor-pointer items-start gap-3 rounded-xl border p-3 ${selected.includes(item.id) ? 'border-primary/30 bg-primary/5' : 'border-border'}`}><input className="mt-1 shrink-0" type="checkbox" checked={selected.includes(item.id)} onChange={() => onToggle(item.id)} /><span className="break-words text-sm">{item.name}</span></label>)}</div>;
}
