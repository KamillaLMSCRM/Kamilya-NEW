'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { coursePublicationError } from '@/lib/coursePublicationError';
import { DOCUMENT_UPLOAD_ACCEPT, documentUploadFile } from '@/lib/documentUpload';
import {
  type DocumentCatalogResponse,
  type DocumentIndexStatus,
  getDuplicateDocumentConflict,
} from '@/lib/documentCatalog';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';
import { toast } from '@/components/ui/Toast';
import { resolveAsyncOperationState } from '@/components/ui/AsyncOperationStatus';
import {
  FileText,
  Building2,
  PenLine,
  Search,
  ClipboardCheck,
  Save,
  Loader2,
  FolderOpen,
  CheckCircle2,
  Upload,
  Send,
  RefreshCw,
  MessageSquare,
  ChevronRight,
  XCircle,
  Rocket,
  AlertTriangle,
  Layers3,
} from 'lucide-react';
import { ReviewBadge, CoursePreviewTree } from './components/CoursePreview';
import { GenerationProgressPanel } from '@/features/ai-generation/GenerationProgressPanel';
import { useGenerationWorkflow } from '@/features/ai-generation/useGenerationWorkflow';
import { WorkspacePage, WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';
import { SourceReviewChecklist, useSourceReviewStatuses } from '@/features/source-editorial-review/SourceReviewChecklist';
import {
  SourceReuseDialog,
  type ReusedSourceCourse,
  type ReuseReason,
} from '@/features/ai-generation/SourceReuseDialog';

interface Document {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size: number;
  description: string;
  embedding_status: 'pending' | 'success' | 'failed';
  embedding_error?: string | null;
  short_summary?: string | null;
  summary_ready?: boolean;
  index_status: DocumentIndexStatus;
}

interface LearningPathDetail {
  id: string;
  status: 'draft' | 'published' | 'archived';
  courses: Array<{ course_id: string; required: boolean }>;
}

type ProgramAttachState = 'idle' | 'attaching' | 'attached' | 'failed';

function parseRetryAfterSeconds(error: any): number | null {
  const headerValue = Number(error?.response?.headers?.['retry-after']);
  if (Number.isFinite(headerValue) && headerValue > 0) return Math.ceil(headerValue);

  const detail = error?.response?.data?.details ?? error?.response?.data?.detail;
  const detailValue = Number(detail?.retry_after_seconds);
  if (Number.isFinite(detailValue) && detailValue > 0) return Math.ceil(detailValue);
  return null;
}

interface CompatibilityDocument {
  id: string;
  title: string;
  filename: string;
}

interface CompatibilityCluster {
  id: string;
  label: string;
  cohesion: number | null;
  documents: CompatibilityDocument[];
}

interface DocumentCompatibility {
  status: 'compatible' | 'mixed' | 'incompatible' | 'unverified';
  score: number | null;
  analysis_mode?: 'semantic' | 'direct_source';
  requires_decision: boolean;
  clusters: CompatibilityCluster[];
  recommended_structure?: {
    requested_format: 'automatic' | 'brief' | 'standard' | 'detailed';
    resolved_format: 'brief' | 'standard' | 'detailed' | 'custom';
    module_count: number;
    lessons_per_module: number;
    recommended_total_lessons: number;
    hard_max_total_lessons: number;
    duration_min_minutes: number;
    duration_max_minutes: number;
    estimated_duration_minutes: number;
    quiz_count: number;
  } | null;
  source_passport?: {
    confidence: 'high' | 'medium' | 'low';
    teachable_units: number;
    primary_sections: string[];
    supporting_sections: string[];
    unknown_sections: string[];
    warnings: string[];
    sections: Array<{
      document_id: string;
      name: string;
      role: 'primary' | 'supporting' | 'unknown';
      chunk_count: number;
      distinct_rows: number;
    }>;
  } | null;
}

type CourseFormat = 'automatic' | 'brief' | 'standard' | 'detailed';

type Step = 'documents' | 'generate' | 'review';

type GenerationConflictState = {
  jobId: string;
  sourceSignature: string;
  actorSignature: string;
  scopeKey: string;
  scopeRevision: number;
  status: 'unread' | 'reading' | 'active' | 'terminal' | 'error' | 'invalid';
  reason?: 'dispatch_unknown';
  job?: AIGenerationJob;
};

const canonicalJobId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isCanonicalJobId(value: unknown): value is string {
  return typeof value === 'string' && canonicalJobId.test(value);
}

function isTerminalJob(job: AIGenerationJob): boolean {
  return ['completed', 'failed', 'cancelled', 'abandoned'].includes(job.status);
}

interface DocumentIndexProgress {
  jobId: string;
  current: number | null;
  total: number | null;
  estimatedRemainingSeconds: number | null;
  status: string;
}
export default function AIGeneratePage() {
  const { t, tp, lang } = useT();
  const unknownAbandonCopy = lang === 'ru'
    ? { action: 'Оставить как прерванную (результат неизвестен)', refresh: 'Обновить статус', title: 'Оставить эту генерацию прерванной?', description: 'Результат у провайдера и стоимость неизвестны. Текущий запрос никогда не будет повторён; история, источники и учёт сохранятся. Следующая генерация будет отдельной затратой.', acknowledge: 'Я понимаю, что результат и стоимость неизвестны.', cancel: 'Продолжить наблюдение', confirm: 'Оставить прерванной', submitting: 'Сохраняем…', abandoned: 'Генерация оставлена прерванной; результат и стоимость провайдера неизвестны.', failed: 'Не удалось оставить генерацию прерванной.' }
    : lang === 'kk'
      ? { action: 'Аяқталмаған деп белгілеу (нәтиже белгісіз)', refresh: 'Күйін жаңарту', title: 'Бұл генерацияны аяқталмаған деп белгілейсіз бе?', description: 'Провайдердің нәтижесі мен құны белгісіз. Ағымдағы сұрау ешқашан қайталанбайды; тарих, бастапқы материалдар және есеп жазбасы сақталады. Кейінгі генерация бөлек шығын болады.', acknowledge: 'Нәтиже мен құнның белгісіз екенін түсінемін.', cancel: 'Бақылауды жалғастыру', confirm: 'Аяқталмаған деп белгілеу', submitting: 'Сақталуда…', abandoned: 'Генерация аяқталмаған деп белгіленді; провайдер нәтижесі мен құны белгісіз.', failed: 'Генерацияны аяқталмаған деп белгілеу мүмкін болмады.' }
    : { action: 'Mark abandoned (outcome unknown)', refresh: 'Refresh outcome', title: 'Abandon this generation?', description: 'The provider outcome and cost are unknown. The current request will never be retried; its history, sources and accounting record stay retained. A later generation is a separate cost.', acknowledge: 'I understand the outcome and cost are unknown.', cancel: 'Keep monitoring', confirm: 'Abandon generation', submitting: 'Abandoning…', abandoned: 'Generation abandoned; provider outcome and cost remain unknown.', failed: 'Could not reconcile the generation.' };
  const stages = [
    { key: 'ingestion', label: t('aiGeneration.stages.ingestion'), icon: FileText, color: 'text-primary' },
    { key: 'architect', label: t('aiGeneration.stages.architect'), icon: Building2, color: 'text-accent' },
    { key: 'content_generation', label: t('aiGeneration.stages.content_generation'), icon: PenLine, color: 'text-primary' },
    { key: 'review', label: t('aiGeneration.stages.review'), icon: Search, color: 'text-accent' },
    { key: 'assessment', label: t('aiGeneration.stages.assessment'), icon: ClipboardCheck, color: 'text-success' },
    { key: 'saving', label: t('aiGeneration.stages.saving'), icon: Save, color: 'text-muted-foreground' },
  ];
  const router = useRouter();
  const token = useAuthStore((s) => s.accessToken);
  const sessionEpoch = useAuthStore((s) => s.sessionEpoch);
  const userId = useAuthStore((s) => s.user?.user_id ?? null);
  const tenantId = useAuthStore((s) => s.user?.tenant_id ?? null);
  const role = useAuthStore((s) => s.user?.role ?? null);

  const [pageStep, setPageStep] = useState<Step>('documents');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [targetAudience, setTargetAudience] = useState('');
  const [courseIntent, setCourseIntent] = useState('');
  const [numModules, setNumModules] = useState(3);
  const [courseFormat, setCourseFormat] = useState<CourseFormat>('automatic');
  const [manualModules, setManualModules] = useState(false);
  const [language, setLanguage] = useState('ru');
  const [requestedProgramId, setRequestedProgramId] = useState<string | null>(null);
  const workflowRequestKeyRef = useRef<() => string>(() => 'initial');
  const [requestedJobId, setRequestedJobId] = useState<string | null>(null);
  const {
    currentJob,
    programId,
    step: workflowStep,
    requestedJobMissing,
    restoreActiveJob,
    startJob,
    refreshJob,
    cancelJob,
    resumeJob,
    resumeReconciliation,
    prepareRetry,
    resetWorkflow,
  } = useGenerationWorkflow(requestedProgramId, () => workflowRequestKeyRef.current(), requestedJobId);
  const step = currentJob ? workflowStep : pageStep;
  const savedAssessmentDraftId = (
    currentJob?.status === 'interrupted'
    && currentJob.course_id
    && 'errors' in currentJob
    && Array.isArray(currentJob.errors)
    && currentJob.errors.some((code) =>
      code === 'assessment_no_valid_questions' || code === 'assessment_coverage_incomplete')
  ) ? currentJob.course_id : null;
  const [dragOver, setDragOver] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [documentIndexProgress, setDocumentIndexProgress] = useState<Record<string, DocumentIndexProgress>>({});
  const documentIndexProgressRef = useRef(documentIndexProgress);
  const [uploadError, setUploadError] = useState('');
  const [youtubeImportAvailability, setYoutubeImportAvailability] = useState<'checking' | 'enabled' | 'disabled'>('checking');
  const [duplicateDocument, setDuplicateDocument] = useState<{
    title: string;
    version: number;
  } | null>(null);
  const [documentLoadError, setDocumentLoadError] = useState('');
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [returnSelectionUnavailable, setReturnSelectionUnavailable] = useState(false);
  const [catalogHasMore, setCatalogHasMore] = useState(false);
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogSearch, setCatalogSearch] = useState('');
  const [visibleDocumentCount, setVisibleDocumentCount] = useState(8);
  const catalogRequest = useRef(0);
  const chosenDocuments = useRef(new Map<string, Document>());
  const pickerCopy = {
    ru: { search: 'Поиск по документам', more: 'Показать ещё', empty: 'Документы не найдены', selected: 'Выбранные документы', remove: 'Убрать', narrow: 'Уточните поиск, чтобы найти остальные документы.', unavailable: 'Не удалось восстановить часть выбранных документов. Найдите и выберите их заново.' },
    en: { search: 'Search documents', more: 'Show more', empty: 'No documents found', selected: 'Selected documents', remove: 'Remove', narrow: 'Narrow the search to find other documents.', unavailable: 'Some selected documents could not be restored. Search for them and select them again.' },
    kk: { search: 'Құжаттарды іздеу', more: 'Тағы көрсету', empty: 'Құжаттар табылмады', selected: 'Таңдалған құжаттар', remove: 'Алып тастау', narrow: 'Қалған құжаттарды табу үшін іздеуді нақтылаңыз.', unavailable: 'Таңдалған құжаттардың бір бөлігі қалпына келмеді. Оларды тауып, қайта таңдаңыз.' },
  }[lang ?? 'ru'];

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setCatalogSearch(catalogQuery.trim());
      setVisibleDocumentCount(8);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [catalogQuery]);
  const [compatibility, setCompatibility] = useState<DocumentCompatibility | null>(null);
  const [compatibilityLoading, setCompatibilityLoading] = useState(false);
  const [compatibilityError, setCompatibilityError] = useState('');
  const [sourceStrategy, setSourceStrategy] = useState<'single_topic' | 'intentional_combination'>('single_topic');
  const [combinationGoal, setCombinationGoal] = useState('');
  const [admissionError, setAdmissionError] = useState(false);
  const [admissionRetryAfter, setAdmissionRetryAfter] = useState<number | null>(null);
  const [generationConflict, setGenerationConflict] = useState<GenerationConflictState | null>(null);
  const [abandonDialog, setAbandonDialog] = useState(false);
  const [abandonAcknowledged, setAbandonAcknowledged] = useState(false);
  const [abandonSubmitting, setAbandonSubmitting] = useState(false);
  const [abandonReconcileOnly, setAbandonReconcileOnly] = useState(false);
  const [abandonTargetJobId, setAbandonTargetJobId] = useState<string | null>(null);
  const abandonAttemptedRef = useRef<string | null>(null);
  const [generationSubmitting, setGenerationSubmitting] = useState(false);
  const generationSubmittingRef = useRef<string | null>(null);
  const [reuseDialog, setReuseDialog] = useState<{
    open: boolean;
    courses: ReusedSourceCourse[];
    reason: ReuseReason | null;
  }>({ open: false, courses: [], reason: null });
  const [languageConfirmation, setLanguageConfirmation] = useState<{
    open: boolean;
    detectedLanguages: string[];
  }>({ open: false, detectedLanguages: [] });
  // Acknowledgements collected from the 409 confirmation dialogs. They persist
  // independently of which dialog opened last so both acknowledgement orders
  // (language -> reuse and reuse -> language) survive into the final request.
  const [acknowledgements, setAcknowledgements] = useState<{
    languageConfirmed: boolean;
    reuseReason: ReuseReason | null;
  }>({ languageConfirmed: false, reuseReason: null });
  const fileRef = useRef<HTMLInputElement>(null);
  const actorSignature = `${sessionEpoch}:${tenantId ?? ''}:${userId ?? ''}:${role ?? ''}`;
  const sourceSignature = JSON.stringify({
    documents: [...selectedDocIds].sort(),
    language,
    sourceStrategy,
    combinationGoal: sourceStrategy === 'intentional_combination' ? combinationGoal.trim() : '',
    targetAudience: targetAudience.trim(),
    courseIntent: courseIntent.trim(),
    courseFormat,
    manualModules,
    numModules: manualModules ? numModules : null,
  });
  const scopeKey = `${actorSignature}:${sourceSignature}:${requestedProgramId ?? ''}`;
  const scopeRevisionRef = useRef(0);
  const scopeKeyRef = useRef(scopeKey);
  if (scopeKeyRef.current !== scopeKey) {
    scopeRevisionRef.current += 1;
    scopeKeyRef.current = scopeKey;
  }
  const generationConflictRef = useRef<GenerationConflictState | null>(null);
  const actorSignatureRef = useRef(actorSignature);
  actorSignatureRef.current = actorSignature;
  const generationPageMountedRef = useRef(true);
  workflowRequestKeyRef.current = () => (
    `${generationPageMountedRef.current ? 'mounted' : 'unmounted'}:${actorSignatureRef.current}:${scopeKeyRef.current}:${scopeRevisionRef.current}`
  );

  useEffect(() => {
    generationPageMountedRef.current = true;
    return () => {
      generationPageMountedRef.current = false;
      scopeRevisionRef.current += 1;
      generationConflictRef.current = null;
    };
  }, []);

  useEffect(() => {
    generationConflictRef.current = generationConflict;
  }, [generationConflict]);

  useEffect(() => {
    setGenerationConflict((current) => {
      if (!current) return current;
      if (current.scopeKey === scopeKey && current.scopeRevision === scopeRevisionRef.current) return current;
      generationConflictRef.current = null;
      return null;
    });
  }, [scopeKey]);

  useEffect(() => {
    const conflict = generationConflictRef.current;
    if (!conflict || conflict.status !== 'active' || !conflict.job) return;
    if (currentJob && currentJob.id !== conflict.jobId) return;
    if (!currentJob || isTerminalJob(currentJob)) {
      generationConflictRef.current = null;
      setGenerationConflict(null);
    }
  }, [currentJob]);

  // Result-step state: preview of the generated course + approval.
  const [preview, setPreview] = useState<any | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [courseMeta, setCourseMeta] = useState<any | null>(null); // includes review_status, reviewer
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [publishSubmitting, setPublishSubmitting] = useState(false);
  const [programAttachState, setProgramAttachState] = useState<ProgramAttachState>('idle');
  const [reviewDialog, setReviewDialog] = useState<{ open: boolean; status: 'approved' | 'needs_changes'; comment: string }>({
    open: false,
    status: 'approved',
    comment: '',
  });

  // ── Chat with AI assistant ──
  const [chatMessages, setChatMessages] = useState<Array<{
    role: 'user' | 'assistant';
    content: string;
    at: number;
    apply_lesson_id?: string;
    apply_lesson_content?: string;
    apply_lesson_title_hint?: string;
    applied_lesson_id?: string; // marker: user already applied this suggestion
  }>>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);
  const [chatContext, setChatContext] = useState<{ context: 'course' | 'module' | 'lesson'; target_id?: string }>({ context: 'course' });

  // ── Regenerate module / lesson ──
  // Tracks an in-flight regenerate job keyed by target. Polled every 2s.
  const [regenJob, setRegenJob] = useState<{
    target_kind: 'module' | 'lesson';
    target_id: string;
    job_id: string;
    progress: number;
    stage: string;
  } | null>(null);
  const [regenDialog, setRegenDialog] = useState<{
    open: boolean;
    kind: 'module' | 'lesson';
    target_id: string;
    target_title: string;
    guidance: string;
    regenerate_quiz: boolean;
  }>({ open: false, kind: 'module', target_id: '', target_title: '', guidance: '', regenerate_quiz: true });

  // ── Inline lesson edit (Phase 5) ──
  const [editingLessonId, setEditingLessonId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{ title: string; content: string }>({ title: '', content: '' });
  const [editSaving, setEditSaving] = useState(false);
  const [loadingLessonId, setLoadingLessonId] = useState<string | null>(null);
  const [editLessonError, setEditLessonError] = useState<{ lessonId: string; message: string } | null>(null);
  const editLessonRequestRef = useRef(0);

  const documentIndexJobKey = Object.entries(documentIndexProgress)
    .filter(([, progress]) => progress.status === 'pending' || progress.status === 'running')
    .map(([documentId, progress]) => `${documentId}:${progress.jobId}`)
    .sort()
    .join('|');

  useEffect(() => {
    documentIndexProgressRef.current = documentIndexProgress;
  }, [documentIndexProgress]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setRequestedProgramId(params.get('program_id')?.trim() || null);
    setRequestedJobId(params.get('job_id')?.trim() || null);
  }, []);

  const clearRequestedJobQuery = useCallback(() => {
    setRequestedJobId(null);
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    if (!params.has('job_id')) return;
    params.delete('job_id');
    const query = params.toString();
    window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
  }, []);

  useEffect(() => {
    setProgramAttachState('idle');
  }, [currentJob?.course_id, programId]);

  const selectedDocuments = selectedDocIds.flatMap(id => {
    const doc = documents.find(item => item.id === id) ?? chosenDocuments.current.get(id);
    return doc ? [doc] : [];
  });
  const { status: sourceReviewStatus, refresh: refreshSourceReviews } = useSourceReviewStatuses(selectedDocIds, actorSignature);
  const [sourceReviewRejected, setSourceReviewRejected] = useState(false);

  const sourceReviewBlocked = sourceReviewStatus?.required === true
    && selectedDocIds.some(id => sourceReviewStatus.documents[id] !== 'approved');
  const selectedNotReadyCount = selectedDocIds.length - selectedDocuments.length;
  const failedDocumentsCount = documents.filter((doc) => doc.index_status === 'failed').length;
  const hasResolvedSourceDecision = !compatibility?.requires_decision
    || (sourceStrategy === 'intentional_combination' && combinationGoal.trim().length >= 20);
  const canGenerate = selectedDocIds.length > 0
    && !sourceReviewBlocked
    && selectedNotReadyCount === 0
    && !compatibilityLoading
    && !!compatibility
    && hasResolvedSourceDecision
    && (!generationConflict || generationConflict.status === 'terminal');
  const uploading = uploadingCount > 0;

  const documentStatusLabel = (status: DocumentIndexStatus) => {
    return t(`aiGeneration.status.${status}` as never);
  };

  const documentStatusClass = (status: DocumentIndexStatus) => {
    if (status === 'ready') return 'bg-success/10 text-success border-success/30';
    if (status === 'partial') return 'bg-warning/10 text-warning border-warning/30';
    if (status === 'failed') return 'bg-destructive/10 text-destructive border-destructive/30';
    return 'bg-primary/10 text-primary border-primary/30';
  };

  const formatIndexingEta = (seconds: number | null) => {
    if (!Number.isInteger(seconds) || (seconds ?? 0) < 0) return null;
    if ((seconds ?? 0) < 60) return `${seconds} с`;
    return `${Math.ceil((seconds ?? 0) / 60)} мин`;
  };

  useEffect(() => {
    if (selectedDocIds.length === 0 || selectedNotReadyCount > 0) {
      setCompatibility(null);
      setCompatibilityError('');
      return;
    }
    let cancelled = false;
    setCompatibility(null);
    setCompatibilityLoading(true);
    const timer = window.setTimeout(async () => {
      setCompatibilityLoading(true);
      setCompatibilityError('');
      try {
        const response = await api.post('/v1/ai/document-compatibility', {
          documents: selectedDocIds,
          course_format: courseFormat,
          ...(manualModules ? { num_modules: numModules } : {}),
        });
        if (!cancelled) setCompatibility(response.data);
      } catch (error: any) {
        if (!cancelled) {
          setCompatibility(null);
          setCompatibilityError(t('aiGeneration.errors.compatibility'));
        }
      } finally {
        if (!cancelled) setCompatibilityLoading(false);
      }
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selectedDocIds, selectedNotReadyCount, courseFormat, manualModules, numModules, t]);

  const fetchDocuments = useCallback(async () => {
    const request = ++catalogRequest.current;
    setDocumentLoadError('');
    try {
      const query = catalogSearch ? '&q=' + encodeURIComponent(catalogSearch) : '';
      const res = await api.get<DocumentCatalogResponse>('/v1/documents/catalog?lifecycle_status=active&limit=100' + query);
      if (catalogRequest.current !== request) return;
      const rows: Document[] = res.data.items.map((document) => ({
        id: document.id,
        title: document.title,
        filename: document.filename,
        content_type: document.content_type,
        size: document.size,
        description: document.description,
        embedding_status: document.index.status === 'ready' || document.index.status === 'partial'
          ? 'success'
          : document.index.status === 'failed' ? 'failed' : 'pending',
        embedding_error: document.index.message,
        short_summary: document.description || null,
        summary_ready: false,
        index_status: document.index.status,
      }));
      for (const row of rows) {
        if (chosenDocuments.current.has(row.id)) chosenDocuments.current.set(row.id, row);
      }
      setDocuments(rows);
      setCatalogHasMore(res.data.page.has_more);
    } catch {
      if (catalogRequest.current === request) setDocumentLoadError(t('aiGeneration.errors.documentLoad'));
    } finally {
      if (catalogRequest.current === request) setCatalogLoaded(true);
    }
  }, [catalogSearch, t]);

  const hasProcessingDocuments = documents.some(
    (document) => document.index_status === 'processing'
  );

  useEffect(() => {
    void fetchDocuments();
  }, [fetchDocuments]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const job = params.get('job_id')?.trim();
    if (job && requestedJobId !== job) return;
    if (!job && (params.get('new') === '1' || params.has('document_id'))) return;
    void restoreActiveJob();
  }, [requestedJobId, restoreActiveJob]);

  useEffect(() => {
    api.get<{ enabled: boolean }>('/v1/youtube/limits')
      .then((response) => setYoutubeImportAvailability(response.data.enabled ? 'enabled' : 'disabled'))
      .catch(() => setYoutubeImportAvailability('disabled'));
  }, []);

  const querySelectionApplied = useRef(false);
  useEffect(() => {
    if (querySelectionApplied.current || !catalogLoaded) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('job_id')?.trim()) return;
    const requested = [...new Set(params.getAll('document_id'))].slice(0, 5);
    if (requested.length === 0) return;
    querySelectionApplied.current = true;
    const selected = requested.flatMap(id => documents.find(doc => doc.id === id) ?? []);
    for (const doc of selected) chosenDocuments.current.set(doc.id, doc);
    setSelectedDocIds(requested);
    const missing = requested.filter(id => !chosenDocuments.current.has(id));
    const requestActor = actorSignatureRef.current;
    if (!missing.length) return;

    void Promise.allSettled(missing.map(async id => {
      const { data } = await api.get<Omit<Document, 'index_status'> & { lifecycle_status: string }>(
        '/v1/documents/' + encodeURIComponent(id),
      );
      if (data.id !== id || data.lifecycle_status !== 'active') return null;
      const indexStatus = data.embedding_status === 'success' ? 'ready' : data.embedding_status === 'failed' ? 'failed' : 'processing';
      const doc: Document = { ...data, index_status: indexStatus };
      return doc;
    })).then(results => {
      if (!generationPageMountedRef.current || actorSignatureRef.current !== requestActor) return;
      const unavailable = new Set(missing);
      for (const result of results) {
        if (result.status === 'fulfilled' && result.value) {
          chosenDocuments.current.set(result.value.id, result.value);
          unavailable.delete(result.value.id);
        }
      }
      setReturnSelectionUnavailable(unavailable.size > 0);
      setSelectedDocIds(current => current.filter(id => !unavailable.has(id)));
    });
  }, [catalogLoaded, documents]);

  useEffect(() => {
    if (!hasProcessingDocuments) return;
    const timer = window.setInterval(() => void fetchDocuments(), 3000);
    return () => window.clearInterval(timer);
  }, [fetchDocuments, hasProcessingDocuments]);

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await uploadFile(file);
    }
  };

  const uploadFile = useCallback(async (file: File) => {
    const accepted = documentUploadFile(file);
    if (!accepted) {
      const message = t('documents.allowedTypes');
      setUploadError(message);
      toast.error(t('aiGeneration.errors.uploadTitle'), { description: message });
      return;
    }
    setUploadingCount((count) => count + 1);
    setUploadingFiles((files) => [...files, file.name]);
    setUploadError('');
    setDuplicateDocument(null);
    const formData = new FormData();
    formData.append('file', accepted);
    formData.append('title', file.name.replace(/\.[^/.]+$/, ''));
    try {
      const response = await api.post<{
        id: string;
        indexing_job_id?: string | null;
      }>('/v1/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (response.data.id && response.data.indexing_job_id) {
        setDocumentIndexProgress((progress) => ({
          ...progress,
          [response.data.id]: {
            jobId: response.data.indexing_job_id!,
            current: null,
            total: null,
            estimatedRemainingSeconds: null,
            status: 'pending',
          },
        }));
      }
      await fetchDocuments();
    } catch (e) {
      const duplicate = getDuplicateDocumentConflict(e);
      if (duplicate) {
        setDuplicateDocument({ title: duplicate.title, version: duplicate.version });
        return;
      }
      const message = t('aiGeneration.errors.upload');
      setUploadError(message);
      toast.error(t('aiGeneration.errors.uploadTitle'), { description: message });
    } finally {
      setUploadingCount((count) => Math.max(0, count - 1));
      setUploadingFiles((files) => files.filter((name) => name !== file.name));
    }
  }, [fetchDocuments, t]);

  useEffect(() => {
    const entries = Object.entries(documentIndexProgressRef.current).filter(([, progress]) => (
      progress.status === 'pending' || progress.status === 'running'
    ));
    if (entries.length === 0) return;

    let cancelled = false;
    const poll = async () => {
      const updates = await Promise.all(entries.map(async ([documentId, progress]) => {
        try {
          const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${progress.jobId}`);
          const job = response.data;
          return [documentId, job] as const;
        } catch {
          return null;
        }
      }));
      if (cancelled) return;
      setDocumentIndexProgress((current) => {
        const next = { ...current };
        let changed = false;
        for (const update of updates) {
          if (!update) continue;
          const [documentId, job] = update;
          const previous = current[documentId];
          if (['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status)) {
            if (previous) {
              delete next[documentId];
              changed = true;
            }
            continue;
          }
          const value: DocumentIndexProgress = {
            ...previous,
            current: Number.isInteger(job.progress_current) ? job.progress_current ?? null : previous?.current ?? null,
            total: Number.isInteger(job.progress_total) ? job.progress_total ?? null : previous?.total ?? null,
            estimatedRemainingSeconds: Number.isInteger(job.estimated_remaining_seconds)
              ? job.estimated_remaining_seconds ?? null
              : previous?.estimatedRemainingSeconds ?? null,
            status: job.status,
          };
          if (!previous
            || previous.current !== value.current
            || previous.total !== value.total
            || previous.estimatedRemainingSeconds !== value.estimatedRemainingSeconds
            || previous.status !== value.status) {
            next[documentId] = value;
            changed = true;
          }
        }
        return changed ? next : current;
      });
      if (!cancelled && updates.some((update) => update && ['completed', 'failed', 'cancelled', 'interrupted'].includes(update[1].status))) {
        void fetchDocuments();
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [documentIndexJobKey, fetchDocuments]);

  const handleFileInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    for (const file of files) {
      await uploadFile(file);
    }
  };

  const toggleDoc = (id: string) => {
    const doc = documents.find((item) => item.id === id) ?? chosenDocuments.current.get(id);
    if (!doc) return;
    if (!selectedDocIds.includes(id) && selectedDocIds.length >= 5) {
      toast.warning(t('aiGeneration.errors.selectionLimit'));
      return;
    }
    if (selectedDocIds.includes(id)) chosenDocuments.current.delete(id);
    else chosenDocuments.current.set(id, doc);
    setSelectedDocIds(prev => prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id]);
    setSourceStrategy('single_topic');
    setCombinationGoal('');
  };

  const handleCompatibilityCluster = (cluster: CompatibilityCluster) => {
    setSelectedDocIds(cluster.documents.map((document) => document.id));
    setSourceStrategy('single_topic');
    setCombinationGoal('');
  };

  const handleGenerate = async (reuseReason?: ReuseReason, languageConfirmed = false) => {
    const requestScopeKey = scopeKey;
    const requestScopeRevision = scopeRevisionRef.current;
    const requestActorSignature = actorSignature;
    const submissionToken = `${requestActorSignature}:${requestScopeKey}:${requestScopeRevision}`;
    if (!canGenerate || generationSubmitting || generationSubmittingRef.current) return;
    generationSubmittingRef.current = submissionToken;
    generationConflictRef.current = null;
    setAdmissionError(false);
    setAdmissionRetryAfter(null);
    setGenerationConflict(null);
    setGenerationSubmitting(true);
    const confirmedLanguage = languageConfirmed || acknowledgements.languageConfirmed;
    const confirmedReuseReason = reuseReason ?? acknowledgements.reuseReason;
    try {
      const res = await api.post('/v1/ai/generate-course', {
        documents: selectedDocIds,
        target_audience: targetAudience,
        course_intent: courseIntent.trim(),
        course_format: courseFormat,
        ...(manualModules ? { num_modules: numModules } : {}),
        language,
        source_strategy: sourceStrategy,
        combination_goal: sourceStrategy === 'intentional_combination' ? combinationGoal.trim() : '',
        language_confirmed: confirmedLanguage,
        ...(confirmedReuseReason ? { reuse_reason: confirmedReuseReason } : {}),
      });
      // An admitted job remains in its server-owned history. Do not persist it
      // into a later account/page; same-actor access-token refresh is valid.
      if (!generationPageMountedRef.current || actorSignatureRef.current !== requestActorSignature) return;
      setReuseDialog({ open: false, courses: [], reason: null });
      setLanguageConfirmation({ open: false, detectedLanguages: [] });
      setAcknowledgements({ languageConfirmed: false, reuseReason: null });
      startJob(res.data);
      clearRequestedJobQuery();
    } catch (e: any) {
      if (!generationPageMountedRef.current || scopeKeyRef.current !== requestScopeKey || scopeRevisionRef.current !== requestScopeRevision) return;
      const detail = e?.response?.data?.details ?? e?.response?.data?.detail;
      if (e?.response?.status === 409 && detail?.code === 'source_editorial_review_required') {
        setSourceReviewRejected(true);
        refreshSourceReviews();
        return;
      }
      if (e?.response?.status === 429 && detail?.code === 'tenant_ai_job_limit_reached') {
        setAdmissionError(true);
        setAdmissionRetryAfter(parseRetryAfterSeconds(e));
        return;
      }
      if (e?.response?.status === 409 && detail?.code === 'generation_already_in_progress') {
        const jobId = detail?.job_id;
        if (isCanonicalJobId(jobId)) {
          setGenerationConflict({ jobId, sourceSignature, actorSignature, scopeKey: requestScopeKey, scopeRevision: requestScopeRevision, status: 'unread' });
        } else {
          setGenerationConflict({
            jobId: '', sourceSignature, actorSignature, scopeKey: requestScopeKey, scopeRevision: requestScopeRevision, status: 'invalid',
          });
        }
        return;
      }
      if (e?.response?.status === 503 || detail?.code === 'ai_job_dispatch_outcome_unknown') {
        const jobId = isCanonicalJobId(detail?.job_id) ? detail.job_id : '';
        setGenerationConflict({ jobId, sourceSignature, actorSignature, scopeKey: requestScopeKey, scopeRevision: requestScopeRevision, status: jobId ? 'unread' : 'invalid', reason: 'dispatch_unknown' });
        return;
      }
      if (['mixed_document_topics', 'source_combination_goal_required'].includes(detail?.code) && detail.analysis) {
        setCompatibility(detail.analysis);
        setPageStep('documents');
        toast.error(t('aiGeneration.compatibility.mixedTopicsTitle'), {
          description: t('aiGeneration.compatibility.mixedTopicsHint'),
        });
        return;
      }
      if (detail?.code === 'mixed_language_sources' && Array.isArray(detail.detected_languages)) {
        setAcknowledgements((state) => ({ ...state, languageConfirmed: confirmedLanguage, reuseReason: confirmedReuseReason ?? state.reuseReason }));
        setLanguageConfirmation({ open: true, detectedLanguages: detail.detected_languages });
        return;
      }
      if (detail?.code === 'source_documents_already_used' && Array.isArray(detail.existing_courses)) {
        setAcknowledgements((state) => ({ ...state, languageConfirmed: confirmedLanguage, reuseReason: confirmedReuseReason ?? state.reuseReason }));
        setReuseDialog({ open: true, courses: detail.existing_courses, reason: null });
        return;
      }
      console.error('Generation failed', e);
      toast.error(t('aiGeneration.errors.generation'), { description: t('aiGeneration.errors.generationHint') });
    } finally {
      if (generationSubmittingRef.current === submissionToken) generationSubmittingRef.current = null;
      setGenerationSubmitting(false);
    }
  };

  const readGenerationConflict = async () => {
    const admitted = generationConflictRef.current;
    if (!generationPageMountedRef.current || !admitted || admitted.status === 'reading' || admitted.status === 'invalid') return;
    if (admitted.scopeKey !== scopeKey || admitted.scopeRevision !== scopeRevisionRef.current) return;
    setGenerationConflict({ ...admitted, status: 'reading' });
    try {
      const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${admitted.jobId}`);
      const job = response.data;
      const current = generationConflictRef.current;
      if (
        !current
        || current.jobId !== admitted.jobId
        || current.scopeKey !== scopeKey
        || current.scopeRevision !== scopeRevisionRef.current
      ) return;
      if (!isCanonicalJobId(job?.id) || job.id !== admitted.jobId) {
        setGenerationConflict({ ...current, status: 'invalid' });
        return;
      }
      if (isTerminalJob(job)) {
        setGenerationConflict({ ...current, status: 'terminal', job });
        return;
      }
      // Explicitly clear both requested and inherited program context. The
      // existing job must never be attached to the current learning program.
      startJob(job, { programId: null });
      setGenerationConflict({ ...current, status: 'active', job });
    } catch {
      const current = generationConflictRef.current;
      if (!current || current.jobId !== admitted.jobId || current.scopeKey !== scopeKey || current.scopeRevision !== scopeRevisionRef.current) return;
      setGenerationConflict({ ...current, status: 'error' });
    }
  };

  const abandonUnknownGeneration = async () => {
    const admitted = generationConflictRef.current;
    const target = abandonTargetJobId === currentJob?.id ? currentJob
      : abandonTargetJobId === admitted?.job?.id ? admitted.job : null;
    if (!abandonAcknowledged || abandonSubmitting || !target || !target.abandon_available) return;
    const reconcileOnly = abandonAttemptedRef.current === target.id;
    abandonAttemptedRef.current = target.id;
    setAbandonSubmitting(true);
    try {
      if (!reconcileOnly) {
        try {
          await api.post(`/v1/ai/jobs/${target.id}/abandon-unknown`, {
            acknowledge_outcome_and_cost_unknown: true,
          });
        } catch {
          // The acknowledgement may have committed; reconcile before showing failure.
        }
      }
      const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${target.id}`);
      const job = response.data;
      if (!isCanonicalJobId(job?.id) || job.id !== target.id) throw new Error('abandon_job_identity_mismatch');
      if (job.status !== 'abandoned') {
        setAbandonReconcileOnly(true);
        toast.error(unknownAbandonCopy.failed, { description: t('aiGeneration.errors.generationConflictReadFailed') });
        return;
      }
      resetWorkflow();
      if (admitted) setGenerationConflict({ ...admitted, status: 'terminal', job });
      setAbandonDialog(false);
      setAbandonAcknowledged(false);
      setAbandonReconcileOnly(false);
      setAbandonTargetJobId(null);
      abandonAttemptedRef.current = null;
    } catch (error: any) {
      setAbandonReconcileOnly(true);
      toast.error(unknownAbandonCopy.failed, {
        description: t('aiGeneration.errors.generationConflictReadFailed'),
      });
    } finally {
      setAbandonSubmitting(false);
    }
  };

  // ── Result step: fetch preview + course meta (with review status) ──
  const loadCoursePreview = async (courseId: string) => {
    setPreviewLoading(true);
    try {
      const [previewRes, metaRes] = await Promise.all([
        api.get(`/v1/courses/${courseId}/preview`),
        api.get(`/v1/courses/${courseId}`),
      ]);
      setPreview(previewRes.data);
      setCourseMeta(metaRes.data);
    } catch (e) {
      console.error('Preview load failed', e);
      setPreview(null);
      setCourseMeta(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  // Reload preview when we land on the review step with a course_id.
  useEffect(() => {
    if (step === 'review' && currentJob?.course_id) {
      loadCoursePreview(currentJob.course_id);
    }
  }, [step, currentJob?.course_id]);

  const submitReview = async () => {
    if (!currentJob?.course_id) return;
    setReviewSubmitting(true);
    try {
      const res = await api.post(`/v1/courses/${currentJob.course_id}/review`, {
        review_status: reviewDialog.status,
        comment: reviewDialog.comment.trim() || null,
      });
      setCourseMeta(res.data);
      await loadCoursePreview(currentJob.course_id);
      setReviewDialog({ open: false, status: 'approved', comment: '' });
    } catch (e) {
      console.error('Review submit failed', e);
    } finally {
      setReviewSubmitting(false);
    }
  };

  const retryGeneration = () => {
    setPageStep('documents');
    prepareRetry();
    clearRequestedJobQuery();
  };

  const createNewCourse = () => {
    setPageStep('documents');
    resetWorkflow();
    clearRequestedJobQuery();
    setSelectedDocIds([]);
    setTargetAudience('');
    setCourseIntent('');
    setNumModules(3);
    setCourseFormat('automatic');
    setManualModules(false);
    setLanguage('ru');
    setPreview(null);
    setCourseMeta(null);
    setPreviewLoading(false);
    setProgramAttachState('idle');
    setReviewDialog({ open: false, status: 'approved', comment: '' });
    setChatMessages([]);
    setChatInput('');
    setChatContext({ context: 'course' });
    setRegenJob(null);
    setEditingLessonId(null);
    setEditForm({ title: '', content: '' });
    setUploadError('');
    setDocumentLoadError('');
    setCompatibility(null);
    setCompatibilityError('');
    setCompatibilityLoading(false);
    setSourceStrategy('single_topic');
    setCombinationGoal('');
    setAdmissionError(false);
    setAdmissionRetryAfter(null);
    setAcknowledgements({ languageConfirmed: false, reuseReason: null });
    if (fileRef.current) fileRef.current.value = '';
  };

  const attachPublishedCourseToProgram = async (courseId: string) => {
    if (!programId) return;
    setProgramAttachState('attaching');
    try {
      const response = await api.get<LearningPathDetail>(`/v1/learning-paths/${encodeURIComponent(programId)}`);
      const program = response.data;
      if (!program || program.id !== programId || program.status !== 'draft' || !Array.isArray(program.courses)) {
        setProgramAttachState('failed');
        return;
      }
      if (program.courses.some((step) => step.course_id === courseId)) {
        setProgramAttachState('attached');
        return;
      }
      await api.put(`/v1/learning-paths/${encodeURIComponent(programId)}/curriculum`, {
        steps: [
          ...program.courses.map((step) => ({ course_id: step.course_id, required: step.required })),
          { course_id: courseId, required: true },
        ],
      });
      setProgramAttachState('attached');
    } catch {
      setProgramAttachState('failed');
    }
  };

  const publishCourse = async () => {
    if (!currentJob?.course_id) return;
    setPublishSubmitting(true);
    try {
      const res = await api.post(`/v1/courses/${currentJob.course_id}/publish`);
      setCourseMeta(res.data);
      if (programId) await attachPublishedCourseToProgram(currentJob.course_id);
       toast.success(t('authenticatedUi.editor.published'), { description: t('aiGeneration.result.publishedHint') });
    } catch (error: any) {
      toast.error(t('aiGeneration.errors.publish'), {
        description: coursePublicationError(error?.response?.data, t) || t('aiGeneration.fallback.backend'),
      });
    } finally {
      setPublishSubmitting(false);
    }
  };

  // ── Chat with AI assistant ──────────────────────────────────────
  const sendChat = async () => {
    if (!currentJob?.course_id || !chatInput.trim() || chatSending) return;
    const userMessage = chatInput.trim();
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: userMessage, at: Date.now() }]);
    setChatSending(true);
    try {
      const res = await api.post('/v1/ai/chat', {
        course_id: currentJob.course_id,
        context: chatContext.context,
        target_id: chatContext.target_id,
        message: userMessage,
      });
      setChatMessages((prev) => [...prev, {
        role: 'assistant',
        content: res.data.reply,
        at: Date.now(),
        apply_lesson_id: res.data.apply_lesson_id || undefined,
        apply_lesson_content: res.data.apply_lesson_content || undefined,
        apply_lesson_title_hint: res.data.apply_lesson_title_hint || undefined,
      }]);
    } catch (e: any) {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `⚠️ ${t('aiGeneration.chat.error')}: ${t('aiGeneration.fallback.backend')}`, at: Date.now() },
      ]);
    } finally {
      setChatSending(false);
    }
  };

  const applyChatSuggestion = async (messageIdx: number, lessonId: string, content: string) => {
    try {
      await api.patch(`/v1/lessons/${lessonId}`, { content });
      setChatMessages((prev) =>
        prev.map((m, i) => (i === messageIdx ? { ...m, applied_lesson_id: lessonId } : m))
      );
      if (currentJob?.course_id) {
        await loadCoursePreview(currentJob.course_id);
      }
    } catch (e: any) {
      alert(t('aiGeneration.errors.apply'));
    }
  };

  // ── Regenerate module / lesson ──────────────────────────────────
  const startRegenerate = (kind: 'module' | 'lesson', target_id: string, target_title: string) => {
    setRegenDialog({ open: true, kind, target_id, target_title, guidance: '', regenerate_quiz: true });
  };

  const submitRegenerate = async () => {
    if (!regenDialog.target_id) return;
    setReviewSubmitting(true); // reuse busy flag
    try {
      const url = regenDialog.kind === 'module'
        ? `/v1/ai/regenerate-module/${regenDialog.target_id}`
        : `/v1/ai/regenerate-lesson/${regenDialog.target_id}`;
      const body = regenDialog.kind === 'module'
        ? { guidance: regenDialog.guidance.trim(), language: 'ru' }
        : { guidance: regenDialog.guidance.trim(), regenerate_quiz: regenDialog.regenerate_quiz };
      const res = await api.post(url, body);
      setRegenJob({
        target_kind: regenDialog.kind,
        target_id: regenDialog.target_id,
        job_id: res.data.id,
        progress: res.data.progress || 0,
        stage: res.data.stage || 'queued',
      });
      setRegenDialog({ open: false, kind: 'module', target_id: '', target_title: '', guidance: '', regenerate_quiz: true });
    } catch (e: any) {
      console.error('Regenerate start failed', e);
      alert(t('aiGeneration.errors.regenerate'));
    } finally {
      setReviewSubmitting(false);
    }
  };

  // Poll regen job every 2s. On completion, refresh preview.
  useEffect(() => {
    if (!regenJob) return;
    let cancelled = false;
    const interval = setInterval(async () => {
      if (cancelled) return;
      try {
        const res = await api.get(`/v1/ai/jobs/${regenJob.job_id}`);
        if (res.data.status === 'completed') {
          if (cancelled) return;
          setRegenJob(null);
          if (currentJob?.course_id) {
            await loadCoursePreview(currentJob.course_id);
          }
        } else if (res.data.status === 'failed' || res.data.status === 'cancelled') {
          if (cancelled) return;
          alert(t('aiGeneration.errors.regenerate'));
          setRegenJob(null);
        } else {
          setRegenJob((j) => j ? { ...j, progress: res.data.progress, stage: res.data.stage } : j);
        }
      } catch {
        // network blip — keep polling
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regenJob?.job_id, currentJob?.course_id]);

  // ── Inline edit (Phase 5) ──
  const startEditLesson = async (lessonId: string) => {
    const requestId = ++editLessonRequestRef.current;
    setLoadingLessonId(lessonId);
    setEditLessonError(null);
    try {
      const response = await api.get(`/v1/lessons/${lessonId}`);
      if (editLessonRequestRef.current !== requestId) return;
      if (typeof response.data?.title !== 'string' || typeof response.data?.content !== 'string') {
        throw new Error('Full lesson response is incomplete');
      }
      setEditForm({
        title: response.data.title,
        content: response.data.content,
      });
      setEditingLessonId(lessonId);
    } catch {
      if (editLessonRequestRef.current === requestId) {
        setEditLessonError({ lessonId, message: t('authenticatedUi.coursePreview.loadLessonFailed') });
      }
    } finally {
      if (editLessonRequestRef.current === requestId) setLoadingLessonId(null);
    }
  };
  const cancelEditLesson = () => {
    editLessonRequestRef.current += 1;
    setEditingLessonId(null);
    setLoadingLessonId(null);
    setEditForm({ title: '', content: '' });
    setEditLessonError(null);
  };
  const saveEditLesson = async () => {
    if (!editingLessonId || editSaving) return;
    setEditSaving(true);
    try {
      await api.patch(`/v1/lessons/${editingLessonId}`, {
        title: editForm.title.trim(),
        content: editForm.content,
      });
      cancelEditLesson();
      if (currentJob?.course_id) {
        await loadCoursePreview(currentJob.course_id);
      }
    } catch (e: any) {
      alert(t('aiGeneration.errors.save'));
    } finally {
      setEditSaving(false);
    }
  };

  const stepConfig = [
    { key: 'documents', label: t('aiGeneration.steps.documents'), num: 1 },
    { key: 'generate', label: t('aiGeneration.steps.generate'), num: 2 },
    { key: 'review', label: t('aiGeneration.steps.review'), num: 3 },
  ];

  return (
    <WorkspacePage id="ai-generation" className="mx-auto max-w-7xl" title={t('ai.title')} icon={<Layers3 />}>

      {/* Step indicator */}
      <WorkspaceToolbar className="grid grid-cols-3 items-center gap-2 sm:gap-4">
        {stepConfig.map((s, i) => (
          <div
            key={s.key}
            aria-current={step === s.key ? 'step' : undefined}
            className="flex min-w-0 flex-col items-center gap-2 text-center sm:flex-row sm:gap-3 sm:text-left"
          >
            <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${
              step === s.key ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
            }`}>
              {s.num}
            </div>
            <span className={`text-xs font-medium leading-tight sm:text-sm ${
              step === s.key ? 'text-foreground' : 'text-muted-foreground'
            }`}>
              {s.label}
            </span>
            {i < stepConfig.length - 1 && (
              <div className="ml-2 hidden h-px w-8 bg-muted sm:block" />
            )}
          </div>
        ))}
      </WorkspaceToolbar>

      {requestedJobMissing && (
        <div className="mb-4 rounded-lg border border-border bg-muted/40 p-4 text-sm text-foreground" role="status">
          {t('aiGeneration.errors.jobContextMissing')}
        </div>
      )}

      {/* STEP 1: Documents */}
      {admissionError && (
        <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm text-foreground" role="alert">
          <p className="font-medium">{t('ai.admissionLimit')}</p>
          {admissionRetryAfter !== null && (
            <p className="mt-1 text-muted-foreground">
              {t('ai.admissionRetryAfter', {
                minutes: Math.max(1, Math.ceil(admissionRetryAfter / 60)),
              })}
            </p>
          )}
        </div>
      )}
      {generationConflict && (
        <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm text-foreground" role="alert">
          {generationConflict.status === 'invalid' ? (
            <>
              <p className="font-medium">{t('aiGeneration.errors.generationConflictInvalid')}</p>
              <p className="mt-1 text-muted-foreground">{t('aiGeneration.errors.generationConflictHint')}</p>
            </>
          ) : generationConflict.status === 'terminal' ? (
            <>
              <p className="font-medium">{generationConflict.job?.status === 'abandoned' ? unknownAbandonCopy.abandoned : t('aiGeneration.errors.generationConflictTerminal')}</p>
              <button type="button" className="mt-3 underline" onClick={() => { generationConflictRef.current = null; setGenerationConflict(null); }}>
                {t('aiGeneration.errors.generationConflictPrepareNew')}
              </button>
            </>
          ) : generationConflict.status === 'error' ? (
            <>
              <p className="font-medium">{t('aiGeneration.errors.generationConflictReadFailed')}</p>
              <button type="button" className="mt-3 underline" onClick={() => void readGenerationConflict()}>
                {t('asyncOperation.checkAgain')}
              </button>
            </>
          ) : (
            <>
              <p className="font-medium">{generationConflict.reason === 'dispatch_unknown' ? (lang === 'ru' ? 'Запрос принят, но подтверждение провайдера неизвестно.' : lang === 'kk' ? 'Сұрау қабылданды, бірақ провайдердің растауы белгісіз.' : 'The request may have been accepted, but provider acknowledgement is unknown.') : t('aiGeneration.errors.generationConflict')}</p>
              <p className="mt-1 text-muted-foreground">{generationConflict.reason === 'dispatch_unknown' ? (lang === 'ru' ? 'Повторная отправка не выполняется. Откройте точный статус сохранённой задачи.' : lang === 'kk' ? 'Қайта жіберу орындалмайды. Сақталған тапсырманың нақты күйін ашыңыз.' : 'The request will not be sent again. Open the exact saved job status.') : t('aiGeneration.errors.generationConflictHint')}</p>
              {generationConflict.status === 'active' && generationConflict.job ? (
                <>
                  <p className="mt-2 text-muted-foreground">
                    {t('aiGeneration.errors.generationConflictProgress', {
                      progress: generationConflict.job.progress ?? 0,
                    })}
                  </p>
                  {generationConflict.job.abandon_available && (
                    <button type="button" className="mt-3 rounded-lg border border-destructive/40 px-3 py-2 font-medium hover:bg-destructive/10" onClick={() => { setAbandonTargetJobId(generationConflict.job!.id); setAbandonDialog(true); }}>
                      {abandonReconcileOnly ? unknownAbandonCopy.refresh : unknownAbandonCopy.action}
                    </button>
                  )}
                </>
              ) : (
                <button
                  type="button"
                  className="mt-3 rounded-lg border border-warning/50 px-3 py-2 font-medium hover:bg-warning/10 disabled:opacity-60"
                  disabled={generationConflict.status === 'reading'}
                  onClick={() => void readGenerationConflict()}
                >
                  {generationConflict.status === 'reading'
                    ? t('aiGeneration.errors.generationConflictReading')
                    : t('aiGeneration.errors.generationConflictOpen')}
                </button>
              )}
            </>
          )}
        </div>
      )}
      {abandonDialog && (generationConflict?.job ?? currentJob)?.abandon_available && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-labelledby="unknown-abandon-title">
          <div className="w-full max-w-lg rounded-2xl border bg-card p-6 shadow-card-lg">
            <h2 id="unknown-abandon-title" className="text-lg font-semibold">{unknownAbandonCopy.title}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{unknownAbandonCopy.description}</p>
            <label className="mt-4 flex items-start gap-2 text-sm">
              <input type="checkbox" checked={abandonAcknowledged} onChange={(event) => setAbandonAcknowledged(event.target.checked)} />
              <span>{unknownAbandonCopy.acknowledge}</span>
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="rounded-lg border px-3 py-2" disabled={abandonSubmitting} onClick={() => { setAbandonDialog(false); setAbandonAcknowledged(false); setAbandonTargetJobId(null); }}>{unknownAbandonCopy.cancel}</button>
              <button type="button" className="rounded-lg bg-destructive px-3 py-2 text-destructive-foreground disabled:opacity-50" disabled={!abandonAcknowledged || abandonSubmitting} onClick={() => void abandonUnknownGeneration()}>{abandonSubmitting ? unknownAbandonCopy.submitting : abandonReconcileOnly ? unknownAbandonCopy.refresh : unknownAbandonCopy.confirm}</button>
            </div>
          </div>
        </div>
      )}
      {step === 'documents' && (
        <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(340px,0.65fr)]">
          <WorkspacePanel title={t('aiGeneration.steps.documents')} bodyClassName="space-y-4">
          <section className="flex flex-col gap-3 rounded-2xl border border-primary/20 bg-primary/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="font-display text-sm font-bold text-foreground">{t('documents.youtubeSourceTitle')}</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('documents.youtubeSourceDescription')}
              </p>
              {youtubeImportAvailability === 'disabled' && (
                <p className="mt-2 text-xs font-medium text-warning">{t('documents.youtubeUnavailable')}</p>
              )}
            </div>
            <button
              type="button"
              disabled={youtubeImportAvailability !== 'enabled'}
              onClick={() => router.push('/documents?import=youtube')}
              className="inline-flex min-h-10 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-card px-4 py-2 text-sm font-semibold text-primary transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {youtubeImportAvailability === 'checking' ? t('documents.youtubeChecking') : t('documents.youtubeAddVideo')}
            </button>
          </section>

          {/* Upload zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`rounded-2xl border-2 border-dashed bg-muted/20 p-6 text-center cursor-pointer transition-all ${
              dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-border hover:bg-muted'
            }`}
          >
            <input ref={fileRef} type="file" multiple onChange={(e) => {
              void handleFileInputChange(e);
            }} className="hidden" accept={DOCUMENT_UPLOAD_ACCEPT} />
            <div className="text-2xl mb-2 text-muted-foreground">
              {uploading ? <Loader2 className="w-8 h-8 mx-auto animate-spin" /> : <FolderOpen className="w-8 h-8 mx-auto" />}
            </div>
            <p className="text-sm text-muted-foreground">
              {uploading ? t('aiGeneration.upload.loading', { files: uploadingFiles.join(', ') || t('aiGeneration.upload.file') }) : t('aiGeneration.upload.prompt')}
            </p>
            {uploading && (
              <p className="mt-1 text-xs text-muted-foreground">
                {t('aiGeneration.upload.progress')}
              </p>
            )}
          </div>

          {uploadError && (
            <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {uploadError}
            </div>
          )}

          {duplicateDocument && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-foreground">
              <span>
                {t('aiGeneration.upload.duplicate', { title: duplicateDocument.title, version: duplicateDocument.version })}
              </span>
              <button
                type="button"
                onClick={() => router.push(`/documents?q=${encodeURIComponent(duplicateDocument.title)}`)}
                className="shrink-0 rounded-lg border border-warning/50 bg-background px-3 py-1.5 font-medium hover:bg-muted"
              >
                {t('aiGeneration.upload.openExisting')}
              </button>
            </div>
          )}

          {documentLoadError && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <span>{documentLoadError}</span>
              <button
                type="button"
                onClick={() => void fetchDocuments()}
                className="shrink-0 rounded-lg border border-destructive/30 px-2 py-1 font-medium hover:bg-destructive/10"
              >
                {t('aiGeneration.upload.retry')}
              </button>
            </div>
          )}

          <label className="block space-y-1 text-sm font-medium">
            <span>{pickerCopy.search}</span>
            <input type="search" value={catalogQuery} maxLength={200} onChange={event => setCatalogQuery(event.target.value)}
              className="block w-full rounded-xl border border-border bg-background px-3 py-2.5" />
          </label>
          {returnSelectionUnavailable && <p role="status" className="text-sm text-muted-foreground">{pickerCopy.unavailable}</p>}
          {selectedDocuments.length > 0 && <section aria-label={pickerCopy.selected} className="space-y-2">
            <h3 className="text-sm font-semibold">{pickerCopy.selected} ({selectedDocuments.length})</h3>
            <ul className="flex flex-wrap gap-2">{selectedDocuments.map(doc => <li key={doc.id} className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-muted/30 px-2 py-1 text-sm">
              <span className="min-w-0 break-words">{doc.title}</span>
              <button type="button" aria-label={pickerCopy.remove + ': ' + doc.title} onClick={() => toggleDoc(doc.id)}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted">
                <XCircle className="h-4 w-4" aria-hidden="true" />
              </button>
            </li>)}</ul>
          </section>}
          {catalogSearch && documents.length === 0 && !documentLoadError && <p role="status" className="text-sm text-muted-foreground">{pickerCopy.empty}</p>}

          {/* Documents list */}
          {documents.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">
                {t('aiGeneration.documents.selected', { count: tp('common.counts.document', selectedDocIds.length) })}
              </div>
              {documents.slice(0, visibleDocumentCount).map(doc => {
                // Catalog is filtered to active sources. Original-file validation,
                // not embedding availability, determines admission on the server.
                const isReady = true;
                const isSelected = selectedDocIds.includes(doc.id);
                const indexProgress = documentIndexProgress[doc.id];
                const hasExactIndexProgress = doc.index_status === 'processing'
                  && Number.isInteger(indexProgress?.current)
                  && Number.isInteger(indexProgress?.total)
                  && (indexProgress?.current ?? -1) >= 0
                  && (indexProgress?.total ?? 0) > 0
                  && (indexProgress?.current ?? 0) <= (indexProgress?.total ?? 0);
                const indexPercent = hasExactIndexProgress
                  ? Math.round(((indexProgress?.current ?? 0) / (indexProgress?.total ?? 1)) * 100)
                  : null;
                const indexEta = hasExactIndexProgress
                  ? formatIndexingEta(indexProgress?.estimatedRemainingSeconds ?? null)
                  : null;

                return (
                  <div
                    key={doc.id}
                    title={doc.index_status === 'failed'
                      ? doc.embedding_error || t('aiGeneration.documents.failedTitle')
                      : doc.index_status === 'partial'
                        ? doc.embedding_error || t('aiGeneration.documents.partialTitle')
                        : undefined}
                    className={`flex min-w-0 flex-wrap items-center gap-3 rounded-xl border p-3 transition-all sm:flex-nowrap ${
                      isSelected
                        ? 'border-primary bg-primary/5'
                        : isReady
                          ? 'border-border hover:border-border cursor-pointer'
                          : 'border-border bg-muted/40 opacity-80 cursor-not-allowed'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      disabled={!isReady}
                      onChange={() => toggleDoc(doc.id)}
                      className="h-4 w-4 rounded border-border text-primary focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label={t('aiGeneration.documents.selectAria', { title: doc.title })}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <div className="text-sm font-medium text-foreground truncate">{doc.title}</div>
                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${documentStatusClass(doc.index_status)}`}>
                          {doc.index_status === 'failed' ? 'Без поискового индекса' : documentStatusLabel(doc.index_status)}
                        </span>
                      </div>
                      {hasExactIndexProgress ? (
                        <div className="mt-1 space-y-1 text-xs text-warning" role="status" aria-live="polite">
                          <div className="flex items-center justify-between gap-2 tabular-nums">
                            <span>Индексация: {indexProgress?.current} / {indexProgress?.total}</span>
                            <span>{indexPercent}%</span>
                          </div>
                          <div
                            className="h-1.5 overflow-hidden rounded-full bg-warning/20"
                            role="progressbar"
                            aria-label={`Индексация документа ${doc.title}`}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={indexPercent ?? 0}
                          >
                            <div className="h-full rounded-full bg-warning transition-[width] duration-500" style={{ width: `${indexPercent}%` }} />
                          </div>
                          {indexEta !== null && <div className="tabular-nums">Осталось примерно: {indexEta}</div>}
                        </div>
                      ) : doc.short_summary ? (
                        <div className="text-xs text-primary/80 truncate italic">
                          {doc.summary_ready ? '📄 ' : '⚠️ '}{doc.short_summary}
                        </div>
                      ) : doc.index_status === 'failed' ? (
                        <div className="text-xs text-destructive truncate">
                          {t('aiGeneration.documents.directSourceHint')}
                        </div>
                      ) : doc.index_status === 'processing' ? (
                        <div className="text-xs text-warning truncate">
                          {t('aiGeneration.documents.processingHint')}
                        </div>
                      ) : doc.description ? (
                        <div className="text-xs text-muted-foreground truncate">{doc.description}</div>
                      ) : null}
                    </div>
                    <div className="ml-7 max-w-full truncate text-xs text-muted-foreground sm:ml-0 sm:max-w-[130px] sm:shrink-0">{doc.filename}</div>
                  </div>
                );
              })}
              {failedDocumentsCount > 0 && (
                <div className="flex items-start justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  <span>
                    {t('aiGeneration.documents.directSourceNotice')}
                  </span>
                  <button
                    type="button"
                    onClick={() => router.push('/documents')}
                    className="shrink-0 rounded-lg border border-destructive/30 px-2 py-1 font-medium transition-colors hover:bg-destructive/10"
                  >
                    {t('aiGeneration.documents.open')}
                  </button>
                </div>
              )}
              {documents.length > visibleDocumentCount && (
                <button type="button" onClick={() => setVisibleDocumentCount(value => value + 8)}
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm font-medium text-primary hover:bg-muted">
                  {pickerCopy.more}
                </button>
              )}
              {catalogHasMore && documents.length <= visibleDocumentCount && (
                <p className="text-sm text-muted-foreground">{pickerCopy.narrow}</p>
              )}
            </div>
          )}

          {selectedDocIds.length > 0 && selectedNotReadyCount === 0 && (
            <section className="rounded-xl border border-border bg-card p-4" aria-live="polite">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  {compatibilityLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Layers3 className="h-5 w-5" />}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-semibold text-foreground">{t('aiGeneration.compatibility.title')}</h3>
                  {compatibilityLoading ? (
                    <p className="mt-1 text-sm text-muted-foreground">{t('aiGeneration.compatibility.checking')}</p>
                  ) : compatibilityError ? (
                    <p className="mt-1 text-sm text-destructive">{compatibilityError}</p>
                  ) : compatibility && !compatibility.requires_decision ? (
                    <p className="mt-1 text-sm text-success">
                      {compatibility.analysis_mode === 'direct_source'
                        ? t('aiGeneration.compatibility.directReady')
                        : t('aiGeneration.compatibility.compatible')}
                    </p>
                  ) : compatibility ? (
                    <div className="mt-2 space-y-4">
                      <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-foreground">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                        <p>
                          {compatibility.analysis_mode === 'direct_source'
                            ? t('aiGeneration.compatibility.directMixed')
                            : t('aiGeneration.compatibility.mixed')}
                        </p>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {compatibility.clusters.map((cluster, index) => (
                          <div key={cluster.id} className="rounded-lg border border-border bg-background p-3">
                            <div className="text-xs font-semibold uppercase text-muted-foreground">{t('aiGeneration.compatibility.group', { index: index + 1 })}</div>
                            <div className="mt-1 text-sm font-semibold text-foreground line-clamp-2">{cluster.label}</div>
                            <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                              {cluster.documents.map((document) => (
                                <li key={document.id} className="truncate" title={document.filename}>• {document.title}</li>
                              ))}
                            </ul>
                            <button
                              type="button"
                              onClick={() => handleCompatibilityCluster(cluster)}
                              className="mt-3 w-full rounded-lg border border-primary/30 px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-primary/5"
                            >
                              {t('aiGeneration.compatibility.useGroup')}
                            </button>
                          </div>
                        ))}
                      </div>
                      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3">
                        <input
                          type="radio"
                          name="source-strategy"
                          checked={sourceStrategy === 'intentional_combination'}
                          onChange={() => setSourceStrategy('intentional_combination')}
                          className="mt-1 h-4 w-4 text-primary focus:ring-primary"
                        />
                        <span>
                           <span className="block text-sm font-medium text-foreground">{t('aiGeneration.compatibility.intentional')}</span>
                           <span className="mt-0.5 block text-xs text-muted-foreground">{t('aiGeneration.compatibility.intentionalHint')}</span>
                        </span>
                      </label>
                      {sourceStrategy === 'intentional_combination' && (
                        <div>
                          <label className="mb-1 block text-xs font-semibold text-muted-foreground" htmlFor="combination-goal">
                             {t('aiGeneration.compatibility.goal')}
                          </label>
                          <textarea
                            id="combination-goal"
                            value={combinationGoal}
                            onChange={(event) => setCombinationGoal(event.target.value)}
                            rows={3}
                            maxLength={2000}
                             placeholder={t('aiGeneration.compatibility.goalPlaceholder')}
                            className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-primary"
                          />
                          <div className={`mt-1 text-xs ${combinationGoal.trim().length >= 20 ? 'text-success' : 'text-muted-foreground'}`}>
                             {t('aiGeneration.compatibility.goalHint')}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
            </section>
          )}

          </WorkspacePanel>
          {/* Config and its admission action stay together beside the sources. */}
          <div className="min-w-0 space-y-4">
          <WorkspacePanel title={t('aiGeneration.generation.settings')} bodyClassName="space-y-4">
            <div>
              <label htmlFor="course-intent" className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.courseIntent')}</label>
              <textarea
                id="course-intent"
                value={courseIntent}
                onChange={(event) => setCourseIntent(event.target.value)}
                rows={3}
                maxLength={2000}
                placeholder={t('ai.courseIntentPlaceholder')}
                className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-y"
              />
              <p className="mt-1 text-xs text-muted-foreground">{t('ai.courseIntentHint')}</p>
            </div>
            <div>
              <label htmlFor="course-target-audience" className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.targetAudience')}</label>
              <textarea
                id="course-target-audience"
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
                rows={2}
                placeholder={t('ai.targetAudiencePlaceholder')}
                className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none"
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="course-format" className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.courseFormat')}</label>
                <select
                  id="course-format"
                  value={courseFormat}
                  onChange={(event) => setCourseFormat(event.target.value as CourseFormat)}
                  className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors"
                >
                  <option value="automatic">{t('ai.courseFormats.automatic')}</option>
                  <option value="brief">{t('ai.courseFormats.brief')}</option>
                  <option value="standard">{t('ai.courseFormats.standard')}</option>
                  <option value="detailed">{t('ai.courseFormats.detailed')}</option>
                </select>
                <p className="mt-1 text-xs text-muted-foreground">{t('ai.courseFormatHint')}</p>
              </div>
              <div>
                <label htmlFor="course-output-language" className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.language')}</label>
                <select
                  id="course-output-language"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors"
                >
                  <option value="ru">{t('ai.languages.ru')}</option>
                  <option value="kk">{t('ai.languages.kk')}</option>
                  <option value="en">{t('ai.languages.en')}</option>
                </select>
              </div>
            </div>
            {compatibility?.recommended_structure && (
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm">
                <div className="font-medium text-foreground">{t('ai.recommendedStructure')}</div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Оценка, а не обещанный результат: после разбора основного материала число модулей и уроков может измениться; справочные строки не задают структуру курса.
                </p>
                <div className="mt-1 text-muted-foreground">
                  {t('ai.recommendedStructureValue', {
                    modules: compatibility.recommended_structure.module_count,
                    lessons: compatibility.recommended_structure.recommended_total_lessons,
                    minMinutes: compatibility.recommended_structure.duration_min_minutes,
                    maxMinutes: compatibility.recommended_structure.duration_max_minutes,
                  })}
                </div>
              </div>
            )}
            {compatibility?.source_passport && (
              <div className="rounded-xl border border-border bg-muted/30 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium text-foreground">{t('ai.sourceInterpretation')}</div>
                  <div className="text-xs text-muted-foreground">
                    {t('ai.interpretationConfidence')}: {t(`ai.confidence.${compatibility.source_passport.confidence}`)}
                  </div>
                </div>
                <div className="mt-1 text-muted-foreground">
                  {t('ai.primarySections')}: {compatibility.source_passport.primary_sections.join(', ') || t('ai.notIdentified')}
                </div>
                {compatibility.source_passport.supporting_sections.length > 0 && (
                  <div className="mt-1 text-muted-foreground">
                    {t('ai.supportingSections')}: {compatibility.source_passport.supporting_sections.join(', ')}
                  </div>
                )}
                {compatibility.source_passport.unknown_sections.length > 0 && (
                  <div className="mt-1 text-warning">
                    {t('ai.unknownSections')}: {compatibility.source_passport.unknown_sections.join(', ')}
                  </div>
                )}
                <p className="mt-2 text-xs text-muted-foreground">
                  {compatibility.source_passport.confidence === 'low'
                    ? t('ai.sourceInterpretationLowHint')
                    : t('ai.sourceInterpretationHint')}
                </p>
              </div>
            )}
            <details className="rounded-xl border border-border px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium text-foreground">{t('ai.advancedStructure')}</summary>
              <label className="mt-3 flex items-start gap-2 text-sm">
                <input type="checkbox" checked={manualModules} onChange={(event) => setManualModules(event.target.checked)} className="mt-1" />
                <span>{t('ai.manualModules')}</span>
              </label>
              {manualModules && (
                <div className="mt-3 max-w-xs">
                  <label htmlFor="manual-module-count" className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.numModules')}</label>
                  <input id="manual-module-count" type="number" min={1} max={10} value={numModules} onChange={(event) => setNumModules(parseInt(event.target.value) || 1)} className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary" />
                  <p className="mt-1 text-xs text-muted-foreground">{t('ai.manualModulesHint')}</p>
                </div>
              )}
            </details>
          </WorkspacePanel>

          <SourceReviewChecklist documents={selectedDocuments} status={sourceReviewStatus}
            requireReview={sourceReviewRejected && !sourceReviewStatus?.required} />
          {!(sourceReviewBlocked || (sourceReviewRejected && !sourceReviewStatus?.required)) && <button
            onClick={() => void handleGenerate()}
            disabled={!canGenerate || generationSubmitting}
            className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {generationSubmitting ? <><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />{t('aiGeneration.generation.starting')}</> : <>{t('ai.generate')} ({tp('common.counts.document', selectedDocIds.length)})</>}
          </button>}
          {selectedDocIds.length > 0 && selectedNotReadyCount > 0 && (
            <div className="text-center text-xs text-warning">
              {t('aiGeneration.generation.notReady')}
            </div>
          )}
          </div>
        </div>
      )}

      {/* STEP 2: Generation progress */}
      {step === 'generate' && currentJob && (
        <div className="space-y-6">
          {currentJob.abandon_available && (
            <button type="button" className="rounded-lg border border-destructive/40 px-3 py-2 font-medium hover:bg-destructive/10" onClick={() => { setAbandonTargetJobId(currentJob.id); setAbandonDialog(true); }}>
              {abandonReconcileOnly ? unknownAbandonCopy.refresh : unknownAbandonCopy.action}
            </button>
          )}
          {currentJob.status === 'reconciliation_required' ? (
            <div role="alert" className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-foreground">
              <p>{currentJob.message}</p>
              <button type="button" className="mt-3 underline" onClick={() => void refreshJob().catch((error: any) => toast.error(t('common.loadFailed'), { description: error?.response?.data?.detail || error?.message }))}>
                {t('asyncOperation.checkAgain')}
              </button>
            </div>
          ) : <GenerationProgressPanel
            lang={lang}
            job={currentJob}
            stages={stages}
            title={t('ai.progress')}
            labels={{ queued: t('asyncOperation.queued'), running: t('asyncOperation.running'), completed: t('asyncOperation.completed'), failed: t('asyncOperation.failed'), cancelled: t('asyncOperation.cancelled'), interrupted: savedAssessmentDraftId ? t('ai.assessmentNeedsReview') : t('asyncOperation.interrupted'), stalled: t('asyncOperation.stalled') }}
            retryLabel={savedAssessmentDraftId ? t('ai.openSavedDraft') : resumeReconciliation ? (lang === 'ru' ? 'Проверить статус' : lang === 'kk' ? 'Күйін тексеру' : 'Check status') : currentJob.status === 'interrupted' ? t('asyncOperation.continue') : resolveAsyncOperationState(currentJob) === 'failed' ? t('ai.newCourse') : t('asyncOperation.retry')}
            checkAgainLabel={t('asyncOperation.checkAgain')}
            cancelLabel={savedAssessmentDraftId ? t('ai.newCourse') : t('asyncOperation.cancel')}
            cancelQueuedLabel={t('asyncOperation.cancelQueued')}
            queueTitle={t('ai.queueTitle')}
            activeJobs={t('ai.activeJobs', { active: currentJob.tenant_active_jobs ?? 0, limit: currentJob.tenant_active_limit ?? 0 })}
            queuePosition={t('ai.queuePosition', { position: currentJob.queue_position ?? 0 })}
            estimatedWait={t('ai.estimatedWait', { minutes: Math.max(1, Math.ceil((currentJob.estimated_wait_seconds ?? 0) / 60)) })}
            queueEstimateHint={t('ai.queueEstimateHint')}
            completedUnitsLabel={t('ai.savedLessonsProgress')}
            onRetry={savedAssessmentDraftId ? () => router.push(`/courses/${savedAssessmentDraftId}/edit`) : resumeReconciliation ? () => void resumeJob().catch(() => toast.error(t('common.loadFailed'))) : currentJob.status === 'interrupted' ? () => void resumeJob().catch(() => toast.error(t('common.loadFailed'))) : resolveAsyncOperationState(currentJob) === 'stalled' ? () => void refreshJob().catch(() => toast.error(t('common.loadFailed'))) : retryGeneration}
            onCancel={savedAssessmentDraftId
              ? createNewCourse
              : currentJob.abandon_available || resumeReconciliation
              ? undefined as unknown as () => void
              : () => void cancelJob().catch((error) => console.error('Cancel failed', error))}
          />}

          {currentJob.status === 'completed' && currentJob.course_id && (
            <button
              onClick={() => router.push(`/courses/${currentJob.course_id}/edit`)}
              className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              {t('aiGeneration.generation.openCourse')} <ChevronRight className="w-4 h-4 ml-1 inline" />
            </button>
          )}

        </div>
      )}

      {/* STEP 3: Review */}
      {step === 'review' && currentJob?.course_id && (
        <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.55fr)]">
          {/* Completion describes the saved draft, not a quality approval. */}
          <WorkspaceToolbar className="items-center justify-between xl:col-span-2">
            <div className="flex min-w-0 flex-1 basis-64 items-start gap-3">
              <CheckCircle2 className="mt-1 h-6 w-6 shrink-0 text-primary" />
            <div>
            <h3 className="text-base font-semibold text-foreground">{courseMeta?.status === 'published' ? t('authenticatedUi.editor.published') : t('generationDraft.title')}</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              {courseMeta?.status === 'published' ? t('aiGeneration.result.publishedHint') : t('generationDraft.hint')}
            </p>
            </div>
            </div>
            {courseMeta?.status !== 'published' && (
              <button type="button" onClick={() => router.push(`/courses/${currentJob.course_id}/edit${programId ? `?programGenerationJob=${encodeURIComponent(currentJob.id)}` : ''}#course-release`)}
                className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                {t('generationDraft.review')} <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            )}
            <button
              type="button"
              onClick={createNewCourse}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              <RefreshCw className="h-4 w-4" />
              Создать новый курс
            </button>
          </WorkspaceToolbar>

          {/* Course meta + review status */}
          {courseMeta && (
            <WorkspacePanel className="xl:col-start-2 xl:row-start-2" bodyClassName="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <h4 className="min-w-0 flex-1 break-words text-lg font-semibold leading-7 text-foreground">
                  {courseMeta.title}
                </h4>
                <ReviewBadge status={courseMeta.review_status} />
              </div>
              <p className="whitespace-pre-line text-sm text-muted-foreground">{courseMeta.description}</p>
              {preview?.source_documents?.length > 0 && (
                <div className="rounded-lg border border-border bg-muted/30 p-3">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                    <FileText className="h-3.5 w-3.5 text-primary" />
                    {t('aiGeneration.result.sources')}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {preview.source_documents.map((document: any) => (
                      <span key={document.id} className="max-w-full truncate rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground" title={document.filename}>
                        {document.title}
                      </span>
                    ))}
                  </div>
                  {preview.source_strategy === 'intentional_combination' && preview.source_combination_goal && (
                    <p className="mt-2 border-t border-border pt-2 text-xs text-muted-foreground">
                       <span className="font-medium text-foreground">{t('aiGeneration.result.learningGoal')}</span> {preview.source_combination_goal}
                    </p>
                  )}
                </div>
              )}

              {/* Reviewer info */}
              {courseMeta.review_status !== 'pending' && courseMeta.reviewer && (
                <div className="text-xs text-muted-foreground border-t border-border pt-3">
                  <span className="font-medium text-foreground">{courseMeta.reviewer.full_name || t('aiGeneration.result.reviewerFallback')}</span>
                  {courseMeta.reviewed_at && (
                    <span> · {new Date(courseMeta.reviewed_at).toLocaleString('ru-RU')}</span>
                  )}
                  {courseMeta.review_comment && (
                    <div className="mt-1 italic text-foreground">«{courseMeta.review_comment}»</div>
                  )}
                </div>
              )}

              {/* Approval actions */}
              {courseMeta.review_status !== 'approved' && (
                <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                  <button
                    type="button"
                    onClick={() => setReviewDialog({ open: true, status: 'needs_changes', comment: '' })}
                    disabled={reviewSubmitting}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-warning/50 bg-warning/10 px-3 py-2 text-sm font-medium text-warning hover:bg-warning/15 transition-colors disabled:opacity-50"
                  >
                    <XCircle className="w-4 h-4" />
                     {t('aiGeneration.result.needsChanges')}
                  </button>
                </div>
              )}
            </WorkspacePanel>
          )}

          {/* Preview: modules → lessons → quiz headers */}
          <WorkspacePanel padded={false} className="overflow-hidden xl:col-start-1 xl:row-start-2">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
              <h4 className="text-sm font-bold text-foreground font-display">
                 {t('aiGeneration.result.structure')}
              </h4>
              {preview && (
                <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                  <span>{tp('common.counts.module', preview.modules_count)}</span>
                  <span>·</span>
                  <span>{tp('common.counts.lesson', preview.lessons_count)}</span>
                  <span>·</span>
                  <span>{tp('common.counts.test', preview.quizzes_count)}</span>
                </div>
              )}
            </div>
            {previewLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : preview && preview.modules?.length > 0 ? (
              <CoursePreviewTree
                modules={preview.modules}
                onRegenerateModule={(moduleId, title) => startRegenerate('module', moduleId, title)}
                onRegenerateLesson={(lessonId, title) => startRegenerate('lesson', lessonId, title)}
                onFocusChat={(context, target_id) => setChatContext({ context, target_id })}
                onEditLesson={startEditLesson}
                loadingLessonId={loadingLessonId}
                editLessonError={editLessonError}
                busyTargetId={regenJob?.target_id ?? null}
                editingLessonId={editingLessonId}
                editForm={editForm}
                editSaving={editSaving}
                onCancelEdit={cancelEditLesson}
                onSaveEdit={saveEditLesson}
                onEditFormChange={setEditForm}
              />
            ) : (
              <div className="p-6 text-center text-sm text-muted-foreground">
                 {t('aiGeneration.result.emptyStructure')}
              </div>
            )}
          </WorkspacePanel>

          {/* AI Assistant chat panel */}
          <WorkspacePanel padded={false} className="overflow-hidden xl:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
              <div className="flex items-center gap-2 min-w-0">
                <MessageSquare className="w-4 h-4 text-primary shrink-0" />
                <h4 className="text-sm font-bold text-foreground font-display truncate">
                   {t('aiGeneration.chat.title')}
                </h4>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {(['course', 'module', 'lesson'] as const).map((ctx) => (
                  <button
                    key={ctx}
                    type="button"
                    onClick={() => {
                      if (ctx === 'course') setChatContext({ context: 'course' });
                    }}
                    disabled={ctx !== 'course' && !chatContext.target_id}
                    className={
                      chatContext.context === ctx
                        ? 'rounded-full bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground'
                        : 'rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted/70 disabled:opacity-50'
                    }
                    title={
                      ctx !== 'course' && !chatContext.target_id
                         ? t('aiGeneration.chat.selectTarget')
                        : undefined
                    }
                  >
                     {ctx === 'course' ? t('aiGeneration.chat.course') : ctx === 'module' ? t('aiGeneration.chat.module') : t('aiGeneration.chat.lesson')}
                  </button>
                ))}
              </div>
            </div>

            <div className="max-h-72 overflow-y-auto p-4 space-y-3 bg-background">
              {chatMessages.length === 0 ? (
                <div className="text-center py-8 text-sm text-muted-foreground">
                   {t('aiGeneration.chat.empty')}
                </div>
              ) : (
                chatMessages.map((m, i) => (
                  <div key={i} className="space-y-1.5">
                    <div className={
                      m.role === 'user'
                        ? 'flex justify-end'
                        : 'flex justify-start'
                    }>
                      <div className={
                        m.role === 'user'
                          ? 'max-w-[85%] rounded-2xl rounded-tr-md bg-primary px-3 py-2 text-sm text-primary-foreground whitespace-pre-wrap'
                          : 'max-w-[85%] rounded-2xl rounded-tl-md bg-muted px-3 py-2 text-sm text-foreground whitespace-pre-wrap'
                      }>
                        {m.content}
                      </div>
                    </div>
                    {m.role === 'assistant' && m.apply_lesson_id && m.apply_lesson_content && (
                      <div className="flex justify-start">
                        <div className="max-w-[85%] rounded-2xl rounded-tl-md border border-success/30 bg-success/5 p-3 space-y-2">
                          <div className="text-[11px] font-semibold uppercase tracking-wider text-success">
                             {t('aiGeneration.chat.applyProposal', { title: m.apply_lesson_title_hint ? `: «${m.apply_lesson_title_hint}»` : '' })}
                          </div>
                          <div className="text-xs text-muted-foreground line-clamp-4 whitespace-pre-line font-mono">
                            {m.apply_lesson_content}
                          </div>
                          <div className="flex items-center justify-between gap-2 pt-1">
                            <span className="text-[10px] text-muted-foreground">
                               {t('aiGeneration.chat.lessonId', { id: m.apply_lesson_id.slice(0, 8) })}
                            </span>
                            {m.applied_lesson_id === m.apply_lesson_id ? (
                              <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-2 py-1 text-[11px] font-medium text-success">
                                <CheckCircle2 className="w-3 h-3" />
                                 {t('aiGeneration.chat.applied')}
                              </span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => applyChatSuggestion(i, m.apply_lesson_id!, m.apply_lesson_content!)}
                                className="inline-flex items-center gap-1 rounded-md bg-success px-2 py-1 text-[11px] font-medium text-success-foreground hover:bg-success/90 transition-colors"
                              >
                                <CheckCircle2 className="w-3 h-3" />
                                 {t('aiGeneration.chat.apply')}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))
              )}
              {chatSending && (
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-tl-md bg-muted px-3 py-2">
                    <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                  </div>
                </div>
              )}
            </div>

            <div className="border-t border-border p-3 flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }}
                placeholder={
                  chatContext.context === 'course'
                     ? t('aiGeneration.chat.coursePlaceholder')
                     : t('aiGeneration.chat.contextPlaceholder', { context: chatContext.context === 'module' ? t('aiGeneration.chat.module') : t('aiGeneration.chat.lesson') })
                }
                disabled={chatSending}
                maxLength={2000}
                className="min-w-0 flex-1 rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none disabled:opacity-50"
              />
              <button
                type="button"
                onClick={sendChat}
                disabled={chatSending || !chatInput.trim()}
                className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                 <span className="hidden sm:inline">{t('aiGeneration.chat.send')}</span>
              </button>
            </div>
          </WorkspacePanel>

          {/* Footer actions */}
          <WorkspaceToolbar className="xl:col-span-2">
            {courseMeta?.status === 'published' && programId && (
              <div className={`mb-4 rounded-xl border p-4 ${programAttachState === 'failed' ? 'border-destructive/30 bg-destructive/5' : 'border-primary/20 bg-primary/5'}`} role="status" aria-live="polite">
                <div className="flex items-start gap-3">
                  {programAttachState === 'attaching' ? <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-primary" /> : programAttachState === 'attached' ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" /> : programAttachState === 'failed' ? <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" /> : <Layers3 className="mt-0.5 h-5 w-5 shrink-0 text-primary" />}
                  <div className="min-w-0 flex-1"><p className="font-medium text-foreground">{t(`ai.programAttach.${programAttachState}` as never)}</p><p className="mt-1 text-sm text-muted-foreground">{programAttachState === 'failed' ? t('ai.programAttach.failedHint' as never) : t('ai.programAttach.hint' as never)}</p></div>
                </div>
                <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                  {(programAttachState === 'idle' || programAttachState === 'failed') && <button type="button" onClick={() => { const courseId = currentJob.course_id; if (courseId) void attachPublishedCourseToProgram(courseId); }} className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"><RefreshCw className="h-4 w-4" />{programAttachState === 'failed' ? t('ai.programAttach.retry' as never) : t('ai.programAttach.attach' as never)}</button>}
                  <button type="button" onClick={() => { const targetProgramId = programId; router.push(programAttachState === 'attached' && targetProgramId ? `/learning-paths?program_id=${encodeURIComponent(targetProgramId)}` : '/learning-paths'); }} className="inline-flex items-center justify-center gap-2 rounded-xl border border-border px-4 py-2 text-sm text-foreground hover:bg-muted transition-colors">{programAttachState === 'attached' ? t('ai.programAttach.returnToProgram' as never) : t('ai.programAttach.returnToPrograms' as never)}<ChevronRight className="h-4 w-4" /></button>
                </div>
              </div>
            )}
            {programId && courseMeta?.review_status === 'approved' && courseMeta?.status !== 'published' && (
              <button
                onClick={publishCourse}
                disabled={publishSubmitting}
                className="flex-1 min-w-[180px] inline-flex items-center justify-center gap-1.5 rounded-xl bg-success px-4 py-3 text-sm font-medium text-success-foreground hover:bg-success/90 transition-colors disabled:opacity-50"
              >
                {publishSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
                 {publishSubmitting ? t('aiGeneration.result.publishStarting') : t('aiGeneration.result.publish')}
              </button>
            )}
            {courseMeta?.status === 'published' && !programId && (
              <button
                onClick={() => router.push(`/assignments?courseId=${encodeURIComponent(currentJob.course_id!)}`)}
                className="flex-1 min-w-[180px] inline-flex items-center justify-center gap-1.5 rounded-xl bg-success px-4 py-3 text-sm font-medium text-success-foreground hover:bg-success/90 transition-colors"
              >
                 {t('aiGeneration.result.assign')} <ChevronRight className="w-4 h-4" />
              </button>
            )}
            {courseMeta?.status === 'published' && <button
              onClick={() => router.push(`/courses/${currentJob.course_id}/edit`)}
              className="flex-1 min-w-[180px] inline-flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
               {t('aiGeneration.result.edit')} <ChevronRight className="w-4 h-4" />
            </button>}
            <button
              onClick={() => router.push('/courses')}
              className="rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground hover:bg-muted transition-colors"
            >
               {t('aiGeneration.result.allCourses')}
            </button>
          </WorkspaceToolbar>
        </div>
      )}

      {reuseDialog.open && (
        <SourceReuseDialog
          courses={reuseDialog.courses}
          reason={reuseDialog.reason}
          submitting={generationSubmitting}
          onReasonChange={(reason) => setReuseDialog((dialog) => ({ ...dialog, reason }))}
          onCancel={() => {
            setAcknowledgements({ languageConfirmed: false, reuseReason: null });
            setReuseDialog({ open: false, courses: [], reason: null });
          }}
          onConfirm={(reason) => void handleGenerate(reason)}
        />
      )}

      {languageConfirmation.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="mixed-language-title">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-card shadow-card-lg">
            <div className="border-b border-border px-5 py-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
                <div>
                  <h3 id="mixed-language-title" className="font-bold text-foreground font-display">{t('aiGeneration.language.title')}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t('aiGeneration.language.description')}
                  </p>
                </div>
              </div>
            </div>
            <div className="space-y-4 px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('aiGeneration.language.detected')}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {languageConfirmation.detectedLanguages.map((detectedLanguage) => (
                    <span key={detectedLanguage} className="rounded-full border border-border bg-muted px-3 py-1 text-sm text-foreground">
                      {t(`aiGeneration.language.${detectedLanguage}` as never)}
                    </span>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm text-foreground">
                {t('aiGeneration.language.courseLanguage', { language: t(`aiGeneration.language.${language}` as never) })}
                {' '}{t('aiGeneration.language.hint')}
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
              <button
                type="button"
                onClick={() => {
                  setAcknowledgements({ languageConfirmed: false, reuseReason: null });
                  setLanguageConfirmation((dialog) => ({ ...dialog, open: false }));
                }}
                disabled={generationSubmitting}
                className="rounded-xl border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
              >
                {t('aiGeneration.language.back')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setLanguageConfirmation((dialog) => ({ ...dialog, open: false }));
                  void handleGenerate(undefined, true);
                }}
                disabled={generationSubmitting}
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {generationSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                {t('aiGeneration.language.confirm')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Review confirmation dialog */}
      {reviewDialog.open && currentJob?.course_id && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-2xl border border-border bg-card shadow-card-lg">
            <div className="border-b border-border px-5 py-4">
              <h3 className="font-bold text-foreground font-display">
                {reviewDialog.status === 'approved' ? t('aiGeneration.reviewDialog.approveTitle') : t('aiGeneration.reviewDialog.changesTitle')}
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                {reviewDialog.status === 'approved'
                  ? t('aiGeneration.reviewDialog.approveDescription')
                  : t('aiGeneration.reviewDialog.changesDescription')}
              </p>
            </div>
            <div className="px-5 py-4">
              <label htmlFor="review-comment" className="block text-xs font-semibold text-muted-foreground mb-1">
                {t('aiGeneration.reviewDialog.comment')}
              </label>
              <textarea
                id="review-comment"
                value={reviewDialog.comment}
                onChange={(e) => setReviewDialog((d) => ({ ...d, comment: e.target.value }))}
                maxLength={2000}
                rows={4}
                placeholder={reviewDialog.status === 'needs_changes' ? t('aiGeneration.reviewDialog.changesPlaceholder') : t('aiGeneration.reviewDialog.generalPlaceholder')}
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
              />
            </div>
            <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
              <button
                type="button"
                onClick={() => setReviewDialog({ open: false, status: 'approved', comment: '' })}
                disabled={reviewSubmitting}
                className="rounded-xl border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
              >
                {t('aiGeneration.reviewDialog.cancel')}
              </button>
              <button
                type="button"
                onClick={submitReview}
                disabled={reviewSubmitting}
                className={
                  reviewDialog.status === 'approved'
                    ? 'rounded-xl bg-success px-4 py-2 text-sm font-medium text-success-foreground hover:bg-success/90 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5'
                    : 'rounded-xl bg-warning px-4 py-2 text-sm font-medium text-warning-foreground hover:bg-warning/90 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5'
                }
              >
                {reviewSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                {reviewDialog.status === 'approved' ? t('aiGeneration.reviewDialog.approve') : t('aiGeneration.reviewDialog.send')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Regenerate confirmation dialog */}
      {regenDialog.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-2xl border border-border bg-card shadow-card-lg">
            <div className="border-b border-border px-5 py-4">
              <h3 className="font-bold text-foreground font-display">
                {t('aiGeneration.regenerateDialog.title', { kind: regenDialog.kind === 'module' ? t('aiGeneration.regenerateDialog.module') : t('aiGeneration.regenerateDialog.lesson') })}
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5 truncate">
                «{regenDialog.target_title}»
              </p>
            </div>
            <div className="px-5 py-4 space-y-3">
              <div>
                <label htmlFor="regen-guidance" className="block text-xs font-semibold text-muted-foreground mb-1">
                  {t('aiGeneration.regenerateDialog.guidance')}
                </label>
                <textarea
                  id="regen-guidance"
                  value={regenDialog.guidance}
                  onChange={(e) => setRegenDialog((d) => ({ ...d, guidance: e.target.value }))}
                  maxLength={1000}
                  rows={3}
                  placeholder={t('aiGeneration.regenerateDialog.placeholder')}
                  className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
                />
              </div>
              {regenDialog.kind === 'lesson' && (
                <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
                  <input
                    type="checkbox"
                    checked={regenDialog.regenerate_quiz}
                    onChange={(e) => setRegenDialog((d) => ({ ...d, regenerate_quiz: e.target.checked }))}
                    className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
                  />
                  {t('aiGeneration.regenerateDialog.quiz')}
                </label>
              )}
              <p className="text-[11px] text-muted-foreground italic">
                {t('aiGeneration.regenerateDialog.warning')}
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
              <button
                type="button"
                onClick={() => setRegenDialog({ open: false, kind: 'module', target_id: '', target_title: '', guidance: '', regenerate_quiz: true })}
                disabled={reviewSubmitting}
                className="rounded-xl border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
              >
                {t('aiGeneration.regenerateDialog.cancel')}
              </button>
              <button
                type="button"
                onClick={submitRegenerate}
                disabled={reviewSubmitting}
                className="inline-flex items-center gap-1.5 rounded-xl bg-warning px-4 py-2 text-sm font-medium text-warning-foreground hover:bg-warning/90 transition-colors disabled:opacity-50"
              >
                {reviewSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                <RefreshCw className="w-4 h-4" />
                {t('aiGeneration.regenerateDialog.start')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Regenerate progress banner (inline, while running) */}
      {regenJob && (
        <div className="fixed bottom-4 right-4 z-30 max-w-sm rounded-2xl border border-warning/30 bg-card shadow-card-lg p-4 space-y-2" role="status" aria-live="polite">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-warning" />
            <span className="text-sm font-medium text-foreground">
               {t('aiGeneration.regenerateDialog.progress', { kind: regenJob.target_kind === 'module' ? t('aiGeneration.regenerateDialog.module') : t('aiGeneration.regenerateDialog.lesson') })}
            </span>
          </div>
          <div className="h-2 bg-muted rounded overflow-hidden">
            <div
              className="h-2 bg-warning rounded transition-all"
              style={{ width: `${regenJob.progress || 5}%` }}
            />
          </div>
          <div className="text-[11px] text-muted-foreground">
             {regenJob.stage} · {regenJob.progress}%
          </div>
        </div>
      )}
    </WorkspacePage>
  );
}
