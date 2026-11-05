'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui';
import { getApprovalRequest, getScopedReviewRequest, startReviewAttempt, type ApprovalRequestSummary, type ReviewAttempt, type ReviewActivityState } from '@/lib/courseApproval';
import { ReviewCoursePlayer } from '@/components/course-approval/ReviewCoursePlayer';
import { ReviewerDecisionPanel } from '@/components/course-approval/ReviewerDecisionPanel';
import { useT } from '@/i18n/useT';
import { workspaceCopy } from '@/features/learning-workspace/copy';
import { useAuthStore } from '@/store/authStore';
import { WorkspacePage, WorkspacePanel } from '@/features/workspace-design';

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

  if (completed) return <WorkspacePage id="review-request" className="mx-auto max-w-3xl"><WorkspacePanel role="status" className="border-success/40" bodyClassName="space-y-5"><h1 className="break-words text-2xl font-semibold tracking-tight">{t('courseApproval.decisionSubmittedTitle')}</h1><p className="text-sm leading-6">{t('courseApproval.decisionSubmittedDescription')}</p>{onExit && <Button variant="outline" onClick={onExit}>{t('courseApproval.close')}</Button>}</WorkspacePanel></WorkspacePage>;
  if (loading || (!visible && !error)) return <WorkspacePage id="review-request" title={m.reviewScreenTitle}><WorkspacePanel aria-busy="true"><p role="status">{t('common.loading')}</p></WorkspacePanel></WorkspacePage>;
  if (error) return <WorkspacePage id="review-request" className="mx-auto max-w-3xl" title={m.reviewScreenTitle}><WorkspacePanel className="border-destructive/40" bodyClassName="space-y-4"><p role="alert" className="break-words text-sm text-destructive">{error}</p><Button variant="outline" onClick={() => void load()}>{t('courseApproval.retry')}</Button></WorkspacePanel></WorkspacePage>;
  if (!visible) return null;
  const { request, attempt } = visible;
  const isCurrent = () => currentIdentity.current === identity;

  return <WorkspacePage id="review-request" data-review-scope="course_review" className="mx-auto max-w-6xl" title={m.reviewScreenTitle} description={m.reviewHint} actions={onExit && <Button variant="outline" onClick={onExit}>{t('courseApproval.close')}</Button>}>
    <WorkspacePanel bodyClassName="space-y-3" className="border-primary/20">
      <p className="break-words text-lg font-semibold">{attempt.snapshot.course.title}</p>
      <details className="text-xs text-muted-foreground"><summary className="min-h-8 cursor-pointer font-medium">{m.snapshot} · v{attempt.snapshot.release_version}</summary><dl className="mt-3 grid gap-4 border-t border-border pt-4 sm:grid-cols-2"><div><dt>{m.request}</dt><dd className="mt-1 break-all font-mono">{request.request_id}</dd></div><div><dt>{m.snapshot}</dt><dd className="mt-1 break-all font-mono">{attempt.snapshot_sha256}</dd></div></dl></details>
    </WorkspacePanel>
    <ReviewCoursePlayer key={`${attempt.attempt_id}:${attempt.snapshot_sha256}`} snapshot={attempt.snapshot} snapshotIdentity={attempt.snapshot_sha256} attemptId={attempt.attempt_id} token={token} initialActivityState={attempt.activity_state} initialLessonPosition={attempt.lesson_position} initialNextSequence={attempt.next_sequence} onComplete={() => { if (isCurrent()) setActivityState('decision_pending'); }} />
    <ReviewerDecisionPanel attemptId={attempt.attempt_id} snapshotLabel={attempt.snapshot_sha256} requestOutcome={request.outcome} activityState={activityState} token={token} onReload={() => void load()} onSubmitted={() => { if (!isCurrent()) return; setCompletion({ requestId, token, actorScope }); onCompleted?.(); }} />
  </WorkspacePage>;
}
