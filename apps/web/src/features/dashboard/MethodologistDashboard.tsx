'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FilePlus2,
  ListChecks,
  LoaderCircle,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import { loadMethodologistDashboard } from './api';
import type { MethodologistDashboardModel } from './model';
import { DashboardTaskQueue, type DashboardTask } from './DashboardTaskQueue';
import { workspaceCopy } from '@/features/learning-workspace/copy';
import { WorkspacePage, WorkspaceToolbar } from '@/features/workspace-design';
import { buildTrainingLogBrowserHref, type TrainingLogFilters } from '@/app/admin/training-log/query';

const copy = {
  ru: {
    title: 'Обзор обучения',
    subtitle: 'Приоритеты, ход обучения и контент, который требует действий.',
    newCourse: 'Создать курс',
    loading: 'Собираем актуальную картину обучения…',
    unavailable: 'Сводка обучения временно недоступна. Данные не заменены нулями — повторите позже.',
    attention: 'Требует внимания',
    attentionHint: 'Сначала разберите просрочки, неудачные попытки и остановившееся обучение.',
    trainingIssues: 'Проблемных назначений',
    weakQuestions: 'Слабых вопросов',
    weakQuestionsHint: 'Здесь показаны вопросы, вызывающие трудности у обучающихся. Для разбора откройте центр действий и выберите курс.',
    openActions: 'Действий открыто',
    overdueActions: 'Из них просрочено',
    missingAssignments: 'Без назначения',
    staleAssignments: 'Требует сверки',
    noIssues: 'Сейчас нет выявленных проблем по обучению.',
    priorityPeople: 'Кому уделить внимание',
    allActions: 'Открыть центр действий',
    progress: 'прогресс {value}%',
    moreItems: 'Показаны первые ситуации. Полный список доступен в центре действий.',
    health: 'Состояние обучения',
    healthHint: 'Текущие назначения без отменённой и заменённой истории.',
    completion: 'Завершено',
    notStarted: 'Не начали',
    inProgress: 'В процессе',
    overdue: 'Просрочено',
    failed: 'Тест не пройден',
    exhausted: 'Попытки исчерпаны',
    content: 'Контент в работе',
    contentHint: 'Курсы и незавершённые генерации — вторичный рабочий контур.',
    allCourses: 'Все курсы',
    published: 'Опубликовано',
    drafts: 'Черновики',
    activeGeneration: 'Генераций идёт',
    generationAttention: 'Генераций с проблемой',
    contentUnavailable: 'Часть данных о контенте недоступна.',
    coursesTruncated: 'Загружены первые 100 курсов. Общие итоги по курсам неизвестны и показаны как «—».',
    jobsScope: 'Счётчики генераций относятся к загруженным заданиям. В списке показано не более пяти.',
    noJobs: 'Активных или проблемных генераций нет.',
    jobsUnavailable: 'Данные о генерациях недоступны. Список не заменён нулём.',
    running: 'В работе',
    jobAttention: 'Требует внимания',
    courseGeneration: 'Создание курса',
    failedGeneration: 'Не удалось создать курс',
    jobStage: 'Этап: {stage}',
    jobRequest: 'заявка {id}',
    unknownStage: 'этап неизвестен',
    jobStages: { pending: 'в очереди', queued: 'в очереди', running: 'выполняется', processing: 'обработка материалов', ingestion: 'обработка материалов', architect: 'проектирование структуры', generating: 'генерация содержания', content_generation: 'генерация содержания', review: 'проверка качества', assessment: 'проверка тестов', saving: 'сохранение', completed: 'завершено', failed: 'ошибка', cancelled: 'отменено', interrupted: 'прервано' },
    quickActions: 'Быстрые действия',
    createFromMaterials: 'Создать курс из материалов',
    reviewCourses: 'Проверить курсы',
    trainingLog: 'Открыть журнал обучения',
    overdueIssue: 'Просрочено',
    failedIssue: 'Тест не пройден',
    stalledIssue: 'Обучение остановилось',
    notStartedIssue: 'Не приступил',
  },
  en: {
    title: 'Learning overview',
    subtitle: 'Priorities, training progress, and content that needs action.',
    newCourse: 'Create course',
    loading: 'Building the current learning picture…',
    unavailable: 'The learning summary is temporarily unavailable. Missing data is not shown as zero.',
    attention: 'Needs attention',
    attentionHint: 'Start with overdue, failed, and stalled learning.',
    trainingIssues: 'Problem assignments',
    weakQuestions: 'Weak questions',
    weakQuestionsHint: 'These questions cause difficulties for learners. Open the action center and select a course to investigate.',
    openActions: 'Open actions',
    overdueActions: 'Overdue actions',
    missingAssignments: 'Missing assignments',
    staleAssignments: 'Needs review',
    noIssues: 'No learning issues are currently detected.',
    priorityPeople: 'People to focus on',
    allActions: 'Open action center',
    progress: '{value}% progress',
    moreItems: 'The first situations are shown. The full list is available in the action center.',
    health: 'Training health',
    healthHint: 'Current assignments, excluding cancelled and superseded history.',
    completion: 'Completed',
    notStarted: 'Not started',
    inProgress: 'In progress',
    overdue: 'Overdue',
    failed: 'Quiz failed',
    exhausted: 'Attempts exhausted',
    content: 'Content in progress',
    contentHint: 'Courses and unfinished generations are a secondary workstream.',
    allCourses: 'All courses',
    published: 'Published',
    drafts: 'Drafts',
    activeGeneration: 'Generations running',
    generationAttention: 'Generations with issues',
    contentUnavailable: 'Some content data is unavailable.',
    coursesTruncated: 'The first 100 courses are loaded. Course totals are unknown and shown as “—”.',
    jobsScope: 'Generation counts cover loaded jobs. The list shows at most five.',
    noJobs: 'There are no active or problematic generations.',
    jobsUnavailable: 'Generation data is unavailable. The list is not shown as zero.',
    running: 'In progress',
    jobAttention: 'Needs attention',
    courseGeneration: 'Course generation',
    failedGeneration: 'Course generation failed',
    jobStage: 'Stage: {stage}',
    jobRequest: 'request {id}',
    unknownStage: 'unknown stage',
    jobStages: { pending: 'queued', queued: 'queued', running: 'running', processing: 'processing materials', ingestion: 'processing materials', architect: 'designing structure', generating: 'generating content', content_generation: 'generating content', review: 'quality review', assessment: 'assessment review', saving: 'saving', completed: 'completed', failed: 'failed', cancelled: 'cancelled', interrupted: 'interrupted' },
    quickActions: 'Quick actions',
    createFromMaterials: 'Create from materials',
    reviewCourses: 'Review courses',
    trainingLog: 'Open training log',
    overdueIssue: 'Overdue',
    failedIssue: 'Quiz failed',
    stalledIssue: 'Learning stalled',
    notStartedIssue: 'Not started',
  },
  kk: {
    title: 'Оқу шолуы',
    subtitle: 'Басымдықтар, оқу барысы және әрекетті қажет ететін контент.',
    newCourse: 'Курс жасау',
    loading: 'Оқудың өзекті көрінісін жинап жатырмыз…',
    unavailable: 'Оқу қорытындысы уақытша қолжетімсіз. Жоқ дерек нөлмен ауыстырылмайды.',
    attention: 'Назар аудару қажет',
    attentionHint: 'Алдымен мерзімі өткен, сәтсіз және тоқтап қалған оқуды қараңыз.',
    trainingIssues: 'Мәселелі тағайындау',
    weakQuestions: 'Әлсіз сұрақ',
    weakQuestionsHint: 'Мұнда оқушыларға қиындық туғызатын сұрақтар көрсетіледі. Талдау үшін әрекеттер орталығын ашып, курсты таңдаңыз.',
    openActions: 'Ашық әрекет',
    overdueActions: 'Мерзімі өткен әрекет',
    missingAssignments: 'Тағайындау жоқ',
    staleAssignments: 'Тексеру қажет',
    noIssues: 'Қазір оқу бойынша анықталған мәселе жоқ.',
    priorityPeople: 'Кімге назар аудару керек',
    allActions: 'Әрекет орталығын ашу',
    progress: 'прогресс {value}%',
    moreItems: 'Алғашқы жағдайлар көрсетілді. Толық тізім әрекет орталығында.',
    health: 'Оқу жағдайы',
    healthHint: 'Жойылған және ауыстырылған тарихсыз ағымдағы тағайындаулар.',
    completion: 'Аяқталды',
    notStarted: 'Бастамады',
    inProgress: 'Орындалуда',
    overdue: 'Мерзімі өтті',
    failed: 'Тест өтпеді',
    exhausted: 'Талпыныс таусылды',
    content: 'Жұмыстағы контент',
    contentHint: 'Курстар мен аяқталмаған генерациялар — екінші жұмыс контуры.',
    allCourses: 'Барлық курс',
    published: 'Жарияланды',
    drafts: 'Жобалар',
    activeGeneration: 'Генерация орындалуда',
    generationAttention: 'Мәселелі генерация',
    contentUnavailable: 'Контент деректерінің бір бөлігі қолжетімсіз.',
    coursesTruncated: 'Алғашқы 100 курс жүктелді. Курстардың жалпы саны белгісіз және «—» түрінде көрсетілген.',
    jobsScope: 'Генерация сандары жүктелген тапсырмаларға қатысты. Тізімде ең көбі бес тапсырма көрсетіледі.',
    noJobs: 'Белсенді немесе мәселелі генерация жоқ.',
    jobsUnavailable: 'Генерация деректері қолжетімсіз. Тізім нөлмен ауыстырылмаған.',
    running: 'Орындалуда',
    jobAttention: 'Назар аудару қажет',
    courseGeneration: 'Курс жасау',
    failedGeneration: 'Курсты жасау мүмкін болмады',
    jobStage: 'Кезең: {stage}',
    jobRequest: 'өтінім {id}',
    unknownStage: 'кезең белгісіз',
    jobStages: { pending: 'кезекте', queued: 'кезекте', running: 'орындалуда', processing: 'материалдарды өңдеу', ingestion: 'материалдарды өңдеу', architect: 'құрылымды жобалау', generating: 'мазмұнды жасау', content_generation: 'мазмұнды жасау', review: 'сапаны тексеру', assessment: 'тесттерді тексеру', saving: 'сақтау', completed: 'аяқталды', failed: 'қате', cancelled: 'тоқтатылды', interrupted: 'үзілді' },
    quickActions: 'Жылдам әрекеттер',
    createFromMaterials: 'Материалдардан курс жасау',
    reviewCourses: 'Курстарды тексеру',
    trainingLog: 'Оқу журналын ашу',
    overdueIssue: 'Мерзімі өтті',
    failedIssue: 'Тест өтпеді',
    stalledIssue: 'Оқу тоқтады',
    notStartedIssue: 'Бастамады',
  },
} as const;

function displayValue(value: number | null) {
  return value === null ? '—' : String(value);
}

export function MethodologistDashboard() {
  const user = useAuthStore((state) => state.user);
  const sessionEpoch = useAuthStore((state) => state.sessionEpoch);
  if (!user?.tenant_id || user.role !== 'methodologist') return null;
  // Remount both the data and the task selection when the active session changes.
  return <DashboardContent key={JSON.stringify([user.tenant_id, user.user_id, sessionEpoch])} />;
}

function DashboardContent() {
  const lang = useLanguageStore((state) => state.lang);
  const m = copy[lang as keyof typeof copy] ?? copy.ru;
  const w = workspaceCopy(lang);
  const [model, setModel] = useState<MethodologistDashboardModel | null>(null);
  const [workView, setWorkView] = useState<'all' | 'training' | 'content'>('all');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setModel(null);
    void loadMethodologistDashboard(controller.signal)
      .then((next) => { if (!controller.signal.aborted) setModel(next); })
      .catch(() => {
        if (!controller.signal.aborted) setModel({
          learningAvailable: false,
          training: null,
          attention: null,
          mandatory: null,
          content: {
            coursesAvailable: false,
            totalCourses: null,
            publishedCourses: null,
            draftCourses: null,
            coursesTruncated: false,
            jobsAvailable: false,
            activeJobs: null,
            attentionJobs: null,
            jobs: [],
          },
        });
      });
    return () => controller.abort();
  }, [refresh]);

  const issueLabel = (issue: string) => ({
    overdue: m.overdueIssue,
    failed_required_quiz: m.failedIssue,
    stalled: m.stalledIssue,
    not_started: m.notStartedIssue,
  }[issue] ?? issue);
  const jobStageLabel = (stage?: string) => (
    stage && stage in m.jobStages
      ? m.jobStages[stage as keyof typeof m.jobStages]
      : m.unknownStage
  );
  const trainingLogHref = (filters: TrainingLogFilters = {}) => buildTrainingLogBrowserHref({
    filters,
    search: '',
    returnTo: '/dashboard',
  });
  const actionCenterHref = `${trainingLogHref()}#learning-action-center`;
  const taskCopy = lang === 'kk'
    ? { status: 'Күйі', due: 'Оқу мерзімі', progress: 'Оқу барысы', stage: 'Кезең', request: 'Тапсырма', journal: 'Журналдағы жазбаны ашу', job: 'Генерацияны ашу', jobs: 'Генерация тапсырмалары', reconcile: 'Сақтау немесе нәтижені тексеру қажет' }
    : lang === 'en'
      ? { status: 'Status', due: 'Training deadline', progress: 'Learning progress', stage: 'Stage', request: 'Job', journal: 'Open journal record', job: 'Open generation job', jobs: 'Generation jobs', reconcile: 'Saving or result verification required' }
      : { status: 'Статус', due: 'Срок обучения', progress: 'Прогресс обучения', stage: 'Этап', request: 'Задание', journal: 'Открыть запись в журнале', job: 'Открыть задание генерации', jobs: 'Задания генерации', reconcile: 'Сохранение или проверка результата' };
  const trainingTasks: DashboardTask[] = (model?.attention?.items ?? []).map((item) => {
    const status = issueLabel(item.issue_type);
    const due = item.assignment_due_at ? new Date(item.assignment_due_at) : null;
    return {
      id: `training:${item.enrollment_id}`, title: item.full_name, subtitle: item.course_title, status,
      details: [
        { label: taskCopy.status, value: status },
        { label: taskCopy.progress, value: `${item.progress_percent}%` },
        ...(due && !Number.isNaN(due.getTime())
          ? [{ label: taskCopy.due, value: new Intl.DateTimeFormat(lang === 'kk' ? 'kk-KZ' : lang === 'en' ? 'en-GB' : 'ru-RU', { dateStyle: 'medium' }).format(due) }]
          : []),
      ],
      href: trainingLogHref({ enrollment_id: item.enrollment_id, course_id: item.course_id }),
      action: taskCopy.journal,
    };
  });
  const generationTasks: DashboardTask[] = (model?.content.jobs ?? []).map((job) => {
    const active = job.status === 'pending' || job.status === 'running';
    const reconciliation = job.status === 'reconciliation_required';
    const status = reconciliation ? taskCopy.reconcile : active ? m.running : m.jobAttention;
    const stage = jobStageLabel(job.stage);
    const reference = job.id.slice(0, 8);
    return {
      id: `generation:${job.id}`,
      title: job.course_title || (active || reconciliation ? m.courseGeneration : m.failedGeneration),
      subtitle: `${m.jobStage.replace('{stage}', stage)} · ${m.jobRequest.replace('{id}', reference)}`,
      status,
      details: [{ label: taskCopy.status, value: status }, { label: taskCopy.stage, value: stage }, { label: taskCopy.request, value: reference }],
      href: `/ai/generate?job_id=${encodeURIComponent(job.id)}`,
      action: taskCopy.job,
    };
  });
  const actionFocusHref = (focus: 'training' | 'weak_questions' | 'open' | 'overdue', issueType?: string) => {
    return `${buildTrainingLogBrowserHref({ filters: {}, search: '', returnTo: '/dashboard', action_focus: focus, issue_type: issueType as 'not_started' | 'stalled' | 'overdue' | 'failed_required_quiz' | undefined })}#learning-action-center`;
  };

  return (
    <WorkspacePage id="dashboard" data-testid="methodologist-dashboard" title={m.title} description={m.subtitle} icon={<ListChecks />} actions={
      <Link href="/ai/generate" className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"><FilePlus2 className="h-4 w-4" />{m.newCourse}</Link>
    }>

      <WorkspaceToolbar className="items-center justify-between" aria-label={w.queueTitle}>
        <div className="min-w-0 flex-1 basis-72"><h2 className="text-base font-semibold tracking-tight text-foreground">{w.queueTitle}</h2>
        <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">{w.queueHint}</p></div>
        <nav className="flex flex-wrap gap-2" aria-label={w.allWork}>
          {([['all', w.allWork], ['training', w.trainingWork], ['content', w.contentWork]] as const).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={workView === value} onClick={() => setWorkView(value)} className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${workView === value ? 'border-primary/30 bg-card text-primary' : 'border-transparent text-muted-foreground hover:bg-card/70'}`}>{label}</button>
          ))}
        </nav>
      </WorkspaceToolbar>

      {!model && <div className="flex items-center gap-3 rounded-2xl border border-border bg-card p-6 text-sm text-muted-foreground"><LoaderCircle className="h-5 w-5 motion-safe:animate-spin" />{m.loading}</div>}
      {model && !model.learningAvailable && <div role="status" className="flex flex-wrap items-start gap-3 rounded-2xl border border-amber-300/70 bg-amber-50 p-5 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100"><CircleAlert className="mt-0.5 h-5 w-5 shrink-0" /><p className="min-w-0 flex-1 basis-64">{m.unavailable}</p><button type="button" onClick={() => setRefresh((value) => value + 1)} className="min-h-10 rounded-lg border border-current/20 px-3 py-2 text-sm font-medium">{w.retry}</button></div>}

      {model && <DashboardTaskQueue key={workView} lang={lang} groups={[
        ...(workView !== 'content' && model.attention ? [{
          id: 'training', title: m.priorityPeople, tasks: trainingTasks, empty: m.noIssues,
          notice: model.attention.truncated ? m.moreItems : undefined,
          link: { href: actionCenterHref, label: m.allActions },
        }] : []),
        ...(workView !== 'training' ? [{
          id: 'generation', title: taskCopy.jobs, tasks: generationTasks,
          empty: model.content.jobsAvailable ? m.noJobs : m.jobsUnavailable,
          notice: model.content.jobsAvailable ? m.jobsScope : undefined,
        }] : []),
      ]} />}

      {workView !== 'content' && model?.training && model.attention && <div className="flex min-w-0 flex-col gap-6">
        <section className="min-w-0 rounded-2xl border border-border bg-card p-5 shadow-card sm:p-6" aria-labelledby="attention-title">
          <SectionHeading id="attention-title" title={m.attention} hint={m.attentionHint} icon={<AlertTriangle className="h-5 w-5" />} tone="amber" />
          <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <Metric label={m.trainingIssues} value={model.attention.trainingIssues} testId="training-issues" href={actionFocusHref('training')} />
            <Metric label={m.weakQuestions} value={model.attention.weakQuestions} href={actionFocusHref('weak_questions')} />
            <Metric label={m.openActions} value={model.attention.openActions} testId="open-actions" href={actionFocusHref('open')} />
            <Metric label={m.overdueActions} value={model.attention.overdueActions} tone={model.attention.overdueActions > 0 ? 'danger' : 'default'} href={actionFocusHref('overdue')} />
            {model.mandatory ? <>
              <Metric label={m.missingAssignments} value={model.mandatory.missing_enrollment} tone={model.mandatory.missing_enrollment > 0 ? 'danger' : 'default'} href="/mandatory-training?action_required=materialize" />
              <Metric label={m.staleAssignments} value={model.mandatory.stale_managed_enrollment} tone={model.mandatory.stale_managed_enrollment > 0 ? 'danger' : 'default'} href="/mandatory-training?action_required=review_stale" />
            </> : <>
              <Metric label={m.missingAssignments} value="—" testId="mandatory-missing-unavailable" />
              <Metric label={m.staleAssignments} value="—" testId="mandatory-stale-unavailable" />
            </>}
            <p className="text-xs leading-5 text-muted-foreground sm:col-span-2 xl:col-span-3">{m.weakQuestionsHint}</p>
          </div>
        </section>

        <section className="grid min-w-0 gap-4 rounded-2xl border border-border bg-card p-5 sm:p-6 xl:grid-cols-[minmax(220px,1fr)_minmax(200px,0.7fr)_minmax(0,2fr)] xl:items-center" aria-labelledby="health-title">
          <SectionHeading id="health-title" title={m.health} hint={m.healthHint} icon={<ListChecks className="h-5 w-5" />} tone="primary" />
          <div><Link href={trainingLogHref({ status: 'completed' })} className="flex items-end justify-between gap-3 rounded-xl transition hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" aria-label={`${m.completion}: ${model.training.completed}`}><div><div className="text-3xl font-semibold tracking-tight text-foreground">{model.training.completionPercent}%</div><div className="mt-1 text-xs text-muted-foreground">{m.completion}: {model.training.completed} / {model.training.total}</div></div><CheckCircle2 className="h-6 w-6 shrink-0 text-success" /></Link>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={m.completion} aria-valuemin={0} aria-valuemax={100} aria-valuenow={model.training.completionPercent}><div className="h-full rounded-full bg-success" style={{ width: `${model.training.completionPercent}%` }} /></div></div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:border-l xl:border-border xl:pl-4"><MetricCompact label={m.notStarted} value={model.training.notStarted} href={trainingLogHref({ status: 'assigned' })} /><MetricCompact label={m.inProgress} value={model.training.inProgress} href={trainingLogHref({ status: 'in_progress' })} /><MetricCompact label={m.overdue} value={model.training.overdue} testId="training-overdue" danger={model.training.overdue > 0} href={trainingLogHref({ status: 'overdue' })} /><MetricCompact label={m.failed} value={model.training.failed} danger={model.training.failed > 0} href={trainingLogHref({ assessment_status: 'failed' })} /><MetricCompact label={m.exhausted} value={model.training.exhausted} danger={model.training.exhausted > 0} href={trainingLogHref({ assessment_status: 'exhausted' })} /></div>
        </section>
      </div>}

      {workView !== 'training' && model && <section className="min-w-0 rounded-2xl border border-border bg-card p-5 shadow-card sm:p-6" aria-labelledby="content-title">
        <SectionHeading id="content-title" title={m.content} hint={m.contentHint} icon={<BookOpen className="h-5 w-5" />} tone="blue" />
        {(!model.content.coursesAvailable || !model.content.jobsAvailable) && <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">{m.contentUnavailable}</p>}
        {model.content.coursesTruncated && <p className="mt-2 text-xs leading-5 text-muted-foreground">{m.coursesTruncated}</p>}
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5"><Metric label={m.allCourses} value={displayValue(model.content.totalCourses)} href="/courses" /><Metric label={m.published} value={displayValue(model.content.publishedCourses)} href="/courses?status=published" /><Metric label={m.drafts} value={displayValue(model.content.draftCourses)} href="/courses?status=draft" /><Metric label={m.activeGeneration} value={displayValue(model.content.activeJobs)} /><Metric label={m.generationAttention} value={displayValue(model.content.attentionJobs)} tone={(model.content.attentionJobs ?? 0) > 0 ? 'danger' : 'default'} /></div>
        <nav aria-label={m.quickActions} className="mt-5 grid gap-2 sm:grid-cols-3"><QuickLink href="/ai/generate" label={m.createFromMaterials} icon={<FilePlus2 className="h-4 w-4" />} /><QuickLink href="/courses" label={m.reviewCourses} icon={<BookOpen className="h-4 w-4" />} /><QuickLink href="/training-log" label={m.trainingLog} icon={<Clock3 className="h-4 w-4" />} /></nav>
      </section>}
    </WorkspacePage>
  );
}

function SectionHeading({ id, title, hint, icon, tone }: { id: string; title: string; hint: string; icon: ReactNode; tone: 'amber' | 'primary' | 'blue' }) {
  const colors = tone === 'amber' ? 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300' : tone === 'blue' ? 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300' : 'bg-primary/10 text-primary';
  return <div className="flex min-w-0 items-start gap-3"><div className={`shrink-0 rounded-xl p-2.5 ${colors}`}>{icon}</div><div className="min-w-0"><h2 id={id} className="text-lg font-bold text-foreground">{title}</h2><p className="mt-1 break-words text-sm text-muted-foreground">{hint}</p></div></div>;
}

function Metric({ label, value, tone = 'default', testId, href }: { label: string; value: number | string; tone?: 'default' | 'danger'; testId?: string; href?: string }) {
  const className = `flex min-w-0 items-center justify-between gap-3 rounded-xl border px-3 py-2.5 ${tone === 'danger' ? 'border-destructive/20 bg-destructive/5' : 'border-border bg-muted/20'}`;
  const content = <><span className="break-words text-xs leading-5 text-muted-foreground">{label}</span><span className={`shrink-0 text-xl font-semibold tabular-nums ${tone === 'danger' ? 'text-destructive' : 'text-foreground'}`}>{value}</span></>;
  return href
    ? <Link data-testid={testId} href={href} aria-label={`${label}: ${value}`} className={`${className} transition hover:border-primary/50 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary`}>{content}</Link>
    : <div data-testid={testId} className={className}>{content}</div>;
}

function MetricCompact({ label, value, danger = false, testId, href }: { label: string; value: number; danger?: boolean; testId?: string; href?: string }) {
  const content = <><span className="text-xs text-muted-foreground">{label}</span><span className={`mt-1 text-xl font-bold ${danger ? 'text-red-600 dark:text-red-300' : 'text-foreground'}`}>{value}</span></>;
  return href
    ? <Link data-testid={testId} href={href} aria-label={`${label}: ${value}`} className="flex flex-col rounded-lg p-2 transition hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">{content}</Link>
    : <div data-testid={testId} className="flex flex-col p-2">{content}</div>;
}

function QuickLink({ href, label, icon }: { href: string; label: string; icon: ReactNode }) {
  return <Link href={href} className="flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-3 text-sm font-medium text-foreground transition hover:border-primary/50 hover:bg-primary/5"><span className="flex items-center gap-2">{icon}{label}</span><ArrowRight className="h-4 w-4 text-muted-foreground" /></Link>;
}
