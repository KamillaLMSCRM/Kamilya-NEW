'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, ClipboardList, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import { closeLearningAction, createLearningAction, getLearningActionCenter } from './api';
import type {
  CreateLearningAction,
  LearningActionCenterPayload,
  LearningActionResolution,
  LearningActionType,
  TrainingAttentionItem,
  WeakQuestionItem,
} from './types';

const messages = {
  ru: {
    title: 'Центр действий методиста',
    subtitle: 'Проблема → действие → проверяемый результат. История обучения не изменяется.',
    loading: 'Загружаем ситуации, требующие внимания…',
    error: 'Не удалось загрузить центр действий.',
    retry: 'Повторить',
    empty: 'Сейчас нет ситуаций, требующих внимания.',
    training: 'Сотрудники, которым требуется внимание',
    questions: 'Слабые вопросы',
    actions: 'Действия в работе',
    open: 'Открыто',
    overdueCount: 'Просрочено действий',
    partial: 'Показана только часть результатов. Выберите курс или уточните фильтры.',
    create: 'Создать действие',
    save: 'Сохранить действие',
    cancel: 'Отмена',
    close: 'Зафиксировать результат',
    actionType: 'Тип действия',
    dueAt: 'Срок',
    comment: 'Комментарий',
    commentPlaceholder: 'Что именно нужно сделать и почему',
    ownerSelf: 'Ответственный: вы',
    mutationError: 'Не удалось сохранить изменение. Проверьте данные и повторите попытку.',
    resolution: 'Как завершено',
    resolutionNote: 'Пояснение результата',
    resolutionNotePlaceholder: 'Что произошло и почему действие можно закрыть',
    observed: 'Результат подтверждён данными системы',
    manual: 'Результат подтверждён вручную',
    cancelledResolution: 'Действие отменено',
    noteRequired: 'Для ручного результата или отмены укажите пояснение.',
    confirmClose: 'Закрыть действие',
    reminder: 'Напомнить',
    reassignment: 'Повторно назначить',
    supplemental_material: 'Добавить материал',
    manual_review: 'Разобрать вручную',
    not_started: 'Не начато',
    stalled: 'Остановилось',
    overdue: 'Просрочено',
    failed_required_quiz: 'Обязательный тест не пройден',
    weak_question: 'Слабый вопрос',
    progress: 'Прогресс: {value}%',
    attempts: 'Попыток теста: {value}',
    incorrect: 'Ошибок: {percent}% из {count} ответов',
  },
  kk: {
    title: 'Әдіскердің әрекет орталығы',
    subtitle: 'Мәселе → әрекет → тексерілетін нәтиже. Оқу тарихы өзгермейді.',
    loading: 'Назар аударуды қажет ететін жағдайлар жүктелуде…',
    error: 'Әрекет орталығын жүктеу мүмкін болмады.',
    retry: 'Қайталау',
    empty: 'Қазір назар аударуды қажет ететін жағдай жоқ.',
    training: 'Назар аударуды қажет ететін қызметкерлер',
    questions: 'Әлсіз сұрақтар',
    actions: 'Орындалып жатқан әрекеттер',
    open: 'Ашық',
    overdueCount: 'Мерзімі өткен әрекеттер',
    partial: 'Нәтижелердің бір бөлігі ғана көрсетілді. Курсты таңдаңыз немесе сүзгілерді нақтылаңыз.',
    create: 'Әрекет құру',
    save: 'Әрекетті сақтау',
    cancel: 'Бас тарту',
    close: 'Нәтижені тіркеу',
    actionType: 'Әрекет түрі',
    dueAt: 'Мерзімі',
    comment: 'Түсініктеме',
    commentPlaceholder: 'Нені және не үшін жасау керек',
    ownerSelf: 'Жауапты: сіз',
    mutationError: 'Өзгерісті сақтау мүмкін болмады. Деректерді тексеріп, қайталап көріңіз.',
    resolution: 'Қалай аяқталды',
    resolutionNote: 'Нәтиже түсіндірмесі',
    resolutionNotePlaceholder: 'Не болды және әрекетті неге жабуға болады',
    observed: 'Нәтиже жүйе деректерімен расталды',
    manual: 'Нәтиже қолмен расталды',
    cancelledResolution: 'Әрекет тоқтатылды',
    noteRequired: 'Қолмен расталған нәтиже немесе тоқтату үшін түсіндірме жазыңыз.',
    confirmClose: 'Әрекетті жабу',
    reminder: 'Еске салу',
    reassignment: 'Қайта тағайындау',
    supplemental_material: 'Материал қосу',
    manual_review: 'Қолмен талдау',
    not_started: 'Басталмаған',
    stalled: 'Тоқтап қалды',
    overdue: 'Мерзімі өтті',
    failed_required_quiz: 'Міндетті тест өтпеді',
    weak_question: 'Әлсіз сұрақ',
    progress: 'Прогресс: {value}%',
    attempts: 'Тест талпыныстары: {value}',
    incorrect: 'Қате: {percent}% / {count} жауап',
  },
  en: {
    title: 'Methodologist action center',
    subtitle: 'Issue → action → verifiable outcome. Training history stays unchanged.',
    loading: 'Loading situations that need attention…',
    error: 'Could not load the action center.',
    retry: 'Retry',
    empty: 'There are no situations requiring attention right now.',
    training: 'Learners who need attention',
    questions: 'Weak questions',
    actions: 'Actions in progress',
    open: 'Open',
    overdueCount: 'Overdue actions',
    partial: 'Only part of the results is shown. Select a course or narrow the filters.',
    create: 'Create action',
    save: 'Save action',
    cancel: 'Cancel',
    close: 'Record outcome',
    actionType: 'Action type',
    dueAt: 'Due date',
    comment: 'Comment',
    commentPlaceholder: 'What must be done and why',
    ownerSelf: 'Owner: you',
    mutationError: 'Could not save the change. Check the data and try again.',
    resolution: 'How it ended',
    resolutionNote: 'Outcome explanation',
    resolutionNotePlaceholder: 'What happened and why this action can be closed',
    observed: 'Outcome confirmed by system data',
    manual: 'Outcome confirmed manually',
    cancelledResolution: 'Action cancelled',
    noteRequired: 'A manual outcome or cancellation requires an explanation.',
    confirmClose: 'Close action',
    reminder: 'Send reminder',
    reassignment: 'Reassign training',
    supplemental_material: 'Add material',
    manual_review: 'Review manually',
    not_started: 'Not started',
    stalled: 'Stalled',
    overdue: 'Overdue',
    failed_required_quiz: 'Required quiz not passed',
    weak_question: 'Weak question',
    progress: 'Progress: {value}%',
    attempts: 'Quiz attempts: {value}',
    incorrect: 'Incorrect: {percent}% of {count} responses',
  },
} as const;

type Target =
  | { kind: 'enrollment'; item: TrainingAttentionItem }
  | { kind: 'question'; item: WeakQuestionItem };

export function LearningActionCenter({ courseId }: { courseId?: string }) {
  const user = useAuthStore((state) => state.user);
  const lang = useLanguageStore((state) => state.lang);
  const m = messages[lang as keyof typeof messages] ?? messages.ru;
  const [data, setData] = useState<LearningActionCenterPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [target, setTarget] = useState<Target | null>(null);
  const [actionType, setActionType] = useState<LearningActionType>('manual_review');
  const [dueAt, setDueAt] = useState('');
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [mutationError, setMutationError] = useState(false);
  const [closingActionId, setClosingActionId] = useState<string | null>(null);
  const [resolution, setResolution] = useState<LearningActionResolution>('observed');
  const [resolutionNote, setResolutionNote] = useState('');
  const generation = useRef(0);
  const allowed = Boolean(user?.tenant_id && user.role === 'methodologist');
  const format = (text: string, values: Record<string, string | number>) => (
    text.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? `{${key}}`))
  );

  const load = useCallback(async () => {
    if (!allowed) return;
    const request = ++generation.current;
    setLoading(true);
    setError(false);
    try {
      const result = await getLearningActionCenter(courseId);
      if (request === generation.current) setData(result);
    } catch {
      if (request === generation.current) setError(true);
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [allowed, courseId]);

  useEffect(() => {
    setData(null);
    setTarget(null);
    void load();
    return () => { generation.current += 1; };
  }, [load, user?.tenant_id, user?.user_id]);

  if (!allowed) return null;
  if (loading && !data) return <Card><CardContent className="p-5 text-sm text-muted-foreground">{m.loading}</CardContent></Card>;
  if (error) return (
    <Card><CardContent className="flex items-center gap-3 p-5 text-sm text-destructive">
      <span>{m.error}</span><Button size="sm" variant="outline" onClick={() => void load()}><RotateCcw className="mr-2 h-4 w-4" />{m.retry}</Button>
    </CardContent></Card>
  );
  if (!data) return null;

  const startAction = (next: Target) => {
    const available = (['reminder', 'reassignment', 'supplemental_material', 'manual_review'] as const)
      .filter((value) => !next.item.active_action_types.includes(value));
    if (available.length === 0) return;
    setTarget(next);
    setActionType(available[0]);
    setDueAt('');
    setComment('');
    setMutationError(false);
  };
  const save = async () => {
    if (!target) return;
    if (target.kind === 'question' && !courseId) return;
    const payload: CreateLearningAction = target.kind === 'enrollment'
      ? {
        target_type: 'enrollment',
        enrollment_id: target.item.enrollment_id,
        issue_type: target.item.issue_type,
        action_type: actionType,
        due_at: dueAt ? new Date(`${dueAt}T23:59:59`).toISOString() : null,
        comment: comment.trim() || null,
      }
      : {
        target_type: 'question',
        course_id: courseId,
        quiz_id: target.item.quiz_id,
        content_release_id: target.item.content_release_id,
        question_id: target.item.question_id,
        question_key: target.item.question_key,
        issue_type: 'weak_question',
        action_type: actionType,
        due_at: dueAt ? new Date(`${dueAt}T23:59:59`).toISOString() : null,
        comment: comment.trim() || null,
      };
    setSaving(true);
    setMutationError(false);
    try {
      await createLearningAction(payload);
      setTarget(null);
      await load();
    } catch {
      setMutationError(true);
    } finally {
      setSaving(false);
    }
  };
  const startClosing = (id: string) => {
    setClosingActionId(id);
    setResolution('observed');
    setResolutionNote('');
    setMutationError(false);
  };
  const close = async () => {
    if (!closingActionId) return;
    const note = resolutionNote.trim();
    if (resolution !== 'observed' && !note) return;
    setSaving(true);
    setMutationError(false);
    try {
      await closeLearningAction(closingActionId, resolution, note || null);
      setClosingActionId(null);
      await load();
    } catch {
      setMutationError(true);
    } finally {
      setSaving(false);
    }
  };
  const noSignals = data.training_items.length === 0 && data.weak_questions.length === 0 && data.actions.length === 0;
  const truncated = data.summary.training_items_truncated || data.summary.actions_truncated;

  return (
    <Card data-testid="learning-action-center">
      <CardHeader className="space-y-2">
        <CardTitle className="flex items-center gap-2"><ClipboardList className="h-5 w-5" />{m.title}</CardTitle>
        <p className="text-sm text-muted-foreground">{m.subtitle}</p>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded bg-muted px-2 py-1">{m.open}: {data.summary.open_action_count}</span>
          <span className="rounded bg-muted px-2 py-1">{m.overdueCount}: {data.summary.overdue_action_count}</span>
        </div>
        {truncated && <p role="status" className="text-sm text-amber-700 dark:text-amber-300">{m.partial}</p>}
      </CardHeader>
      <CardContent className="space-y-6">
        {noSignals && <p className="text-sm text-muted-foreground">{m.empty}</p>}
        {data.training_items.length > 0 && <section className="space-y-2">
          <h3 className="font-medium">{m.training}</h3>
          {data.training_items.map((item) => <article key={item.enrollment_id} className="rounded-lg border p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><p className="font-medium">{item.full_name}</p><p className="text-sm text-muted-foreground">{item.course_title} · {m[item.issue_type]}</p>
                <p className="text-xs text-muted-foreground">{format(m.progress, { value: item.progress_percent })} · {format(m.attempts, { value: item.quiz_attempts_count })}</p>
              </div>
              {item.active_action_types.length < 4 && <Button size="sm" variant="outline" onClick={() => startAction({ kind: 'enrollment', item })}>{m.create}</Button>}
            </div>
          </article>)}
        </section>}
        {data.weak_questions.length > 0 && <section className="space-y-2">
          <h3 className="font-medium">{m.questions}</h3>
          {data.weak_questions.map((item) => <article key={item.question_key} className="rounded-lg border p-3">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-medium">{item.text}</p><p className="text-xs text-muted-foreground">{item.quiz_title} · {format(m.incorrect, { percent: item.incorrect_percent, count: item.respondents })}</p></div>
              {item.active_action_types.length < 4 && <Button size="sm" variant="outline" onClick={() => startAction({ kind: 'question', item })}>{m.create}</Button>}
            </div>
          </article>)}
        </section>}
        {data.actions.length > 0 && <section className="space-y-2">
          <h3 className="font-medium">{m.actions}</h3>
          {data.actions.map((action) => <article key={action.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
            <div><p className="font-medium">{m[action.action_type]}</p><p className="text-sm text-muted-foreground">{m[action.issue_type]}</p>{action.comment && <p className="text-sm">{action.comment}</p>}</div>
            {action.status === 'open' && <Button size="sm" onClick={() => startClosing(action.id)}><CheckCircle2 className="mr-2 h-4 w-4" />{m.close}</Button>}
          </article>)}
        </section>}
        {closingActionId && <section className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4">
          <div className="flex items-center gap-2 font-medium"><CheckCircle2 className="h-4 w-4" />{m.close}</div>
          <label className="grid gap-1 text-sm"><span>{m.resolution}</span><select aria-label={m.resolution} className="h-10 rounded-md border bg-background px-3" value={resolution} onChange={(event) => setResolution(event.target.value as LearningActionResolution)}>
            <option value="observed">{m.observed}</option>
            <option value="manual">{m.manual}</option>
            <option value="cancelled">{m.cancelledResolution}</option>
          </select></label>
          <label className="grid gap-1 text-sm"><span>{m.resolutionNote}</span><textarea aria-label={m.resolutionNote} className="min-h-20 rounded-md border bg-background p-3" placeholder={m.resolutionNotePlaceholder} value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} /></label>
          {resolution !== 'observed' && !resolutionNote.trim() && <p className="text-sm text-muted-foreground">{m.noteRequired}</p>}
          {mutationError && <p role="alert" className="text-sm text-destructive">{m.mutationError}</p>}
          <div className="flex gap-2"><Button disabled={saving || (resolution !== 'observed' && !resolutionNote.trim())} onClick={() => void close()}>{m.confirmClose}</Button><Button variant="outline" disabled={saving} onClick={() => setClosingActionId(null)}>{m.cancel}</Button></div>
        </section>}
        {target && <section className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4">
          <div className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" />{m.create}</div>
          <p className="text-sm text-muted-foreground">{m.ownerSelf}</p>
          <label className="grid gap-1 text-sm"><span>{m.actionType}</span><select aria-label={m.actionType} className="h-10 rounded-md border bg-background px-3" value={actionType} onChange={(event) => setActionType(event.target.value as LearningActionType)}>
            {(['reminder', 'reassignment', 'supplemental_material', 'manual_review'] as const).map((value) => <option key={value} value={value} disabled={target.item.active_action_types.includes(value)}>{m[value]}</option>)}
          </select></label>
          <label className="grid gap-1 text-sm"><span>{m.dueAt}</span><input type="date" className="h-10 rounded-md border bg-background px-3" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label>
          <label className="grid gap-1 text-sm"><span>{m.comment}</span><textarea aria-label={m.comment} className="min-h-20 rounded-md border bg-background p-3" placeholder={m.commentPlaceholder} value={comment} onChange={(event) => setComment(event.target.value)} /></label>
          {mutationError && <p role="alert" className="text-sm text-destructive">{m.mutationError}</p>}
          <div className="flex gap-2"><Button disabled={saving} onClick={() => void save()}>{m.save}</Button><Button variant="outline" disabled={saving} onClick={() => setTarget(null)}>{m.cancel}</Button></div>
        </section>}
      </CardContent>
    </Card>
  );
}
