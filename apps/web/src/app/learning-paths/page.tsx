'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { BookOpen, CheckCircle2, GripVertical, Plus, Save } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';

type PathSummary = { id: string; title: string; description: string; status: 'draft' | 'published' | 'archived'; course_count: number };
type PathDetail = PathSummary & { courses: { course_id: string; title: string; order_index: number; required: boolean }[] };
type LearnerPath = { id: string; title: string; description: string; total_courses: number; completed_courses: number; progress_percent: number };
type Course = { id: string; title: string; status: string };
const MANAGER_ROLES = ['admin', 'org_admin', 'methodologist'];

export default function LearningPathsPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const canManage = !!role && MANAGER_ROLES.includes(role);
  const [paths, setPaths] = useState<PathSummary[]>([]);
  const [learnerPaths, setLearnerPaths] = useState<LearnerPath[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [selected, setSelected] = useState<PathDetail | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [status, setStatus] = useState<'draft' | 'published' | 'archived'>('draft');
  const [courseIds, setCourseIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (canManage) {
        const [pathsRes, coursesRes] = await Promise.all([api.get<PathSummary[]>('/v1/learning-paths'), api.get<Course[]>('/v1/courses')]);
        setPaths(pathsRes.data); setCourses(coursesRes.data);
      } else {
        const response = await api.get<LearnerPath[]>('/v1/learning-paths/my');
        setLearnerPaths(response.data);
      }
    } catch (error: any) {
      toast.error(t('learningPaths.loadFailed'), { description: error?.response?.data?.detail || error?.message });
    } finally { setLoading(false); }
  }, [canManage, t]);

  useEffect(() => { load(); }, [load]);

  const selectPath = async (path: PathSummary) => {
    try {
      const response = await api.get<PathDetail>(`/v1/learning-paths/${path.id}`);
      setSelected(response.data); setTitle(response.data.title); setDescription(response.data.description); setStatus(response.data.status); setCourseIds(response.data.courses.map((course) => course.course_id));
    } catch (error: any) { toast.error(t('learningPaths.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
  };

  const createPath = async () => {
    if (!title.trim()) return;
    setSaving(true);
    try { const response = await api.post<PathSummary>('/v1/learning-paths', { title: title.trim(), description, status: 'published' }); await load(); await selectPath(response.data); toast.success(t('learningPaths.created')); }
    catch (error: any) { toast.error(t('learningPaths.saveFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  const savePath = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await api.patch(`/v1/learning-paths/${selected.id}`, { title: title.trim(), description, status });
      const response = await api.put<PathDetail>(`/v1/learning-paths/${selected.id}/courses`, { course_ids: courseIds });
      setSelected(response.data); setPaths((items) => items.map((item) => item.id === response.data.id ? { ...item, ...response.data, course_count: response.data.courses.length } : item)); toast.success(t('learningPaths.saved'));
    } catch (error: any) { toast.error(t('learningPaths.saveFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="p-6 text-muted-foreground">{t('common.loading')}</div>;
  if (!canManage) return <div className="mx-auto max-w-5xl space-y-6 p-6"><div><h1 className="text-2xl font-bold">{t('learningPaths.title')}</h1><p className="text-muted-foreground">{t('learningPaths.learnerDescription')}</p></div>{learnerPaths.length === 0 ? <Card><CardContent className="p-8 text-center text-muted-foreground">{t('learningPaths.empty')}</CardContent></Card> : <div className="grid gap-4 md:grid-cols-2">{learnerPaths.map((path) => <Card key={path.id}><CardContent className="space-y-4 p-5"><div className="flex items-start gap-3"><BookOpen className="mt-1 h-5 w-5 shrink-0 text-primary" /><div><h2 className="font-semibold">{path.title}</h2><p className="mt-1 text-sm text-muted-foreground">{path.description}</p></div></div><div><div className="mb-1 flex justify-between text-xs text-muted-foreground"><span>{path.completed_courses}/{path.total_courses} {t('learningPaths.courses')}</span><span>{path.progress_percent}%</span></div><div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${path.progress_percent}%` }} /></div></div><Link href="/student"><Button variant="outline" size="sm">{path.progress_percent === 100 ? <CheckCircle2 className="mr-2 h-4 w-4" /> : null}{t('learningPaths.openLearning')}</Button></Link></CardContent></Card>)}</div>}</div>;

  return <div className="mx-auto max-w-7xl space-y-6 p-6"><div><h1 className="text-2xl font-bold">{t('learningPaths.title')}</h1><p className="text-muted-foreground">{t('learningPaths.managerDescription')}</p></div><div className="grid gap-6 lg:grid-cols-[280px_1fr]"><Card><CardContent className="space-y-3 p-4"><Button className="w-full gap-2" onClick={() => { setSelected(null); setTitle(''); setDescription(''); setCourseIds([]); }}><Plus className="h-4 w-4" />{t('learningPaths.new')}</Button>{paths.map((path) => <button key={path.id} onClick={() => selectPath(path)} className={`w-full rounded-lg border p-3 text-left ${selected?.id === path.id ? 'border-primary bg-primary/5' : 'border-border'}`}><div className="truncate font-medium">{path.title}</div><div className="mt-1 text-xs text-muted-foreground">{path.course_count} {t('learningPaths.courses')} · {t(`learningPaths.status.${path.status}` as any)}</div></button>)}{!paths.length && <p className="p-3 text-sm text-muted-foreground">{t('learningPaths.empty')}</p>}</CardContent></Card><Card><CardContent className="space-y-5 p-6"><div className="grid gap-4 md:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('learningPaths.name')}<Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t('learningPaths.namePlaceholder')} /></label><label className="space-y-2 text-sm font-medium">{t('learningPaths.description')}<Input value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t('learningPaths.descriptionPlaceholder')} /></label></div><div><h2 className="mb-3 font-semibold">{t('learningPaths.selectCourses')}</h2><div className="grid gap-2 sm:grid-cols-2">{courses.map((course) => <label key={course.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3"><input type="checkbox" checked={courseIds.includes(course.id)} onChange={() => setCourseIds((items) => items.includes(course.id) ? items.filter((id) => id !== course.id) : [...items, course.id])} /><GripVertical className="h-4 w-4 text-muted-foreground" /><span className="min-w-0 truncate">{course.title}</span></label>)}</div>{!courses.length && <p className="text-sm text-muted-foreground">{t('learningPaths.noCourses')}</p>}</div>{courseIds.length > 0 && <p className="text-sm text-muted-foreground">{t('learningPaths.selectedCount', { count: courseIds.length })}</p>}<div className="flex justify-end"><Button onClick={selected ? savePath : createPath} disabled={saving || !title.trim()} className="gap-2"><Save className="h-4 w-4" />{selected ? t('learningPaths.save') : t('learningPaths.create')}</Button></div></CardContent></Card></div></div>;
}
