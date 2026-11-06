'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { WorkspacePage, WorkspacePanel } from '@/features/workspace-design';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { sourceReviewHref, type ReviewCommand, type SourceReview } from './contract';
import { sourceReviewCopy } from './copy';

const field = 'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const code = 'whitespace-pre-wrap break-words rounded-lg border border-border bg-muted/30 p-3 text-sm [overflow-wrap:anywhere]';
type Action = Omit<ReviewCommand, 'expected_revision' | 'request_id'>;
type Notice = 'conflict' | 'unknown' | 'error' | 'invalidAnchor' | 'overlapping';

function responseStatus(error: unknown): number | undefined {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = error.response;
    if (response && typeof response === 'object' && 'status' in response && typeof response.status === 'number') return response.status;
  }
}

function reviewErrorCode(error: unknown): string | undefined {
  const data = (error as { response?: { data?: { details?: { code?: string }; detail?: { code?: string } } } } | null)?.response?.data;
  return data?.details?.code ?? data?.detail?.code;
}

export default function SourceEditorialReview() {
  const { id, approvalId } = useParams<{ id: string; approvalId?: string }>();
  const actor = useAuthStore((state) => state.user);
  const sessionEpoch = useAuthStore((state) => state.sessionEpoch);
  if (actor?.role !== 'methodologist') return null;
  return <ReviewWorkspace key={[sessionEpoch, actor.user_id, actor.tenant_id, id, approvalId].join(':')}
    id={id} approvalId={approvalId} />;
}

function ReviewWorkspace({ id, approvalId }: { id: string; approvalId?: string }) {
  const { lang } = useT();
  const copy = sourceReviewCopy(lang);
  const endpoint = '/v1' + sourceReviewHref(id);
  const [review, setReview] = useState<SourceReview | null>(null);
  const [courseDocuments, setCourseDocuments] = useState<string[]>([]);
  const [pageInput, setPageInput] = useState<{ first: string; last: string } | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<'idle' | 'loading' | 'failed'>('idle');
  useEffect(() => {
    const ids = new URLSearchParams(window.location.search).getAll('document_id');
    if (ids.includes(id)) setCourseDocuments([...new Set(ids)].slice(0, 5));
  }, [id]);
  const generationHref = '/ai/generate?' + new URLSearchParams(
    (courseDocuments.length ? courseDocuments : [id]).map(documentId => ['document_id', documentId])
  ).toString();
  const [loadError, setLoadError] = useState(false);
  const [selected, select] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<ReviewCommand | null>(null);
  const [conflictInput, setConflictInput] = useState<Action | null>(null);
  const [reason, setReason] = useState('');
  const [replacement, setReplacement] = useState('');
  const [anchor, setAnchor] = useState('');
  const [decision, setDecision] = useState<'replace' | 'keep'>('replace');
  const [undoItem, setUndoItem] = useState<string | null>(null);
  const [undoReason, setUndoReason] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [manual, setManual] = useState({ quote: '', replacement: '', reason: '' });
  const detail = useRef<HTMLHeadingElement>(null);
  const commandLock = useRef(false);
  const version = useRef(0);
  const requestVersion = useRef(0);

  const accept = useCallback((data: SourceReview) => {
    if (data.document_id !== id || data.revision < version.current) return;
    version.current = data.revision;
    setReview(data);
    setLoadError(false);
  }, [id]);

  const load = useCallback(async (signal?: AbortSignal) => {
    const attempt = ++requestVersion.current;
    try {
      const response = await api.get<SourceReview>(approvalId ? endpoint + '/' + encodeURIComponent(approvalId) : endpoint, { signal });
      if (!signal?.aborted && attempt === requestVersion.current) accept(response.data);
    } catch {
      if (!signal?.aborted && attempt === requestVersion.current) setLoadError(true);
    }
  }, [accept, endpoint, approvalId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (approvalId || !review || !['queued', 'running'].includes(review.status)) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => void load(controller.signal), 4500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [approvalId, load, review]);

  const submit = async (body: ReviewCommand) => {
    if (commandLock.current || approvalId) return false;
    commandLock.current = true;
    setSaving(true);
    setNotice(null);
    try {
      const result = await api.post<SourceReview>(endpoint, body);
      accept(result.data);
      setPending(null);
      setConflictInput(null);
      return true;
    } catch (error) {
      const status = responseStatus(error);
      if (status === 409) {
        const code = reviewErrorCode(error);
        const invalidAnchor = code === 'source_review_quote_not_unique';
        const overlapping = code === 'source_review_overlapping_or_stale_edit';
        setNotice(invalidAnchor ? 'invalidAnchor' : overlapping ? 'overlapping' : 'conflict');
        if (!invalidAnchor && !overlapping && (body.reason || body.replacement)) setConflictInput(body);
        setPending(null);
        await load();
      } else if (!status || status >= 500) {
        setNotice('unknown');
        setPending(body);
      } else {
        setNotice('error');
        setPending(null);
      }
      return false;
    } finally {
      commandLock.current = false;
      setSaving(false);
    }
  };

  const action = (args: Action) => review && !pending
    ? submit({ ...args, expected_revision: review.revision, request_id: crypto.randomUUID() })
    : Promise.resolve(false);
  const question = review?.questions.find((item) => item.id === selected) ?? review?.questions.find((item) => !item.resolution)
    ?? review?.questions[0];
  const open = review?.questions.filter((item) => !item.resolution).length ?? 0;
  const readOnly = Boolean(approvalId) || review?.status !== 'in_review';
  const disabled = saving || Boolean(pending);
  const showQuestion = (item: string) => {
    if (question?.id !== item) {
      select(item);
      setReason('');
      setReplacement('');
      setAnchor('');
      setDecision('replace');
    }
    requestAnimationFrame(() => detail.current?.focus());
  };
  const stamp = (value: string) => new Date(value).toLocaleString(lang === 'kk' ? 'kk-KZ' : lang === 'en' ? 'en-GB' : 'ru-RU');
  const range = pageInput ?? {
    first: review?.pages ? String(review.pages.first_page) : '',
    last: review?.pages ? String(review.pages.last_page) : '',
  };
  const usePages = Boolean(range.first || range.last);
  const firstPage = Number(range.first);
  const lastPage = Number(range.last);
  const validPages = !usePages || (Number.isInteger(firstPage) && Number.isInteger(lastPage)
    && firstPage >= 1 && lastPage >= firstPage && lastPage <= 10000);
  const failureMessage = review?.error === 'direct_source_pdf_range_invalid' ? copy.rangeFailure
    : review?.error === 'direct_source_pptx_ocr_required' ? copy.presentationOcrRequired
    : review?.error === 'source_review_provider_unavailable' ? copy.providerFailure
    : review?.error === 'source_review_provider_outcome_unknown' ? copy.providerOutcomeUnknown
    : review?.error === 'source_review_timeout' ? copy.timeoutFailure
    : review?.error === 'source_review_invalid_response' || review?.error?.startsWith('source_review_clue_disposition_') ? copy.responseFailure
    : review?.error?.startsWith('direct_source_') || review?.error === 'source_review_extraction_incomplete' ? copy.protected
    : review?.error === 'source_review_analysis_failed' ? copy.analysisFailure : copy.recovery;

  const downloadOriginal = async () => {
    setDownloadStatus('loading');
    try {
      const { data } = await api.get<Blob>(`/v1/documents/${encodeURIComponent(id)}/download`, { responseType: 'blob' });
      const url = URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = `document-${id}.pdf`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloadStatus('idle');
    } catch {
      setDownloadStatus('failed');
    }
  };

  return <WorkspacePage id="source-editorial-review" title={copy.title}>
    <Link className="inline-flex text-sm text-primary underline underline-offset-4"
      href={courseDocuments.length ? generationHref : '/documents'}>
      {courseDocuments.length ? copy.returnToCourse : copy.documents}
    </Link>
    {loadError && <WorkspacePanel bodyClassName="space-y-3" role="alert">
      <p>{copy.loadError}</p><Button variant="outline" onClick={() => void load()}>{copy.readAgain}</Button>
    </WorkspacePanel>}
    {!review && !loadError && <p role="status">{copy.loading}</p>}
    {review && <>
      <WorkspacePanel bodyClassName="space-y-3">
        <h2 className="break-words text-lg font-semibold">{review.title}</h2>
        <p className="text-sm text-muted-foreground">{copy.version} {review.document_version} · {copy.revision} {review.revision}</p>
        <p role="status" className="text-sm font-medium">{copy.statusLabels[review.status]}</p>
        {['not_started', 'failed', 'interrupted'].includes(review.status) && !approvalId && <>
          <p className="text-sm">{review.status === 'not_started' ? copy.startHint : failureMessage}</p>
          {review.error && /^[a-z0-9_]{2,100}$/.test(review.error) && <code className="break-all text-xs text-muted-foreground">{review.error}</code>}
          {review.pdf && <fieldset className="space-y-2 rounded-xl border border-border p-3">
            <legend className="px-1 text-sm font-medium">{copy.pagesTitle}</legend>
            <p className="text-xs text-muted-foreground">{copy.pagesHint}</p>
            <div className="flex flex-wrap items-end gap-2">
              <label className="block text-sm">{copy.firstPage}
                <input type="number" min={1} max={10000} value={range.first} onChange={event => setPageInput({ ...range, first: event.target.value })}
                  className={field + ' mt-1 block w-24'} /></label>
              <label className="block text-sm">{copy.lastPage}
                <input type="number" min={1} max={10000} value={range.last} onChange={event => setPageInput({ ...range, last: event.target.value })}
                  className={field + ' mt-1 block w-24'} /></label>
              <Button variant="outline" disabled={downloadStatus === 'loading'} onClick={() => void downloadOriginal()}>{copy.downloadOriginal}</Button>
            </div>
            {!validPages && <p role="status" className="text-sm text-destructive">{copy.pagesInvalid}</p>}
            {downloadStatus === 'failed' && <p role="alert" className="text-sm text-destructive">{copy.loadError}</p>}
          </fieldset>}
          <Button disabled={disabled || !validPages} onClick={() => void action({
            action: 'start', ...(review.pdf && usePages ? { pages: { first_page: firstPage, last_page: lastPage } } : {}),
          })}>{review.status === 'not_started' ? copy.check : copy.retry}</Button>
        </>}
        {review.pages && <p className="text-sm text-muted-foreground">{copy.chosenPages}: {review.pages.first_page}–{review.pages.last_page}</p>}
        {['queued', 'running'].includes(review.status) && <p className="text-sm text-muted-foreground">{copy.startHint}</p>}
        {review.approval && <div className="flex flex-wrap items-center gap-3">
          <p className="w-full text-sm">{copy.approved} · {stamp(review.approval.created_at)}. {copy.afterApproval}</p>
          {!approvalId && <>
            <Link className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground" href={generationHref}>{copy.generate}</Link>
            <Link className="text-sm text-primary underline" href={sourceReviewHref(id, review.approval.approval_id)}>{copy.preview}</Link>
            <Button variant="outline" disabled={disabled} onClick={() => void action({ action: 'reopen' })}>{copy.reopen}</Button>
          </>}
        </div>}
      </WorkspacePanel>
      {notice && <WorkspacePanel role="alert" bodyClassName="space-y-2">
        <p>{copy[notice]}</p>
        {conflictInput && <details open><summary>{copy.savedDraft}</summary>
          <p className={code}>{[conflictInput.replacement, conflictInput.quote, conflictInput.reason].filter(Boolean).join('\n')}</p>
        </details>}
        {pending && <Button variant="outline" disabled={saving} onClick={() => void submit(pending)}>{copy.repeatCommand}</Button>}
      </WorkspacePanel>}
      {review.original_text && <>
        <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <WorkspacePanel bodyClassName="space-y-3">
            <h2 className="font-semibold">{copy.list}</h2>
            <p className="text-sm text-muted-foreground">{copy.openCount}: {open}</p>
            {review.questions.length === 0 ? <p className="text-sm">{copy.noQuestions}</p> :
              <ol className="space-y-2">{review.questions.map((item, index) => <li key={item.id}>
                <button type="button" onClick={() => showQuestion(item.id)} aria-current={item.id === question?.id}
                  className={`w-full break-words rounded-lg border px-3 py-2 text-left text-sm focus-visible:ring-2 focus-visible:ring-ring ${item.id === question?.id ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'}`}>
                  <span className="block font-medium">{index + 1}. {item.quote.length > 120 ? item.quote.slice(0, 120) + '…' : item.quote}</span>
                  <span className="text-xs text-muted-foreground">{item.resolution ? copy.closed : copy.open}</span>
                </button>
              </li>)}</ol>}
          </WorkspacePanel>
          {question && <WorkspacePanel bodyClassName="space-y-4">
            <h2 ref={detail} tabIndex={-1} className="font-semibold focus-visible:ring-2 focus-visible:ring-ring">{copy.question}</h2>
            <p className="whitespace-pre-wrap break-words text-sm">{question.reason}</p>
            <div><p className="mb-1 text-xs font-medium text-muted-foreground">{question.start == null ? copy.unbound : copy.quote}</p>
              <blockquote className={code}>{question.quote}</blockquote></div>
            {question.resolution && <div className="space-y-2 text-sm">
              <p className="font-medium">{copy.closed}</p>
              <p className={code}>{question.resolution.after}</p>
              <p>{question.resolution.reason}</p>
            </div>}
            {!readOnly && <form className="space-y-3" onSubmit={async (event) => {
              event.preventDefault();
              const args: Action = question.resolution
                ? { action: 'reopen_issue', item_id: question.id, reason }
                : { action: 'resolve', item_id: question.id, reason, decision,
                    ...(decision === 'replace' ? { replacement, ...(question.start == null ? { quote: anchor } : {}) } : {}) };
              if (await action(args)) { setReason(''); setReplacement(''); setAnchor(''); }
            }}>
              {!question.resolution && <>
                <fieldset className="flex flex-wrap gap-4 text-sm">
                  <label className="flex gap-2"><input type="radio" checked={decision === 'replace'} onChange={() => setDecision('replace')} />{copy.replace}</label>
                  <label className="flex gap-2"><input type="radio" checked={decision === 'keep'} onChange={() => setDecision('keep')} />{copy.keep}</label>
                </fieldset>
                {decision === 'replace' && <>
                  {question.start == null && <label className="block space-y-1 text-sm"><span>{copy.anchor}</span>
                    <textarea className={field} value={anchor} onChange={(e) => setAnchor(e.target.value)} required maxLength={5000} /></label>}
                  <label className="block space-y-1 text-sm"><span>{copy.replacement}</span>
                    <textarea className={field} value={replacement} onChange={(e) => setReplacement(e.target.value)} required maxLength={5000} rows={4} /></label>
                </>}
              </>}
              <label className="block space-y-1 text-sm"><span>{copy.reason}</span>
                <textarea className={field} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={1500} rows={2} placeholder={copy.reasonHint} />
              </label>
              <Button type="submit" disabled={disabled}>{question.resolution ? copy.reopenIssue : copy.save}</Button>
            </form>}
          </WorkspacePanel>}
        </div>
        {!readOnly && <WorkspacePanel bodyClassName="space-y-3">
          <h2 className="font-semibold">{copy.manualTitle}</h2>
          <p className="text-sm text-muted-foreground">{copy.manualHint}</p>
          {manualOpen ? <form className="space-y-3" onSubmit={async (event) => {
            event.preventDefault();
            if (await action({ action: 'add_edit', ...manual })) {
              setManual({ quote: '', replacement: '', reason: '' });
              setManualOpen(false);
            }
          }}>
            <label className="block space-y-1 text-sm"><span>{copy.anchor}</span>
              <textarea className={field} value={manual.quote} onChange={(e) => setManual({ ...manual, quote: e.target.value })} required maxLength={5000} rows={2} /></label>
            <label className="block space-y-1 text-sm"><span>{copy.replacement}</span>
              <textarea className={field} value={manual.replacement} onChange={(e) => setManual({ ...manual, replacement: e.target.value })} required maxLength={5000} rows={3} /></label>
            <label className="block space-y-1 text-sm"><span>{copy.reason}</span>
              <textarea className={field} value={manual.reason} onChange={(e) => setManual({ ...manual, reason: e.target.value })} required minLength={3} maxLength={1500} rows={2} /></label>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={disabled}>{copy.saveManual}</Button>
              <Button type="button" variant="outline" disabled={disabled} onClick={() => {
                setManual({ quote: '', replacement: '', reason: '' });
                setManualOpen(false);
              }}>{copy.hideManual}</Button>
            </div>
          </form> : <Button variant="outline" disabled={disabled} onClick={() => setManualOpen(true)}>{copy.addManual}</Button>}
        </WorkspacePanel>}
        <WorkspacePanel bodyClassName="space-y-3">
          <h2 className="font-semibold">{copy.automatic}</h2>
          {review.automatic.length === 0 && <p className="text-sm text-muted-foreground">{copy.noEdits}</p>}
          {review.automatic.map((change) => <details key={change.id} className="rounded-lg border border-border p-3">
            <summary className="cursor-pointer break-words text-sm">{change.before} → {change.after} {change.undone ? ` · ${copy.undone}` : ''}</summary>
            <p className="mt-2 text-sm">{change.reason}</p>
            {!readOnly && !change.undone && (undoItem === change.id
              ? <form className="mt-2 space-y-2" onSubmit={async (e) => {
                e.preventDefault();
                if (await action({ action: 'undo_auto', item_id: change.id, reason: undoReason })) setUndoItem(null);
              }}><label className="block text-sm">{copy.reason}<textarea className={field} value={undoReason} onChange={(e) => setUndoReason(e.target.value)} minLength={3} maxLength={1500} required /></label>
                <Button type="submit" disabled={disabled}>{copy.undo}</Button></form>
              : <Button className="mt-2" variant="outline" disabled={disabled} onClick={() => { setUndoReason(''); setUndoItem(change.id); }}>{copy.undo}</Button>)}
          </details>)}
        </WorkspacePanel>
        <WorkspacePanel bodyClassName="space-y-3">
          <details open={Boolean(approvalId)}><summary className="cursor-pointer font-semibold">{copy.working}</summary>
            <pre className={`mt-3 max-h-[34rem] overflow-auto ${code}`}>{review.working_text}</pre></details>
          <details><summary className="cursor-pointer font-semibold">{copy.original}</summary>
            <pre className={`mt-3 max-h-[34rem] overflow-auto ${code}`}>{review.original_text}</pre></details>
          {!readOnly && <div className="space-y-2"><Button disabled={disabled || open > 0 || Boolean(manual.quote || manual.replacement || manual.reason)} onClick={() => void action({ action: 'approve' })}>{copy.approve}</Button>
            {open > 0 && <p className="text-sm text-muted-foreground">{copy.blocking}</p>}
            {(manual.quote || manual.replacement || manual.reason) && <p className="text-sm text-muted-foreground">{copy.unsavedManual}</p>}</div>}
        </WorkspacePanel>
        <WorkspacePanel bodyClassName="space-y-3">
          <h2 className="font-semibold">{copy.history}</h2>
          {review.journal.length === 0 ? <p className="text-sm">{copy.noEdits}</p> : <ol className="space-y-2">
            {[...review.journal].reverse().map((entry) => <li key={entry.id + ':' + (entry.item_id ?? '')}>
              <details className="rounded-lg border border-border p-3">
                <summary className="cursor-pointer text-sm">{copy.eventLabels[entry.kind as keyof typeof copy.eventLabels] ?? entry.kind} · {copy.revision} {entry.revision} · {stamp(entry.created_at)}</summary>
                <p className="mt-2 break-words text-xs text-muted-foreground">{entry.actor_id ? copy.reviewer + ': ' + entry.actor_id : copy.automated}</p>
                {entry.before && <p className={`mt-2 ${code}`}>{copy.before}: {entry.before}{'\n'}{copy.after}: {entry.after}</p>}
                {entry.reason && <p className="mt-2 break-words text-sm">{entry.reason}</p>}
              </details>
            </li>)}
          </ol>}
        </WorkspacePanel>
      </>}
    </>}
  </WorkspacePage>;
}
