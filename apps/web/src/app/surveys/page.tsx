'use client';

import { useCallback, useEffect, useState } from 'react';
import { MessageSquare, Plus, Send } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';

type Survey = { id: string; course_id: string; title: string; status: string; question_count: number };
type Question = { id: string; text: string; type: 'rating' | 'text'; required: boolean };
type LearnerSurvey = { id: string; course_id: string; course_title: string; title: string; questions: Question[]; submitted: boolean };

export default function SurveysPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const manager = ['admin', 'org_admin', 'methodologist', 'teacher'].includes(role || '');
  const [items, setItems] = useState<Survey[]>([]);
  const [learnerItems, setLearnerItems] = useState<LearnerSurvey[]>([]);
  const [courses, setCourses] = useState<{ id: string; title: string }[]>([]);
  const [title, setTitle] = useState('');
  const [courseId, setCourseId] = useState('');
  const [question, setQuestion] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      if (manager) { const [surveys, courseList] = await Promise.all([api.get<Survey[]>('/v1/surveys'), api.get<any[]>('/v1/courses')]); setItems(surveys.data); setCourses(courseList.data.map((course) => ({ id: course.id, title: course.title }))); }
      else { const response = await api.get<LearnerSurvey[]>('/v1/surveys/my'); setLearnerItems(response.data); }
    } catch (error: any) { toast.error(t('surveys.loadFailed'), { description: error?.response?.data?.detail || error?.message }); }
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

  if (manager) return <div className="mx-auto max-w-6xl space-y-6 p-6"><div><h1 className="text-2xl font-bold">{t('surveys.title')}</h1><p className="text-muted-foreground">{t('surveys.managerSubtitle')}</p></div><Card><CardContent className="space-y-4 p-6"><div className="grid gap-4 md:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('surveys.name')}<Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t('surveys.namePlaceholder')} /></label><label className="space-y-2 text-sm font-medium">{t('surveys.course')}<select value={courseId} onChange={(event) => setCourseId(event.target.value)} className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">{t('surveys.selectCourse')}</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label></div><label className="space-y-2 text-sm font-medium">{t('surveys.question')}<Input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={t('surveys.questionPlaceholder')} /></label><div className="flex justify-end"><Button onClick={create} disabled={saving || !title.trim() || !courseId || !question.trim()} className="gap-2"><Plus className="h-4 w-4" />{t('surveys.create')}</Button></div></CardContent></Card><div className="space-y-3">{items.map((item) => <Card key={item.id}><CardContent className="flex items-center justify-between gap-4 p-5"><div><h2 className="font-semibold">{item.title}</h2><p className="text-sm text-muted-foreground">{item.question_count} {t('surveys.questions')} · {item.status}</p></div><MessageSquare className="h-5 w-5 text-primary" /></CardContent></Card>)}{!items.length && <Card><CardContent className="p-8 text-center text-muted-foreground">{t('surveys.empty')}</CardContent></Card>}</div></div>;

  return <div className="mx-auto max-w-5xl space-y-6 p-6"><div><h1 className="text-2xl font-bold">{t('surveys.title')}</h1><p className="text-muted-foreground">{t('surveys.learnerSubtitle')}</p></div>{learnerItems.length === 0 ? <Card><CardContent className="p-8 text-center text-muted-foreground">{t('surveys.noPending')}</CardContent></Card> : <div className="space-y-4">{learnerItems.map((survey) => <Card key={survey.id}><CardContent className="space-y-4 p-6"><div><h2 className="font-semibold">{survey.title}</h2><p className="text-sm text-muted-foreground">{survey.course_title}</p></div>{survey.submitted ? <p className="text-sm text-success">{t('surveys.alreadySubmitted')}</p> : <div className="flex flex-wrap gap-2"><span className="mr-2 self-center text-sm">{survey.questions[0]?.text}</span>{[1, 2, 3, 4, 5].map((value) => <Button key={value} variant="outline" size="sm" disabled={saving} onClick={() => submit(survey, value)}>{value}</Button>)}<Send className="ml-2 h-4 w-4 self-center text-primary" /></div>}</CardContent></Card>)}</div>}</div>;
}
