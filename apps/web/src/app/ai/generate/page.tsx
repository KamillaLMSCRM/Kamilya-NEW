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
  { key: 'ingestion', label: 'Обработка документов', icon: FileText, color: 'text-blue-500' },
  { key: 'architect', label: 'Проектирование структуры', icon: Building2, color: 'text-gold-500' },
  { key: 'content_generation', label: 'Генерация контента', icon: PenLine, color: 'text-primary' },
  { key: 'review', label: 'Проверка качества', icon: Search, color: 'text-violet-500' },
  { key: 'assessment', label: 'Генерация тестов', icon: ClipboardCheck, color: 'text-emerald-500' },
  { key: 'saving', label: 'Сохранение', icon: Save, color: 'text-warm-500' },
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
      if (res.data.status === 'running' || res.data.status === 'pending') {
        setCurrentJob(res.data);
        setStep('generate');
      } else {
        localStorage.removeItem('ai_active_job_id');
      }
    } catch {
      localStorage.removeItem('ai_active_job_id');
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
        } else if (res.data.status === 'failed') {
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
      <h1 className="text-2xl font-bold text-warm-800 font-display">{t('ai.title')}</h1>

      {/* Step indicator */}
      <div className="flex items-center gap-4">
        {stepConfig.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${
              step === s.key ? 'bg-primary text-white' : 'bg-warm-100 text-warm-400'
            }`}>
              {s.num}
            </div>
            <span className={`text-sm font-medium ${step === s.key ? 'text-warm-800' : 'text-warm-400'}`}>
              {s.label}
            </span>
            {i < stepConfig.length - 1 && <div className="w-8 h-px bg-warm-200 ml-2" />}
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
              dragOver ? 'border-primary bg-primary/5' : 'border-warm-200 hover:border-warm-300 hover:bg-warm-50'
            }`}
          >
            <input ref={fileRef} type="file" multiple onChange={(e) => {
              Array.from(e.target.files || []).forEach(uploadFile);
            }} className="hidden" accept=".pdf,.doc,.docx,.txt,.md,.pptx,.xlsx,.csv" />
            <div className="text-2xl mb-2 text-warm-400">
              {uploading ? <Loader2 className="w-8 h-8 mx-auto animate-spin" /> : <FolderOpen className="w-8 h-8 mx-auto" />}
            </div>
            <p className="text-sm text-warm-500">
              {uploading ? 'Загрузка...' : 'Перетащите документы или нажмите для выбора'}
            </p>
          </div>

          {/* Documents list */}
          {documents.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-warm-400 uppercase tracking-wider px-1">
                Загруженные документы ({selectedDocIds.length} выбрано)
              </div>
              {documents.map(doc => (
                <label
                  key={doc.id}
                  className={`flex items-center gap-3 rounded-xl border p-3 cursor-pointer transition-all ${
                    selectedDocIds.includes(doc.id)
                      ? 'border-primary bg-primary/5'
                      : 'border-warm-100 hover:border-warm-200'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocIds.includes(doc.id)}
                    onChange={() => toggleDoc(doc.id)}
                    className="h-4 w-4 rounded border-warm-300 text-primary focus:ring-primary"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-warm-800 truncate">{doc.title}</div>
                    {doc.description && <div className="text-xs text-warm-400 truncate">{doc.description}</div>}
                  </div>
                  <div className="text-xs text-warm-300 shrink-0">{doc.filename}</div>
                </label>
              ))}
            </div>
          )}

          {/* Config */}
          <div className="rounded-2xl border border-warm-100 bg-white p-5 space-y-4">
            <h3 className="font-bold text-warm-800 font-display">Настройки генерации</h3>
            <div>
              <label className="block text-xs font-semibold text-warm-500 mb-1">{t('ai.targetAudience')}</label>
              <textarea
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
                rows={2}
                placeholder={t('ai.targetAudiencePlaceholder')}
                className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-warm-500 mb-1">{t('ai.numModules')}</label>
                <input
                  type="number" min={1} max={10}
                  value={numModules}
                  onChange={(e) => setNumModules(parseInt(e.target.value) || 3)}
                  className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-warm-500 mb-1">{t('ai.language')}</label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors"
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
          <div className="rounded-2xl border border-warm-100 bg-white p-6">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-bold text-warm-800">{t('ai.progress')}</span>
              <span className="text-sm font-bold text-primary">{currentJob.progress}%</span>
            </div>
            <div className="h-2 bg-warm-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-primary to-gold-500 rounded-full transition-all duration-500"
                style={{ width: `${currentJob.progress}%` }}
              />
            </div>
            <p className="text-xs text-warm-400 mt-2">{currentJob.message}</p>
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
                    isDone ? 'border-emerald-200 bg-emerald-50' :
                    'border-warm-100 opacity-50'
                  }`}
                >
                  <div className={`${isDone ? 'text-emerald-500' : isActive ? stage.color : 'text-warm-300'}`}>
                    {isDone ? <CheckCircle2 className="w-5 h-5" /> : <stage.icon className="w-5 h-5" />}
                  </div>
                  <span className={`text-sm font-medium ${isDone ? 'text-emerald-600' : isActive ? 'text-warm-800' : 'text-warm-400'}`}>
                    {stage.label}
                  </span>
                  {isActive && (
                    <div className="ml-auto h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  )}
                </div>
              );
            })}
          </div>

          {currentJob.status === 'completed' && currentJob.course_id && (
            <button
              onClick={() => router.push(`/courses/${currentJob.course_id}/edit`)}
              className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-white hover:bg-primary/90 transition-colors"
            >
              Открыть курс <ChevronRight className="w-4 h-4 ml-1 inline" />
            </button>
          )}

          {currentJob.status === 'failed' && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
              Ошибка: {currentJob.message}
            </div>
          )}
        </div>
      )}

      {/* STEP 3: Review */}
      {step === 'review' && currentJob?.course_id && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 text-center">
            <div className="mb-3">
              <CheckCircle2 className="w-12 h-12 mx-auto text-emerald-500" />
            </div>
            <h3 className="font-bold text-emerald-800 font-display text-lg">Курс успешно сгенерирован!</h3>
            <p className="text-sm text-emerald-600 mt-1">Перейдите к редактированию для финальных правок</p>
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
              className="rounded-xl border border-warm-200 px-4 py-3 text-sm text-warm-500 hover:bg-warm-50 transition-colors"
            >
              Все курсы
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
