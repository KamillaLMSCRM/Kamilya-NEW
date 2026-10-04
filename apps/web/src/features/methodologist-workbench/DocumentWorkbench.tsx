"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';
import type { DocumentCatalogItem, DocumentCatalogResponse } from '@/lib/documentCatalog';
import {
  confirmDocumentPlan, interpretDocument, loadDocumentPlan, previewDocumentPlan,
  type AIGenerateRequest, type DocumentCandidate, type DocumentPlan, type DocumentPreview,
} from '@/lib/documentWorkbench';

const enabled = () => process.env.NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED === 'true';
const initialCandidate: DocumentCandidate = {
  target_audience: '', course_intent: '', course_format: 'automatic', language: 'ru', source_strategy: 'single_topic', combination_goal: '',
};

export default function DocumentWorkbench() {
  const role = useAuthStore((state) => state.user?.role);
  const sessionKey = useAuthStore((state) => `${state.accessToken ?? ''}:${state.user?.user_id ?? ''}`);
  if (!enabled() || role !== 'methodologist') return null;
  return <DocumentWorkbenchInner key={`${sessionKey}:${role}`} />;
}

function DocumentWorkbenchInner() {
  const [documents, setDocuments] = useState<DocumentCatalogItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [instruction, setInstruction] = useState('');
  const [candidate, setCandidate] = useState<DocumentCandidate>(initialCandidate);
  const [languageConfirmed, setLanguageConfirmed] = useState(false);
  const [reuseReason, setReuseReason] = useState<AIGenerateRequest['reuse_reason']>(null);
  const [plan, setPlan] = useState<DocumentPlan | null>(null);
  const [job, setJob] = useState<AIGenerationJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const epoch = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const catalogController = useRef<AbortController | null>(null);
  const polling = useRef(false);

  const clearStale = useCallback(() => {
    requestController.current?.abort();
    requestController.current = null;
    epoch.current += 1;
    setPending(false);
    setUploading(false);
    setUploadStatus(null);
    setError(null);
    setLanguageConfirmed(false);
    setPlan(null);
    setJob(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('document_plan');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }, []);

  const fetchDocuments = useCallback(async (signal?: AbortSignal) => {
    const response = await api.get<DocumentCatalogResponse>('/v1/documents/catalog?lifecycle_status=active&limit=100', signal ? { signal } : undefined);
    if (!mounted.current || signal?.aborted) return response.data.items;
    setDocuments(response.data.items.filter((item) => item.lifecycle_status === 'active' && (item.index.status === 'ready' || item.index.status === 'partial')));
    return response.data.items;
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    catalogController.current = controller;
    void fetchDocuments(controller.signal).catch((cause) => { if (mounted.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError('Не удалось загрузить каталог документов.'); });
    return () => { mounted.current = false; controller.abort(); catalogController.current?.abort(); requestController.current?.abort(); };
  }, [fetchDocuments]);

  useEffect(() => {
    const planId = new URLSearchParams(window.location.search).get('document_plan');
    if (!planId) return;
    const current = ++epoch.current;
    const controller = new AbortController();
    requestController.current = controller;
    setPending(true);
    void loadDocumentPlan(planId, controller.signal).then((loaded) => {
      if (!mounted.current || current !== epoch.current) return;
      setPlan(loaded);
      if (loaded.state === 'submitted') setJob(loaded.job);
      else { setInstruction(loaded.instruction); setCandidate(loaded.generation); setLanguageConfirmed(loaded.generation.language_confirmed); setReuseReason(loaded.generation.reuse_reason ?? null); setSelected(loaded.generation.documents); }
    }).catch((cause) => {
      if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError('Не удалось восстановить план документа.');
    }).finally(() => { if (mounted.current && current === epoch.current) setPending(false); });
    return () => { controller.abort(); epoch.current += 1; };
  }, []);

  useEffect(() => {
    if (!job || ['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status)) return;
    const controller = new AbortController();
    const refresh = async () => {
      if (polling.current || controller.signal.aborted || !mounted.current) return;
      polling.current = true;
      try {
        const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${encodeURIComponent(job.id)}`, { signal: controller.signal });
        if (!controller.signal.aborted && mounted.current && response.data.id === job.id) setJob(response.data);
      } catch { /* transient polling errors leave the factual last state visible */ }
      finally { polling.current = false; }
    };
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [job]);

  const toggleDocument = (id: string) => {
    clearStale();
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : current.length >= 5 ? current : [...current, id]);
  };

  const upload = async (file: File) => {
    const current = ++epoch.current;
    const controller = new AbortController();
    requestController.current?.abort(); requestController.current = controller;
    setUploading(true); setUploadStatus('Загрузка документа…'); setError(null);
    const form = new FormData(); form.append('file', file); form.append('title', file.name.replace(/\.[^/.]+$/, ''));
    try {
      const response = await api.post<{ id: string; indexing_job_id?: string | null }>('/v1/documents/upload', form, { headers: { 'Content-Type': 'multipart/form-data' }, signal: controller.signal });
      if (!mounted.current || current !== epoch.current) return;
      const jobId = response.data.indexing_job_id;
      if (jobId) {
        let ready = false;
        let indexingFailed = false;
        for (let attempt = 0; attempt < 20 && !controller.signal.aborted; attempt += 1) {
          setUploadStatus(`Индексация документа… (${attempt + 1}/20)`);
          const statusResponse: { data: AIGenerationJob } = await api.get<AIGenerationJob>(`/v1/ai/jobs/${encodeURIComponent(jobId)}`, { signal: controller.signal });
          if (!mounted.current || current !== epoch.current || controller.signal.aborted) return;
          if (statusResponse.data.id !== jobId) throw new Error('Indexing job identity mismatch');
          await fetchDocuments(controller.signal);
          if (!mounted.current || current !== epoch.current || controller.signal.aborted) return;
          if (['completed', 'failed', 'cancelled', 'interrupted'].includes(statusResponse.data.status)) {
            ready = statusResponse.data.status === 'completed';
            if (!ready) { indexingFailed = true; setError(statusResponse.data.message || 'Индексация документа завершилась с ошибкой.'); }
            break;
          }
          await new Promise<void>((resolve) => window.setTimeout(resolve, 3000));
        }
        if (!ready && !indexingFailed && mounted.current && current === epoch.current && !controller.signal.aborted) setError('Индексация не завершилась в допустимое время.');
      } else await fetchDocuments(controller.signal);
      if (mounted.current && current === epoch.current) setUploadStatus(null);
    } catch (cause: any) { if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError('Не удалось загрузить документ.'); }
    finally { if (mounted.current && current === epoch.current) setUploading(false); }
  };

  const generation = (): AIGenerateRequest => ({ documents: selected, ...candidate, language_confirmed: languageConfirmed, reuse_reason: reuseReason });
  const preview = async () => {
    if (!instruction.trim() || !candidate.course_intent.trim() || selected.length < 1 || selected.length > 5 || pending) return;
    const current = ++epoch.current; const controller = new AbortController(); requestController.current = controller;
    setPending(true); setError(null); setJob(null); setPlan(null);
    try {
      const result = await previewDocumentPlan({ instruction, generation: generation() }, controller.signal);
      if (mounted.current && current === epoch.current) { setPlan(result); window.history.replaceState(window.history.state, '', `${window.location.pathname}?document_plan=${encodeURIComponent(result.plan_id)}`); }
    } catch (cause: any) { if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError('Не удалось подготовить предварительный план.'); }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  const confirm = async () => {
    if (!plan || plan.state !== 'preview_ready' || pending) return;
    const current = ++epoch.current; setPending(true); setError(null);
    try {
      const result = await confirmDocumentPlan(plan);
      if (mounted.current && current === epoch.current) { setPlan(result); setJob(result.job); }
    } catch (cause: any) { if (mounted.current && current === epoch.current) setError(cause?.response?.status === 409 ? 'План устарел или уже подтверждён. Обновите его.' : 'Не удалось подтвердить план.'); }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  const interpret = async () => {
    if (!instruction.trim() || pending) return;
    clearStale();
    const current = ++epoch.current; const controller = new AbortController(); requestController.current = controller;
    setPending(true); setError(null);
    try {
      const result = await interpretDocument(instruction, candidate.language, controller.signal);
      if (mounted.current && current === epoch.current && result.state === 'interpreted') { setCandidate((value) => ({ ...value, ...result.candidate })); setLanguageConfirmed(false); setPlan(null); }
      if (mounted.current && current === epoch.current && result.state === 'clarification_needed') { setPlan(null); setError('Уточните описание документа и попробуйте снова.'); }
    } catch (cause: any) { if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError('Интерпретация временно недоступна.'); }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  return <Card className="mt-6 border-primary/30">
    <CardHeader><CardTitle>Документ → черновик курса</CardTitle><p className="text-sm text-muted-foreground">Выберите до пяти проверенных источников, проверьте параметры и подтвердите один неизменяемый план.</p></CardHeader>
    <CardContent className="space-y-4">
      <label className="block text-sm font-medium">Загрузить документ<input type="file" className="mt-2 block w-full text-sm" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''; }} /></label>{uploadStatus && <p role="status" className="text-sm text-muted-foreground">{uploadStatus}</p>}
      <div className="space-y-2"><p className="text-sm font-medium">Источники ({selected.length}/5)</p>{documents.length === 0 ? <p className="text-sm text-muted-foreground">Нет готовых документов.</p> : documents.map((document) => <label key={document.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.includes(document.id)} onChange={() => toggleDocument(document.id)} disabled={!selected.includes(document.id) && selected.length >= 5} />{document.title} <span className="text-xs text-muted-foreground">v{document.version} · {document.index.status}</span></label>)}</div>
      <label className="block text-sm font-medium">Инструкция<textarea value={instruction} onChange={(event) => { clearStale(); setInstruction(event.target.value); }} maxLength={4000} rows={3} className="mt-2 w-full rounded border p-2" /></label><p className="text-xs text-muted-foreground">Инструкция сохраняется в плане как исходный след. Для генерации обязательно укажите редактируемую цель курса ниже; интерпретация инструкции необязательна.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Аудитория<input value={candidate.target_audience} onChange={(event) => { clearStale(); setCandidate({ ...candidate, target_audience: event.target.value }); }} maxLength={2000} className="mt-1 w-full rounded border p-2" /></label>
        <label className="text-sm">Цель курса<input value={candidate.course_intent} onChange={(event) => { clearStale(); setCandidate({ ...candidate, course_intent: event.target.value }); }} maxLength={2000} className="mt-1 w-full rounded border p-2" /></label>
        <label className="text-sm">Язык<select value={candidate.language} onChange={(event) => { clearStale(); setCandidate({ ...candidate, language: event.target.value as DocumentCandidate['language'] }); }} className="mt-1 w-full rounded border p-2"><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option></select></label>
        <label className="text-sm">Формат<select value={candidate.course_format} onChange={(event) => { clearStale(); setCandidate({ ...candidate, course_format: event.target.value as DocumentCandidate['course_format'] }); }} className="mt-1 w-full rounded border p-2"><option value="automatic">Автоматический</option><option value="brief">Краткий</option><option value="standard">Стандартный</option><option value="detailed">Подробный</option></select></label>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={candidate.source_strategy === 'intentional_combination'} onChange={(event) => { clearStale(); setCandidate({ ...candidate, source_strategy: event.target.checked ? 'intentional_combination' : 'single_topic' }); }} />Объединить источники с общей целью</label>
      {candidate.source_strategy === 'intentional_combination' && <textarea value={candidate.combination_goal} onChange={(event) => { clearStale(); setCandidate({ ...candidate, combination_goal: event.target.value }); }} maxLength={2000} rows={2} placeholder="Общая учебная цель (не менее 20 символов)" className="w-full rounded border p-2 text-sm" />}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={languageConfirmed} onChange={(event) => { clearStale(); setLanguageConfirmed(event.target.checked); }} />Я подтверждаю язык будущего курса</label>
      <label className="text-sm">Причина повторного использования источника<select value={reuseReason ?? ''} onChange={(event) => { clearStale(); setReuseReason((event.target.value || null) as AIGenerateRequest['reuse_reason']); }} className="mt-1 w-full rounded border p-2"><option value="">Не указана</option><option value="different_audience">Другая аудитория</option><option value="different_language">Другой язык</option><option value="different_depth">Другая глубина</option><option value="updated_revision">Обновлённая версия</option><option value="recurring_training">Повторное обучение</option><option value="other">Другое</option></select></label>
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => void interpret()} disabled={pending || !instruction.trim()}>Интерпретировать</Button><Button type="button" onClick={() => void preview()} disabled={pending || !instruction.trim() || !candidate.course_intent.trim() || selected.length < 1}>Подготовить план</Button></div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {plan?.state === 'preview_ready' && <PreviewCard preview={plan} pending={pending} onConfirm={() => void confirm()} />}
      {job && <JobCard job={job} />}
    </CardContent>
  </Card>;
}

function PreviewCard({ preview, pending, onConfirm }: { preview: DocumentPreview; pending: boolean; onConfirm: () => void }) {
  const generation = preview.generation;
  return <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm"><p className="font-medium">План готов · ревизия {preview.revision}</p><dl className="mt-2 grid gap-1 sm:grid-cols-2"><div><dt className="text-xs text-muted-foreground">Аудитория</dt><dd>{generation.target_audience || 'не указана'}</dd></div><div><dt className="text-xs text-muted-foreground">Цель</dt><dd>{generation.course_intent || 'не указана'}</dd></div><div><dt className="text-xs text-muted-foreground">Язык</dt><dd>{generation.language}</dd></div><div><dt className="text-xs text-muted-foreground">Формат</dt><dd>{generation.course_format}</dd></div><div><dt className="text-xs text-muted-foreground">Объединение</dt><dd>{generation.source_strategy === 'intentional_combination' ? generation.combination_goal : 'нет'}</dd></div><div><dt className="text-xs text-muted-foreground">Повторное использование</dt><dd>{generation.reuse_reason || 'не подтверждено'}</dd></div></dl><p className="mt-2">Источники: {preview.sources.map((source) => `${source.title} v${source.version}`).join(', ')}</p><p>Действителен до: {new Date(preview.expires_at).toLocaleString('ru-RU')}</p><p className="text-xs text-muted-foreground">Отпечаток: {preview.fingerprint}</p><Button className="mt-3" type="button" onClick={onConfirm} disabled={pending}>Подтвердить и запустить</Button></div>;
}

function JobCard({ job }: { job: AIGenerationJob }) {
  const done = job.status === 'completed' && job.course_id;
  const errors = Array.isArray((job as AIGenerationJob & { errors?: Array<string | { message?: string }> }).errors)
    ? (job as AIGenerationJob & { errors: Array<string | { message?: string }> }).errors.map((item: string | { message?: string }) => typeof item === 'string' ? item : item.message || JSON.stringify(item)).join('; ')
    : '';
  return <div className="rounded border p-3 text-sm" role="status" aria-live="polite"><p className="font-medium">Задача: {job.status}</p><p>{job.message || `Этап: ${job.stage || 'не указан'}`} · прогресс {job.progress}%</p>{errors && <p role="alert" className="mt-1 text-destructive">{errors}</p>}{done && <div className="mt-2 flex gap-3"><a className="text-primary underline" href={`/courses/${job.course_id}/edit`}>Открыть курс</a><a className="text-primary underline" href={`/ai/generate?job_id=${encodeURIComponent(job.id)}`}>Открыть генерацию</a></div>}</div>;
}
