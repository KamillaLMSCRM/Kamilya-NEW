'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardContent } from '@/components/ui';
import { listApprovalRequests, type ApprovalRequestSummary } from '@/lib/courseApproval';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';

export default function CourseReviewInboxPage() {
  const [requests, setRequests] = useState<ApprovalRequestSummary[]>([]);
  const [error, setError] = useState('');
  const { t } = useT();
  const userId = useAuthStore((state) => state.user?.user_id);
  useEffect(() => { if (!userId) return; listApprovalRequests().then((rows) => setRequests(rows.filter((row) => row.reviewers?.some((reviewer) => reviewer.reviewer_id === userId)))).catch(() => setError('Не удалось загрузить входящие проверки.')); }, [userId]);
  return <div className="mx-auto max-w-4xl space-y-6"><header><h1 className="text-2xl font-bold">{t('courseApproval.reviewMode')}</h1><p className="mt-1 text-sm text-muted-foreground">{t('courseApproval.reviewInboxHint')}</p></header>{error && <p role="alert" className="break-words rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</p>}<div className="space-y-3">{requests.length === 0 && !error && <Card><CardContent className="p-5 text-sm text-muted-foreground">{t('courseApproval.noPendingReviews')}</CardContent></Card>}{requests.map((request) => <Card key={request.request_id}><CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><h2 className="font-semibold">{t('courseApproval.request')} {request.request_id.slice(0, 8)}</h2><p className="break-all text-xs text-muted-foreground">{t('courseApproval.version')} {request.revision_id} · {request.outcome}</p></div><Link className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" href={`/course-review-requests/${request.request_id}`}>{t('courseApproval.openReview')}</Link></CardContent></Card>)}</div></div>;
}
