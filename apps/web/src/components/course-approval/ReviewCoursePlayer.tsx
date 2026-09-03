'use client';

import { useMemo, useState } from 'react';
import { Badge, Button, Card, CardContent } from '@/components/ui';
import { saveReviewProgress, submitReviewTest, type ReviewActivityState, type ReviewSnapshot } from '@/lib/courseApproval';
import { useT } from '@/i18n/useT';

interface ReviewDiagnostic { score_percent?: number; passed?: boolean; answered_count?: number }

export function ReviewCoursePlayer({ snapshot, attemptId, token, initialActivityState = 'not_started', onComplete }: { snapshot: ReviewSnapshot; attemptId: string; token?: string; initialActivityState?: ReviewActivityState; onComplete: () => void }) {
  const [position, setPosition] = useState(0);
  const [sequence, setSequence] = useState(1);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [diagnostics, setDiagnostics] = useState<Record<string, ReviewDiagnostic>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [reviewComplete, setReviewComplete] = useState(initialActivityState === 'completed');
  const { t } = useT();
  const lessons = useMemo(() => snapshot.modules.flatMap((module) => module.lessons.map((lesson) => ({ ...lesson, moduleTitle: module.title }))), [snapshot.modules]);
  const lesson = lessons[position];

  async function recordActivity(nextPosition: number, payload: Record<string, unknown> = {}) {
    const response = await saveReviewProgress(attemptId, sequence, nextPosition, 'in_progress', payload, token);
    setSequence((value) => value + 1);
    if (response.diagnostics && typeof payload.quiz_id === 'string') setDiagnostics((current) => ({ ...current, [payload.quiz_id as string]: response.diagnostics || {} }));
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
    if (!quiz) return;
    const submitted = quiz.questions.map((question) => ({ question_id: question.id, choice_id: answers[question.id] || null }));
    setBusy(true); setMessage('');
    try { const response = await submitReviewTest(attemptId, submitted.map((item) => ({ question_id: item.question_id, selected_choice_ids: item.choice_id ? [item.choice_id] : [] })), token); setSequence((value) => value + 1); if (response.result || response.diagnostics) { const result = response.result || response.diagnostics || {}; setDiagnostics((current) => ({ ...current, [quizId]: result })); if (result.complete) { setReviewComplete(true); onComplete(); } } else setMessage(t('courseApproval.answersAccepted')); }
    catch { setMessage(t('courseApproval.answersError')); }
    finally { setBusy(false); }
  }

  async function complete() {
    setBusy(true); setMessage('');
    try { if (reviewComplete) { onComplete(); return; } await saveReviewProgress(attemptId, sequence, position, 'completed', { activity: 'review_completed', initial_activity_state: initialActivityState }, token); setSequence((value) => value + 1); setReviewComplete(true); onComplete(); }
    catch { setMessage(t('courseApproval.finishError')); }
    finally { setBusy(false); }
  }

  return <section aria-label={t('courseApproval.reviewMode')} className="space-y-4"><div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{t('courseApproval.reviewMode')}</Badge><Badge variant="secondary">{t('courseApproval.version')} {snapshot.release_version}</Badge><span className="break-all text-xs text-muted-foreground">{snapshot.course.id}</span><span className="text-xs text-muted-foreground">{initialActivityState}</span></div><div className="grid gap-4 lg:grid-cols-[220px_1fr]"><Card><CardContent className="space-y-1 p-3"><h2 className="mb-2 px-2 text-sm font-semibold">{t('courseApproval.contents')}</h2>{lessons.map((item, index) => <button key={item.id} type="button" aria-current={index === position ? 'step' : undefined} disabled={busy || reviewComplete} onClick={() => void selectLesson(index)} className={`block min-h-11 w-full rounded px-2 text-left text-sm break-words ${index === position ? 'bg-primary/10 text-primary' : 'hover:bg-muted'}`}>{index + 1}. {item.title}</button>)}</CardContent></Card><Card><CardContent className="space-y-4 p-5"><p className="text-xs text-muted-foreground">{lesson?.moduleTitle || snapshot.course.title} · {position + 1} / {Math.max(lessons.length, 1)}</p><h2 className="text-xl font-semibold break-words">{lesson?.title || snapshot.course.title}</h2><p className="whitespace-pre-wrap break-words text-sm leading-7">{lesson?.content || '—'}</p>{lesson?.quizzes.map((quiz) => <div key={quiz.id} className="space-y-4 rounded-lg border p-4"><h3 className="font-semibold break-words">{quiz.title}</h3>{quiz.questions.map((question) => <fieldset key={question.id} className="space-y-2"><legend className="break-words text-sm">{question.text}</legend><div className="space-y-1">{question.choices.map((choice) => <label key={choice.id} className="flex min-h-11 items-center gap-3 rounded border px-3 py-2 text-sm break-words"><input type="radio" name={`review-${question.id}`} checked={answers[question.id] === choice.id} onChange={() => setAnswers((current) => ({ ...current, [question.id]: choice.id }))} disabled={reviewComplete} />{choice.text}</label>)}</div></fieldset>)}<div className="flex flex-wrap items-center gap-3"><Button size="sm" variant="outline" onClick={() => void submitQuiz(quiz.id)} disabled={busy || reviewComplete}>{t('courseApproval.submitAnswers')}</Button>{diagnostics[quiz.id] && <span role="status" className="break-words text-sm">{t('courseApproval.serverResult')}: {diagnostics[quiz.id].score_percent != null ? `${diagnostics[quiz.id].score_percent}%` : '✓'}{diagnostics[quiz.id].passed === true ? ' · ✓' : diagnostics[quiz.id].passed === false ? ' · ×' : ''}</span>}</div></div>)}{message && <p role="alert" className="break-words text-sm text-destructive">{message}</p>}<div className="flex flex-wrap justify-between gap-2"><Button variant="outline" disabled={position === 0 || busy || reviewComplete} onClick={() => void selectLesson(position - 1)}>{t('courseApproval.previous')}</Button>{position < lessons.length - 1 ? <Button onClick={() => void selectLesson(position + 1)} disabled={busy || reviewComplete}>{t('courseApproval.next')}</Button> : <Button onClick={() => void complete()} disabled={busy || reviewComplete}>{busy ? t('courseApproval.sending') : t('courseApproval.finish')}</Button>}</div></CardContent></Card></div></section>;
}
