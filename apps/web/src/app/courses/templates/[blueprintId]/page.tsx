'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, BookOpenCheck, CheckCircle2, FileText, ShieldCheck } from 'lucide-react';

import { Button, Input } from '@/components/ui';
import { LoadError } from '@/components/ui/LoadError';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
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

function FinanceBlueprintPageContent() {
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
        setAnswers(adaptationResult.value.data.answers || {});
        setSelectedDocumentIds(adaptationResult.value.data.source_document_ids || []);
      } else {
        setAnswers({});
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
    () => blueprint?.checklist.filter((item) => Boolean(answers[item.id]?.trim())).length || 0,
    [answers, blueprint],
  );
  const readiness = blueprint
    ? Math.min(
        100,
        blueprint.estimated_ready_percent
          + Math.round(blueprint.customization_percent * completedCount / blueprint.checklist.length),
      )
    : 0;

  const toggleDocument = (documentId: string) => {
    setSelectedDocumentIds((current) => (
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId]
    ));
  };

  const save = async () => {
    if (!blueprint) return;
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
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t('courses.blueprint.pageTitle')}</h1>
            <p className="mt-3 text-muted-foreground">{t('courses.blueprint.pageSubtitle')}</p>
            <p className="mt-3 text-sm font-medium text-foreground">{blueprint.audience}</p>
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

      <section className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border bg-card p-5"><BookOpenCheck className="h-5 w-5 text-primary" /><div className="mt-3 text-2xl font-bold">{blueprint.lesson_count}</div><div className="text-sm text-muted-foreground">{t('courses.lessons')}</div></div>
        <div className="rounded-2xl border bg-card p-5"><CheckCircle2 className="h-5 w-5 text-primary" /><div className="mt-3 text-2xl font-bold">{blueprint.quiz_question_count}</div><div className="text-sm text-muted-foreground">{t('quiz.question')}</div></div>
        <div className="rounded-2xl border bg-card p-5"><FileText className="h-5 w-5 text-primary" /><div className="mt-3 text-2xl font-bold">v{blueprint.version}</div><div className="text-sm text-muted-foreground">{t('courses.blueprint.basePart')}</div></div>
      </section>

      <section className="rounded-2xl border bg-card p-6 shadow-card">
        <label className="block text-sm font-semibold" htmlFor="blueprint-course-title">{t('courses.blueprint.courseName')}</label>
        <Input id="blueprint-course-title" className="mt-2" value={title} onChange={(event) => setTitle(event.target.value)} />
      </section>

      <section className="rounded-2xl border bg-card p-6 shadow-card">
        <h2 className="text-lg font-bold">{t('courses.blueprint.checklist')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('courses.blueprint.checklistHint')}</p>
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          {blueprint.checklist.map((item, index) => (
            <label key={item.id} className="rounded-2xl border border-border p-4 focus-within:border-primary">
              <span className="flex items-start gap-3">
                <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${answers[item.id]?.trim() ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>
                  {answers[item.id]?.trim() ? '✓' : index + 1}
                </span>
                <span>
                  <span className="block font-semibold">{item.title}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">{item.description}</span>
                </span>
              </span>
              <textarea
                value={answers[item.id] || ''}
                onChange={(event) => setAnswers((current) => ({ ...current, [item.id]: event.target.value }))}
                placeholder={item.answer_placeholder}
                rows={4}
                maxLength={4000}
                className="mt-4 w-full resize-y rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border bg-card p-6 shadow-card">
        <h2 className="text-lg font-bold">{t('courses.blueprint.documents')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('courses.blueprint.documentsHint')}</p>
        {documents.length ? (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {documents.map((document) => (
              <label key={document.id} className="flex cursor-pointer items-start gap-3 rounded-xl border p-3 hover:border-primary/50">
                <input type="checkbox" className="mt-1" checked={selectedDocumentIds.includes(document.id)} onChange={() => toggleDocument(document.id)} />
                <span className="min-w-0"><span className="block truncate text-sm font-medium">{document.title}</span><span className="block truncate text-xs text-muted-foreground">{document.filename} · v{document.version}</span></span>
              </label>
            ))}
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed p-5 text-sm text-muted-foreground">
            {t('courses.blueprint.noDocuments')}{' '}
            <Link href="/documents" className="font-medium text-primary hover:underline">{t('courses.blueprint.uploadDocuments')}</Link>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-warning/30 bg-warning/5 p-5">
        <h2 className="font-bold">{t('courses.blueprint.limitationTitle')}</h2>
        <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
          {blueprint.limitations.map((limitation) => <li key={limitation}>• {limitation}</li>)}
          {courseId && <li>• {t('courses.blueprint.manualEditWarning')}</li>}
        </ul>
      </section>

      <div className="sticky bottom-4 flex justify-end">
        <Button onClick={save} disabled={saving || !title.trim()} className="min-h-12 px-6 shadow-lg">
          {saving ? t('courses.blueprint.creating') : courseId ? t('courses.blueprint.updateDraft') : t('courses.blueprint.createDraft')}
        </Button>
      </div>
    </div>
  );
}

export default function FinanceBlueprintPage() {
  return (
    <Suspense fallback={<div className="flex min-h-80 items-center justify-center">...</div>}>
      <FinanceBlueprintPageContent />
    </Suspense>
  );
}
