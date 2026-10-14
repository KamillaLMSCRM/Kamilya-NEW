'use client';

import { useLayoutEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui';
import { loadCorrectionSourceFile, type CorrectionCitation, type CorrectionLocale } from '@/lib/lessonCorrection';

const COPY = {
  ru: {
    current: 'Скачивается текущий документ из библиотеки. Текущий файл может отличаться от версии, использованной для правки. Хеш фрагмента не подтверждает версию файла.',
    document: 'Документ', prepare: 'Подготовить скачивание документа', download: 'Скачать', loading: 'Подготовка файла…',
    technical: 'Сведения об источнике', fragment: 'Хеш фрагмента', forbidden: 'Нет доступа к исходному документу. Проверьте вход и права.',
    missing: 'Документ или файл недоступен. Проверьте библиотеку источников.', invalid: 'Получен некорректный файл. Проверьте документ в библиотеке.',
    failed: 'Не удалось подготовить файл. Попробуйте ещё раз.',
  },
  kk: {
    current: 'Кітапханадағы ағымдағы құжат жүктеледі. Ағымдағы файл түзетуге пайдаланылған нұсқадан өзгеше болуы мүмкін. Үзінді хеші файл нұсқасын растамайды.',
    document: 'Құжат', prepare: (index: number) => `${index}-құжатты жүктеуге дайындау`, download: 'Жүктеу', loading: 'Файл дайындалуда…',
    technical: 'Дереккөз туралы мәлімет', fragment: 'Үзінді хеші', forbidden: 'Бастапқы құжатқа қолжетімділік жоқ. Кіруді және құқықтарды тексеріңіз.',
    missing: 'Құжат немесе файл қолжетімсіз. Дереккөз кітапханасын тексеріңіз.', invalid: 'Жарамсыз файл алынды. Кітапханадағы құжатты тексеріңіз.',
    failed: 'Файлды дайындау мүмкін болмады. Қайта көріңіз.',
  },
  en: {
    current: 'Downloads the current library document. The current file may differ from the version used for the correction. A fragment hash does not verify the file version.',
    document: 'Document', prepare: (index: number) => `Prepare document ${index} download`, download: 'Download', loading: 'Preparing file…',
    technical: 'Source details', fragment: 'Fragment hash', forbidden: 'No access to the source document. Check your sign-in and permissions.',
    missing: 'The document or file is unavailable. Check the source library.', invalid: 'An invalid file was received. Check the document in the library.',
    failed: 'Could not prepare the file. Try again.',
  },
} as const;

type Session = { active: boolean; pending: boolean; controller: AbortController | null; url: string | null };
type Prepared = { documentId: string; title: string; filename: string; url: string };

/** Key by preview/session/locale in the parent; one retained file, no eager requests. */
export default function CorrectionSources({ citations, locale }: { citations: CorrectionCitation[]; locale: CorrectionLocale }) {
  const ui = COPY[locale];
  const sessionRef = useRef<Session | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [error, setError] = useState<{ documentId: string; message: string } | null>(null);
  const documents = new Map<string, CorrectionCitation[]>();
  citations.forEach((citation) => documents.set(citation.document_id, [...(documents.get(citation.document_id) ?? []), citation]));

  useLayoutEffect(() => {
    const session: Session = { active: true, pending: false, controller: null, url: null };
    sessionRef.current = session;
    return () => {
      session.active = false;
      session.controller?.abort();
      if (session.url) URL.revokeObjectURL(session.url);
    };
  }, []);

  const prepare = async (documentId: string) => {
    const session = sessionRef.current;
    if (!session?.active || session.pending) return;
    session.pending = true;
    if (session.url) { URL.revokeObjectURL(session.url); session.url = null; }
    setPrepared(null); setError(null); setLoading(documentId);
    const controller = new AbortController(); session.controller = controller;
    const current = () => session.active && sessionRef.current === session && !controller.signal.aborted;
    try {
      const file = await loadCorrectionSourceFile(documentId, controller.signal);
      if (!current()) return;
      session.url = URL.createObjectURL(file.blob);
      setPrepared({ documentId, title: file.title, filename: file.filename, url: session.url });
    } catch (cause) {
      if (!current()) return;
      const status = (cause as { response?: { status?: number } } | null)?.response?.status;
      const message = status === 401 || status === 403 ? ui.forbidden : status === 404 ? ui.missing
        : cause instanceof Error && cause.message === 'Invalid source file' ? ui.invalid : ui.failed;
      setError({ documentId, message });
    } finally {
      session.pending = false;
      if (current()) setLoading(null);
    }
  };

  return <div className="mt-2 min-w-0 space-y-3 text-sm">
    <p className="text-muted-foreground">{ui.current}</p>
    <ul className="space-y-3">{Array.from(documents, ([documentId, references], index) => <li key={documentId} className="min-w-0 rounded border p-3">
      <p className="mb-2 break-words font-medium">{prepared?.documentId === documentId ? prepared.title : `${ui.document} ${index + 1}`}</p>
      {prepared?.documentId === documentId
        ? <a className="inline-block max-w-full break-words text-primary underline" href={prepared.url} download={prepared.filename}>{ui.download} {prepared.filename}</a>
        : <Button type="button" variant="outline" className="h-auto max-w-full whitespace-normal text-left" disabled={loading !== null} onClick={() => void prepare(documentId)}>{typeof ui.prepare === 'function' ? ui.prepare(index + 1) : `${ui.prepare} ${index + 1}`}</Button>}
      {loading === documentId && <p role="status" aria-live="polite">{ui.loading}</p>}
      {error?.documentId === documentId && <p role="alert" className="mt-2 text-destructive">{error.message}</p>}
      <details className="mt-2 min-w-0 break-all text-xs text-muted-foreground"><summary className="cursor-pointer">{ui.technical}</summary><p>{documentId}</p>
        <ul>{references.map((reference, i) => <li key={`${reference.locator}:${i}`} className="mt-2"><span>{reference.locator}</span><span className="block">{ui.fragment}: SHA256 {reference.evidence_hash}</span></li>)}</ul>
      </details>
    </li>)}</ul>
  </div>;
}
