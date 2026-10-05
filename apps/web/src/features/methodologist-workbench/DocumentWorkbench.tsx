"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
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

type DocumentLocale = 'ru' | 'kk' | 'en';
const DOCUMENT_COPY = {
  ru: { title: 'Документ → черновик курса', description: 'Выберите до пяти проверенных источников, проверьте параметры и подтвердите один неизменяемый план.', upload: 'Загрузить документ', uploading: 'Загрузка документа…', indexing: 'Индексация документа…', catalogError: 'Не удалось загрузить каталог документов.', uploadError: 'Не удалось загрузить документ.', indexingError: 'Индексация документа завершилась с ошибкой.', indexingTimeout: 'Индексация не завершилась в допустимое время.', sources: 'Источники', empty: 'Нет готовых документов.', instruction: 'Инструкция', instructionHelp: 'Инструкция сохраняется в плане как исходный след. Для генерации обязательно укажите редактируемую цель курса ниже; интерпретация инструкции необязательна.', audience: 'Аудитория', goal: 'Цель курса', language: 'Язык', format: 'Формат', languages: { ru: 'Русский', kk: 'Қазақша', en: 'English' }, formats: { automatic: 'Автоматический', brief: 'Краткий', standard: 'Стандартный', detailed: 'Подробный' }, combine: 'Объединить источники с общей целью', combinationPlaceholder: 'Общая учебная цель (не менее 20 символов)', confirmLanguage: 'Я подтверждаю язык будущего курса', reuse: 'Причина повторного использования источника', reuseOptions: { '': 'Не указана', different_audience: 'Другая аудитория', different_language: 'Другой язык', different_depth: 'Другая глубина', updated_revision: 'Обновлённая версия', recurring_training: 'Повторное обучение', other: 'Другое' }, interpret: 'Интерпретировать', prepare: 'Подготовить план', confirm: 'Подтвердить и запустить', previewError: 'Не удалось подготовить предварительный план.', restoreError: 'Не удалось восстановить план документа.', confirmError: 'Не удалось подтвердить план.', stalePlan: 'План устарел или уже подтверждён. Обновите его.', clarify: 'Уточните описание документа и попробуйте снова.', interpretationError: 'Интерпретация временно недоступна.', previewReady: 'План готов · ревизия', audienceMissing: 'не указана', combinationNone: 'нет', reuseMissing: 'не подтверждено', sourcesList: 'Источники:', validUntil: 'Действителен до:', fingerprint: 'Отпечаток:', task: 'Задача:', stage: 'Этап:', progress: 'прогресс', noStage: 'не указан', openCourse: 'Открыть курс', openGeneration: 'Открыть генерацию', indexStatus: { ready: 'готов', partial: 'частично' } },
  kk: { title: 'Құжат → курс жобасы', description: 'Беске дейін тексерілген дереккөзді таңдап, параметрлерді тексеріп, өзгермейтін жоспарды растаңыз.', upload: 'Құжат жүктеу', uploading: 'Құжат жүктелуде…', indexing: 'Құжат индекстелуде…', catalogError: 'Құжаттар каталогын жүктеу мүмкін болмады.', uploadError: 'Құжатты жүктеу мүмкін болмады.', indexingError: 'Құжатты индекстеу қатемен аяқталды.', indexingTimeout: 'Индекстеу рұқсат етілген уақытта аяқталмады.', sources: 'Дереккөздер', empty: 'Дайын құжаттар жоқ.', instruction: 'Нұсқаулық', instructionHelp: 'Нұсқаулық жоспарға бастапқы із ретінде сақталады. Генерация үшін төменде өзгертілетін курс мақсатын көрсетіңіз; нұсқаулықты талдау міндетті емес.', audience: 'Аудитория', goal: 'Курс мақсаты', language: 'Тіл', format: 'Пішім', languages: { ru: 'Орысша', kk: 'Қазақша', en: 'Ағылшынша' }, formats: { automatic: 'Автоматты', brief: 'Қысқа', standard: 'Стандартты', detailed: 'Толық' }, combine: 'Дереккөздерді ортақ мақсатпен біріктіру', combinationPlaceholder: 'Ортақ оқу мақсаты (кемінде 20 таңба)', confirmLanguage: 'Болашақ курс тілін растаймын', reuse: 'Дереккөзді қайта пайдалану себебі', reuseOptions: { '': 'Көрсетілмеген', different_audience: 'Басқа аудитория', different_language: 'Басқа тіл', different_depth: 'Басқа тереңдік', updated_revision: 'Жаңартылған нұсқа', recurring_training: 'Қайта оқыту', other: 'Басқа' }, interpret: 'Талдау', prepare: 'Жоспар дайындау', confirm: 'Растау және іске қосу', previewError: 'Алдын ала жоспарды дайындау мүмкін болмады.', restoreError: 'Құжат жоспарын қалпына келтіру мүмкін болмады.', confirmError: 'Жоспарды растау мүмкін болмады.', stalePlan: 'Жоспар ескірген немесе расталған. Жаңартыңыз.', clarify: 'Құжат сипаттамасын нақтылап, қайталап көріңіз.', interpretationError: 'Талдау уақытша қолжетімсіз.', previewReady: 'Жоспар дайын · нұсқа', audienceMissing: 'көрсетілмеген', combinationNone: 'жоқ', reuseMissing: 'расталмаған', sourcesList: 'Дереккөздер:', validUntil: 'Жарамды мерзімі:', fingerprint: 'Бақылау ізі:', task: 'Тапсырма:', stage: 'Кезең:', progress: 'ілгерілеу', noStage: 'көрсетілмеген', openCourse: 'Курсты ашу', openGeneration: 'Генерацияны ашу', indexStatus: { ready: 'дайын', partial: 'ішінара' } },
  en: { title: 'Document → course draft', description: 'Choose up to five verified sources, review the parameters, and confirm one immutable plan.', upload: 'Upload document', uploading: 'Uploading document…', indexing: 'Indexing document…', catalogError: 'Could not load the document catalog.', uploadError: 'Could not upload the document.', indexingError: 'Document indexing failed.', indexingTimeout: 'Indexing did not finish within the allowed time.', sources: 'Sources', empty: 'No ready documents.', instruction: 'Instruction', instructionHelp: 'The instruction is saved in the plan as the original trace. For generation, provide an editable course goal below; interpreting the instruction is optional.', audience: 'Audience', goal: 'Course goal', language: 'Language', format: 'Format', languages: { ru: 'Russian', kk: 'Kazakh', en: 'English' }, formats: { automatic: 'Automatic', brief: 'Brief', standard: 'Standard', detailed: 'Detailed' }, combine: 'Combine sources with a shared goal', combinationPlaceholder: 'Shared learning goal (at least 20 characters)', confirmLanguage: 'I confirm the future course language', reuse: 'Reason for reusing the source', reuseOptions: { '': 'Not specified', different_audience: 'Different audience', different_language: 'Different language', different_depth: 'Different depth', updated_revision: 'Updated revision', recurring_training: 'Recurring training', other: 'Other' }, interpret: 'Interpret', prepare: 'Prepare plan', confirm: 'Confirm and launch', previewError: 'Could not prepare the preview plan.', restoreError: 'Could not restore the document plan.', confirmError: 'Could not confirm the plan.', stalePlan: 'The plan is stale or already confirmed. Refresh it.', clarify: 'Clarify the document description and try again.', interpretationError: 'Interpretation is temporarily unavailable.', previewReady: 'Plan ready · revision', audienceMissing: 'not specified', combinationNone: 'none', reuseMissing: 'not confirmed', sourcesList: 'Sources:', validUntil: 'Valid until:', fingerprint: 'Fingerprint:', task: 'Task:', stage: 'Stage:', progress: 'progress', noStage: 'not specified', openCourse: 'Open course', openGeneration: 'Open generation', indexStatus: { ready: 'ready', partial: 'partial' } },
} as const;
const localeOf = (lang: string): DocumentLocale => lang === 'kk' || lang === 'en' ? lang : 'ru';

export default function DocumentWorkbench() {
  const role = useAuthStore((state) => state.user?.role);
  const sessionKey = useAuthStore((state) => `${state.accessToken ?? ''}:${state.user?.user_id ?? ''}`);
  if (!enabled() || role !== 'methodologist') return null;
  return <DocumentWorkbenchInner key={`${sessionKey}:${role}`} />;
}

function DocumentWorkbenchInner() {
  const locale = localeOf(useLanguageStore((state) => state.lang));
  const ui = DOCUMENT_COPY[locale];
  const uiRef = useRef(ui);
  uiRef.current = ui;
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
  const [uploadStatus, setUploadStatus] = useState<'uploading' | 'indexing' | null>(null);
  const [indexAttempt, setIndexAttempt] = useState<number | null>(null);
  const epoch = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const uploadEpoch = useRef(0);
  const uploadController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const catalogController = useRef<AbortController | null>(null);
  const polling = useRef(false);

  const clearStale = useCallback(() => {
    requestController.current?.abort();
    requestController.current = null;
    epoch.current += 1;
    setPending(false);
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
    void fetchDocuments(controller.signal).catch((cause) => { if (mounted.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.catalogError); });
    return () => { mounted.current = false; controller.abort(); catalogController.current?.abort(); requestController.current?.abort(); uploadController.current?.abort(); };
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
      else {
        const restored = loaded.generation;
        setInstruction(loaded.instruction);
        setCandidate({
          target_audience: restored.target_audience, course_intent: restored.course_intent,
          course_format: restored.course_format, language: restored.language,
          source_strategy: restored.source_strategy, combination_goal: restored.combination_goal,
        });
        setLanguageConfirmed(restored.language_confirmed);
        setReuseReason(restored.reuse_reason ?? null);
        setSelected(restored.documents);
      }
    }).catch((cause) => {
      if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.restoreError);
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
    const current = ++uploadEpoch.current;
    const controller = new AbortController();
    uploadController.current?.abort(); uploadController.current = controller;
    setUploading(true); setUploadStatus('uploading'); setIndexAttempt(null); setError(null);
    const form = new FormData(); form.append('file', file); form.append('title', file.name.replace(/\.[^/.]+$/, ''));
    try {
      const response = await api.post<{ id: string; indexing_job_id?: string | null }>('/v1/documents/upload', form, { headers: { 'Content-Type': 'multipart/form-data' }, signal: controller.signal });
      if (!mounted.current || current !== uploadEpoch.current) return;
      const jobId = response.data.indexing_job_id;
      if (jobId) {
        let ready = false;
        let indexingFailed = false;
        for (let attempt = 0; attempt < 20 && !controller.signal.aborted; attempt += 1) {
          setUploadStatus('indexing'); setIndexAttempt(attempt + 1);
          const statusResponse: { data: AIGenerationJob } = await api.get<AIGenerationJob>(`/v1/ai/jobs/${encodeURIComponent(jobId)}`, { signal: controller.signal });
          if (!mounted.current || current !== uploadEpoch.current || controller.signal.aborted) return;
          if (statusResponse.data.id !== jobId) throw new Error('Indexing job identity mismatch');
          await fetchDocuments(controller.signal);
          if (!mounted.current || current !== uploadEpoch.current || controller.signal.aborted) return;
          if (['completed', 'failed', 'cancelled', 'interrupted'].includes(statusResponse.data.status)) {
            ready = statusResponse.data.status === 'completed';
            if (!ready) { indexingFailed = true; setError(statusResponse.data.message || uiRef.current.indexingError); }
            break;
          }
          await new Promise<void>((resolve) => window.setTimeout(resolve, 3000));
        }
        if (!ready && !indexingFailed && mounted.current && current === uploadEpoch.current && !controller.signal.aborted) setError(uiRef.current.indexingTimeout);
      } else await fetchDocuments(controller.signal);
      if (mounted.current && current === uploadEpoch.current) { setUploadStatus(null); setIndexAttempt(null); }
    } catch (cause: any) { if (mounted.current && current === uploadEpoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.uploadError); }
    finally { if (mounted.current && current === uploadEpoch.current) { uploadController.current = null; setUploading(false); } }
  };

  const generation = (): AIGenerateRequest => ({ ...candidate, documents: selected, language_confirmed: languageConfirmed, reuse_reason: reuseReason });
  const preview = async () => {
    if (!instruction.trim() || !candidate.course_intent.trim() || selected.length < 1 || selected.length > 5 || pending) return;
    const current = ++epoch.current; const controller = new AbortController(); requestController.current = controller;
    setPending(true); setError(null); setJob(null); setPlan(null);
    try {
      const result = await previewDocumentPlan({ instruction, generation: generation() }, controller.signal);
      if (mounted.current && current === epoch.current) { setPlan(result); window.history.replaceState(window.history.state, '', `${window.location.pathname}?document_plan=${encodeURIComponent(result.plan_id)}`); }
    } catch (cause: any) { if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.previewError); }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  const confirm = async () => {
    if (!plan || plan.state !== 'preview_ready' || pending) return;
    const current = ++epoch.current; setPending(true); setError(null);
    try {
      const result = await confirmDocumentPlan(plan);
      if (mounted.current && current === epoch.current) { setPlan(result); setJob(result.job); }
    } catch (cause: any) { if (mounted.current && current === epoch.current) setError(cause?.response?.status === 409 ? uiRef.current.stalePlan : uiRef.current.confirmError); }
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
      if (mounted.current && current === epoch.current && result.state === 'clarification_needed') { setPlan(null); setError(uiRef.current.clarify); }
    } catch (cause: any) { if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.interpretationError); }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  return <Card className="mt-6 border-primary/30">
    <CardHeader><CardTitle>{ui.title}</CardTitle><p className="text-sm text-muted-foreground">{ui.description}</p></CardHeader>
    <CardContent className="space-y-4">
      <label className="block text-sm font-medium">{ui.upload}<input type="file" className="mt-2 block w-full text-sm" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''; }} /></label>{uploadStatus && <p role="status" className="text-sm text-muted-foreground">{uploadStatus === 'uploading' ? ui.uploading : `${ui.indexing} (${indexAttempt}/20)`}</p>}
      <div className="space-y-2"><p className="text-sm font-medium">{ui.sources} ({selected.length}/5)</p>{documents.length === 0 ? <p className="text-sm text-muted-foreground">{ui.empty}</p> : documents.map((document) => <label key={document.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.includes(document.id)} onChange={() => toggleDocument(document.id)} disabled={!selected.includes(document.id) && selected.length >= 5} />{document.title} <span className="text-xs text-muted-foreground">v{document.version} · {ui.indexStatus[document.index.status as keyof typeof ui.indexStatus] ?? document.index.status}</span></label>)}</div>
      <label className="block text-sm font-medium">{ui.instruction}<textarea value={instruction} onChange={(event) => { clearStale(); setInstruction(event.target.value); }} maxLength={4000} rows={3} className="mt-2 w-full rounded border p-2" /></label><p className="text-xs text-muted-foreground">{ui.instructionHelp}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">{ui.audience}<input value={candidate.target_audience} onChange={(event) => { clearStale(); setCandidate({ ...candidate, target_audience: event.target.value }); }} maxLength={2000} className="mt-1 w-full rounded border p-2" /></label>
        <label className="text-sm">{ui.goal}<input value={candidate.course_intent} onChange={(event) => { clearStale(); setCandidate({ ...candidate, course_intent: event.target.value }); }} maxLength={2000} className="mt-1 w-full rounded border p-2" /></label>
        <label className="text-sm">{ui.language}<select value={candidate.language} onChange={(event) => { clearStale(); setCandidate({ ...candidate, language: event.target.value as DocumentCandidate['language'] }); }} className="mt-1 w-full rounded border p-2"><option value="ru">{ui.languages.ru}</option><option value="kk">{ui.languages.kk}</option><option value="en">{ui.languages.en}</option></select></label>
        <label className="text-sm">{ui.format}<select value={candidate.course_format} onChange={(event) => { clearStale(); setCandidate({ ...candidate, course_format: event.target.value as DocumentCandidate['course_format'] }); }} className="mt-1 w-full rounded border p-2"><option value="automatic">{ui.formats.automatic}</option><option value="brief">{ui.formats.brief}</option><option value="standard">{ui.formats.standard}</option><option value="detailed">{ui.formats.detailed}</option></select></label>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={candidate.source_strategy === 'intentional_combination'} onChange={(event) => { clearStale(); setCandidate({ ...candidate, source_strategy: event.target.checked ? 'intentional_combination' : 'single_topic' }); }} />{ui.combine}</label>
      {candidate.source_strategy === 'intentional_combination' && <textarea value={candidate.combination_goal} onChange={(event) => { clearStale(); setCandidate({ ...candidate, combination_goal: event.target.value }); }} maxLength={2000} rows={2} placeholder={ui.combinationPlaceholder} className="w-full rounded border p-2 text-sm" />}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={languageConfirmed} onChange={(event) => { clearStale(); setLanguageConfirmed(event.target.checked); }} />{ui.confirmLanguage}</label>
      <label className="text-sm">{ui.reuse}<select value={reuseReason ?? ''} onChange={(event) => { clearStale(); setReuseReason((event.target.value || null) as AIGenerateRequest['reuse_reason']); }} className="mt-1 w-full rounded border p-2">{Object.entries(ui.reuseOptions).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => void interpret()} disabled={pending || !instruction.trim()}>{ui.interpret}</Button><Button type="button" onClick={() => void preview()} disabled={pending || !instruction.trim() || !candidate.course_intent.trim() || selected.length < 1}>{ui.prepare}</Button></div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {plan?.state === 'preview_ready' && <PreviewCard preview={plan} pending={pending} onConfirm={() => void confirm()} ui={ui} locale={locale} />}
      {job && <JobCard job={job} ui={ui} />}
    </CardContent>
  </Card>;
}

function PreviewCard({ preview, pending, onConfirm, ui, locale }: { preview: DocumentPreview; pending: boolean; onConfirm: () => void; ui: typeof DOCUMENT_COPY[DocumentLocale]; locale: DocumentLocale }) {
  const generation = preview.generation;
  return <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm"><p className="font-medium">{ui.previewReady} {preview.revision}</p><dl className="mt-2 grid gap-1 sm:grid-cols-2"><div><dt className="text-xs text-muted-foreground">{ui.audience}</dt><dd>{generation.target_audience || ui.audienceMissing}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.goal}</dt><dd>{generation.course_intent || ui.audienceMissing}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.language}</dt><dd>{ui.languages[generation.language]}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.format}</dt><dd>{ui.formats[generation.course_format]}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.combine}</dt><dd>{generation.source_strategy === 'intentional_combination' ? generation.combination_goal : ui.combinationNone}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.reuse}</dt><dd>{generation.reuse_reason ? ui.reuseOptions[generation.reuse_reason] : ui.reuseMissing}</dd></div></dl><p className="mt-2">{ui.sourcesList} {preview.sources.map((source) => `${source.title} v${source.version}`).join(', ')}</p><p>{ui.validUntil} {new Date(preview.expires_at).toLocaleString({ ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[locale])}</p><p className="text-xs text-muted-foreground">{ui.fingerprint} {preview.fingerprint}</p><Button className="mt-3" type="button" onClick={onConfirm} disabled={pending}>{ui.confirm}</Button></div>;
}

function JobCard({ job, ui }: { job: AIGenerationJob; ui: typeof DOCUMENT_COPY[DocumentLocale] }) {
  const done = job.status === 'completed' && job.course_id;
  const errors = Array.isArray((job as AIGenerationJob & { errors?: Array<string | { message?: string }> }).errors)
    ? (job as AIGenerationJob & { errors: Array<string | { message?: string }> }).errors.map((item: string | { message?: string }) => typeof item === 'string' ? item : item.message || JSON.stringify(item)).join('; ')
    : '';
  return <div className="rounded border p-3 text-sm" role="status" aria-live="polite"><p className="font-medium">{ui.task} {job.status}</p><p>{job.message || `${ui.stage} ${job.stage || ui.noStage}`} · {ui.progress} {job.progress}%</p>{errors && <p role="alert" className="mt-1 text-destructive">{errors}</p>}{done && <div className="mt-2 flex gap-3"><a className="text-primary underline" href={`/courses/${job.course_id}/edit`}>{ui.openCourse}</a><a className="text-primary underline" href={`/ai/generate?job_id=${encodeURIComponent(job.id)}`}>{ui.openGeneration}</a></div>}</div>;
}
