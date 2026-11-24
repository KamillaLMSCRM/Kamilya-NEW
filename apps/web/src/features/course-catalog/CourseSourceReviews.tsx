'use client';

import Link from 'next/link';
import { useEffect, useId, useState } from 'react';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { sourceReviewHref, type SourceReviewStatus } from '@/features/source-editorial-review/contract';
import { sourceReviewCopy } from '@/features/source-editorial-review/copy';
import { getCourseCatalogCopy } from './copy';

type Entry = { document_id: string; title: string; status: SourceReviewStatus };
type ReviewQueue = { items: Entry[]; next_offset: number | null };

export function CourseSourceReviews() {
  const { lang, t } = useT();
  const copy = getCourseCatalogCopy(lang);
  const sourceCopy = sourceReviewCopy(lang);
  const titleId = useId();
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState(true);

  useEffect(() => {
    const request = new AbortController();
    api.get<ReviewQueue>('/v1/documents/editorial-review/queue', {
      params: { offset, limit: 4 }, signal: request.signal,
    }).then(({ data }) => {
      if (request.signal.aborted) return;
      if (!Array.isArray(data?.items)) return;
      setQueue(previous => ({
        items: offset === 0 ? data.items : [...new Map(
          [...(previous?.items ?? []), ...data.items].map(item => [item.document_id, item]),
        ).values()],
        next_offset: data.next_offset,
      }));
      setFailed(false);
    }).catch(error => {
      if (!request.signal.aborted && error?.response?.status !== 404) setFailed(true);
    }).finally(() => {
      if (!request.signal.aborted) setPending(false);
    });
    return () => request.abort();
  }, [offset, attempt]);

  if (!queue?.items.length && !failed) return null;
  return (
    <section aria-labelledby={titleId} className="rounded-2xl border border-border bg-card p-4 sm:p-5">
      <h2 id={titleId} className="font-semibold">{copy.sourceReviews}</h2>
      <ul className="mt-1 divide-y divide-border">
        {queue?.items.map(item => (
          <li key={item.document_id} className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
            <span className="min-w-0 text-sm [overflow-wrap:anywhere]">{item.title}</span>
            <div className="flex flex-wrap items-center gap-x-3">
              <span className="text-xs text-muted-foreground">{sourceCopy.statusLabels[item.status]}</span>
              <Link href={sourceReviewHref(item.document_id) + '?' + new URLSearchParams({ document_id: item.document_id })}
                className="inline-flex min-h-9 items-center text-sm font-medium text-primary hover:underline">
                {copy.openSourceReview}
              </Link>
            </div>
          </li>
        ))}
      </ul>
      {failed && <div className="flex flex-wrap items-center gap-3 text-sm">
        <span role="status">{t('common.loadFailed')}</span>
        <button type="button" className="text-primary hover:underline" onClick={() => {
          setPending(true);
          setAttempt(value => value + 1);
        }} disabled={pending}>{t('common.retry')}</button>
      </div>}
      {queue && queue.next_offset !== null && !failed && <button type="button" className="min-h-9 text-sm text-primary hover:underline"
        onClick={() => { setPending(true); setOffset(queue.next_offset ?? 0); }} disabled={pending}>
        {copy.moreSourceReviews}
      </button>}
    </section>
  );
}
