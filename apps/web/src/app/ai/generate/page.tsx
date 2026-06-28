'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
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
} from 'lucide-react';
import { ReviewBadge, CoursePreviewTree } from './components/CoursePreview';

interface Document {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size: number;
  description: string;
  short_summary?: string | null;
  summary_ready?: boolean;
}

interface AIGenerationJob {
  id: string;
  status: string;
  course_id: string | null;
  progress: number;
  stage: string;
  message: string;
}

type Step = 'documents' | 'generate' | 'review';

const STAGES = [
  { key: 'ingestion', label: 'Обработка документов', icon: FileText, color: 'text-primary' },
  { key: 'architect', label: 'Проектирование структуры', icon: Building2, color: 'text-accent' },
  { key: 'content_generation', label: 'Генерация контента', icon: PenLine, color: 'text-primary' },
  { key: 'review', label: 'Проверка качества', icon: Search, color: 'text-accent' },
  { key: 'assessment', label: 'Генерация тестов', icon: ClipboardCheck, color: 'text-success' },
  { key: 'saving', label: 'Сохранение', icon: Save, color: 'text-muted-foreground' },
];

export default function AIGeneratePage() {
  const { t } = useT();
  const router = useRouter();
  const token = useAuthStore((s) => s.accessToken);

  const [step, setStep] = useState<Step>('documents');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [targetAudience, setTargetAudience] = useState('');
  const [numModules, setNumModules] = useState(3);
  const [language, setLanguage] = useState('ru');
  const [currentJob, setCurrentJob] = useState<AIGenerationJob | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Result-step state: preview of the generated course + approval.
  const [preview, setPreview] = useState<any | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [courseMeta, setCourseMeta] = useState<any | null>(null); // includes review_status, reviewer
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
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

  useEffect(() => { fetchDocuments(); restoreActiveJob(); }, []);

  const restoreActiveJob = async () => {
    const savedJobId = localStorage.getItem('ai_active_job_id');
    if (!savedJobId) return;
    try {
      const res = await api.get(`/v1/ai/jobs/${savedJobId}`);
      const status = res.data.status;
      if (status === 'running' || status === 'pending') {
        setCurrentJob(res.data);
        setStep('generate');
      } else {
        // Backend confirmed terminal state — safe to drop reference
        localStorage.removeItem('ai_active_job_id');
      }
    } catch (err: any) {
      // Transient network error — keep the id in localStorage and try again
      // on the next polling tick (Layout.tsx also polls globally). Only drop
      // if the backend confirms 404 (job truly gone).
      if (err?.response?.status === 404) {
        localStorage.removeItem('ai_active_job_id');
      }
    }
  };

  const fetchDocuments = async () => {
    try {
      const res = await api.get('/v1/documents');
      setDocuments(Array.isArray(res.data) ? res.data : []);
    } catch {}
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await uploadFile(file);
    }
  };

  const uploadFile = async (file: File) => {
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', file.name.replace(/\.[^/.]+$/, ''));
    try {
      await api.post('/v1/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      await fetchDocuments();
    } catch (e) {
      console.error('Upload failed', e);
    } finally {
      setUploading(false);
    }
  };

  const toggleDoc = (id: string) => {
    setSelectedDocIds(prev => prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id]);
  };

  const handleGenerate = async () => {
    try {
      const res = await api.post('/v1/ai/generate-course', {
        documents: selectedDocIds,
        target_audience: targetAudience,
        num_modules: numModules,
        language,
      });
      setCurrentJob(res.data);
      localStorage.setItem('ai_active_job_id', res.data.id);
      setStep('generate');
    } catch (e) {
      console.error('Generation failed', e);
    }
  };

  const handleCancel = async () => {
    if (!currentJob) return;
    try {
      await api.post(`/v1/ai/jobs/${currentJob.id}/cancel`);
      localStorage.removeItem('ai_active_job_id');
      setCurrentJob(null);
      setStep('documents');
    } catch (e) {
      console.error('Cancel failed', e);
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
      setReviewDialog({ open: false, status: 'approved', comment: '' });
    } catch (e) {
      console.error('Review submit failed', e);
    } finally {
      setReviewSubmitting(false);
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
        { role: 'assistant', content: `⚠️ Ошибка: ${e?.response?.data?.detail || e?.message || 'неизвестно'}`, at: Date.now() },
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
      alert(`Не удалось применить: ${e?.response?.data?.detail || e?.message || 'неизвестно'}`);
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
      alert(`Не удалось запустить перегенерацию: ${e?.response?.data?.detail || e?.message || 'неизвестно'}`);
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
          alert(`Перегенерация ${res.data.status}: ${res.data.message || ''}`);
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
  const startEditLesson = (lessonId: string, lessonTitle: string, lessonContent: string) => {
    setEditingLessonId(lessonId);
    setEditForm({ title: lessonTitle, content: lessonContent });
  };
  const cancelEditLesson = () => {
    setEditingLessonId(null);
    setEditForm({ title: '', content: '' });
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
      alert(`Не удалось сохранить: ${e?.response?.data?.detail || e?.message || 'неизвестно'}`);
    } finally {
      setEditSaving(false);
    }
  };

  // Poll job status
  useEffect(() => {
    if (!currentJob || currentJob.status === 'completed' || currentJob.status === 'failed') return;
    const interval = setInterval(async () => {
      try {
        const res = await api.get(`/v1/ai/jobs/${currentJob.id}`);
        setCurrentJob(res.data);
        if (res.data.status === 'completed') {
          localStorage.removeItem('ai_active_job_id');
          setStep('review');
        } else if (res.data.status === 'failed' || res.data.status === 'cancelled') {
          localStorage.removeItem('ai_active_job_id');
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [currentJob]);

  const getStageIndex = (stageKey: string) => STAGES.findIndex(s => s.key === stageKey);

  const stepConfig = [
    { key: 'documents', label: 'Документы', num: 1 },
    { key: 'generate', label: 'Генерация', num: 2 },
    { key: 'review', label: 'Результат', num: 3 },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-foreground font-display">{t('ai.title')}</h1>

      {/* Step indicator */}
      <div className="flex items-center gap-4">
        {stepConfig.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${
              step === s.key ? 'bg-primary text-white' : 'bg-muted text-muted-foreground'
            }`}>
              {s.num}
            </div>
            <span className={`text-sm font-medium ${step === s.key ? 'text-foreground' : 'text-muted-foreground'}`}>
              {s.label}
            </span>
            {i < stepConfig.length - 1 && <div className="w-8 h-px bg-muted ml-2" />}
          </div>
        ))}
      </div>

      {/* STEP 1: Documents */}
      {step === 'documents' && (
        <div className="space-y-4">
          {/* Upload zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`rounded-2xl border-2 border-dashed p-6 text-center cursor-pointer transition-all ${
              dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-border hover:bg-muted'
            }`}
          >
            <input ref={fileRef} type="file" multiple onChange={(e) => {
              Array.from(e.target.files || []).forEach(uploadFile);
            }} className="hidden" accept=".pdf,.doc,.docx,.txt,.md,.pptx,.xlsx,.csv" />
            <div className="text-2xl mb-2 text-muted-foreground">
              {uploading ? <Loader2 className="w-8 h-8 mx-auto animate-spin" /> : <FolderOpen className="w-8 h-8 mx-auto" />}
            </div>
            <p className="text-sm text-muted-foreground">
              {uploading ? 'Загрузка...' : 'Перетащите документы или нажмите для выбора'}
            </p>
          </div>

          {/* Documents list */}
          {documents.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">
                Загруженные документы ({selectedDocIds.length} выбрано)
              </div>
              {documents.map(doc => (
                <label
                  key={doc.id}
                  className={`flex items-center gap-3 rounded-xl border p-3 cursor-pointer transition-all ${
                    selectedDocIds.includes(doc.id)
                      ? 'border-primary bg-primary/5'
                      : 'border-border hover:border-border'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocIds.includes(doc.id)}
                    onChange={() => toggleDoc(doc.id)}
                    className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">{doc.title}</div>
                    {doc.short_summary ? (
                      <div className="text-xs text-primary/80 truncate italic">
                        {doc.summary_ready ? '📄 ' : '⚠️ '}{doc.short_summary}
                      </div>
                    ) : doc.description ? (
                      <div className="text-xs text-muted-foreground truncate">{doc.description}</div>
                    ) : null}
                  </div>
                  <div className="text-xs text-muted-foreground shrink-0">{doc.filename}</div>
                </label>
              ))}
            </div>
          )}

          {/* Config */}
          <div className="rounded-2xl border border-border bg-card p-5 space-y-4">
            <h3 className="font-bold text-foreground font-display">Настройки генерации</h3>
            <div>
              <label className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.targetAudience')}</label>
              <textarea
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
                rows={2}
                placeholder={t('ai.targetAudiencePlaceholder')}
                className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.numModules')}</label>
                <input
                  type="number" min={1} max={10}
                  value={numModules}
                  onChange={(e) => setNumModules(parseInt(e.target.value) || 3)}
                  className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">{t('ai.language')}</label>
                <select
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
          </div>

          <button
            onClick={handleGenerate}
            disabled={selectedDocIds.length === 0}
            className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {t('ai.generate')} ({selectedDocIds.length} документов)
          </button>
        </div>
      )}

      {/* STEP 2: Generation progress */}
      {step === 'generate' && currentJob && (
        <div className="space-y-6">
          {/* Progress bar */}
          <div className="rounded-2xl border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-bold text-foreground">{t('ai.progress')}</span>
              <span className="text-sm font-bold text-primary">{currentJob.progress}%</span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-primary to-gold-500 rounded-full transition-all duration-500"
                style={{ width: `${currentJob.progress}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-2">{currentJob.message}</p>
          </div>

          {/* Stages */}
          <div className="space-y-2">
            {STAGES.map((stage, i) => {
              const isAllDone = currentJob.stage === 'completed' || currentJob.status === 'completed';
              const currentIdx = getStageIndex(currentJob.stage);
              const stageIdx = getStageIndex(stage.key);
              const isActive = !isAllDone && currentJob.stage === stage.key;
              const isDone = isAllDone || stageIdx < currentIdx;

              return (
                <div
                  key={stage.key}
                  className={`flex items-center gap-3 rounded-xl border p-3 transition-all ${
                    isActive ? 'border-primary bg-primary/5 shadow-sm' :
                    isDone ? 'border-success/40 bg-success/10' :
                    'border-border opacity-50'
                  }`}
                >
                  <div className={`${isDone ? 'text-success' : isActive ? stage.color : 'text-muted-foreground'}`}>
                    {isDone ? <CheckCircle2 className="w-5 h-5" /> : <stage.icon className="w-5 h-5" />}
                  </div>
                  <span className={`text-sm font-medium ${isDone ? 'text-success' : isActive ? 'text-foreground' : 'text-muted-foreground'}`}>
                    {stage.label}
                  </span>
                  {isActive && (
                    <div className="ml-auto h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  )}
                </div>
              );
            })}
          </div>

          {/* Cancel button */}
          {currentJob.status === 'running' && (
            <button
              onClick={handleCancel}
              className="w-full rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive hover:bg-destructive/15 transition-colors flex items-center justify-center gap-2"
            >
              <XCircle className="w-4 h-4" />
              Отменить генерацию
            </button>
          )}

          {currentJob.status === 'completed' && currentJob.course_id && (
            <button
              onClick={() => router.push(`/courses/${currentJob.course_id}/edit`)}
              className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-white hover:bg-primary/90 transition-colors"
            >
              Открыть курс <ChevronRight className="w-4 h-4 ml-1 inline" />
            </button>
          )}

          {currentJob.status === 'failed' && (
            <div className="rounded-2xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
              Ошибка: {currentJob.message}
            </div>
          )}

          {currentJob.status === 'cancelled' && (
            <div className="rounded-2xl border border-border bg-muted p-4 text-sm text-foreground">
              Генерация отменена
            </div>
          )}
        </div>
      )}

      {/* STEP 3: Review */}
      {step === 'review' && currentJob?.course_id && (
        <div className="space-y-4">
          {/* Success header */}
          <div className="rounded-2xl border border-success/40 bg-success/10 p-6 text-center">
            <div className="mb-3">
              <CheckCircle2 className="w-12 h-12 mx-auto text-success" />
            </div>
            <h3 className="font-bold text-success font-display text-lg">Курс успешно сгенерирован!</h3>
            <p className="text-sm text-success mt-1">
              Проверьте структуру ниже. Методолог должен одобрить курс перед публикацией.
            </p>
          </div>

          {/* Course meta + review status */}
          {courseMeta && (
            <div className="rounded-2xl border border-border bg-card p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <h4 className="text-base font-bold text-foreground font-display flex-1 min-w-0 truncate">
                  {courseMeta.title}
                </h4>
                <ReviewBadge status={courseMeta.review_status} />
              </div>
              <p className="text-sm text-muted-foreground line-clamp-2">{courseMeta.description}</p>

              {/* Reviewer info */}
              {courseMeta.review_status !== 'pending' && courseMeta.reviewer && (
                <div className="text-xs text-muted-foreground border-t border-border pt-3">
                  <span className="font-medium text-foreground">{courseMeta.reviewer.full_name || 'Методолог'}</span>
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
                    onClick={() => setReviewDialog({ open: true, status: 'approved', comment: '' })}
                    disabled={reviewSubmitting}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-success px-3 py-2 text-sm font-medium text-success-foreground hover:bg-success/90 transition-colors disabled:opacity-50"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    Одобрить как методолог
                  </button>
                  <button
                    type="button"
                    onClick={() => setReviewDialog({ open: true, status: 'needs_changes', comment: '' })}
                    disabled={reviewSubmitting}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-warning/50 bg-warning/10 px-3 py-2 text-sm font-medium text-warning hover:bg-warning/15 transition-colors disabled:opacity-50"
                  >
                    <XCircle className="w-4 h-4" />
                    Нужны правки
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Preview: modules → lessons → quiz headers */}
          <div className="rounded-2xl border border-border bg-card overflow-hidden">
            <div className="border-b border-border bg-muted/50 px-4 py-3 flex items-center justify-between">
              <h4 className="text-sm font-bold text-foreground font-display">
                Структура курса
              </h4>
              {preview && (
                <div className="flex gap-3 text-xs text-muted-foreground">
                  <span>{preview.modules_count} модулей</span>
                  <span>·</span>
                  <span>{preview.lessons_count} уроков</span>
                  <span>·</span>
                  <span>{preview.quizzes_count} тестов</span>
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
                Структура пуста. Откройте курс в редакторе для просмотра.
              </div>
            )}
          </div>

          {/* AI Assistant chat panel */}
          <div className="rounded-2xl border border-border bg-card overflow-hidden">
            <div className="border-b border-border bg-muted/50 px-4 py-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 min-w-0">
                <MessageSquare className="w-4 h-4 text-primary shrink-0" />
                <h4 className="text-sm font-bold text-foreground font-display truncate">
                  AI-ассистент методолога
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
                        ? 'Сначала выберите урок или модуль'
                        : undefined
                    }
                  >
                    {ctx === 'course' ? 'Весь курс' : ctx === 'module' ? 'Модуль' : 'Урок'}
                  </button>
                ))}
              </div>
            </div>

            <div className="max-h-72 overflow-y-auto p-4 space-y-3 bg-background">
              {chatMessages.length === 0 ? (
                <div className="text-center py-8 text-sm text-muted-foreground">
                  Спросите AI: «Что спорно в модуле 2?», «Перепиши урок про охрану труда проще», «Сделай тест сложнее».
                  Чтобы сфокусировать на конкретном уроке или модуле — нажмите «Спросить AI» рядом с ним.
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
                            Предложение замены{m.apply_lesson_title_hint ? `: «${m.apply_lesson_title_hint}»` : ''}
                          </div>
                          <div className="text-xs text-muted-foreground line-clamp-4 whitespace-pre-line font-mono">
                            {m.apply_lesson_content}
                          </div>
                          <div className="flex items-center justify-between gap-2 pt-1">
                            <span className="text-[10px] text-muted-foreground">
                              Урок id: {m.apply_lesson_id.slice(0, 8)}…
                            </span>
                            {m.applied_lesson_id === m.apply_lesson_id ? (
                              <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-2 py-1 text-[11px] font-medium text-success">
                                <CheckCircle2 className="w-3 h-3" />
                                Применено
                              </span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => applyChatSuggestion(i, m.apply_lesson_id!, m.apply_lesson_content!)}
                                className="inline-flex items-center gap-1 rounded-md bg-success px-2 py-1 text-[11px] font-medium text-success-foreground hover:bg-success/90 transition-colors"
                              >
                                <CheckCircle2 className="w-3 h-3" />
                                Применить к уроку
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
                    ? 'Спросите что угодно про этот курс…'
                    : `Спросите про ${chatContext.context === 'module' ? 'модуль' : 'урок'}…`
                }
                disabled={chatSending}
                maxLength={2000}
                className="flex-1 rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none disabled:opacity-50"
              />
              <button
                type="button"
                onClick={sendChat}
                disabled={chatSending || !chatInput.trim()}
                className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                <span className="hidden sm:inline">Отправить</span>
              </button>
            </div>
          </div>

          {/* Footer actions */}
          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => router.push(`/courses/${currentJob.course_id}/edit`)}
              className="flex-1 min-w-[180px] inline-flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Редактировать курс <ChevronRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => router.push('/courses')}
              className="rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground hover:bg-muted transition-colors"
            >
              Все курсы
            </button>
          </div>
        </div>
      )}

      {/* Review confirmation dialog */}
      {reviewDialog.open && currentJob?.course_id && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-2xl border border-border bg-card shadow-card-lg">
            <div className="border-b border-border px-5 py-4">
              <h3 className="font-bold text-foreground font-display">
                {reviewDialog.status === 'approved' ? 'Одобрить курс' : 'Курс требует правок'}
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                {reviewDialog.status === 'approved'
                  ? 'Курс будет помечен как одобренный методологом. Это действие фиксируется в audit log.'
                  : 'Методолог может оставить комментарий — курс останется в статусе "нужны правки" пока вы не одобрите.'}
              </p>
            </div>
            <div className="px-5 py-4">
              <label htmlFor="review-comment" className="block text-xs font-semibold text-muted-foreground mb-1">
                Комментарий (опционально)
              </label>
              <textarea
                id="review-comment"
                value={reviewDialog.comment}
                onChange={(e) => setReviewDialog((d) => ({ ...d, comment: e.target.value }))}
                maxLength={2000}
                rows={4}
                placeholder={reviewDialog.status === 'needs_changes' ? 'Что нужно поправить…' : 'Любые замечания…'}
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
                Отмена
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
                {reviewDialog.status === 'approved' ? 'Одобрить' : 'Отправить'}
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
                Перегенерировать {regenDialog.kind === 'module' ? 'модуль' : 'урок'}
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5 truncate">
                «{regenDialog.target_title}»
              </p>
            </div>
            <div className="px-5 py-4 space-y-3">
              <div>
                <label htmlFor="regen-guidance" className="block text-xs font-semibold text-muted-foreground mb-1">
                  Что поправить (опционально)
                </label>
                <textarea
                  id="regen-guidance"
                  value={regenDialog.guidance}
                  onChange={(e) => setRegenDialog((d) => ({ ...d, guidance: e.target.value }))}
                  maxLength={1000}
                  rows={3}
                  placeholder="Например: «Добавь больше примеров», «Сделай тон проще», «Убери устаревшие ссылки»"
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
                  Перегенерировать тест (3 вопроса)
                </label>
              )}
              <p className="text-[11px] text-muted-foreground italic">
                Текущий контент будет заменён. Действие нельзя отменить (можно начать новую генерацию).
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
              <button
                type="button"
                onClick={() => setRegenDialog({ open: false, kind: 'module', target_id: '', target_title: '', guidance: '', regenerate_quiz: true })}
                disabled={reviewSubmitting}
                className="rounded-xl border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={submitRegenerate}
                disabled={reviewSubmitting}
                className="inline-flex items-center gap-1.5 rounded-xl bg-warning px-4 py-2 text-sm font-medium text-warning-foreground hover:bg-warning/90 transition-colors disabled:opacity-50"
              >
                {reviewSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                <RefreshCw className="w-4 h-4" />
                Запустить
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
              Перегенерация {regenJob.target_kind === 'module' ? 'модуля' : 'урока'}
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
    </div>
  );
}
