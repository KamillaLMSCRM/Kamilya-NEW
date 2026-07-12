'use client';

import { useCallback, useEffect, useState } from 'react';
import { Users, Plus, Save } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';

type Cohort = { id: string; name: string; description: string; member_count: number; course_count: number };
type Option = { id: string; name: string };
type Detail = Cohort & { user_ids: string[]; course_ids: string[] };
type Progress = { total_assignments: number; assigned: number; in_progress: number; completed: number };

export default function CohortsPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const manager = ['admin', 'org_admin', 'methodologist', 'teacher'].includes(role || '');
  const [items, setItems] = useState<Cohort[]>([]);
  const [users, setUsers] = useState<Option[]>([]);
  const [courses, setCourses] = useState<Option[]>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [name, setName] = useState(''); const [description, setDescription] = useState(''); const [userIds, setUserIds] = useState<string[]>([]); const [courseIds, setCourseIds] = useState<string[]>([]); const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    try { if (manager) { const [cohorts, userList, courseList] = await Promise.all([api.get<Cohort[]>('/v1/cohorts'), api.get<any>('/v1/users?per_page=500'), api.get<any[]>('/v1/courses')]); setItems(cohorts.data); const rows: any[] = Array.isArray(userList.data) ? userList.data : (userList.data?.items || []); setUsers(rows.map((item: any) => ({ id: item.id, name: `${item.first_name || ''} ${item.last_name || ''}`.trim() || item.email || item.id }))); setCourses(courseList.data.map((item) => ({ id: item.id, name: item.title }))); } }
    catch (error: any) { toast.error(t('cohorts.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
  }, [manager, t]);
  useEffect(() => { load(); }, [load]);
  const open = async (item: Cohort) => { try { const [detail, stats] = await Promise.all([api.get<Detail>(`/v1/cohorts/${item.id}`), api.get<Progress>(`/v1/cohorts/${item.id}/progress`)]); setSelected(detail.data); setName(detail.data.name); setDescription(detail.data.description); setUserIds(detail.data.user_ids); setCourseIds(detail.data.course_ids); setProgress(stats.data); } catch (error: any) { toast.error(t('cohorts.loadFailed'), { description: error?.response?.data?.detail || error?.message }); } };
  const create = async () => { if (!name.trim()) return; setSaving(true); try { const response = await api.post<Cohort>('/v1/cohorts', { name: name.trim(), description }); setItems((list) => [response.data, ...list]); setSelected({ ...response.data, user_ids: [], course_ids: [] }); toast.success(t('cohorts.created')); } catch (error: any) { toast.error(t('cohorts.saveFailed'), { description: error?.response?.data?.detail || error?.message }); } finally { setSaving(false); } };
  const saveLinks = async () => { if (!selected) return; setSaving(true); try { await api.put(`/v1/cohorts/${selected.id}/links`, { user_ids: userIds, course_ids: courseIds }); await load(); toast.success(t('cohorts.saved')); } catch (error: any) { toast.error(t('cohorts.saveFailed'), { description: error?.response?.data?.detail || error?.message }); } finally { setSaving(false); } };
  const apply = async () => { if (!selected) return; setSaving(true); try { const response = await api.post(`/v1/cohorts/${selected.id}/apply`); const stats = await api.get<Progress>(`/v1/cohorts/${selected.id}/progress`); setProgress(stats.data); toast.success(t('cohorts.applied', { count: response.data.added })); } catch (error: any) { toast.error(t('cohorts.applyFailed'), { description: error?.response?.data?.detail || error?.message }); } finally { setSaving(false); } };
  const toggle = (setter: React.Dispatch<React.SetStateAction<string[]>>, id: string) => setter((list) => list.includes(id) ? list.filter((item) => item !== id) : [...list, id]);
  if (!manager) return <div className="p-6"><h1 className="text-2xl font-bold">{t('cohorts.title')}</h1><p className="mt-2 text-muted-foreground">{t('cohorts.learnerHint')}</p></div>;
  return <div className="mx-auto max-w-7xl space-y-6 p-6"><div><h1 className="text-2xl font-bold">{t('cohorts.title')}</h1><p className="text-muted-foreground">{t('cohorts.subtitle')}</p></div><div className="grid gap-6 lg:grid-cols-[280px_1fr]"><Card><CardContent className="space-y-3 p-4"><Button className="w-full gap-2" onClick={() => { setSelected(null); setName(''); setDescription(''); setUserIds([]); setCourseIds([]); setProgress(null); }}><Plus className="h-4 w-4" />{t('cohorts.new')}</Button>{items.map((item) => <button key={item.id} onClick={() => open(item)} className={`w-full rounded-lg border p-3 text-left ${selected?.id === item.id ? 'border-primary bg-primary/5' : 'border-border'}`}><div className="truncate font-medium">{item.name}</div><div className="mt-1 text-xs text-muted-foreground">{item.member_count} {t('cohorts.members')} · {item.course_count} {t('cohorts.courses')}</div></button>)}{!items.length && <p className="p-3 text-sm text-muted-foreground">{t('cohorts.empty')}</p>}</CardContent></Card><Card><CardContent className="space-y-5 p-6"><div className="grid gap-4 md:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('cohorts.name')}<Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t('cohorts.namePlaceholder')} /></label><label className="space-y-2 text-sm font-medium">{t('cohorts.description')}<Input value={description} onChange={(event) => setDescription(event.target.value)} /></label></div>{selected ? <><Selector title={t('cohorts.members')} items={users} selected={userIds} onToggle={(id) => toggle(setUserIds, id)} /><Selector title={t('cohorts.courses')} items={courses} selected={courseIds} onToggle={(id) => toggle(setCourseIds, id)} /><div className="flex flex-wrap items-center justify-between gap-3"><span className="text-sm text-muted-foreground">{progress ? `${t('cohorts.progress')}: ${progress.completed}/${progress.total_assignments}` : ''}</span><div className="flex gap-2"><Button variant="outline" onClick={saveLinks} disabled={saving} className="gap-2"><Save className="h-4 w-4" />{t('cohorts.save')}</Button><Button onClick={apply} disabled={saving || !userIds.length || !courseIds.length}>{t('cohorts.apply')}</Button></div></div></> : <div className="flex justify-end"><Button onClick={create} disabled={saving || !name.trim()}>{t('cohorts.create')}</Button></div>}</CardContent></Card></div></div>;
}

function Selector({ title, items, selected, onToggle }: { title: string; items: Option[]; selected: string[]; onToggle: (id: string) => void }) { return <section><h2 className="mb-3 flex items-center gap-2 font-semibold"><Users className="h-4 w-4 text-primary" />{title}</h2><div className="grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">{items.map((item) => <label key={item.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3"><input type="checkbox" checked={selected.includes(item.id)} onChange={() => onToggle(item.id)} /><span className="truncate text-sm">{item.name}</span></label>)}</div></section>; }
