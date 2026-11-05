'use client';

import { useCallback, useEffect, useState } from 'react';
import { MessageSquare, Plus, Send } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Input } from '@/components/ui';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';
import { toast } from '@/components/ui/Toast';

type Survey = { id: string; course_id: string; title: string; status: string; question_count: number };
type Question = { id: string; text: string; type: 'rating' | 'text'; required: boolean };
type LearnerSurvey = { id: string; course_id: string; course_title: string; title: string; questions: Question[]; submitted: boolean };

export default function SurveysPage() {
  const { t, tp } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const manager = ['admin', 'methodologist'].includes(role || '');
  const [items, setItems] = useState<Survey[]>([]);
  const [learnerItems, setLearnerItems] = useState<LearnerSurvey[]>([]);
  const [courses, setCourses] = useState<{ id: string; title: string }[]>([]);
  const [title, setTitle] = useState('');
  const [courseId, setCourseId] = useState('');
  const [question, setQuestion] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      if (manager) { const [surveys, courseList] = await Promise.all([api.get<Survey[]>('/v1/surveys'), api.get<any[]>('/v1/courses')]); setItems(surveys.data); setCourses(courseList.data.map((course) => ({ id: course.id, title: course.title }))); }
      else { const response = await api.get<LearnerSurvey[]>('/v1/surveys/my'); setLearnerItems(response.data); }
    } catch (error: any) { setLoadError(true); toast.error(t('surveys.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setLoading(false); }
  }, [manager, t]);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!title.trim() || !courseId || !question.trim()) return;
    setSaving(true);
    try { await api.post('/v1/surveys', { title: title.trim(), course_id: courseId, status: 'published', questions: [{ id: 'overall', text: question.trim(), type: 'rating', required: true }] }); setTitle(''); setCourseId(''); setQuestion(''); await load(); toast.success(t('surveys.created')); }
    catch (error: any) { toast.error(t('surveys.saveFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  const submit = async (survey: LearnerSurvey, value: number | string) => {
    setSaving(true);
    try { await api.post(`/v1/surveys/${survey.id}/responses`, { answers: { [survey.questions[0]?.id || 'overall']: value } }); await load(); toast.success(t('surveys.submitted')); }
    catch (error: any) { toast.error(t('surveys.submitFailed'), { description: error?.response?.data?.detail || error?.message }); }
    finally { setSaving(false); }
  };

  const readState = loading ? <p role="status" className="p-6 text-sm text-muted-foreground">{t('common.loading')}</p> : loadError ? <div role="alert" className="space-y-3 p-6 text-sm text-destructive"><p>{t('surveys.loadFailed')}</p><Button variant="outline" onClick={() => void load()}>{t('common.retry')}</Button></div> : null;

  if (manager) return (
    <WorkspacePage id="surveys" title={t('surveys.title')} description={t('surveys.managerSubtitle')} icon={<MessageSquare />} className="mx-auto max-w-6xl">
      <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <WorkspacePanel title={t('surveys.create')} bodyClassName="space-y-5">
          <div className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-1">
            <label className="block min-w-0 space-y-2 text-sm font-medium">{t('surveys.name')}<Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t('surveys.namePlaceholder')} /></label>
            <label className="block min-w-0 space-y-2 text-sm font-medium">{t('surveys.course')}<select value={courseId} onChange={(event) => setCourseId(event.target.value)} className="min-h-10 w-full min-w-0 rounded-md border border-border bg-background px-3 py-2 text-sm"><option value="">{t('surveys.selectCourse')}</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>
          </div>
          <label className="block space-y-2 text-sm font-medium">{t('surveys.question')}<Input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={t('surveys.questionPlaceholder')} /></label>
          <div className="flex flex-wrap justify-end border-t border-border pt-4"><Button onClick={create} disabled={saving || !title.trim() || !courseId || !question.trim()} className="gap-2"><Plus className="h-4 w-4" aria-hidden="true" />{t('surveys.create')}</Button></div>
        </WorkspacePanel>
        <WorkspacePanel title={t('surveys.title')} padded={false}>
          {readState || (items.length ? <ul className="divide-y divide-border">{items.map((item) => <li key={item.id} className="flex min-w-0 items-start gap-3 p-5"><MessageSquare className="mt-1 h-5 w-5 shrink-0 text-primary" aria-hidden="true" /><div className="min-w-0"><h3 className="break-words font-semibold">{item.title}</h3><p className="mt-2 text-sm text-muted-foreground">{tp('common.counts.question', item.question_count)} · {item.status}</p></div></li>)}</ul> : <div className="p-5"><WorkspaceEmpty title={t('surveys.empty')} /></div>)}
        </WorkspacePanel>
      </div>
    </WorkspacePage>
  );

  return (
    <WorkspacePage id="surveys" title={t('surveys.title')} description={t('surveys.learnerSubtitle')} icon={<MessageSquare />} className="mx-auto max-w-5xl">
      {readState || (learnerItems.length === 0 ? <WorkspaceEmpty title={t('surveys.noPending')} /> : <div className="grid min-w-0 gap-5">{learnerItems.map((survey) => (
        <WorkspacePanel key={survey.id} title={survey.title} description={survey.course_title} bodyClassName="space-y-4">
          {survey.submitted ? <p role="status" className="rounded-xl border border-success/20 bg-success/5 p-4 text-sm text-success">{t('surveys.alreadySubmitted')}</p> : <>
            <p className="break-words text-sm font-medium">{survey.questions[0]?.text}</p>
            <WorkspaceToolbar role="group" aria-label={survey.questions[0]?.text} className="border-0 bg-muted/30">
              {[1, 2, 3, 4, 5].map((value) => <Button key={value} variant="outline" disabled={saving} onClick={() => submit(survey, value)} className="min-h-11 min-w-11">{value}</Button>)}
              <Send className="ml-2 h-4 w-4 self-center text-primary" aria-hidden="true" />
            </WorkspaceToolbar>
          </>}
        </WorkspacePanel>
      ))}</div>)}
    </WorkspacePage>
  );
}
