'use client';

import { useEffect, useState } from 'react';
import { Badge, Button } from '@/components/ui';
import { useLearningInsightsT } from '@/features/learning-insights/i18n';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

interface Attempt {
  id: string;
  number: number;
  completed_at: string | null;
  score_percent: number | null;
  passed: boolean | null;
}

interface CheckAssignment {
  id: string;
  title: string;
  revision: number;
  status: 'assigned' | 'in_progress' | 'passed' | 'failed';
  due_at: string | null;
  attempt_limit: number;
  attempts_count: number;
  attempts: Attempt[];
}

interface AttemptDetail {
  assignment_id: string;
  answers: Array<{ question_id: string; selected_choice_ids: string[] }>;
  snapshot: { questions: Array<{
    id: string; text: string; type: string; explanation?: string | null;
    choices: Array<{ id: string; text: string; is_correct: boolean }>;
  }> };
}

const PAGE_SIZE = 12;
const labels = {
  ru: { title: 'Самостоятельные проверки знаний', empty: 'Самостоятельных проверок пока нет.', revision: 'Редакция', attempts: 'Попытки', notAnswered: 'Нет ответа', inProgress: 'Попытка выполняется' },
  kk: { title: 'Дербес білім тексерулері', empty: 'Дербес білім тексерулері әлі жоқ.', revision: 'Нұсқа', attempts: 'Әрекеттер', notAnswered: 'Жауап жоқ', inProgress: 'Әрекет орындалуда' },
  en: { title: 'Standalone knowledge checks', empty: 'No standalone knowledge checks yet.', revision: 'Revision', attempts: 'Attempts', notAnswered: 'No answer', inProgress: 'Attempt in progress' },
} as const;

export function useEmployeeKnowledgeCopy() {
  return labels[useT().lang];
}

export function EmployeeKnowledgeChecks({ employeeId }: { employeeId: string }) {
  const { t, lang } = useT();
  const copy = useEmployeeKnowledgeCopy();
  const { text } = useLearningInsightsT();
  const token = useAuthStore((state) => state.accessToken);
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<{ key: string; result: { items: CheckAssignment[]; has_more: boolean } | null }>();
  const [activeAttempt, setActiveAttempt] = useState<string | null>(null);
  const key = JSON.stringify([employeeId, token, offset, retry]);
  const path = '/v1/knowledge-checks/employees/' + encodeURIComponent(employeeId);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    void api.get<{ items: CheckAssignment[]; has_more: boolean }>(path + '/assignments', {
      params: { limit: PAGE_SIZE, offset }, signal: controller.signal,
    }).then(({ data: result }) => {
      if (!controller.signal.aborted) setData({ key, result });
    }).catch(() => {
      if (!controller.signal.aborted) setData({ key, result: null });
    });
    return () => controller.abort();
  }, [key, offset, path, token]);

  const result = data?.key === key ? data.result : undefined;
  if (result === undefined) return <p role="status">{t('common.loading')}</p>;
  if (result === null) return <div role="status" className="space-y-2 text-sm">
    <p>{t('common.loadFailed')}</p>
    <Button type="button" variant="outline" onClick={() => setRetry((value) => value + 1)}>{t('common.retry')}</Button>
  </div>;

  const statusText = { assigned: t('trainingLog.badge.assigned'), in_progress: copy.inProgress,
    passed: text('passed'), failed: text('notPassed') };
  return <section className="space-y-3">
    <h4 className="font-semibold">{copy.title}</h4>
    {!result.items.length && <p className="text-sm text-muted-foreground">{copy.empty}</p>}
    {result.items.map((assignment) => (
      <article key={assignment.id} className="space-y-2 rounded-xl border border-border p-3">
        <h5 className="font-semibold [overflow-wrap:anywhere]">{assignment.title}</h5>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge variant="outline">{statusText[assignment.status]}</Badge>
          <span>{copy.revision} {assignment.revision}</span>
          <span>{copy.attempts}: {assignment.attempts_count} / {assignment.attempt_limit}</span>
          {assignment.due_at && <span>{t('trainingLog.table.deadline')}: {new Date(assignment.due_at).toLocaleDateString(lang)}</span>}
        </div>
        {assignment.attempts.map((attempt) => (
          <div key={attempt.id} className="space-y-2 border-t border-border pt-2 text-sm">
            <p>{text('attempt', { count: attempt.number })}
              {attempt.score_percent !== null && ' · ' + text('score', { count: attempt.score_percent })}
              {' · '}{attempt.passed === null ? copy.inProgress : text(attempt.passed ? 'passed' : 'notPassed')}
            </p>
            {attempt.completed_at && <Button type="button" variant="outline" aria-expanded={activeAttempt === attempt.id}
              onClick={() => setActiveAttempt((id) => id === attempt.id ? null : attempt.id)}>{text('answers')}</Button>}
            {activeAttempt === attempt.id && <SavedAttempt key={attempt.id} path={path} assignmentId={assignment.id} attemptId={attempt.id} />}
          </div>
        ))}
      </article>
    ))}
    {(offset > 0 || result.has_more) && <div className="flex flex-wrap gap-2">
      <Button type="button" variant="outline" disabled={!offset} onClick={() => setOffset(offset - PAGE_SIZE)}>{t('common.back')}</Button>
      <Button type="button" variant="outline" disabled={!result.has_more} onClick={() => setOffset(offset + PAGE_SIZE)}>{t('common.next')}</Button>
    </div>}
  </section>;
}

function SavedAttempt({ path, assignmentId, attemptId }: { path: string; assignmentId: string; attemptId: string }) {
  const { t } = useT();
  const copy = useEmployeeKnowledgeCopy();
  const { text } = useLearningInsightsT();
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<AttemptDetail | null>();

  useEffect(() => {
    const controller = new AbortController();
    void api.get<AttemptDetail>(path + '/attempts/' + encodeURIComponent(attemptId), { signal: controller.signal })
      .then(({ data: result }) => {
        if (!controller.signal.aborted) setData(result.assignment_id === assignmentId ? result : null);
      }).catch(() => {
        if (!controller.signal.aborted) setData(null);
      });
    return () => controller.abort();
  }, [assignmentId, attemptId, path, retry]);

  if (data === undefined) return <p role="status">{t('common.loading')}</p>;
  if (data === null) return <div role="status" className="space-y-2">
    <p>{text('unavailable')}</p>
    <Button type="button" variant="outline" onClick={() => { setData(undefined); setRetry((value) => value + 1); }}>{t('common.retry')}</Button>
  </div>;

  const answers = new Map(data.answers.map((answer) => [answer.question_id, answer.selected_choice_ids]));
  return <ol className="space-y-3">
    {data.snapshot.questions.map((question) => {
      const choices = new Map(question.choices.map((choice) => [choice.id, choice.text]));
      const ordered = question.type === 'ordering';
      const paired = question.type === 'matching_pairs';
      const correct = question.choices.filter((choice) => ordered || paired || choice.is_correct).map((choice) => choice.id);
      const format = (ids: string[]) => {
        const values = ids.map((id) => choices.get(id)).filter((value): value is string => Boolean(value));
        if (paired) return values.filter((_, index) => index % 2 === 0)
          .map((label, index) => label + ' — ' + (values[index * 2 + 1] ?? '…')).join('; ');
        return values.join(ordered ? ' → ' : ', ');
      };
      return <li key={question.id} className="space-y-1 rounded-md bg-muted/40 p-3 [overflow-wrap:anywhere]">
        <p className="font-medium">{question.text}</p>
        <p>{text('selected')}: {format(answers.get(question.id) ?? []) || copy.notAnswered}</p>
        <p>{text('correct')}: {format(correct)}</p>
        {question.explanation && <p className="text-muted-foreground">{question.explanation}</p>}
      </li>;
    })}
  </ol>;
}
