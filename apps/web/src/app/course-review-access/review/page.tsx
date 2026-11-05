'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getScopedReviewRequest, type ScopedReviewRequest } from '@/lib/courseApproval';
import { PublicWorkspace, WorkspacePanel } from '@/features/workspace-design';
import { getPublicWorkspaceCopy } from '@/features/workspace-design/publicCopy';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { PublicLegalFooter } from '@/components/legal/PublicLegalFooter';
import { useT } from '@/i18n/useT';

export default function ScopedReviewInboxPage() {
  const { lang } = useT();
  const copy = getPublicWorkspaceCopy(lang);
  const [request, setRequest] = useState<ScopedReviewRequest | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { getScopedReviewRequest().then(setRequest).catch(() => setError(copy.revoked)); }, [copy.revoked]);
  return <PublicWorkspace id="review-access-inbox" title={copy.reviewInbox} description={copy.reviewInboxHint} actions={<LanguageSwitcher />}>
    {error && <p role="alert" className="rounded-2xl border border-destructive/30 bg-card p-5 text-sm leading-6 text-destructive">{error}</p>}
    {!request && !error && <WorkspacePanel><p role="status" className="text-sm text-muted-foreground">{copy.loading}</p></WorkspacePanel>}
    {request && <WorkspacePanel key={request.request_id}>
      <div className="flex min-w-0 flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-2"><h2 className="text-lg font-semibold">{copy.request} {request.request_id.slice(0, 8)}</h2><p className="text-sm text-muted-foreground">{copy.status}: {request.reviewer.activity_state || 'not_started'} · {request.outcome}</p><details className="text-xs text-muted-foreground"><summary className="cursor-pointer font-medium">{copy.version}</summary><p className="mt-2 break-all font-mono">{request.revision_id}</p></details></div>
        <Link className="inline-flex min-h-11 items-center justify-center rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" href={`/course-review-access/review/requests/${request.request_id}`}>{copy.openReview}</Link>
      </div>
    </WorkspacePanel>}
    <PublicLegalFooter />
  </PublicWorkspace>;
}
