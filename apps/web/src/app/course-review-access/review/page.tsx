'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardContent } from '@/components/ui';
import { getScopedReviewRequest, type ScopedReviewRequest } from '@/lib/courseApproval';

export default function ScopedReviewInboxPage() {
  const [request, setRequest] = useState<ScopedReviewRequest | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { getScopedReviewRequest().then(setRequest).catch(() => setError('Ссылка недействительна или доступ отозван.')); }, []);
  return <div className="mx-auto max-w-4xl space-y-6 p-4"><header><h1 className="text-2xl font-bold">Проверка курсов</h1><p className="mt-1 text-sm text-muted-foreground">Режим проверки не записывает данные в журнал обучения.</p></header>{error && <p role="alert" className="break-words rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</p>}<div className="space-y-3">{!request && !error && <Card><CardContent className="p-5 text-sm text-muted-foreground">Загрузка…</CardContent></Card>}{request && <Card key={request.request_id}><CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><h2 className="font-semibold">Запрос {request.request_id.slice(0, 8)}</h2><p className="break-all text-xs text-muted-foreground">Версия {request.revision_id} · {request.outcome}</p><p className="break-words text-xs text-muted-foreground">Статус: {request.reviewer.activity_state || 'not_started'}</p></div><Link className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" href={`/course-review-access/review/requests/${request.request_id}`}>Открыть проверку</Link></CardContent></Card>}</div></div>;
}
