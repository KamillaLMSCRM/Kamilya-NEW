'use client';

import { useId, useRef, useState, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';

export function RecordList<T>({ records, getId, title, description, status, detailsLabel, renderDetails, selection }: {
  records: readonly T[];
  getId: (record: T) => string;
  title: (record: T) => ReactNode;
  description?: (record: T) => ReactNode;
  status?: (record: T) => ReactNode;
  detailsLabel: string;
  renderDetails: (record: T) => ReactNode;
  selection?: (record: T) => ReactNode;
}) {
  const [selectedId, setSelectedId] = useState<string>();
  const detail = useRef<HTMLElement>(null);
  const detailId = useId();
  const selected = records.find((record) => getId(record) === selectedId) ?? records[0];
  if (!selected) return null;

  return <div className="methodologist-split" data-methodologist-records>
    <ul className="min-w-0 divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      {records.map((record) => {
        const id = getId(record);
        const active = getId(selected) === id;
        return <li key={id} className="flex min-w-0 items-center">
          {selection?.(record)}
          <button type="button" aria-pressed={active} aria-controls={detailId}
            className={`flex min-h-14 w-full min-w-0 items-center gap-3 border-l-[3px] px-3 py-2.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-ring ${active ? 'border-primary bg-primary/5' : 'border-transparent hover:bg-muted/50'}`}
            onClick={() => {
              setSelectedId(id);
              if (window.matchMedia?.('(max-width: 1023px)').matches) detail.current?.focus();
            }}>
            <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
              <span className="block text-sm font-semibold">{title(record)}</span>
              {description && <span className="mt-1 block text-xs text-muted-foreground">{description(record)}</span>}
            </span>
            {status && <span className="max-w-[36%] rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">{status(record)}</span>}
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          </button>
        </li>;
      })}
    </ul>
    <section ref={detail} id={detailId} tabIndex={-1} aria-label={detailsLabel}
      className="min-w-0 scroll-mt-32 rounded-2xl border border-border bg-card shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
      {renderDetails(selected)}
    </section>
  </div>;
}
