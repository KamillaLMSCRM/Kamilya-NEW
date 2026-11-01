'use client';

import { AlertTriangle, Download, FileText } from 'lucide-react';
import { Button, Modal } from '@/components/ui';
import type { DocumentCatalogItem } from '@/lib/documentCatalog';
import { workspaceCopy } from './copy';

export function DocumentInspection({ document, lang, downloading, onClose, onDownload, onUsages }: {
  document: DocumentCatalogItem;
  lang: string;
  downloading: boolean;
  onClose: () => void;
  onDownload: () => void;
  onUsages: () => void;
}) {
  const m = workspaceCopy(lang);
  const status = document.lifecycle_status !== 'active' ? m.inactive : {
    ready: m.ready, partial: m.partial, processing: m.working, failed: m.failed,
  }[document.index.status];
  const count = (value: number | null | undefined) => value == null ? '—' : value;
  return <Modal open title={m.sourceDetails} description={m.sourceHint} onClose={onClose} className="max-w-3xl">
    <div className="grid min-w-0 gap-5 md:grid-cols-2">
      <section className="min-w-0 rounded-xl border border-border bg-card p-5">
        <FileText className="h-7 w-7 text-primary" aria-hidden="true" />
        <h3 className="mt-4 break-words text-lg font-semibold">{document.title}</h3>
        <p className="mt-2 break-all text-sm text-muted-foreground">{document.filename}</p>
        <dl className="mt-5 space-y-3 text-sm">
          <div className="flex justify-between gap-3"><dt>{m.version}</dt><dd>v{document.version}</dd></div>
          <div className="flex justify-between gap-3"><dt>{m.revision}</dt><dd>{document.index.revision}</dd></div>
          <div className="flex justify-between gap-3"><dt>{m.uses}</dt><dd>{count(document.usages_summary?.total)}</dd></div>
        </dl>
        <Button type="button" className="mt-6 w-full" onClick={onDownload} disabled={downloading}><Download className="mr-2 h-4 w-4" aria-hidden="true" />{m.original}</Button>
        <Button type="button" variant="outline" className="mt-2 w-full" onClick={onUsages}>{m.uses}</Button>
      </section>
      <section className="min-w-0 space-y-4">
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="font-semibold">{m.processing}</h3>
          <p className="mt-2 text-sm font-medium">{status}</p>
          <p className="mt-3 text-sm text-muted-foreground">{m.chunks}: {count(document.index.chunks_indexed)} / {count(document.index.chunks_total)}</p>
          {document.index.message && <p className="mt-3 break-words text-sm text-muted-foreground">{document.index.message}</p>}
        </div>
        <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm">
          <AlertTriangle className="mb-2 h-5 w-5 text-warning" aria-hidden="true" />
          <p>{m.meaning}</p><p className="mt-3 text-xs leading-6 text-muted-foreground">{m.noExtraction}</p>
        </div>
      </section>
    </div>
  </Modal>;
}
