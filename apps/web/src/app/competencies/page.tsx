'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus, Save, Target } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';

type Item = { id: string; name: string; description: string; position_count: number; course_count: number };
type LinkItem = { id: string; name: string };
type Detail = Item & { position_ids: string[]; course_ids: string[] };

export default function CompetenciesPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const allowed = ['admin', 'org_admin', 'methodologist'].includes(role || '');
  const [items, setItems] = useState<Item[]>([]);
  const [positions, setPositions] = useState<LinkItem[]>([]);
  const [courses, setCourses] = useState<LinkItem[]>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [positionIds, setPositionIds] = useState<string[]>([]);
  const [courseIds, setCourseIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [competencies, positionList, courseList] = await Promise.all([
        api.get<Item[]>('/v1/competencies'), api.get<any[]>('/v1/positions'), api.get<any[]>('/v1/courses'),
      ]);
      setItems(competencies.data); setPositions(positionList.data.map((item) => ({ id: item.id, name: item.name }))); setCourses(courseList.data.map((item) => ({ id: item.id, name: item.title })));
    } catch (error: any) { toast.error(t('competencies.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
  }, [t]);

  useEffect(() => { if (allowed) load(); }, [allowed, load]);

  const open = async (item: Item) => {
    try { const response = await api.get<Detail>(`/v1/competencies/${item.id}`); setSelected(response.data); setName(response.data.name); setDescription(response.data.description); setPositionIds(response.data.position_ids); setCourseIds(response.data.course_ids); }
    catch (error: any) { toast.error(t('competencies.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
  };

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try { const response = await api.post<Detail>('/v1/competencies', { name: name.trim(), description }); await load(); await open(response.data); toast.success(t('competencies.created')); }
    catch (error: any) { toast.error(t('competencies.saveFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    try { await api.patch(`/v1/competencies/${selected.id}`, { name: name.trim(), description }); await api.put(`/v1/competencies/${selected.id}/links`, { position_ids: positionIds, course_ids: courseIds }); await load(); toast.success(t('competencies.saved')); }
    catch (error: any) { toast.error(t('competencies.saveFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  if (!allowed) return <div className="p-8 text-center text-muted-foreground">{t('competencies.forbidden')}</div>;
  return <div className="mx-auto max-w-7xl space-y-6 p-6"><div><h1 className="text-2xl font-bold">{t('competencies.title')}</h1><p className="text-muted-foreground">{t('competencies.subtitle')}</p></div><div className="grid gap-6 lg:grid-cols-[300px_1fr]"><Card><CardContent className="space-y-3 p-4"><Button className="w-full gap-2" onClick={() => { setSelected(null); setName(''); setDescription(''); setPositionIds([]); setCourseIds([]); }}><Plus className="h-4 w-4" />{t('competencies.new')}</Button>{items.map((item) => <button key={item.id} onClick={() => open(item)} className={`w-full rounded-lg border p-3 text-left ${selected?.id === item.id ? 'border-primary bg-primary/5' : 'border-border'}`}><div className="truncate font-medium">{item.name}</div><div className="mt-1 text-xs text-muted-foreground">{item.position_count} {t('competencies.positions')} · {item.course_count} {t('competencies.courses')}</div></button>)}{!items.length && <p className="p-3 text-sm text-muted-foreground">{t('competencies.empty')}</p>}</CardContent></Card><Card><CardContent className="space-y-6 p-6"><div className="grid gap-4 md:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('competencies.name')}<Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t('competencies.namePlaceholder')} /></label><label className="space-y-2 text-sm font-medium">{t('competencies.description')}<Input value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t('competencies.descriptionPlaceholder')} /></label></div><LinkSelector title={t('competencies.positions')} items={positions} selected={positionIds} onToggle={(id) => setPositionIds((list) => list.includes(id) ? list.filter((value) => value !== id) : [...list, id])} /><LinkSelector title={t('competencies.courses')} items={courses} selected={courseIds} onToggle={(id) => setCourseIds((list) => list.includes(id) ? list.filter((value) => value !== id) : [...list, id])} /><div className="flex justify-end"><Button onClick={selected ? save : create} disabled={saving || !name.trim()} className="gap-2"><Save className="h-4 w-4" />{selected ? t('competencies.save') : t('competencies.create')}</Button></div></CardContent></Card></div></div>;
}

function LinkSelector({ title, items, selected, onToggle }: { title: string; items: LinkItem[]; selected: string[]; onToggle: (id: string) => void }) {
  return <section><h2 className="mb-3 flex items-center gap-2 font-semibold"><Target className="h-4 w-4 text-primary" />{title}</h2><div className="grid gap-2 sm:grid-cols-2">{items.map((item) => <label key={item.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3"><input type="checkbox" checked={selected.includes(item.id)} onChange={() => onToggle(item.id)} /><span className="truncate text-sm">{item.name}</span></label>)}</div>{!items.length && <p className="text-sm text-muted-foreground">-</p>}</section>;
}
