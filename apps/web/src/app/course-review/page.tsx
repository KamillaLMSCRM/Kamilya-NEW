'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardContent } from '@/components/ui';
import { listApprovalRequests, type ApprovalRequestSummary } from '@/lib/courseApproval';

export default function CourseReviewInboxPage() {
  const [requests, setRequests] = useState<ApprovalRequestSummary[]>([]);
  const [error, setError] = useState('');
  useEffect(() => { listApprovalRequests().then(setRequests).catch(() => setError('Не удалось загрузить входящие проверки.')); }, []);
  return <div className="mx-auto max-w-4xl space-y-6"><header><h1 className="text-2xl font-bold">Проверка курсов</h1><p className="mt-1 text-sm text-muted-foreground">Вы видите только назначенные вам версии. Проверка проходит в отдельном режиме и не записывается в журнал обучения.</p></header>{error && <p role="alert" className="break-words rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</p>}<div className="space-y-3">{requests.length === 0 && !error && <Card><CardContent className="p-5 text-sm text-muted-foreground">Новых проверок нет.</CardContent></Card>}{requests.map((request) => <Card key={request.request_id}><CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><h2 className="font-semibold">Запрос {request.request_id.slice(0, 8)}</h2><p className="break-all text-xs text-muted-foreground">Версия {request.revision_id} · {request.outcome}</p></div><Link className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" href={`/course-review-requests/${request.request_id}`}>Открыть проверку</Link></CardContent></Card>)}</div></div>;
}
