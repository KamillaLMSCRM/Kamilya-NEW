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
  ChevronRight,
  XCircle,
} from 'lucide-react';

interface Document {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size: number;
  description: string;
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
                    {doc.description && <div className="text-xs text-muted-foreground truncate">{doc.description}</div>}
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
          <div className="rounded-2xl border border-success/40 bg-success/10 p-6 text-center">
            <div className="mb-3">
              <CheckCircle2 className="w-12 h-12 mx-auto text-success" />
            </div>
            <h3 className="font-bold text-success font-display text-lg">Курс успешно сгенерирован!</h3>
            <p className="text-sm text-success mt-1">Перейдите к редактированию для финальных правок</p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => router.push(`/courses/${currentJob.course_id}/edit`)}
              className="flex-1 rounded-xl bg-primary px-4 py-3 text-sm font-medium text-white hover:bg-primary/90 transition-colors"
            >
              Редактировать курс <ChevronRight className="w-4 h-4 ml-1 inline" />
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
    </div>
  );
}
