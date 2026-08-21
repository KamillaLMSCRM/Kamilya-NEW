'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, Check, ChevronLeft, ChevronRight, Info, ShieldCheck } from 'lucide-react';

import { Button, Input } from '@/components/ui';
import { LoadError } from '@/components/ui/LoadError';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import {
  adaptationResumeStep,
  buildAdaptationSteps,
  completedAnswerCount,
  firstIncompleteStep,
  firstMissingAnswer,
} from '@/lib/blueprintAdaptation';
import {
  isDocumentSelectable,
  type DocumentCatalogItem,
  type DocumentCatalogResponse,
} from '@/lib/documentCatalog';

type BlueprintLocale = 'ru' | 'kk';

interface ChecklistItem {
  id: string;
  title: string;
  description: string;
  required: boolean;
  answer_placeholder: string;
}

interface CourseBlueprint {
  id: string;
  version: string;
  locale: BlueprintLocale;
  title: string;
  description: string;
  audience: string;
  applicability?: string;
  compliance_mode?: 'lms_only' | 'blended' | 'external_certified';
  tags?: string[];
  estimated_ready_percent: number;
  customization_percent: number;
  module_count: number;
  lesson_count: number;
  quiz_question_count: number;
  checklist: ChecklistItem[];
  limitations: string[];
}

interface AdaptationSnapshot {
  locale: BlueprintLocale;
  answers: Record<string, string>;
  source_document_ids: string[];
}

interface InstantiationResponse {
  course_id: string;
  readiness_percent: number;
  edit_url: string;
  adaptation_url: string;
}

function BlueprintPageContent() {
  const { t, lang } = useT();
  const params = useParams<{ blueprintId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const blueprintId = params.blueprintId;
  const courseId = searchParams.get('course_id');
  const requestedLocale: BlueprintLocale = lang === 'kk' ? 'kk' : 'ru';

  const [blueprint, setBlueprint] = useState<CourseBlueprint | null>(null);
  const [documents, setDocuments] = useState<DocumentCatalogItem[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [saving, setSaving] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [validationError, setValidationError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const blueprintResponse = await api.get<CourseBlueprint>(
        `/v1/course-blueprints/${encodeURIComponent(blueprintId)}?locale=${requestedLocale}`,
      );
      const [documentsResult, adaptationResult, courseResult] = await Promise.allSettled([
        api.get<DocumentCatalogResponse>('/v1/documents/catalog?limit=100&lifecycle_status=active'),
        courseId
          ? api.get<AdaptationSnapshot>(`/v1/courses/${courseId}/blueprint-adaptation`)
          : Promise.resolve(null),
        courseId ? api.get<{ title: string }>(`/v1/courses/${courseId}`) : Promise.resolve(null),
      ]);

      setBlueprint(blueprintResponse.data);
      setTitle(
        courseResult.status === 'fulfilled' && courseResult.value
          ? courseResult.value.data.title
          : blueprintResponse.data.title,
      );
      if (documentsResult.status === 'fulfilled') {
        setDocuments(documentsResult.value.data.items.filter(isDocumentSelectable));
      }
      if (adaptationResult.status === 'fulfilled' && adaptationResult.value) {
        const restoredAnswers = adaptationResult.value.data.answers || {};
        setAnswers(restoredAnswers);
        setCurrentStep(adaptationResumeStep(blueprintResponse.data.checklist, restoredAnswers));
        setSelectedDocumentIds(adaptationResult.value.data.source_document_ids || []);
      } else {
        setAnswers({});
        setCurrentStep(0);
        setSelectedDocumentIds([]);
      }
    } catch (error) {
      console.error('Course blueprint load failed', error);
      setLoadError(t('courses.blueprint.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [blueprintId, courseId, requestedLocale, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const completedCount = useMemo(
    () => blueprint ? completedAnswerCount(blueprint.checklist, answers) : 0,
    [answers, blueprint],
  );
  const readiness = blueprint
    ? Math.min(
        100,
        blueprint.estimated_ready_percent
          + Math.round(blueprint.customization_percent * completedCount / Math.max(1, blueprint.checklist.length)),
      )
    : 0;
  const requiredCount = blueprint?.checklist.filter((item) => item.required).length || 0;
  const allRequiredComplete = completedCount === requiredCount;
  const adaptationSteps = useMemo(() => buildAdaptationSteps(blueprint?.checklist || []), [blueprint]);
  const activeStep = adaptationSteps[currentStep] || adaptationSteps[0];
  const isFinanceBlueprint = blueprint?.id === 'kz-finance-information-security';
  const activeItems = blueprint?.checklist.filter((item) => activeStep?.itemIds.includes(item.id)) || [];

  const firstMissingId = (stepIndex: number) => {
    return firstMissingAnswer(adaptationSteps[stepIndex], blueprint?.checklist || [], answers);
  };

  const focusField = (fieldId: string) => {
    window.requestAnimationFrame(() => {
      document.getElementById(`blueprint-answer-${fieldId}`)?.focus();
    });
  };

  const continueToNextStep = () => {
    const missingId = firstMissingId(currentStep);
    if (missingId) {
      setValidationError(t('courses.blueprint.completeCurrentStep'));
      focusField(missingId);
      return;
    }
    setValidationError('');
    setCurrentStep((step) => Math.min(step + 1, adaptationSteps.length - 1));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const toggleDocument = (documentId: string) => {
    setSelectedDocumentIds((current) => (
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId]
    ));
  };

  const save = async (requireComplete: boolean) => {
    if (!blueprint) return;
    const incompleteStep = firstIncompleteStep(blueprint.checklist, answers);
    if (requireComplete && incompleteStep >= 0) {
      setCurrentStep(incompleteStep);
      setValidationError(t('courses.blueprint.completeAllRequired'));
      const missingId = firstMissingId(incompleteStep);
      if (missingId) focusField(missingId);
      return;
    }
    setSaving(true);
    const payload = {
      locale: blueprint.locale,
      title: title.trim() || blueprint.title,
      answers,
      source_document_ids: selectedDocumentIds,
    };
    try {
      const response = courseId
        ? await api.put<InstantiationResponse>(`/v1/courses/${courseId}/blueprint-adaptation`, payload)
        : await api.post<InstantiationResponse>(
            `/v1/course-blueprints/${encodeURIComponent(blueprint.id)}/instantiate`,
            payload,
          );
      toast.success(courseId ? t('courses.blueprint.updated') : t('courses.blueprint.created'));
      router.push(response.data.edit_url);
    } catch (error: any) {
      const details = error?.response?.data?.details;
      if (details?.code === 'blueprint_already_instantiated' && details.existing_course_id) {
        toast.info(t('courses.blueprint.existing'));
        router.push(`/courses/templates/${blueprint.id}?course_id=${details.existing_course_id}`);
        return;
      }
      toast.error(t('courses.blueprint.saveFailed'), {
        description: details?.message || error?.response?.data?.message || error?.message,
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="flex min-h-80 items-center justify-center text-muted-foreground">{t('common.loading')}</div>;
  }
  if (loadError || !blueprint) {
    return (
      <LoadError
        title={t('courses.blueprint.loadFailed')}
        message={loadError || t('courses.blueprint.loadFailed')}
        retryLabel={t('common.retry')}
        onRetry={() => void load()}
      />
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 pb-12">
      <Link href="/courses" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        {t('courses.blueprint.back')}
      </Link>

      <header className="overflow-hidden rounded-3xl border border-primary/20 bg-gradient-to-br from-primary/15 via-card to-accent/10 p-6 shadow-card sm:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-3xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-sm font-semibold text-primary">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              {t('courses.blueprint.badge')}
            </div>
             <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{blueprint.title}</h1>
             <p className="mt-3 text-muted-foreground">{blueprint.description}</p>
             <p className="mt-3 text-sm font-medium text-foreground">{blueprint.audience}</p>
             {blueprint.applicability && (
               <p className="mt-2 text-sm text-muted-foreground">{blueprint.applicability}</p>
             )}
             {blueprint.compliance_mode && (
               <span className="mt-3 inline-flex rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
                 {blueprint.compliance_mode === 'blended'
                   ? t('courses.blueprint.complianceModes.blended')
                   : blueprint.compliance_mode === 'external_certified'
                     ? t('courses.blueprint.complianceModes.externalCertified')
                     : t('courses.blueprint.complianceModes.lmsOnly')}
               </span>
             )}
          </div>
          <div className="w-full max-w-xs rounded-2xl border bg-card/90 p-5">
            <div className="flex items-end justify-between">
              <span className="text-sm text-muted-foreground">{t('courses.blueprint.readiness')}</span>
              <strong className="text-3xl text-primary">{readiness}%</strong>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${readiness}%` }} />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
              <span>{t('courses.blueprint.basePart')}: {blueprint.estimated_ready_percent}%</span>
              <span>{t('courses.blueprint.tenantPart')}: {completedCount}/{blueprint.checklist.length}</span>
            </div>
          </div>
        </div>
      </header>

      <section className="rounded-2xl border border-primary/20 bg-primary/5 p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
          <div>
            <h2 className="font-bold">{t(isFinanceBlueprint ? 'courses.blueprint.introTitle' : 'courses.blueprint.genericIntroTitle')}</h2>
            <p className="mt-1 text-sm text-foreground">{t(isFinanceBlueprint ? 'courses.blueprint.introBody' : 'courses.blueprint.genericIntroBody')}</p>
            <p className="mt-2 text-sm text-muted-foreground">{t('courses.blueprint.introNotice')}</p>
            <p className="mt-2 text-xs text-muted-foreground">{t('courses.blueprint.introMicrocopy')}</p>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border bg-card p-6 shadow-card">
        <label className="block text-sm font-semibold" htmlFor="blueprint-course-title">{t('courses.blueprint.courseNameOptional')}</label>
        <p className="mt-1 text-xs text-muted-foreground">{t('courses.blueprint.courseNameHint')}</p>
        <Input id="blueprint-course-title" className="mt-2" value={title} onChange={(event) => setTitle(event.target.value)} />
      </section>

       <nav aria-label={t('courses.blueprint.adaptationSteps')} className="grid gap-3">
         {adaptationSteps.map((step, index) => {
          const complete = !firstMissingId(index);
          const active = index === currentStep;
          return (
            <button
              key={step.id}
              type="button"
              onClick={() => {
                if (index <= currentStep || complete) {
                  setCurrentStep(index);
                  setValidationError('');
                }
              }}
              className={`min-w-0 rounded-2xl border p-4 text-left transition ${active ? 'border-primary bg-primary/5 shadow-sm' : complete ? 'border-success/40 bg-success/5' : 'border-border bg-card'}`}
              aria-current={active ? 'step' : undefined}
            >
              <span className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
                <span className={`flex h-6 w-6 items-center justify-center rounded-full ${complete ? 'bg-success text-white' : active ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
                  {complete ? <Check className="h-4 w-4" aria-hidden="true" /> : index + 1}
                </span>
                 {t('courses.blueprint.stepProgress', { current: index + 1, total: adaptationSteps.length })}
              </span>
              <span className="mt-2 block font-semibold">{t(step.titleKey as never)}</span>
            </button>
          );
        })}
      </nav>

      <section className="rounded-2xl border bg-card p-5 shadow-card sm:p-6">
        <div className="flex flex-col gap-2 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-xl font-bold">{t(activeStep.titleKey as never)}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t(activeStep.descriptionKey as never)}</p>
          </div>
          <span className="text-sm font-medium text-primary">
            {t('courses.blueprint.completedRules', { completed: completedCount, total: requiredCount })}
          </span>
        </div>
        <div className="mt-5 space-y-4">
          {activeItems.map((item) => (
            <div key={item.id} className="rounded-2xl border border-border p-4 focus-within:border-primary sm:p-5">
              <label className="block" htmlFor={`blueprint-answer-${item.id}`}>
                <span className="flex flex-wrap items-center gap-2">
                   <span className="font-semibold">{item.title}</span>
                   <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${item.required ? 'bg-warning/10 text-warning-foreground' : 'bg-muted text-muted-foreground'}`}>{item.required ? t('courses.blueprint.requiredLabel') : t('courses.blueprint.optionalLabel')}</span>
                </span>
                <span className="mt-2 block text-sm text-muted-foreground">
                  <strong className="font-medium text-foreground">{t('courses.blueprint.whyLabel')}:</strong>{' '}
                   {item.description}
                </span>
               </label>
               <details className="mt-3 text-sm text-muted-foreground">
                 <summary className="cursor-pointer font-medium text-primary">{t('courses.blueprint.showExample')}</summary>
                 <p className="mt-2 rounded-lg bg-muted/50 p-3">{item.answer_placeholder}</p>
               </details>
               <textarea
                id={`blueprint-answer-${item.id}`}
                required={item.required}
                aria-required={item.required}
                value={answers[item.id] || ''}
                onChange={(event) => {
                  setAnswers((current) => ({ ...current, [item.id]: event.target.value }));
                  setValidationError('');
                }}
                placeholder={item.answer_placeholder}
                rows={3}
                maxLength={4000}
                className="mt-4 w-full resize-y rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
              <p className="mt-2 text-xs text-muted-foreground">{t('courses.blueprint.notApplicableHint')}</p>
            </div>
          ))}
          {!activeItems.length && (
            <p className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
              {t('courses.blueprint.checklistEmpty')}
            </p>
          )}
        </div>
      </section>

      {currentStep === adaptationSteps.length - 1 && (
        <section className="rounded-2xl border border-dashed bg-muted/20 p-5 sm:p-6">
          <h2 className="text-lg font-bold">{t('courses.blueprint.documentsOptional')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t('courses.blueprint.documentsOptionalHint')}</p>
          {documents.length ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {documents.map((document) => (
                <label key={document.id} className="flex cursor-pointer items-start gap-3 rounded-xl border bg-card p-3 hover:border-primary/50">
                  <input type="checkbox" className="mt-1" checked={selectedDocumentIds.includes(document.id)} onChange={() => toggleDocument(document.id)} />
                  <span className="min-w-0"><span className="block truncate text-sm font-medium">{document.title}</span><span className="block truncate text-xs text-muted-foreground">{document.filename} · v{document.version}</span></span>
                </label>
              ))}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed bg-card p-5 text-sm text-muted-foreground">
              {t('courses.blueprint.noDocumentsOptional')}{' '}
              <Link href="/documents" className="font-medium text-primary hover:underline">{t('courses.blueprint.uploadDocuments')}</Link>
            </div>
          )}
        </section>
      )}

      {currentStep === adaptationSteps.length - 1 && <section className="rounded-2xl border border-warning/30 bg-warning/5 p-5">
        <h2 className="font-bold">{t('courses.blueprint.limitationTitle')}</h2>
        <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
          {blueprint.limitations.map((limitation) => <li key={limitation}>• {limitation}</li>)}
          {courseId && <li>• {t('courses.blueprint.manualEditWarning')}</li>}
        </ul>
      </section>}

      <div className="sticky bottom-3 rounded-2xl border bg-card/95 p-3 shadow-lg backdrop-blur sm:bottom-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
        <div className="mb-3 text-xs text-muted-foreground sm:mb-0">
           {currentStep === adaptationSteps.length - 1 ? t('courses.blueprint.finalHint') : t('courses.blueprint.stepHint')}
          {validationError && <p role="alert" className="mt-1 font-medium text-destructive">{validationError}</p>}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:shrink-0">
          {!allRequiredComplete && (
            <Button
              type="button"
              variant="ghost"
              className="col-span-2 sm:col-span-1"
              disabled={saving}
              onClick={() => void save(false)}
            >
              {courseId ? t('courses.blueprint.savePartialUpdate') : t('courses.blueprint.savePartialDraft')}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={currentStep === 0 || saving}
            onClick={() => {
              setValidationError('');
              setCurrentStep((step) => Math.max(0, step - 1));
            }}
          >
            <ChevronLeft className="mr-1 h-4 w-4" aria-hidden="true" />
            {t('courses.blueprint.previous')}
          </Button>
          {currentStep < adaptationSteps.length - 1 ? (
            <Button type="button" onClick={continueToNextStep} disabled={saving}>
              {t('courses.blueprint.next')}
              <ChevronRight className="ml-1 h-4 w-4" aria-hidden="true" />
            </Button>
          ) : (
            <Button onClick={() => void save(true)} disabled={saving || !allRequiredComplete}>
              {saving ? t('courses.blueprint.creating') : courseId ? t('courses.blueprint.updateDraft') : t('courses.blueprint.createDraft')}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BlueprintPage() {
  return (
    <Suspense fallback={<div className="flex min-h-80 items-center justify-center">...</div>}>
      <BlueprintPageContent />
    </Suspense>
  );
}
