'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui';
import { getApprovalRequest, getScopedReviewRequest, startReviewAttempt, type ApprovalRequestSummary, type ReviewAttempt, type ReviewActivityState } from '@/lib/courseApproval';
import { ReviewCoursePlayer } from '@/components/course-approval/ReviewCoursePlayer';
import { ReviewerDecisionPanel } from '@/components/course-approval/ReviewerDecisionPanel';
import { useT } from '@/i18n/useT';
import { workspaceCopy } from '@/features/learning-workspace/copy';
import { useAuthStore } from '@/store/authStore';

export function ReviewRequestScreen({ requestId, token, requireCapability = false, onCompleted, onExit }: { requestId: string; token?: string; requireCapability?: boolean; onCompleted?: () => void; onExit?: () => void }) {
  const actor = useAuthStore((state) => state.user);
  const session = useAuthStore((state) => Boolean(state.accessToken));
  const sessionEpoch = useAuthStore((state) => state.sessionEpoch);
  const actorScope = token ? 'limited-review' : JSON.stringify([actor?.user_id, actor?.tenant_id, actor?.role, session, sessionEpoch]);
  const identity = JSON.stringify([requestId, token, actorScope, requireCapability]);
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const generation = useRef(0);
  const [loaded, setLoaded] = useState<{ identity: string; request: ApprovalRequestSummary; attempt: ReviewAttempt } | null>(null);
  const [activityState, setActivityState] = useState<ReviewActivityState>('not_started');
  const [failure, setFailure] = useState<{ identity: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [completion, setCompletion] = useState<{ requestId: string; token?: string; actorScope: string } | null>(null);
  // Removing a spent limited token retains its receipt; a replacement capability does not.
  const completed = completion?.requestId === requestId && (completion.token
    ? completion.token === token || !token
    : !token && completion.actorScope === actorScope);
  useEffect(() => {
    if (completion && (completion.requestId !== requestId || Boolean(token && token !== completion.token)
      || (!completion.token && completion.actorScope !== actorScope))) setCompletion(null);
  }, [actorScope, completion, requestId, token]);
  const { t, lang } = useT();
  const m = workspaceCopy(lang);
  const visible = loaded?.identity === identity ? loaded : null;
  const error = failure?.identity === identity ? failure.message : '';

  const load = useCallback(async () => {
    if (completed) return;
    const requestGeneration = ++generation.current;
    const isCurrent = () => currentIdentity.current === identity && generation.current === requestGeneration;
    setLoading(true);
    setFailure(null);
    try {
      if (requireCapability && !token) throw new Error(m.decisionScopeChanged);
      const [summary, nextAttempt] = await Promise.all([
        token ? getScopedReviewRequest(token, requestId) : getApprovalRequest(requestId),
        startReviewAttempt(requestId, token),
      ]);
      if (!isCurrent()) return;
      const normalizedSummary: ApprovalRequestSummary = 'reviewer' in summary
        ? { request_id: summary.request_id, revision_id: summary.revision_id, outcome: summary.outcome, delivery_mode: summary.delivery_mode, due_at: summary.due_at, reviewers: [summary.reviewer], reviewer_count: 1 }
        : summary;
      setLoaded({ identity, request: normalizedSummary, attempt: nextAttempt });
      setActivityState(nextAttempt.activity_state);
    } catch (cause) {
      if (!isCurrent()) return;
      const status = typeof cause === 'object' && cause !== null && 'response' in cause
        ? (cause as { response?: { status?: number } }).response?.status : undefined;
      if (status === 401 || status === 403 || status === 404) sessionStorage.removeItem('course_review_token');
      setFailure({ identity, message: cause instanceof Error ? cause.message : m.decisionScopeChanged });
    } finally { if (isCurrent()) setLoading(false); }
  }, [completed, identity, requestId, token, requireCapability, m.decisionScopeChanged]);

  useEffect(() => {
    void load();
    return () => { generation.current += 1; };
  }, [load]);

  if (completed) return <main className="mx-auto max-w-3xl space-y-4 p-6"><div role="status" className="rounded-xl border border-success/40 bg-success/10 p-5"><h1 className="text-2xl font-bold">{t('courseApproval.decisionSubmittedTitle')}</h1><p className="mt-2 text-sm">{t('courseApproval.decisionSubmittedDescription')}</p></div>{onExit && <Button variant="outline" onClick={onExit}>{t('courseApproval.close')}</Button>}</main>;
  if (loading || (!visible && !error)) return <div className="p-6" role="status">{t('common.loading')}</div>;
  if (error) return <div className="mx-auto max-w-3xl space-y-3 p-6"><p role="alert" className="break-words rounded-xl border border-destructive/40 p-4 text-sm text-destructive">{error}</p><Button variant="outline" onClick={() => void load()}>{t('courseApproval.retry')}</Button></div>;
  if (!visible) return null;
  const { request, attempt } = visible;
  const isCurrent = () => currentIdentity.current === identity;

  return <div data-review-scope="course_review" className="mx-auto max-w-6xl space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-border bg-card p-5 sm:p-6">
      <div className="min-w-0 flex-1"><h1 className="text-2xl font-bold tracking-tight">{m.reviewScreenTitle}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{m.reviewHint}</p><details className="mt-3 text-xs text-muted-foreground"><summary className="cursor-pointer font-medium">{m.snapshot} · v{attempt.snapshot.release_version}</summary><p className="mt-2 break-all font-mono">{m.request}: {request.request_id}<br />{m.snapshot}: {attempt.snapshot_sha256}</p></details></div>
      {onExit && <Button variant="outline" onClick={onExit}>{t('courseApproval.close')}</Button>}
    </header>
    <ReviewCoursePlayer key={`${attempt.attempt_id}:${attempt.snapshot_sha256}`} snapshot={attempt.snapshot} snapshotIdentity={attempt.snapshot_sha256} answerStorageScope={token ? 'limited-review' : JSON.stringify([actor?.user_id, actor?.tenant_id, actor?.role])} attemptId={attempt.attempt_id} token={token} initialActivityState={attempt.activity_state} initialLessonPosition={attempt.lesson_position} initialNextSequence={attempt.next_sequence} onComplete={() => { if (isCurrent()) setActivityState('decision_pending'); }} />
    <ReviewerDecisionPanel attemptId={attempt.attempt_id} snapshotLabel={attempt.snapshot_sha256} requestOutcome={request.outcome} activityState={activityState} token={token} onReload={() => void load()} onSubmitted={() => { if (!isCurrent()) return; setCompletion({ requestId, token, actorScope }); onCompleted?.(); }} />
  </div>;
}
