'use client';

import { useCallback, useEffect, useState } from 'react';
import { Mail, Plus, Send } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';

type Announcement = { id: string; title: string; body: string; course_id: string | null; status: string; recipients_count: number; sent_count: number; failed_count: number; created_at: string };
type Option = { id: string; title: string };

export default function AnnouncementsPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const allowed = ['admin', 'org_admin', 'methodologist'].includes(role || '');
  const [items, setItems] = useState<Announcement[]>([]);
  const [courses, setCourses] = useState<Option[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [courseId, setCourseId] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try { const [announcements, courseList] = await Promise.all([api.get<Announcement[]>('/v1/announcements'), api.get<any[]>('/v1/courses')]); setItems(announcements.data); setCourses(courseList.data.map((course) => ({ id: course.id, title: course.title }))); }
    catch (error: any) { toast.error(t('announcements.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
  }, [t]);
  useEffect(() => { if (allowed) load(); }, [allowed, load]);

  const create = async () => {
    if (!title.trim() || !body.trim()) return;
    setSaving(true);
    try { await api.post('/v1/announcements', { title: title.trim(), body: body.trim(), course_id: courseId || null }); setTitle(''); setBody(''); setCourseId(''); await load(); toast.success(t('announcements.created')); }
    catch (error: any) { toast.error(t('announcements.saveFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  const send = async (id: string) => {
    setSaving(true);
    try { const response = await api.post(`/v1/announcements/${id}/send`); await load(); toast.success(t('announcements.sent', { count: response.data.sent_count })); }
    catch (error: any) { toast.error(t('announcements.sendFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  if (!allowed) return <div className="p-8 text-center text-muted-foreground">{t('announcements.forbidden')}</div>;
  return <div className="mx-auto max-w-6xl space-y-6 p-6"><div><h1 className="text-2xl font-bold">{t('announcements.title')}</h1><p className="text-muted-foreground">{t('announcements.subtitle')}</p></div><Card><CardContent className="space-y-4 p-6"><div className="grid gap-4 md:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('announcements.subject')}<Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t('announcements.subjectPlaceholder')} /></label><label className="space-y-2 text-sm font-medium">{t('announcements.course')}<select value={courseId} onChange={(event) => setCourseId(event.target.value)} className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">{t('announcements.allCourses')}</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label></div><label className="space-y-2 text-sm font-medium">{t('announcements.message')}<textarea value={body} onChange={(event) => setBody(event.target.value)} rows={5} placeholder={t('announcements.messagePlaceholder')} className="w-full rounded-md border border-border bg-background p-3 text-sm outline-none focus:ring-2 focus:ring-primary" /></label><div className="flex justify-end"><Button onClick={create} disabled={saving || !title.trim() || !body.trim()} className="gap-2"><Plus className="h-4 w-4" />{t('announcements.create')}</Button></div></CardContent></Card><div className="space-y-3">{items.map((item) => <Card key={item.id}><CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex items-center gap-2"><Mail className="h-4 w-4 text-primary" /><h2 className="truncate font-semibold">{item.title}</h2></div><p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{item.body}</p><p className="mt-2 text-xs text-muted-foreground">{item.status === 'draft' ? t('announcements.draft') : t('announcements.delivery', { sent: item.sent_count, total: item.recipients_count })}</p></div>{item.status === 'draft' && <Button variant="outline" onClick={() => send(item.id)} disabled={saving} className="shrink-0 gap-2"><Send className="h-4 w-4" />{t('announcements.send')}</Button>}</CardContent></Card>)}{!items.length && <Card><CardContent className="p-8 text-center text-muted-foreground">{t('announcements.empty')}</CardContent></Card>}</div></div>;
}
