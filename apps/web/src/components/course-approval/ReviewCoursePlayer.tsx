'use client';

import { useEffect, useMemo, useState } from 'react';
import { Badge, Button } from '@/components/ui';
import { LessonContent } from '@/features/course-authoring/LessonContent';
import { ReviewSourceImageProvider } from '@/components/AuthenticatedSourceImage';
import { saveReviewProgress, submitReviewTest, type ReviewActivityState, type ReviewDiagnostic, type ReviewSnapshot } from '@/lib/courseApproval';
import { useT } from '@/i18n/useT';
import { WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';

function initialPosition(value: number | null | undefined, lessonCount: number) {
  if (!Number.isSafeInteger(value) || value == null || value < 0 || value >= lessonCount || lessonCount === 0) return 0;
  return value;
}

function initialSequence(value: number | undefined) {
  return Number.isSafeInteger(value) && value !== undefined && value > 0 ? value : 1;
}

function restoreAnswers(key: string, snapshot: ReviewSnapshot): Record<string, string> {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(key) || '{}');
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return {};
    const restored: Record<string, string> = {};
    for (const courseModule of snapshot.modules) for (const lesson of courseModule.lessons) for (const quiz of lesson.quizzes) for (const question of quiz.questions) {
      const choice = (saved as Record<string, unknown>)[question.id];
      if (typeof choice === 'string' && question.choices.some((item) => item.id === choice)) restored[question.id] = choice;
    }
    return restored;
  } catch { return {}; }
}

export function ReviewCoursePlayer({ snapshot, attemptId, token, initialActivityState = 'not_started', initialLessonPosition, initialNextSequence, snapshotIdentity: providedSnapshotIdentity, answerStorageScope = 'isolated-review', onComplete }: { snapshot: ReviewSnapshot; attemptId: string; token?: string; initialActivityState?: ReviewActivityState; initialLessonPosition?: number | null; initialNextSequence?: number; snapshotIdentity?: string; answerStorageScope?: string; onComplete: () => void }) {
  const lessons = useMemo(() => snapshot.modules.flatMap((module) => module.lessons.map((lesson) => ({ ...lesson, moduleTitle: module.title }))), [snapshot.modules]);
  const snapshotIdentity = providedSnapshotIdentity || `${snapshot.course.id}:${snapshot.release_version}`;
  const answerStorageKey = JSON.stringify(['kamilya-review-answers-v1', answerStorageScope, attemptId, snapshotIdentity]);
  const [position, setPosition] = useState(() => initialPosition(initialLessonPosition, lessons.length));
  const [sequence, setSequence] = useState(() => initialSequence(initialNextSequence));
  const [answers, setAnswers] = useState<Record<string, string>>(() => restoreAnswers(answerStorageKey, snapshot));
  const [diagnostics, setDiagnostics] = useState<ReviewDiagnostic | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [reviewComplete, setReviewComplete] = useState(initialActivityState === 'completed' || initialActivityState === 'decision_pending');
  const { t } = useT();
  const lesson = lessons[position];

  useEffect(() => {
    setPosition(initialPosition(initialLessonPosition, lessons.length));
    setSequence(initialSequence(initialNextSequence));
    setAnswers(restoreAnswers(answerStorageKey, snapshot));
    setDiagnostics(null);
    setBusy(false);
    setMessage('');
    setReviewComplete(initialActivityState === 'completed' || initialActivityState === 'decision_pending');
  }, [attemptId, initialActivityState, initialLessonPosition, initialNextSequence, lessons.length, snapshotIdentity, answerStorageKey, snapshot]);

  async function recordActivity(nextPosition: number, payload: Record<string, unknown> = {}) {
    const response = await saveReviewProgress(attemptId, sequence, nextPosition, 'in_progress', payload, token, 'checkpoint');
    setSequence((value) => value + 1);
    return response;
  }

  async function selectLesson(nextPosition: number) {
    if (nextPosition === position || !lessons[nextPosition]) return;
    setBusy(true); setMessage('');
    try { await recordActivity(nextPosition, { lesson_id: lessons[nextPosition].id, activity: 'lesson_opened' }); setPosition(nextPosition); }
    catch { setMessage(t('courseApproval.progressError')); }
    finally { setBusy(false); }
  }

  async function submitQuiz(quizId: string) {
    const quiz = lesson?.quizzes.find((item) => item.id === quizId);
    if (!quiz || quiz.questions.some((question) => !answers[question.id])) return;
    // The server grades the immutable course snapshot, not the visible quiz.
    const submitted = lessons.flatMap((item) => item.quizzes.flatMap((itemQuiz) => itemQuiz.questions))
      .filter((question) => answers[question.id])
      .map((question) => ({ question_id: question.id, selected_choice_ids: [answers[question.id]] }));
    setBusy(true); setMessage('');
    try { const response = await submitReviewTest(attemptId, submitted, token); const result = response.result ?? response.diagnostics; if (result) { setDiagnostics(result); if (result.complete === true) { setReviewComplete(true); onComplete(); } } else setMessage(t('courseApproval.answersAccepted')); }
    catch { setMessage(t('courseApproval.answersError')); }
    finally { setBusy(false); }
  }

  async function complete() {
    setBusy(true); setMessage('');
    try {
      if (reviewComplete) { onComplete(); return; }
      const response = await saveReviewProgress(attemptId, sequence, position, 'in_progress', { activity: 'review_completed', initial_activity_state: initialActivityState }, token, 'checkpoint');
      setSequence((value) => value + 1);
      if (response.activity_state === 'decision_pending') {
        setReviewComplete(true);
        onComplete();
      } else {
        setMessage(t('courseApproval.finishNeedsCheckpoints'));
      }
    }
    catch { setMessage(t('courseApproval.finishError')); }
    finally { setBusy(false); }
  }

  return <section aria-label={t('courseApproval.reviewMode')} className="space-y-5">
    <WorkspaceToolbar className="items-center">
      <Badge variant="outline">{t('courseApproval.reviewMode')}</Badge>
      <Badge variant="secondary">{t('courseApproval.version')} {snapshot.release_version}</Badge>
      <span className="min-w-0 break-all font-mono text-xs text-muted-foreground">{snapshot.course.id}</span>
      <span className="text-xs text-muted-foreground">{initialActivityState}</span>
    </WorkspaceToolbar>
    <div className="grid min-w-0 gap-5 lg:grid-cols-[248px_minmax(0,1fr)]">
      <WorkspacePanel title={t('courseApproval.contents')} className="h-fit lg:sticky lg:top-6" bodyClassName="space-y-1">
        <nav aria-label={t('courseApproval.contents')}>
          {lessons.map((item, index) => <button key={item.id} type="button" aria-current={index === position ? 'step' : undefined} disabled={busy || reviewComplete} onClick={() => void selectLesson(index)} className={`block min-h-11 w-full break-words rounded-xl px-3 py-3 text-left text-sm leading-6 ${index === position ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-muted'}`}>{index + 1}. {item.title}</button>)}
        </nav>
      </WorkspacePanel>
      <WorkspacePanel bodyClassName="space-y-6 sm:p-8">
        <header className="space-y-2 border-b border-border pb-5">
          <p className="break-words text-xs leading-5 text-muted-foreground">{lesson?.moduleTitle || snapshot.course.title} · {position + 1} / {Math.max(lessons.length, 1)}</p>
          <h2 className="break-words text-2xl font-semibold leading-tight">{lesson?.title || snapshot.course.title}</h2>
        </header>
        <article className="min-w-0 break-words [&_table]:block [&_table]:overflow-x-auto">
          {lesson?.content ? <ReviewSourceImageProvider attemptId={attemptId} lessonId={lesson.id} token={token}>
            <LessonContent text={lesson.content} omitFirstHeading={lesson.title} className="text-base leading-8" />
          </ReviewSourceImageProvider> : <p className="whitespace-pre-wrap break-words text-sm leading-7">—</p>}
        </article>
        {lesson?.quizzes.map((quiz) => <section key={quiz.id} className="space-y-5 rounded-xl border border-border bg-muted/20 p-4 sm:p-5">
          <h3 className="break-words font-semibold">{quiz.title}</h3>
          {quiz.questions.map((question) => <fieldset key={question.id} className="min-w-0 space-y-3">
            <legend className="break-words text-sm font-medium leading-6">{question.text}</legend>
            <div className="space-y-2">{question.choices.map((choice) => <label key={choice.id} className="flex min-h-11 items-start gap-3 rounded-xl border border-border bg-card px-4 py-3 text-sm leading-6"><input className="mt-1 shrink-0" type="radio" name={`review-${question.id}`} checked={answers[question.id] === choice.id} onChange={() => { const next = { ...answers, [question.id]: choice.id }; setAnswers(next); setDiagnostics(null); try { sessionStorage.setItem(answerStorageKey, JSON.stringify(next)); } catch { /* Draft storage is optional; server writes remain authoritative. */ } }} disabled={busy || reviewComplete} /><span className="min-w-0 break-words">{choice.text}</span></label>)}</div>
          </fieldset>)}
          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <Button size="sm" variant="outline" onClick={() => void submitQuiz(quiz.id)} disabled={busy || reviewComplete || quiz.questions.some((question) => !answers[question.id])}>{t('courseApproval.submitAnswers')}</Button>
            {diagnostics && <span role="status" className="break-words text-sm">{t('courseApproval.courseResult', { answered: diagnostics.answered, total: diagnostics.total, score: diagnostics.score_percent })}</span>}
          </div>
        </section>)}
        {message && <p role="alert" className="break-words rounded-xl border border-destructive/30 p-4 text-sm text-destructive">{message}</p>}
        <footer className="flex flex-wrap justify-between gap-3 border-t border-border pt-5 [&_button]:min-h-11 [&_button]:whitespace-normal">
          <Button variant="outline" disabled={position === 0 || busy || reviewComplete} onClick={() => void selectLesson(position - 1)}>{t('courseApproval.previous')}</Button>
          {position < lessons.length - 1 ? <Button onClick={() => void selectLesson(position + 1)} disabled={busy || reviewComplete}>{t('courseApproval.next')}</Button> : <Button onClick={() => void complete()} disabled={busy || reviewComplete}>{busy ? t('courseApproval.sending') : t('courseApproval.finish')}</Button>}
        </footer>
      </WorkspacePanel>
    </div>
  </section>;
}
