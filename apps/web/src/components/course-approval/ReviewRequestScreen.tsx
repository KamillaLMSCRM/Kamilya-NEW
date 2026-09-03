'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui';
import { getApprovalRequest, getScopedReviewRequest, startReviewAttempt, type ApprovalRequestSummary, type ReviewAttempt, type ReviewActivityState } from '@/lib/courseApproval';
import { ReviewCoursePlayer } from '@/components/course-approval/ReviewCoursePlayer';
import { ReviewerDecisionPanel } from '@/components/course-approval/ReviewerDecisionPanel';

export function ReviewRequestScreen({ requestId, token, onCompleted, onExit }: { requestId: string; token?: string; onCompleted?: () => void; onExit?: () => void }) {
  const [request, setRequest] = useState<ApprovalRequestSummary | null>(null);
  const [attempt, setAttempt] = useState<ReviewAttempt | null>(null);
  const [activityState, setActivityState] = useState<ReviewActivityState>('not_started');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [summary, nextAttempt] = await Promise.all([token ? getScopedReviewRequest(token, requestId) : getApprovalRequest(requestId), startReviewAttempt(requestId, token)]);
      const normalizedSummary: ApprovalRequestSummary = 'reviewer' in summary
        ? { request_id: summary.request_id, revision_id: summary.revision_id, outcome: summary.outcome, delivery_mode: summary.delivery_mode, due_at: summary.due_at, reviewers: [summary.reviewer], reviewer_count: 1 }
        : summary;
      setRequest(normalizedSummary); setAttempt(nextAttempt); setActivityState(nextAttempt.activity_state);
    } catch (cause) {
      const status = typeof cause === 'object' && cause !== null && 'response' in cause
        ? (cause as { response?: { status?: number } }).response?.status
        : undefined;
      if (status === 401 || status === 403 || status === 404) sessionStorage.removeItem('course_review_token');
      setError(cause instanceof Error ? cause.message : 'Не удалось открыть проверку.');
    }
    finally { setLoading(false); }
  }, [requestId, token]);
  useEffect(() => { void load(); }, [load]);
  if (loading) return <div className="p-6">Загрузка…</div>;
  if (error) return <div className="mx-auto max-w-3xl space-y-3 p-6"><p role="alert" className="break-words rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</p><Button variant="outline" onClick={() => void load()}>Повторить</Button></div>;
  if (!request || !attempt) return null;
  return <div data-review-scope="course_review" className="mx-auto max-w-5xl space-y-6"><header className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-2xl font-bold">Проверка версии курса</h1><p className="mt-1 break-all text-sm text-muted-foreground">Запрос {request.request_id} · неизменяемый снимок {attempt.snapshot_sha256}</p></div>{onExit && <Button variant="outline" onClick={onExit}>Выйти</Button>}</header><ReviewCoursePlayer snapshot={attempt.snapshot} attemptId={attempt.attempt_id} token={token} initialActivityState={attempt.activity_state} onComplete={() => { setActivityState('decision_pending'); }} /><ReviewerDecisionPanel attemptId={attempt.attempt_id} activityState={activityState} token={token} onSubmitted={onCompleted} /></div>;
}
