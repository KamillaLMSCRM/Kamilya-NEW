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
    openActions: 'Действий открыто',
    overdueActions: 'Из них просрочено',
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
    noJobs: 'Активных или проблемных генераций нет.',
    running: 'В работе',
    jobAttention: 'Требует внимания',
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
    openActions: 'Open actions',
    overdueActions: 'Overdue actions',
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
    noJobs: 'There are no active or problematic generations.',
    running: 'In progress',
    jobAttention: 'Needs attention',
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
    openActions: 'Ашық әрекет',
    overdueActions: 'Мерзімі өткен әрекет',
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
    noJobs: 'Белсенді немесе мәселелі генерация жоқ.',
    running: 'Орындалуда',
    jobAttention: 'Назар аудару қажет',
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
  const lang = useLanguageStore((state) => state.lang);
  const m = copy[lang as keyof typeof copy] ?? copy.ru;
  const [model, setModel] = useState<MethodologistDashboardModel | null>(null);
  const allowed = Boolean(user?.tenant_id && user.role === 'methodologist');

  useEffect(() => {
    if (!allowed) return;
    const controller = new AbortController();
    setModel(null);
    void loadMethodologistDashboard(controller.signal)
      .then((next) => { if (!controller.signal.aborted) setModel(next); })
      .catch(() => {
        if (!controller.signal.aborted) setModel({
          learningAvailable: false,
          training: null,
          attention: null,
          content: {
            coursesAvailable: false,
            totalCourses: null,
            publishedCourses: null,
            draftCourses: null,
            jobsAvailable: false,
            activeJobs: null,
            attentionJobs: null,
            jobs: [],
          },
        });
      });
    return () => controller.abort();
  }, [allowed, user?.tenant_id, user?.user_id]);

  if (!allowed) return null;

  const issueLabel = (issue: string) => ({
    overdue: m.overdueIssue,
    failed_required_quiz: m.failedIssue,
    stalled: m.stalledIssue,
    not_started: m.notStartedIssue,
  }[issue] ?? issue);

  return (
    <div className="space-y-6" data-testid="methodologist-dashboard">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div><h1 className="text-2xl font-bold text-foreground font-display">{m.title}</h1><p className="mt-1 text-sm text-muted-foreground">{m.subtitle}</p></div>
        <Link href="/ai/generate" className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"><FilePlus2 className="h-4 w-4" />{m.newCourse}</Link>
      </header>

      {!model && <div className="flex items-center gap-3 rounded-2xl border border-border bg-card p-6 text-sm text-muted-foreground"><LoaderCircle className="h-5 w-5 animate-spin" />{m.loading}</div>}
      {model && !model.learningAvailable && <div role="status" className="flex items-start gap-3 rounded-2xl border border-amber-300/70 bg-amber-50 p-5 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100"><CircleAlert className="mt-0.5 h-5 w-5 shrink-0" />{m.unavailable}</div>}

      {model?.training && model.attention && <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.75fr)]">
        <section className="rounded-2xl border border-border bg-card p-5 shadow-card sm:p-6" aria-labelledby="attention-title">
          <SectionHeading id="attention-title" title={m.attention} hint={m.attentionHint} icon={<AlertTriangle className="h-5 w-5" />} tone="amber" />
          <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label={m.trainingIssues} value={model.attention.trainingIssues} testId="training-issues" />
            <Metric label={m.weakQuestions} value={model.attention.weakQuestions} />
            <Metric label={m.openActions} value={model.attention.openActions} testId="open-actions" />
            <Metric label={m.overdueActions} value={model.attention.overdueActions} tone={model.attention.overdueActions > 0 ? 'danger' : 'default'} />
          </dl>
          <div className="mt-6 border-t border-border pt-5">
            <div className="flex items-center justify-between gap-3"><h3 className="font-semibold text-foreground">{m.priorityPeople}</h3><Link href="/training-log" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">{m.allActions}<ArrowRight className="h-4 w-4" /></Link></div>
            {model.attention.items.length === 0 ? <p className="mt-3 text-sm text-muted-foreground">{m.noIssues}</p> : <ul className="mt-3 divide-y divide-border">
              {model.attention.items.map((item) => <li key={item.enrollment_id} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><p className="truncate text-sm font-semibold text-foreground">{item.full_name}</p><p className="truncate text-sm text-muted-foreground">{item.course_title}</p></div><div className="flex shrink-0 items-center gap-2 text-xs"><span className="rounded-full bg-amber-100 px-2.5 py-1 font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-200">{issueLabel(item.issue_type)}</span><span className="text-muted-foreground">{m.progress.replace('{value}', String(item.progress_percent))}</span></div></li>)}
            </ul>}
            {model.attention.truncated && <p className="mt-2 text-xs text-muted-foreground">{m.moreItems}</p>}
          </div>
        </section>

        <section className="rounded-2xl border border-border bg-card p-5 shadow-card sm:p-6" aria-labelledby="health-title">
          <SectionHeading id="health-title" title={m.health} hint={m.healthHint} icon={<ListChecks className="h-5 w-5" />} tone="primary" />
          <div className="mt-6 flex items-end justify-between"><div><div className="text-4xl font-bold tracking-tight text-foreground">{model.training.completionPercent}%</div><div className="mt-1 text-sm text-muted-foreground">{m.completion}: {model.training.completed} / {model.training.total}</div></div><CheckCircle2 className="h-9 w-9 text-emerald-500" /></div>
          <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${model.training.completionPercent}%` }} /></div>
          <dl className="mt-6 grid grid-cols-2 gap-x-5 gap-y-4"><MetricCompact label={m.notStarted} value={model.training.notStarted} /><MetricCompact label={m.inProgress} value={model.training.inProgress} /><MetricCompact label={m.overdue} value={model.training.overdue} testId="training-overdue" danger={model.training.overdue > 0} /><MetricCompact label={m.failed} value={model.training.failed} danger={model.training.failed > 0} /><MetricCompact label={m.exhausted} value={model.training.exhausted} danger={model.training.exhausted > 0} /></dl>
        </section>
      </div>}

      {model && <section className="rounded-2xl border border-border bg-card p-5 shadow-card sm:p-6" aria-labelledby="content-title">
        <SectionHeading id="content-title" title={m.content} hint={m.contentHint} icon={<BookOpen className="h-5 w-5" />} tone="blue" />
        {(!model.content.coursesAvailable || !model.content.jobsAvailable) && <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">{m.contentUnavailable}</p>}
        <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5"><Metric label={m.allCourses} value={displayValue(model.content.totalCourses)} /><Metric label={m.published} value={displayValue(model.content.publishedCourses)} /><Metric label={m.drafts} value={displayValue(model.content.draftCourses)} /><Metric label={m.activeGeneration} value={displayValue(model.content.activeJobs)} /><Metric label={m.generationAttention} value={displayValue(model.content.attentionJobs)} tone={(model.content.attentionJobs ?? 0) > 0 ? 'danger' : 'default'} /></dl>
        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.45fr)]">
          <div className="rounded-xl border border-border">{model.content.jobs.length === 0 ? <p className="p-4 text-sm text-muted-foreground">{m.noJobs}</p> : <ul className="divide-y divide-border">{model.content.jobs.map((job) => { const active = job.status === 'pending' || job.status === 'running'; return <li key={job.id} className="flex items-center justify-between gap-3 p-4"><div className="min-w-0"><p className="truncate text-sm font-medium text-foreground">{job.course_title || job.id.slice(0, 8)}</p><p className="mt-0.5 text-xs text-muted-foreground">{job.stage || job.status}</p></div><span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${active ? 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200' : 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200'}`}>{active ? m.running : m.jobAttention}</span></li>; })}</ul>}</div>
          <nav aria-label={m.quickActions} className="space-y-2"><h3 className="mb-3 font-semibold text-foreground">{m.quickActions}</h3><QuickLink href="/ai/generate" label={m.createFromMaterials} icon={<FilePlus2 className="h-4 w-4" />} /><QuickLink href="/courses" label={m.reviewCourses} icon={<BookOpen className="h-4 w-4" />} /><QuickLink href="/training-log" label={m.trainingLog} icon={<Clock3 className="h-4 w-4" />} /></nav>
        </div>
      </section>}
    </div>
  );
}

function SectionHeading({ id, title, hint, icon, tone }: { id: string; title: string; hint: string; icon: ReactNode; tone: 'amber' | 'primary' | 'blue' }) {
  const colors = tone === 'amber' ? 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300' : tone === 'blue' ? 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300' : 'bg-primary/10 text-primary';
  return <div className="flex items-start gap-3"><div className={`rounded-xl p-2.5 ${colors}`}>{icon}</div><div><h2 id={id} className="text-lg font-bold text-foreground">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{hint}</p></div></div>;
}

function Metric({ label, value, tone = 'default', testId }: { label: string; value: number | string; tone?: 'default' | 'danger'; testId?: string }) {
  return <div data-testid={testId} className={`flex flex-col rounded-xl border p-3 ${tone === 'danger' ? 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30' : 'border-border bg-muted/30'}`}><dt className="order-2 mt-1 text-xs leading-4 text-muted-foreground">{label}</dt><dd className={`order-1 text-2xl font-bold ${tone === 'danger' ? 'text-red-700 dark:text-red-300' : 'text-foreground'}`}>{value}</dd></div>;
}

function MetricCompact({ label, value, danger = false, testId }: { label: string; value: number; danger?: boolean; testId?: string }) {
  return <div data-testid={testId}><dt className="text-xs text-muted-foreground">{label}</dt><dd className={`mt-1 text-xl font-bold ${danger ? 'text-red-600 dark:text-red-300' : 'text-foreground'}`}>{value}</dd></div>;
}

function QuickLink({ href, label, icon }: { href: string; label: string; icon: ReactNode }) {
  return <Link href={href} className="flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-3 text-sm font-medium text-foreground transition hover:border-primary/50 hover:bg-primary/5"><span className="flex items-center gap-2">{icon}{label}</span><ArrowRight className="h-4 w-4 text-muted-foreground" /></Link>;
}
