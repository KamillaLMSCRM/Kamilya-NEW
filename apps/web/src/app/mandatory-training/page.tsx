'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'next/navigation';
import { AlertTriangle, BookOpenCheck, RefreshCw, Search } from 'lucide-react';

import { Badge, Button, Card, CardContent, Input, Table } from '@/components/ui';
import {
  loadMandatoryTraining,
  type MandatoryTrainingFilters,
} from '@/features/mandatory-training/api';
import type {
  MandatoryTrainingPage as MandatoryTrainingPageModel,
  MandatoryTrainingRow,
  MandatoryTrainingSummary,
  RequirementAction,
  RequirementState,
} from '@/features/mandatory-training/types';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

const copy = {
  ru: {
    title: 'Обязательное обучение',
    subtitle: 'Кому и какой курс требуется пройти, почему он назначен и где правило ещё не материализовалось.',
    searchPlaceholder: 'Сотрудник, email или табельный номер',
    apply: 'Применить', retry: 'Повторить', allStates: 'Все состояния',
    loading: 'Собираем матрицу обязательного обучения…',
    loadError: 'Не удалось загрузить матрицу. Данные не заменены нулями — повторите попытку.',
    empty: 'По выбранным условиям строк нет.', total: 'Всего требований',
    materialized: 'Назначение создано', missing: 'Без назначения', protected: 'Защищено', stale: 'Требует сверки',
    employee: 'Сотрудник', structure: 'Структура', course: 'Курс', state: 'Состояние', reason: 'Почему назначено', action: 'Что делать',
    inactive: 'Неактивен', noPosition: 'Без должности', noUnit: 'Без подразделения',
    source: 'Источник правила', path: 'Путь действия правила', noSource: 'Точный объект источника не сохранён',
    progress: 'Прогресс', due: 'Срок',
    deadlineLabels: { none: 'Без срока', upcoming: 'Срок приближается', overdue: 'Просрочено', completed_on_time: 'Завершено в срок', completed_late: 'Завершено с опозданием' },
    evidenceLabels: { awaiting_return: 'Ожидается подписанный экземпляр', uploaded_pending_review: 'Скан ожидает проверки', accepted: 'Подписанный экземпляр принят', replacement_requested: 'Запрошена замена скана' },
    restrictedScope: 'Показаны только сотрудники из подразделений и групп, за которые вы отвечаете.',
    previousPage: 'Предыдущая страница', nextPage: 'Следующая страница', range: (from: number, to: number, total: number) => `${from}–${to} из ${total}`,
    stateLabels: {
      materialized: 'Назначение создано', missing_enrollment: 'Назначение ещё не создано',
      protected_assignment: 'Ручное или программное назначение защищено', stale_managed_enrollment: 'Назначение требует сверки',
    },
    reasonLabels: {
      position: 'По должности', department: 'По подразделению', organization: 'Для всей организации',
      manual: 'Вручную', cohort: 'По группе', learning_path: 'По программе', recurring: 'По циклу обучения',
      auto: 'Автоматически', unknown: 'Источник не определён',
    },
    actionLabels: { none: 'Действие не требуется', materialize: 'Нужно создать назначение', review_stale: 'Нужно проверить назначение' },
  },
  en: {
    title: 'Mandatory training', subtitle: 'Who must complete which course, why it is assigned, and where a rule has not materialized yet.',
    searchPlaceholder: 'Employee, email, or personnel number', apply: 'Apply', retry: 'Retry', allStates: 'All states',
    loading: 'Building the mandatory-training matrix…', loadError: 'Could not load the matrix. Missing data is not shown as zero.',
    empty: 'No rows match the selected filters.', total: 'Total requirements', materialized: 'Assigned', missing: 'Missing assignment', protected: 'Protected', stale: 'Needs review',
    employee: 'Employee', structure: 'Structure', course: 'Course', state: 'State', reason: 'Why assigned', action: 'Next action',
    inactive: 'Inactive', noPosition: 'No position', noUnit: 'No organization unit', source: 'Rule source', path: 'Rule scope', noSource: 'The exact source object was not retained',
    progress: 'Progress', due: 'Due',
    deadlineLabels: { none: 'No deadline', upcoming: 'Due soon', overdue: 'Overdue', completed_on_time: 'Completed on time', completed_late: 'Completed late' },
    evidenceLabels: { awaiting_return: 'Signed copy expected', uploaded_pending_review: 'Scan awaiting review', accepted: 'Signed copy accepted', replacement_requested: 'Replacement scan requested' },
    restrictedScope: 'Only employees in the organization units and groups assigned to you are shown.',
    previousPage: 'Previous page', nextPage: 'Next page', range: (from: number, to: number, total: number) => `${from}–${to} of ${total}`,
    stateLabels: { materialized: 'Assignment created', missing_enrollment: 'Assignment has not been created', protected_assignment: 'Manual or program assignment is protected', stale_managed_enrollment: 'Assignment needs review' },
    reasonLabels: { position: 'By position', department: 'By organization unit', organization: 'Organization-wide', manual: 'Manual', cohort: 'By cohort', learning_path: 'By program', recurring: 'By learning cycle', auto: 'Automatic', unknown: 'Unknown source' },
    actionLabels: { none: 'No action required', materialize: 'Create the assignment', review_stale: 'Review the assignment' },
  },
  kk: {
    title: 'Міндетті оқу', subtitle: 'Кім қандай курстан өтуі тиіс, неге тағайындалған және қай ереже әлі тағайындауға айналмаған.',
    searchPlaceholder: 'Қызметкер, email немесе табельдік нөмір', apply: 'Қолдану', retry: 'Қайталау', allStates: 'Барлық күйлер',
    loading: 'Міндетті оқу матрицасы жиналуда…', loadError: 'Матрицаны жүктеу мүмкін болмады. Жоқ дерек нөлмен ауыстырылмайды.',
    empty: 'Таңдалған шарттар бойынша жол жоқ.', total: 'Барлық талап', materialized: 'Тағайындалды', missing: 'Тағайындау жоқ', protected: 'Қорғалған', stale: 'Тексеру қажет',
    employee: 'Қызметкер', structure: 'Құрылым', course: 'Курс', state: 'Күйі', reason: 'Неге тағайындалды', action: 'Не істеу керек',
    inactive: 'Белсенді емес', noPosition: 'Лауазымсыз', noUnit: 'Бөлімшесіз', source: 'Ереже көзі', path: 'Ереже аумағы', noSource: 'Нақты дереккөз нысаны сақталмаған',
    progress: 'Прогресс', due: 'Мерзімі',
    deadlineLabels: { none: 'Мерзімсіз', upcoming: 'Мерзімі жақындады', overdue: 'Мерзімі өтті', completed_on_time: 'Уақытында аяқталды', completed_late: 'Кеш аяқталды' },
    evidenceLabels: { awaiting_return: 'Қол қойылған дана күтілуде', uploaded_pending_review: 'Скан тексеруді күтуде', accepted: 'Қол қойылған дана қабылданды', replacement_requested: 'Сканды ауыстыру сұралды' },
    restrictedScope: 'Сізге бекітілген бөлімшелер мен топтардағы қызметкерлер ғана көрсетілген.',
    previousPage: 'Алдыңғы бет', nextPage: 'Келесі бет', range: (from: number, to: number, total: number) => `${from}–${to} / ${total}`,
    stateLabels: { materialized: 'Тағайындау жасалды', missing_enrollment: 'Тағайындау әлі жасалмаған', protected_assignment: 'Қолмен немесе бағдарлама арқылы тағайындау қорғалған', stale_managed_enrollment: 'Тағайындауды тексеру қажет' },
    reasonLabels: { position: 'Лауазым бойынша', department: 'Бөлімше бойынша', organization: 'Бүкіл ұйым үшін', manual: 'Қолмен', cohort: 'Топ бойынша', learning_path: 'Бағдарлама бойынша', recurring: 'Оқу циклі бойынша', auto: 'Автоматты түрде', unknown: 'Дереккөз анықталмаған' },
    actionLabels: { none: 'Әрекет қажет емес', materialize: 'Тағайындау жасау керек', review_stale: 'Тағайындауды тексеру керек' },
  },
} as const;

export default function MandatoryTrainingPage() {
  const user = useAuthStore((state) => state.user);
  const lang = useLanguageStore((state) => state.lang);
  const searchParams = useSearchParams();
  const m = copy[lang as keyof typeof copy] ?? copy.ru;
  const allowed = Boolean(user?.tenant_id && (user.role === 'methodologist' || user.role === 'admin'));
  const initialAction = normalizeAction(searchParams.get('action_required'));
  const [filters, setFilters] = useState<MandatoryTrainingFilters>({ action_required: initialAction, limit: 100, offset: 0 });
  const [search, setSearch] = useState('');
  const [state, setState] = useState<RequirementState | ''>('');
  const [page, setPage] = useState<MandatoryTrainingPageModel | null>(null);
  const [summary, setSummary] = useState<MandatoryTrainingSummary | null>(null);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!allowed) return;
    const controller = new AbortController();
    setError(false);
    setPage(null);
    setSummary(null);
    void loadMandatoryTraining(filters, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setPage(result.page);
          setSummary(result.summary);
        }
      })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [allowed, filters, reload, user?.tenant_id]);

  if (!allowed) return null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFilters({
      action_required: initialAction,
      search: search.trim() || undefined,
      requirement_state: state || undefined,
      limit: 100,
      offset: 0,
    });
  };

  return <div className="space-y-6" data-testid="mandatory-training-page">
    <header className="flex items-start gap-3">
      <div className="rounded-xl bg-primary/10 p-3 text-primary"><BookOpenCheck className="h-6 w-6" /></div>
      <div><h1 className="text-2xl font-bold text-foreground font-display">{m.title}</h1><p className="mt-1 max-w-4xl text-sm text-muted-foreground">{m.subtitle}</p></div>
    </header>

    {error && <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-950"><span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4" />{m.loadError}</span><Button variant="outline" size="sm" onClick={() => setReload((value) => value + 1)}><RefreshCw className="mr-2 h-4 w-4" />{m.retry}</Button></div>}
    {!error && (!page || !summary) && <div className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">{m.loading}</div>}

    {page && summary && <>
      {page.reporting_scope === 'restricted' && <div role="status" className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm text-foreground">{m.restrictedScope}</div>}
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label={m.total}>
        <Summary label={m.total} value={summary.total} />
        <Summary label={m.materialized} value={summary.materialized} />
        <Summary label={m.missing} value={summary.missing_enrollment} testId="missing-enrollment-count" tone="danger" />
        <Summary label={m.protected} value={summary.protected_assignment} />
        <Summary label={m.stale} value={summary.stale_managed_enrollment} tone="warning" />
      </section>

      <Card><CardContent className="p-4 sm:p-5">
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-[minmax(0,1fr)_240px_auto]">
          <label className="relative"><span className="sr-only">{m.searchPlaceholder}</span><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" /><Input className="pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={m.searchPlaceholder} /></label>
          <select value={state} onChange={(event) => setState(event.target.value as RequirementState | '')} aria-label={m.state} className="h-10 rounded-md border border-input bg-background px-3 text-sm">
            <option value="">{m.allStates}</option>
            {(Object.keys(m.stateLabels) as RequirementState[]).map((value) => <option key={value} value={value}>{m.stateLabels[value]}</option>)}
          </select>
          <Button type="submit">{m.apply}</Button>
        </form>
      </CardContent></Card>

      {page.items.length === 0 ? <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">{m.empty}</div> : <>
        <div className="grid gap-3 lg:hidden">{page.items.map((row) => <MobileRow key={`${row.user_id}-${row.course_id}`} row={row} m={m} />)}</div>
        <Table className="hidden overflow-x-auto lg:block" tableClassName="min-w-[1180px]">
          <thead><tr className="text-left text-xs text-muted-foreground"><th className="px-4 py-3">{m.employee}</th><th className="px-4 py-3">{m.structure}</th><th className="px-4 py-3">{m.course}</th><th className="px-4 py-3">{m.state}</th><th className="px-4 py-3">{m.reason}</th><th className="px-4 py-3">{m.action}</th></tr></thead>
          <tbody>{page.items.map((row) => <DesktopRow key={`${row.user_id}-${row.course_id}`} row={row} m={m} />)}</tbody>
        </Table>
      </>}
      {page.total > 0 && <nav className="flex items-center justify-end gap-3" aria-label={m.total}>
        <span className="text-sm tabular-nums text-muted-foreground">{m.range(page.offset + 1, Math.min(page.offset + page.items.length, page.total), page.total)}</span>
        <Button type="button" variant="outline" disabled={page.offset === 0} onClick={() => setFilters((current) => ({ ...current, offset: Math.max(0, page.offset - page.limit) }))}>{m.previousPage}</Button>
        <Button type="button" variant="outline" disabled={page.offset + page.limit >= page.total} onClick={() => setFilters((current) => ({ ...current, offset: page.offset + page.limit }))}>{m.nextPage}</Button>
      </nav>}
    </>}
  </div>;
}

type Copy = typeof copy[keyof typeof copy];

function Summary({ label, value, testId, tone }: { label: string; value: number; testId?: string; tone?: 'danger' | 'warning' }) {
  return <div className={`rounded-xl border p-4 ${tone === 'danger' ? 'border-red-200 bg-red-50/70' : tone === 'warning' ? 'border-amber-200 bg-amber-50/70' : 'border-border bg-card'}`}><div className="text-xs text-muted-foreground">{label}</div><div data-testid={testId} className="mt-1 text-2xl font-bold tabular-nums text-foreground">{value}</div></div>;
}

function Reason({ row, m }: { row: MandatoryTrainingRow; m: Copy }) {
  const reason = row.assignment_reason;
  return <details><summary className="cursor-pointer font-medium text-primary">{m.reasonLabels[reason.kind]}</summary><div className="mt-2 space-y-1 text-xs text-muted-foreground"><p><span className="font-medium text-foreground">{m.source}:</span> {reason.source_name || m.noSource}</p>{reason.scope_path_names.length > 0 && <p><span className="font-medium text-foreground">{m.path}:</span> {reason.scope_path_names.join(' → ')}</p>}</div></details>;
}

function DesktopRow({ row, m }: { row: MandatoryTrainingRow; m: Copy }) {
  return <tr className="border-t border-border align-top"><td className="px-4 py-4"><div className="font-medium">{row.full_name}</div><div className="text-xs text-muted-foreground">{row.personnel_number || '—'}{!row.is_active && ` · ${m.inactive}`}</div></td><td className="px-4 py-4 text-sm"><div>{row.position_name || m.noPosition}</div><div className="mt-1 text-xs text-muted-foreground">{row.organization_unit_path.join(' → ') || m.noUnit}</div></td><td className="px-4 py-4"><div className="font-medium">{row.course_title}</div><div className="text-xs uppercase text-muted-foreground">{row.delivery_type}</div></td><td className="space-y-2 px-4 py-4"><Badge variant={row.requirement_state === 'missing_enrollment' ? 'destructive' : 'secondary'}>{m.stateLabels[row.requirement_state]}</Badge><OperationalState row={row} m={m} /></td><td className="px-4 py-4"><Reason row={row} m={m} /></td><td className="px-4 py-4 text-sm">{m.actionLabels[row.action_required]}</td></tr>;
}

function MobileRow({ row, m }: { row: MandatoryTrainingRow; m: Copy }) {
  return <article className="space-y-3 rounded-xl border border-border bg-card p-4"><div className="flex items-start justify-between gap-3"><div><h2 className="font-semibold">{row.full_name}</h2><p className="text-sm text-muted-foreground">{row.course_title}</p></div><Badge variant={row.requirement_state === 'missing_enrollment' ? 'destructive' : 'secondary'}>{m.stateLabels[row.requirement_state]}</Badge></div><p className="text-sm">{row.position_name || m.noPosition} · {row.organization_unit_path.join(' → ') || m.noUnit}</p><OperationalState row={row} m={m} /><Reason row={row} m={m} /><p className="text-sm font-medium">{m.actionLabels[row.action_required]}</p></article>;
}

function OperationalState({ row, m }: { row: MandatoryTrainingRow; m: Copy }) {
  if (!row.enrollment_id) return null;
  return <div className="space-y-1 text-xs text-muted-foreground">
    {row.progress_percent != null && <div className="flex gap-1"><span>{m.progress}:</span><strong className="font-semibold text-foreground">{row.progress_percent}%</strong></div>}
    {row.deadline_state && <div className="flex flex-wrap items-center gap-1"><span>{m.due}:</span><Badge variant={row.deadline_state === 'overdue' ? 'destructive' : 'outline'}>{m.deadlineLabels[row.deadline_state]}</Badge></div>}
    {row.latest_evidence_event_id && row.evidence_signed_copy_status && <Badge variant={row.evidence_signed_copy_status === 'replacement_requested' ? 'destructive' : 'outline'}>{m.evidenceLabels[row.evidence_signed_copy_status]}</Badge>}
  </div>;
}

function normalizeAction(value: string | null): RequirementAction | undefined {
  return value === 'materialize' || value === 'review_stale' || value === 'none' ? value : undefined;
}
