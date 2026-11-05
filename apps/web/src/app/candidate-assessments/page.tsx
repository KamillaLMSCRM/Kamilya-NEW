'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Button, Input } from '@/components/ui';
import { ClipboardCheck } from 'lucide-react';
import { WorkspacePage, WorkspacePanel } from '@/features/workspace-design';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';

type Campaign = { id: string; title: string; status: string; expires_at: string };
type Course = { id: string; title: string; status: string; current_release_id: string | null };
type IssuedAccess = { access_url: string; temporary_pin: string };
type ErrorCode = '' | 'load' | 'createNoQuestions' | 'createReleaseMissing' | 'createGeneric' | 'invite' | 'clipboard' | 'csv' | 'status';
type FeedbackCode = '' | 'created' | 'copied';

const copy = {
  ru: {
    title: 'Тестирование кандидатов',
    description: 'Проведите тест до найма по персональной ссылке и PIN. Кандидат не добавляется в штат и список обучающихся.',
    newCampaign: 'Новая кампания',
    campaignTitle: 'Название кампании',
    campaignTitlePlaceholder: 'Название',
    publishedCourse: 'Опубликованный курс',
    chooseCourse: 'Выберите опубликованный курс',
    create: 'Создать',
    inviteCandidate: 'Пригласить кандидата',
    candidateName: 'Имя кандидата',
    candidateNamePlaceholder: 'Имя Фамилия',
    candidateEmail: 'Email кандидата (необязательно)',
    candidateEmailPlaceholder: 'Email (необязательно)',
    inviteHint: 'Нажмите «Пригласить» в активной кампании. Защищённая ссылка и PIN будут показаны один раз.',
    nameRequired: 'Введите имя кандидата, чтобы активировать приглашение.',
    candidateAccess: 'Доступ кандидата',
    pin: 'PIN',
    campaigns: 'Кампании',
    loading: 'Загружаем кампании…',
    empty: 'Кампаний пока нет. Создайте первую кампанию.',
    loadFailed: 'Не удалось загрузить оценки кандидатов.',
    coursesLoadFailed: 'Не удалось загрузить список опубликованных курсов.',
    noCourses: 'Нет опубликованных курсов с готовой версией.',
    courseLimit: 'Загружены первые 100 опубликованных курсов. Остальные в этом списке недоступны.',
    retry: 'Повторить',
    statusDraft: 'Черновик',
    statusActive: 'Активна',
    statusClosed: 'Закрыта',
    statusUnknown: 'Неизвестный статус',
    until: 'до',
    csv: 'CSV',
    start: 'Запустить',
    close: 'Закрыть',
    invite: 'Пригласить',
    instructions: 'Пройдите оценку самостоятельно до указанного срока.',
    feedbackCreated: 'Кампания создана. Запустите её перед приглашением кандидата.',
    feedbackCopied: 'Защищённая ссылка и PIN скопированы. Передайте их кандидату раздельно.',
    errors: {
      load: 'Не удалось загрузить оценки кандидатов.',
      createNoQuestions: 'В опубликованной версии курса нет одобренных вопросов. Проверьте тесты и опубликуйте новую версию курса.',
      createReleaseMissing: 'Опубликованная версия курса не найдена. Обновите страницу и выберите курс снова.',
      createGeneric: 'Не удалось создать кампанию для выбранного курса.',
      invite: 'Не удалось создать приглашение кандидата.',
      clipboard: 'Не удалось скопировать автоматически. Скопируйте ссылку и PIN из блока ниже.',
      csv: 'Не удалось выгрузить CSV.',
      status: 'Не удалось изменить статус кампании.',
    },
  },
  kk: {
    title: 'Кандидаттарды тестілеу',
    description: 'Жұмысқа қабылдауға дейін жеке сілтеме және PIN арқылы тест өткізіңіз. Кандидат штатқа және оқушылар тізіміне қосылмайды.',
    newCampaign: 'Жаңа кампания',
    campaignTitle: 'Кампания атауы',
    campaignTitlePlaceholder: 'Атауы',
    publishedCourse: 'Жарияланған курс',
    chooseCourse: 'Жарияланған курсты таңдаңыз',
    create: 'Құру',
    inviteCandidate: 'Кандидатты шақыру',
    candidateName: 'Кандидаттың аты',
    candidateNamePlaceholder: 'Аты Тегі',
    candidateEmail: 'Кандидаттың emailі (міндетті емес)',
    candidateEmailPlaceholder: 'Email (міндетті емес)',
    inviteHint: 'Белсенді кампанияда «Шақыру» түймесін басыңыз. Қорғалған сілтеме мен PIN бір рет көрсетіледі.',
    nameRequired: 'Шақыруды белсендіру үшін кандидаттың атын енгізіңіз.',
    candidateAccess: 'Кандидатқа қолжетімділік',
    pin: 'PIN',
    campaigns: 'Кампаниялар',
    loading: 'Кампаниялар жүктелуде…',
    empty: 'Кампаниялар әзірге жоқ. Бірінші кампанияны құрыңыз.',
    loadFailed: 'Кандидаттарды бағалауды жүктеу мүмкін болмады.',
    coursesLoadFailed: 'Жарияланған курстар тізімін жүктеу мүмкін болмады.',
    noCourses: 'Дайын нұсқасы бар жарияланған курстар жоқ.',
    courseLimit: 'Алғашқы 100 жарияланған курс жүктелді. Қалғандары бұл тізімде қолжетімсіз.',
    retry: 'Қайталау',
    statusDraft: 'Жоба',
    statusActive: 'Белсенді',
    statusClosed: 'Жабық',
    statusUnknown: 'Белгісіз мәртебе',
    until: 'дейін',
    csv: 'CSV',
    start: 'Бастау',
    close: 'Жабу',
    invite: 'Шақыру',
    instructions: 'Бағалауды көрсетілген мерзімге дейін өз бетінше орындаңыз.',
    feedbackCreated: 'Кампания құрылды. Кандидатты шақыру алдында оны іске қосыңыз.',
    feedbackCopied: 'Қорғалған сілтеме мен PIN көшірілді. Оларды кандидатқа бөлек жіберіңіз.',
    errors: {
      load: 'Кандидаттарды бағалауды жүктеу мүмкін болмады.',
      createNoQuestions: 'Курстың жарияланған нұсқасында мақұлданған сұрақтар жоқ. Тесттерді тексеріп, курстың жаңа нұсқасын жариялаңыз.',
      createReleaseMissing: 'Курстың жарияланған нұсқасы табылмады. Бетті жаңартып, курсты қайта таңдаңыз.',
      createGeneric: 'Таңдалған курс үшін кампания құру мүмкін болмады.',
      invite: 'Кандидатты шақыруды құру мүмкін болмады.',
      clipboard: 'Автоматты көшіру мүмкін болмады. Төмендегі блоктан сілтеме мен PINді көшіріңіз.',
      csv: 'CSV жүктеу мүмкін болмады.',
      status: 'Кампания мәртебесін өзгерту мүмкін болмады.',
    },
  },
  en: {
    title: 'Candidate assessment',
    description: 'Run a pre-hire assessment through a personal link and PIN. The candidate is not added to staff or learners.',
    newCampaign: 'New campaign',
    campaignTitle: 'Campaign title',
    campaignTitlePlaceholder: 'Title',
    publishedCourse: 'Published course',
    chooseCourse: 'Select a published course',
    create: 'Create',
    inviteCandidate: 'Invite candidate',
    candidateName: 'Candidate name',
    candidateNamePlaceholder: 'First Last',
    candidateEmail: 'Candidate email (optional)',
    candidateEmailPlaceholder: 'Email (optional)',
    inviteHint: 'Select Invite in an active campaign. The secure link and PIN are shown once.',
    nameRequired: 'Enter the candidate name to enable the invitation.',
    candidateAccess: 'Candidate access',
    pin: 'PIN',
    campaigns: 'Campaigns',
    loading: 'Loading campaigns…',
    empty: 'No campaigns yet. Create the first campaign.',
    loadFailed: 'Could not load candidate assessments.',
    coursesLoadFailed: 'Could not load the published course list.',
    noCourses: 'No published courses with a ready version.',
    courseLimit: 'The first 100 published courses are loaded. Other courses are not available in this list.',
    retry: 'Retry',
    statusDraft: 'Draft',
    statusActive: 'Active',
    statusClosed: 'Closed',
    statusUnknown: 'Unknown status',
    until: 'until',
    csv: 'CSV',
    start: 'Start',
    close: 'Close',
    invite: 'Invite',
    instructions: 'Complete the assessment independently before the deadline.',
    feedbackCreated: 'Campaign created. Start it before inviting a candidate.',
    feedbackCopied: 'The secure link and PIN were copied. Share them with the candidate separately.',
    errors: {
      load: 'Could not load candidate assessments.',
      createNoQuestions: 'The published course version has no approved questions. Check the quizzes and publish a new course version.',
      createReleaseMissing: 'The published course version was not found. Refresh the page and select the course again.',
      createGeneric: 'Could not create a campaign for the selected course.',
      invite: 'Could not create the candidate invitation.',
      clipboard: 'Could not copy automatically. Copy the link and PIN from the block below.',
      csv: 'Could not export CSV.',
      status: 'Could not change the campaign status.',
    },
  },
} as const;

function campaignCreationError(error: unknown): ErrorCode {
  const message = (error as { response?: { data?: { message?: string } } })?.response?.data?.message;
  if (message === 'Release has no approved assessment questions') return 'createNoQuestions';
  if (message === 'Content release not found') return 'createReleaseMissing';
  return 'createGeneric';
}

export default function CandidateAssessmentsPage() {
  const lang = useLanguageStore((state) => state.lang);
  const m = copy[lang as keyof typeof copy] ?? copy.ru;
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [releaseId, setReleaseId] = useState('');
  const [title, setTitle] = useState('');
  const [candidateName, setCandidateName] = useState('');
  const [candidateEmail, setCandidateEmail] = useState('');
  const [issued, setIssued] = useState<IssuedAccess | null>(null);
  const [feedback, setFeedback] = useState<FeedbackCode>('');
  const [error, setError] = useState<ErrorCode>('');
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [courseLoadFailed, setCourseLoadFailed] = useState(false);
  const [courseListLimited, setCourseListLimited] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    setCourseLoadFailed(false);
    setCourseListLimited(false);
    const [campaignResult, courseResult] = await Promise.allSettled([
      api.get('/v1/candidate-assessments'),
      api.get('/v1/courses?status=published&per_page=100'),
    ]);
    if (campaignResult.status === 'fulfilled') {
      setCampaigns(Array.isArray(campaignResult.value.data) ? campaignResult.value.data : []);
    } else {
      setLoadFailed(true);
    }
    if (courseResult.status === 'fulfilled') {
      setCourseListLimited(Array.isArray(courseResult.value.data) && courseResult.value.data.length >= 100);
      setCourses((courseResult.value.data as Course[]).filter((course) => course.current_release_id));
    } else {
      setCourseLoadFailed(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const statusLabel = (status: string) => {
    const labels: Record<string, string> = {
      draft: m.statusDraft,
      active: m.statusActive,
      closed: m.statusClosed,
    };
    return labels[status] ?? m.statusUnknown;
  };

  const formatDate = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const numeric = new Intl.DateTimeFormat('en-GB', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }).format(date);
    // Chromium's kk short-date pattern is ISO-like; keep the numeric
    // Kazakhstan day.month.year order aligned with the Russian UI.
    return lang === 'en' ? numeric : numeric.replace(/\//g, '.');
  };

  async function create(event: FormEvent) {
    event.preventDefault();
    setError('');
    setFeedback('');
    try {
      await api.post('/v1/candidate-assessments', {
        content_release_id: releaseId,
        title,
        instructions: m.instructions,
        expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
        attempt_limit: 1,
        retention_days: 180,
      });
      setReleaseId('');
      setTitle('');
      setFeedback('created');
      await load();
    } catch (requestError) {
      setError(campaignCreationError(requestError));
    }
  }

  async function invite(campaignId: string) {
    setError('');
    setFeedback('');
    setIssued(null);
    const [firstName, ...lastParts] = candidateName.trim().split(/\s+/);
    try {
      const response = await api.post(`/v1/candidate-assessments/${campaignId}/candidates`, {
        first_name: firstName,
        last_name: lastParts.join(' '),
        email: candidateEmail || null,
        phone: null,
      });
      const access = response.data as IssuedAccess;
      setIssued(access);
      try {
        await navigator.clipboard.writeText(`${access.access_url}\nPIN: ${access.temporary_pin}`);
        setFeedback('copied');
      } catch {
        setError('clipboard');
      }
      setCandidateName('');
      setCandidateEmail('');
    } catch {
      setError('invite');
    }
  }

  async function exportCsv(campaign: Campaign) {
    setError('');
    try {
      const response = await api.get(`/v1/candidate-assessments/${campaign.id}/results.csv`, { responseType: 'blob' });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${campaign.title}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('csv');
    }
  }

  async function changeStatus(campaign: Campaign, status: 'active' | 'closed') {
    setError('');
    try {
      await api.patch(`/v1/candidate-assessments/${campaign.id}`, { status });
      await load();
    } catch {
      setError('status');
    }
  }

  return (
    <WorkspacePage
      id="candidate-assessments"
      title={m.title}
      description={m.description}
      icon={<ClipboardCheck />}
      className="mx-auto max-w-7xl px-4 py-6 sm:px-6"
    >
      {feedback === 'created' && <p role="status" className="rounded-xl border border-border bg-card p-4 text-sm text-foreground">{m.feedbackCreated}</p>}
      {feedback === 'copied' && <p role="status" className="rounded-xl border border-border bg-card p-4 text-sm text-foreground">{m.feedbackCopied}</p>}
      {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{m.errors[error]}</p>}
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="min-w-0 space-y-5">
          <WorkspacePanel title={m.newCampaign}>
            <form className="space-y-4" onSubmit={create}>
              <label className="block space-y-2 text-sm font-medium">
                <span>{m.campaignTitle}</span>
                <Input aria-label={m.campaignTitle} placeholder={m.campaignTitlePlaceholder} value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                <span>{m.publishedCourse}</span>
                <select aria-label={m.publishedCourse} className="min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={releaseId} onChange={(e) => setReleaseId(e.target.value)}>
                  <option value="">{m.chooseCourse}</option>
                  {courses.map((course) => <option key={course.id} value={course.current_release_id || ''}>{course.title}</option>)}
                </select>
              </label>
              {courseLoadFailed && <div className="flex flex-wrap items-center gap-2" role="alert">
                <p className="text-sm text-destructive">{m.coursesLoadFailed}</p>
                <Button type="button" variant="outline" size="sm" onClick={() => void load()}>{m.retry}</Button>
              </div>}
              {!courseLoadFailed && !loading && courses.length === 0 && <p className="text-sm text-muted-foreground">{m.noCourses}</p>}
              {!courseLoadFailed && !loading && courseListLimited && <p role="status" className="text-sm text-foreground">{m.courseLimit}</p>}
              <div className="flex justify-end border-t border-border pt-4"><Button disabled={!title || !releaseId}>{m.create}</Button></div>
            </form>
          </WorkspacePanel>
          <WorkspacePanel title={m.inviteCandidate} bodyClassName="space-y-4">
            <label className="block space-y-2 text-sm font-medium">
              <span>{m.candidateName}</span>
              <Input aria-label={m.candidateName} value={candidateName} onChange={(e) => setCandidateName(e.target.value)} placeholder={m.candidateNamePlaceholder} />
            </label>
            <label className="block space-y-2 text-sm font-medium">
              <span>{m.candidateEmail}</span>
              <Input aria-label={m.candidateEmail} value={candidateEmail} onChange={(e) => setCandidateEmail(e.target.value)} placeholder={m.candidateEmailPlaceholder} />
            </label>
            <p className="text-xs leading-5 text-muted-foreground">{m.inviteHint}</p>
            {!candidateName.trim() && <p className="text-xs leading-5 text-muted-foreground">{m.nameRequired}</p>}
          </WorkspacePanel>
          {issued && <WorkspacePanel title={m.candidateAccess} className="border-primary/30" bodyClassName="space-y-3"><p className="break-all rounded-lg bg-muted/40 p-3 text-sm">{issued.access_url}</p><p className="font-mono text-lg">{m.pin}: {issued.temporary_pin}</p></WorkspacePanel>}
        </div>
        <section aria-label={m.campaigns} className="min-w-0 space-y-4">
          {loading ? (
            <p role="status" className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">{m.loading}</p>
          ) : loadFailed ? (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" role="alert">
              <span>{m.loadFailed}</span>
              <Button type="button" variant="outline" onClick={() => void load()}>{m.retry}</Button>
            </div>
          ) : campaigns.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border bg-card p-4 text-sm text-muted-foreground">{m.empty}</p>
          ) : campaigns.map((campaign) => (
            <WorkspacePanel
              key={campaign.id}
              title={campaign.title}
              description={<>{statusLabel(campaign.status)} · {m.until} {formatDate(campaign.expires_at)}</>}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Button variant="outline" onClick={() => void exportCsv(campaign)}>{m.csv}</Button>
                <div className="flex flex-wrap gap-2">
                  {campaign.status === 'draft' && <Button variant="outline" onClick={() => void changeStatus(campaign, 'active')}>{m.start}</Button>}
                  {campaign.status === 'active' && <Button variant="outline" onClick={() => void changeStatus(campaign, 'closed')}>{m.close}</Button>}
                  <Button disabled={campaign.status !== 'active' || !candidateName.trim()} onClick={() => void invite(campaign.id)}>{m.invite}</Button>
                </div>
              </div>
            </WorkspacePanel>
          ))}
        </section>
      </div>
    </WorkspacePage>
  );
}
