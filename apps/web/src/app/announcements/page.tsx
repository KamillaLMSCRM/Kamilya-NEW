'use client';

import { useCallback, useEffect, useState } from 'react';
import { Mail, Plus, Send } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Input } from '@/components/ui';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';
import { toast } from '@/components/ui/Toast';

type Announcement = { id: string; title: string; body: string; course_id: string | null; status: string; recipients_count: number; sent_count: number; failed_count: number; created_at: string };
type Option = { id: string; title: string };

export default function AnnouncementsPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const allowed = ['admin', 'methodologist'].includes(role || '');
  const [items, setItems] = useState<Announcement[]>([]);
  const [courses, setCourses] = useState<Option[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [courseId, setCourseId] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try { const [announcements, courseList] = await Promise.all([api.get<Announcement[]>('/v1/announcements'), api.get<any[]>('/v1/courses')]); setItems(announcements.data); setCourses(courseList.data.map((course) => ({ id: course.id, title: course.title }))); }
    catch (error: any) { setLoadError(true); toast.error(t('announcements.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setLoading(false); }
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
  return (
    <WorkspacePage id="announcements" title={t('announcements.title')} description={t('announcements.subtitle')} icon={<Mail />} className="mx-auto max-w-6xl">
      <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <WorkspacePanel title={t('announcements.create')} bodyClassName="space-y-5">
          <div className="space-y-4">
            <label className="block min-w-0 space-y-2 text-sm font-medium">{t('announcements.subject')}<Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t('announcements.subjectPlaceholder')} /></label>
            <label className="block min-w-0 space-y-2 text-sm font-medium">{t('announcements.course')}<select value={courseId} onChange={(event) => setCourseId(event.target.value)} className="min-h-10 w-full min-w-0 rounded-md border border-border bg-background px-3 py-2 text-sm"><option value="">{t('announcements.allCourses')}</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>
          </div>
          <label className="block space-y-2 text-sm font-medium">{t('announcements.message')}<textarea value={body} onChange={(event) => setBody(event.target.value)} rows={6} placeholder={t('announcements.messagePlaceholder')} className="w-full rounded-md border border-border bg-background p-3 text-sm outline-none focus:ring-2 focus:ring-primary" /></label>
          <div className="flex flex-wrap justify-end border-t border-border pt-4"><Button onClick={create} disabled={saving || !title.trim() || !body.trim()} className="gap-2"><Plus className="h-4 w-4" aria-hidden="true" />{t('announcements.create')}</Button></div>
        </WorkspacePanel>
        <div className="min-w-0 space-y-4">
          {loading ? <WorkspacePanel><p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p></WorkspacePanel> : loadError ? <WorkspacePanel><div role="alert" className="space-y-3 text-sm text-destructive"><p>{t('announcements.loadFailed')}</p><Button variant="outline" onClick={() => void load()}>{t('common.retry')}</Button></div></WorkspacePanel> : items.length ? items.map((item) => (
            <WorkspacePanel key={item.id} title={item.title} description={item.status === 'draft' ? t('announcements.draft') : undefined} bodyClassName="space-y-4" actions={item.status === 'draft' && <Button variant="outline" onClick={() => send(item.id)} disabled={saving} className="gap-2"><Send className="h-4 w-4" aria-hidden="true" />{t('announcements.send')}</Button>}>
              <p className="whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">{item.body}</p>
              {item.status !== 'draft' && <WorkspaceToolbar className="border-0 bg-muted/30"><p className="text-sm font-medium tabular-nums">{t('announcements.delivery', { sent: item.sent_count, total: item.recipients_count })}</p></WorkspaceToolbar>}
            </WorkspacePanel>
          )) : <WorkspaceEmpty title={t('announcements.empty')} />}
        </div>
      </div>
    </WorkspacePage>
  );
}
