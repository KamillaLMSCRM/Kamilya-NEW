'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { sourceReviewHref, type SourceReviewStatus } from './contract';
import { sourceReviewCopy } from './copy';

type ReviewStatuses = { required: boolean; documents: Record<string, SourceReviewStatus> };

export function useSourceReviewStatuses(ids: string[], scope: string) {
  const query = new URLSearchParams(ids.map(id => ['document_ids', id])).toString();
  const key = scope + ':' + query;
  const [state, setState] = useState<{ key: string; data: ReviewStatuses } | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  useEffect(() => {
    if (!query || !scope) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        const { data } = await api.get<ReviewStatuses>('/v1/documents/editorial-review/status?' + query, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted && typeof data?.required === 'boolean' && data.documents) setState({ key, data });
      } catch {
        // The generation endpoint owns admission, including during a frontend/
        // backend rollout and when this non-mutating lookup cannot be reached.
      }
    };
    void load();
    const onFocus = () => void load();
    window.addEventListener('focus', onFocus);
    return () => { controller.abort(); window.removeEventListener('focus', onFocus); };
  }, [key, query, refreshToken, scope]);
  return {
    status: state?.key === key ? state.data : undefined,
    refresh: () => setRefreshToken(value => value + 1),
  };
}

export function SourceReviewChecklist({ documents, status, requireReview = false }: {
  documents: Array<{ id: string; title: string }>;
  status?: ReviewStatuses;
  requireReview?: boolean;
}) {
  const { lang } = useT();
  const copy = sourceReviewCopy(lang);
  if (!documents.length || (!status?.required && !requireReview)) return null;
  const allApproved = !requireReview && documents.every(doc => status?.documents[doc.id] === 'approved');
  return <section className="space-y-2 rounded-xl border border-border bg-muted/20 p-4" aria-label={copy.status}>
    <h3 className="text-sm font-semibold">{copy.status}</h3>
    {!allApproved && <p className="text-sm text-muted-foreground">{copy.beforeGeneration}</p>}
    <ul className="space-y-2">
      {documents.map(doc => {
        const item = status?.documents[doc.id] ?? 'not_started';
        return <li className="flex flex-wrap items-baseline justify-between gap-2 text-sm" key={doc.id}>
          <span className="min-w-0 break-words">{doc.title} <span className="text-xs text-muted-foreground">· {copy.statusLabels[item]}</span></span>
          <Link href={sourceReviewHref(doc.id)} className="shrink-0 text-primary underline underline-offset-4">{copy.short}</Link>
        </li>;
      })}
    </ul>
  </section>;
}
