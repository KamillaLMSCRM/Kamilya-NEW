'use client';

import { FormEvent, useEffect, useState } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { api } from '@/lib/api';

type Campaign = { id: string; title: string; status: string; expires_at: string };
type Course = { id: string; title: string; status: string; current_release_id: string | null };
type IssuedAccess = { access_url: string; temporary_pin: string };

export default function CandidateAssessmentsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [releaseId, setReleaseId] = useState('');
  const [title, setTitle] = useState('');
  const [candidateName, setCandidateName] = useState('');
  const [candidateEmail, setCandidateEmail] = useState('');
  const [issued, setIssued] = useState<IssuedAccess | null>(null);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  async function load() {
    const [campaignResponse, courseResponse] = await Promise.all([
      api.get('/v1/candidate-assessments'),
      api.get('/v1/courses?status=published&per_page=100'),
    ]);
    setCampaigns(campaignResponse.data);
    setCourses((courseResponse.data as Course[]).filter((course) => course.current_release_id));
  }
  useEffect(() => { void load().catch(() => setError('Не удалось загрузить оценки кандидатов.')); }, []);

  async function create(event: FormEvent) {
    event.preventDefault(); setError(''); setFeedback('');
    try {
      await api.post('/v1/candidate-assessments', {
        content_release_id: releaseId, title,
        instructions: 'Пройдите оценку самостоятельно до указанного срока.',
        expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
        attempt_limit: 1, retention_days: 180,
      });
      setReleaseId(''); setTitle(''); setFeedback('Кампания создана. Запустите её перед приглашением кандидата.'); await load();
    } catch { setError('Не удалось создать кампанию для выбранного курса.'); }
  }

  async function invite(campaignId: string) {
    setError(''); setFeedback(''); setIssued(null);
    const [firstName, ...lastParts] = candidateName.trim().split(/\s+/);
    try {
      const response = await api.post(`/v1/candidate-assessments/${campaignId}/candidates`, {
        first_name: firstName, last_name: lastParts.join(' '), email: candidateEmail || null, phone: null,
      });
      const access = response.data as IssuedAccess;
      setIssued(access);
      try {
        await navigator.clipboard.writeText(`${access.access_url}\nPIN: ${access.temporary_pin}`);
        setFeedback('Защищённая ссылка и PIN скопированы. Передайте их кандидату раздельно.');
      } catch { setError('Не удалось скопировать автоматически. Скопируйте ссылку и PIN из блока ниже.'); }
      setCandidateName(''); setCandidateEmail('');
    } catch { setError('Не удалось создать приглашение кандидата.'); }
  }

  async function exportCsv(campaign: Campaign) {
    setError('');
    try {
      const response = await api.get(`/v1/candidate-assessments/${campaign.id}/results.csv`, { responseType: 'blob' });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${campaign.title}.csv`; anchor.click();
      URL.revokeObjectURL(url);
    } catch { setError('Не удалось выгрузить CSV.'); }
  }

  async function changeStatus(campaign: Campaign, status: 'active' | 'closed') {
    setError('');
    try { await api.patch(`/v1/candidate-assessments/${campaign.id}`, { status }); await load(); }
    catch { setError('Не удалось изменить статус кампании.'); }
  }

  return <div className="space-y-6 p-6">
    <div><h1 className="text-2xl font-bold">Тестирование кандидатов</h1><p className="text-sm text-muted-foreground">Проведите тест до найма по персональной ссылке и PIN. Кандидат не добавляется в штат и список обучающихся.</p></div>
    <Card><CardHeader><CardTitle>Новая кампания</CardTitle></CardHeader><CardContent>
      <form className="grid gap-3 sm:grid-cols-3" onSubmit={create}>
        <Input aria-label="Название кампании" placeholder="Название" value={title} onChange={(e) => setTitle(e.target.value)} />
        <select aria-label="Опубликованный курс" className="h-10 rounded-md border bg-background px-3 text-sm" value={releaseId} onChange={(e) => setReleaseId(e.target.value)}><option value="">Выберите опубликованный курс</option>{courses.map((course) => <option key={course.id} value={course.current_release_id || ''}>{course.title}</option>)}</select>
        <Button disabled={!title || !releaseId}>Создать</Button>
      </form>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>Пригласить кандидата</CardTitle></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2"><Input aria-label="Имя кандидата" value={candidateName} onChange={(e) => setCandidateName(e.target.value)} placeholder="Имя Фамилия" /><Input aria-label="Email кандидата (необязательно)" value={candidateEmail} onChange={(e) => setCandidateEmail(e.target.value)} placeholder="Email (необязательно)" /><p className="text-xs text-muted-foreground sm:col-span-2">Нажмите «Пригласить» в активной кампании. Защищённая ссылка и PIN будут показаны один раз.</p></CardContent></Card>
    {issued && <Card><CardContent className="space-y-2 p-4"><p className="font-medium">Доступ кандидата</p><p className="break-all text-sm">{issued.access_url}</p><p className="font-mono text-lg">PIN: {issued.temporary_pin}</p></CardContent></Card>}
    {feedback && <p role="status" className="text-sm text-foreground">{feedback}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="grid gap-3">{campaigns.map((campaign) => <Card key={campaign.id}><CardContent className="flex flex-wrap items-center justify-between gap-3 p-4"><div><p className="font-semibold">{campaign.title}</p><p className="text-sm text-muted-foreground">{campaign.status} · до {new Date(campaign.expires_at).toLocaleDateString('ru-RU')}</p></div><div className="flex gap-2"><Button variant="outline" onClick={() => void exportCsv(campaign)}>CSV</Button>{campaign.status === 'draft' && <Button variant="outline" onClick={() => void changeStatus(campaign, 'active')}>Запустить</Button>}{campaign.status === 'active' && <Button variant="outline" onClick={() => void changeStatus(campaign, 'closed')}>Закрыть</Button>}<Button disabled={campaign.status !== 'active' || !candidateName.trim()} onClick={() => void invite(campaign.id)}>Пригласить</Button></div></CardContent></Card>)}</div>
  </div>;
}
