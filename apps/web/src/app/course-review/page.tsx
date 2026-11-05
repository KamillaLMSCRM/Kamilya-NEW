'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Badge } from '@/components/ui';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel } from '@/features/workspace-design';
import { listApprovalRequests, type ApprovalRequestSummary } from '@/lib/courseApproval';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';

export default function CourseReviewInboxPage() {
  const [requests, setRequests] = useState<ApprovalRequestSummary[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const { t } = useT();
  const userId = useAuthStore((state) => state.user?.user_id);
  useEffect(() => {
    let active = true;
    setRequests([]); setError(''); setLoading(Boolean(userId));
    if (userId) void listApprovalRequests()
      .then((rows) => { if (active) setRequests(rows.filter((row) => row.reviewers?.some((reviewer) => reviewer.reviewer_id === userId))); })
      .catch(() => { if (active) setError('Не удалось загрузить входящие проверки.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [userId]);

  return <WorkspacePage id="course-review" title={t('courseApproval.reviewMode')} description={t('courseApproval.reviewInboxHint')}>
    {loading ? <WorkspacePanel aria-busy="true"><p role="status">{t('common.loading')}</p></WorkspacePanel>
      : error ? <WorkspacePanel role="alert" className="border-destructive/40"><p className="break-words text-sm text-destructive">{error}</p></WorkspacePanel>
      : requests.length === 0 ? <WorkspaceEmpty title={t('courseApproval.noPendingReviews')} />
      : <WorkspacePanel padded={false} bodyClassName="divide-y divide-border">
        {requests.map((request) => <article key={request.request_id} className="flex min-w-0 flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div className="min-w-0 space-y-2"><h2 className="break-words font-semibold">{t('courseApproval.request')} {request.request_id.slice(0, 8)}</h2><p className="break-all font-mono text-xs leading-5 text-muted-foreground">{t('courseApproval.version')} {request.revision_id}</p><Badge variant="outline">{request.outcome}</Badge></div>
          <Link className="inline-flex min-h-11 items-center justify-center rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" href={`/course-review-requests/${request.request_id}`}>{t('courseApproval.openReview')}</Link>
        </article>)}
      </WorkspacePanel>}
  </WorkspacePage>;
}
