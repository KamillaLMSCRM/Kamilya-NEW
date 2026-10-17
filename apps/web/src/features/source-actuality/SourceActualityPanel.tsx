'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Clock3, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';
import { api } from '@/lib/api';
import type { DocumentCatalogItem } from '@/lib/documentCatalog';
import { useT } from '@/i18n/useT';

type State = 'unassigned' | 'current' | 'due_soon' | 'overdue';
type ReviewStatus = 'pending' | 'processing' | 'ready' | 'resolved' | 'failed';
type Decision = 'no_learning_impact' | 'update_future' | 'update_and_retrain' | 'suspend_old_assignments';
type Owner = { id: string; first_name: string; last_name: string; email?: string | null; role: string; is_active: boolean };
type FactChange = {
  subject: string;
  attribute: string;
  old_value: string | null;
  new_value: string | null;
  old_confidence?: number | null;
  new_confidence?: number | null;
  old_uncertainty?: string | null;
  new_uncertainty?: string | null;
};

interface Family {
  source_family_id: string;
  latest_document_id: string;
  latest_version: number;
  title: string;
  filename: string;
  actuality_state: State;
  owner_id: string | null;
  owner_name: string | null;
  reviewed_at: string | null;
  next_review_at: string | null;
  pending_review_id: string | null;
  pending_review_status: ReviewStatus | null;
}

interface Review {
  id: string;
  status: ReviewStatus;
  added_fact_count: number;
  removed_fact_count: number;
  changed_fact_count: number;
  impacted_course_count: number;
  impacted_lesson_count: number;
  assessment_questions_requiring_review: number;
  impacted_courses: Array<{
    title: string;
    impacted_lesson_ids: string[];
    assessment_questions_requiring_review: number;
    active_enrollments: number;
    completed_enrollments: number;
  }>;
  added_facts: FactChange[];
  removed_facts: FactChange[];
  changed_facts: FactChange[];
  analysis_truncated: boolean;
  decision: Decision | null;
}

const localDateTime = (value: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};
const toAwareIso = (value: string) => value ? new Date(value).toISOString() : null;

export function SourceActualityPanel({ userId, isImpersonating = false, catalogDocuments }: { userId?: string; isImpersonating?: boolean; catalogDocuments: DocumentCatalogItem[] }) {
  const { t } = useT();
  const [families, setFamilies] = useState<Family[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [active, setActive] = useState<Family | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [owners, setOwners] = useState<Owner[]>([]);
  const [ownersLoading, setOwnersLoading] = useState(false);
  const [ownersError, setOwnersError] = useState(false);
  const [ownerReload, setOwnerReload] = useState(0);
  const [ownerId, setOwnerId] = useState('');
  const [reviewedAt, setReviewedAt] = useState('');
  const [nextReviewAt, setNextReviewAt] = useState('');
  const [reason, setReason] = useState('');
  const [decision, setDecision] = useState<Decision | ''>('');
  const [retrainingDueAt, setRetrainingDueAt] = useState('');
  const dialogGeneration = useRef(0);
  const activeFamilyId = active?.source_family_id;

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const response = await api.get<{ items: Family[] }>("/v1/admin/source-actuality");
      setFamilies(response.data.items);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Reuse the tenant-scoped team API, never the platform operator's profile.
  // Read every page so a larger team is not silently restricted to page one.
  useEffect(() => {
    if (!activeFamilyId) return;
    let cancelled = false;
    const controller = new AbortController();
    setOwners([]);
    setOwnersLoading(true);
    setOwnersError(false);
    const loadOwners = async () => {
      const all: Owner[] = [];
      try {
        for (let page = 1; ; page += 1) {
          const response = await api.get<{ users: Owner[]; total: number }>(
            `/v1/users?role=methodologist&is_active=true&per_page=100&page=${page}`,
            { signal: controller.signal },
          );
          if (cancelled) return;
          all.push(...response.data.users);
          if (all.length >= response.data.total) break;
          if (!response.data.users.length || page >= 100) throw new Error('Incomplete owner list');
        }
        if (!cancelled) setOwners(all.filter((owner) => owner.role === 'methodologist' && owner.is_active));
      } catch {
        if (!cancelled) setOwnersError(true);
      } finally {
        if (!cancelled) setOwnersLoading(false);
      }
    };
    void loadOwners();
    return () => { cancelled = true; controller.abort(); };
  }, [activeFamilyId, ownerReload]);

  const closeFamily = () => {
    dialogGeneration.current += 1;
    setActive(null);
    setDialogBusy(false);
  };

  const openFamily = async (family: Family) => {
    const generation = ++dialogGeneration.current;
    setActive(family);
    setDialogBusy(false);
    setReview(null);
    setDialogError(false);
    setPolicyError(null);
    setOwnerId(family.owner_id || '');
    setReviewedAt(localDateTime(family.reviewed_at));
    setNextReviewAt(localDateTime(family.next_review_at));
    setReason('');
    setDecision('');
    setRetrainingDueAt('');
    if (!family.pending_review_id) return;
    setDialogBusy(true);
    try {
      const result = await api.get<Review>(`/v1/admin/source-actuality/reviews/${family.pending_review_id}`);
      if (dialogGeneration.current === generation) setReview(result.data);
    } catch {
      if (dialogGeneration.current === generation) setDialogError(true);
    } finally {
      if (dialogGeneration.current === generation) setDialogBusy(false);
    }
  };

  useEffect(() => {
    if (!active?.pending_review_id || !['pending', 'processing'].includes(review?.status || active.pending_review_status || '')) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const result = await api.get<Review>(`/v1/admin/source-actuality/reviews/${active.pending_review_id}`);
        if (stopped) return;
        setReview(result.data);
        if (!['pending', 'processing'].includes(result.data.status)) window.clearInterval(timer);
      } catch {
        if (!stopped) setDialogError(true);
      }
    }, 2000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [active, review?.status]);

  const savePolicy = async (owner: string | null) => {
    if (!active) return;
    const generation = dialogGeneration.current;
    setPolicyError(null);
    if ((reviewedAt && Number.isNaN(new Date(reviewedAt).getTime())) || (nextReviewAt && Number.isNaN(new Date(nextReviewAt).getTime()))) {
      setPolicyError(t('documents.sourceActuality.invalidDate'));
      return;
    }
    if (reviewedAt && nextReviewAt && new Date(nextReviewAt) < new Date(reviewedAt)) {
      setPolicyError(t('documents.sourceActuality.invalidWindow'));
      return;
    }
    if (owner && !owners.some((candidate) => candidate.id === owner)) {
      setPolicyError(t('documents.sourceActuality.ownerUnavailable'));
      return;
    }
    setDialogBusy(true);
    setDialogError(false);
    try {
      await api.put(`/v1/admin/source-actuality/${active.source_family_id}/policy`, {
        owner_id: owner,
        reviewed_at: toAwareIso(reviewedAt),
        next_review_at: toAwareIso(nextReviewAt),
      });
      await load();
      if (dialogGeneration.current === generation) closeFamily();
    } catch (error) {
      if (dialogGeneration.current !== generation) return;
      const response = (error as { response?: { status?: number; data?: { detail?: unknown; message?: unknown } } }).response;
      const ownerError = 'Policy owner must be an active tenant methodologist';
      const ownerRejected = response?.data?.detail === ownerError || response?.data?.message === ownerError;
      setPolicyError(t(ownerRejected ? 'documents.sourceActuality.ownerUnavailable' : response?.status === 422 ? 'documents.sourceActuality.policyValidationError' : 'documents.sourceActuality.policySaveError'));
    } finally {
      if (dialogGeneration.current === generation) setDialogBusy(false);
    }
  };

  const analyze = async () => {
    if (!active) return;
    const generation = dialogGeneration.current;
    setDialogBusy(true);
    setDialogError(false);
    try {
      const result = await api.post<Review>(`/v1/admin/source-actuality/documents/${active.latest_document_id}/analyze`);
      setFamilies((items) => items.map((item) => item.source_family_id === active.source_family_id
        ? { ...item, pending_review_id: result.data.id, pending_review_status: result.data.status }
        : item));
      if (dialogGeneration.current === generation) {
        setReview(result.data);
        setActive({ ...active, pending_review_id: result.data.id, pending_review_status: result.data.status });
      }
    } catch {
      if (dialogGeneration.current === generation) setDialogError(true);
    } finally {
      if (dialogGeneration.current === generation) setDialogBusy(false);
    }
  };

  const submitDecision = async () => {
    if (!active?.pending_review_id || !decision || reason.trim().length < 20) return;
    const generation = dialogGeneration.current;
    setDialogBusy(true);
    setDialogError(false);
    try {
      await api.post(`/v1/admin/source-actuality/reviews/${active.pending_review_id}/decision`, {
        decision,
        reason: reason.trim(),
        ...(decision === 'update_and_retrain' && retrainingDueAt ? { retraining_due_at: toAwareIso(retrainingDueAt) } : {}),
      });
      await load();
      if (dialogGeneration.current === generation) closeFamily();
    } catch {
      if (dialogGeneration.current === generation) setDialogError(true);
    } finally {
      if (dialogGeneration.current === generation) setDialogBusy(false);
    }
  };

  const labels: Record<State, string> = {
    current: t('documents.sourceActuality.current'),
    due_soon: t('documents.sourceActuality.dueSoon'),
    overdue: t('documents.sourceActuality.overdue'),
    unassigned: t('documents.sourceActuality.unassignedStatus'),
  };

  return (
    <section className="mb-6 rounded-xl border border-border bg-card p-4 sm:p-5" aria-labelledby="source-actuality-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="source-actuality-title" className="font-display text-lg font-bold">{t('documents.sourceActuality.title')}</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('documents.sourceActuality.description')}</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-3 text-sm hover:bg-muted disabled:opacity-50">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}{t('documents.sourceActuality.refresh')}
        </button>
      </div>

      {loading ? <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground" role="status"><Loader2 className="h-4 w-4 animate-spin" />{t('documents.sourceActuality.loading')}</p>
        : error ? <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-destructive" role="alert"><AlertCircle className="h-4 w-4" />{t('documents.sourceActuality.loadError')}<button className="underline" onClick={() => void load()}>{t('documents.sourceActuality.retry')}</button></div>
          : families.length === 0 ? <p className="mt-4 text-sm text-muted-foreground">{t('documents.sourceActuality.empty')}</p>
            : <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{families.map((family) => {
              const catalogDocument = catalogDocuments.find((document) => document.id === family.latest_document_id && document.source_family_id === family.source_family_id);
              return (
              <article key={family.source_family_id} className="min-w-0 rounded-lg border border-border p-4">
                <h3 className="truncate font-semibold" title={catalogDocument?.title || family.title}>{catalogDocument?.title || family.title}</h3>
                <p className="mt-1 truncate text-xs text-muted-foreground">{catalogDocument?.filename || family.filename} · v{catalogDocument?.version || family.latest_version}</p>
                <p className={`mt-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${family.actuality_state === 'overdue' ? 'bg-destructive/10 text-destructive' : family.actuality_state === 'due_soon' ? 'bg-warning/10 text-warning' : 'bg-primary/10 text-primary'}`}>
                  {family.actuality_state === 'overdue' ? <ShieldAlert className="h-3.5 w-3.5" /> : <Clock3 className="h-3.5 w-3.5" />}{labels[family.actuality_state]}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">{t('documents.sourceActuality.owner')}: {family.owner_name || (family.owner_id ? t('documents.sourceActuality.ownerAssigned') : t('documents.sourceActuality.ownerUnassigned'))}</p>
                <p className="mt-2 text-xs text-muted-foreground">{t('documents.sourceActuality.nextReview')}: {family.next_review_at ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(family.next_review_at)) : '—'}</p>
                <button type="button" onClick={() => void openFamily(family)} className="mt-3 min-h-10 w-full rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">{family.pending_review_id ? t('documents.sourceActuality.openReview') : t('documents.sourceActuality.manage')}</button>
              </article>
            ); })}</div>}

      {active && <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center sm:p-4" role="presentation">
        <button className="absolute inset-0 bg-black/50" aria-label={t('common.close')} onClick={closeFamily} />
        <section role="dialog" aria-modal="true" aria-labelledby="actuality-dialog-title" className="relative z-10 max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-2xl bg-card p-4 shadow-card-lg sm:rounded-2xl sm:p-6">
          <div className="flex items-start justify-between gap-4"><div className="min-w-0"><h2 id="actuality-dialog-title" className="text-lg font-bold">{active.title}</h2><p className="mt-1 text-sm text-muted-foreground">{t('documents.sourceActuality.dialogDescription')}</p></div><button type="button" onClick={closeFamily} className="min-h-10 shrink-0 rounded-lg border border-border px-3 text-sm">{t('common.close')}</button></div>
          <div className="mt-5">
            <label className="block text-sm">{t('documents.sourceActuality.ownerLabel')}
              <select value={ownerId} disabled={dialogBusy || ownersLoading || ownersError} onChange={(event) => { setOwnerId(event.target.value); setPolicyError(null); }} className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3">
                <option value="">{t('documents.sourceActuality.ownerUnassigned')}</option>
                {ownerId && !owners.some((owner) => owner.id === ownerId) && <option value={ownerId} disabled>{active.owner_name || t('documents.sourceActuality.ownerAssigned')}</option>}
                {owners.map((owner) => <option key={owner.id} value={owner.id}>{[owner.first_name, owner.last_name].filter(Boolean).join(' ') || owner.email || t('documents.sourceActuality.ownerAssigned')}</option>)}
              </select>
            </label>
            <p className="mt-1 text-xs text-muted-foreground">{t('documents.sourceActuality.ownerHint')}</p>
            {isImpersonating && <p className="mt-2 text-sm text-muted-foreground">{t('documents.sourceActuality.previewOwnerHint')}</p>}
            {ownersLoading && <p role="status" className="mt-2 text-sm">{t('documents.sourceActuality.ownersLoading')}</p>}
            {ownersError && <p role="alert" className="mt-2 text-sm text-destructive">{t('documents.sourceActuality.ownersError')} <button type="button" className="underline" onClick={() => setOwnerReload((value) => value + 1)}>{t('documents.sourceActuality.retry')}</button></p>}
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-sm">{t('documents.sourceActuality.reviewedAt')}<input type="datetime-local" value={reviewedAt} onChange={(e) => setReviewedAt(e.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3" /></label>
            <label className="text-sm">{t('documents.sourceActuality.nextReview')}<input type="datetime-local" value={nextReviewAt} onChange={(e) => setNextReviewAt(e.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3" /></label>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" disabled={dialogBusy || ownersLoading || ownersError} onClick={() => void savePolicy(ownerId || null)} className="min-h-10 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50">{t('common.save')}</button>
            {!isImpersonating && <button type="button" disabled={dialogBusy || ownersLoading || !userId || !owners.some((owner) => owner.id === userId)} onClick={() => void savePolicy(userId || null)} className="min-h-10 rounded-lg border border-border px-3 text-sm disabled:opacity-50">{t('documents.sourceActuality.assignMe')}</button>}
            <button type="button" disabled={dialogBusy} onClick={() => void savePolicy(null)} className="min-h-10 rounded-lg border border-border px-3 text-sm disabled:opacity-50">{t('documents.sourceActuality.clearOwner')}</button>
          </div>
          {policyError && <p role="alert" className="mt-3 text-sm text-destructive">{policyError} <button type="button" className="underline" onClick={() => setOwnerReload((value) => value + 1)}>{t('documents.sourceActuality.refresh')}</button></p>}
          <div className="mt-6 border-t border-border pt-5"><h3 className="font-semibold">{t('documents.sourceActuality.analysisTitle')}</h3><p className="mt-1 text-sm text-muted-foreground">{t('documents.sourceActuality.analysisDescription')}</p>
            {!active.pending_review_id && active.latest_version <= 1 && <p className="mt-3 text-sm text-muted-foreground">{t('documents.sourceActuality.noPreviousVersion')}</p>}
            {!active.pending_review_id && active.latest_version > 1 && <button type="button" disabled={dialogBusy} onClick={() => void analyze()} className="mt-3 min-h-10 rounded-lg border border-primary px-3 text-sm font-medium text-primary disabled:opacity-50">{dialogBusy ? t('documents.sourceActuality.working') : t('documents.sourceActuality.startAnalysis')}</button>}
            {dialogBusy && <p className="mt-3 flex items-center gap-2 text-sm" role="status"><Loader2 className="h-4 w-4 animate-spin" />{t('documents.sourceActuality.working')}</p>}
            {review && ['pending', 'processing'].includes(review.status) && <p className="mt-3 text-sm" role="status">{t('documents.sourceActuality.processing')}</p>}
            {!review && active.pending_review_id && ['pending', 'processing'].includes(active.pending_review_status || '') && !dialogError && <p className="mt-3 text-sm" role="status">{t('documents.sourceActuality.processing')}</p>}
            {review?.status === 'failed' && <p className="mt-3 text-sm text-destructive" role="alert">{t('documents.sourceActuality.analysisFailed')}</p>}
            {review?.status === 'failed' && <button type="button" disabled={dialogBusy} onClick={() => void analyze()} className="mt-2 min-h-10 rounded-lg border border-border px-3 text-sm">{t('documents.sourceActuality.retry')}</button>}
            {review?.status === 'ready' && <>
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-5"><Metric label={t('documents.sourceActuality.addedFacts')} value={review.added_fact_count} /><Metric label={t('documents.sourceActuality.removedFacts')} value={review.removed_fact_count} /><Metric label={t('documents.sourceActuality.changedFacts')} value={review.changed_fact_count} /><Metric label={t('documents.sourceActuality.impactedLessons')} value={review.impacted_lesson_count} /><Metric label={t('documents.sourceActuality.impactedQuestions')} value={review.assessment_questions_requiring_review} /></div>
              <ImpactList heading={t('documents.sourceActuality.added')} facts={review.added_facts} />
              <ImpactList heading={t('documents.sourceActuality.removed')} facts={review.removed_facts} />
              <ImpactList heading={t('documents.sourceActuality.changed')} facts={review.changed_facts} />
              <div className="mt-4"><h4 className="text-sm font-semibold">{t('documents.sourceActuality.impactedCourses')}</h4>{review.impacted_courses.length ? <ul className="mt-2 space-y-2">{review.impacted_courses.map((course, index) => <li key={`${course.title}-${index}`} className="rounded-lg border border-border p-3 text-sm"><p className="font-medium">{course.title}</p><p className="mt-1 text-xs text-muted-foreground">{t('documents.sourceActuality.lessonCount', { count: course.impacted_lesson_ids.length })} · {t('documents.sourceActuality.questionCount', { count: course.assessment_questions_requiring_review })} · {t('documents.sourceActuality.activeEnrollments', { count: course.active_enrollments })} · {t('documents.sourceActuality.completedEnrollments', { count: course.completed_enrollments })}</p></li>)}</ul> : <p className="mt-1 text-sm text-muted-foreground">{t('documents.sourceActuality.none')}</p>}</div>
              <p className="mt-3 text-xs text-muted-foreground">{t('documents.sourceActuality.questionScope')}{review.analysis_truncated ? ` ${t('documents.sourceActuality.truncated')}` : ''}</p>
              <div className="mt-4 space-y-3"><label className="block text-sm">{t('documents.sourceActuality.decision')}<select value={decision} onChange={(e) => setDecision(e.target.value as Decision | '')} className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3"><option value="">{t('documents.sourceActuality.chooseDecision')}</option>{(['no_learning_impact', 'update_future', 'update_and_retrain', 'suspend_old_assignments'] as Decision[]).map((value) => <option key={value} value={value}>{t(`documents.sourceActuality.decisions.${value}`)}</option>)}</select></label>
                {decision === 'update_and_retrain' && <label className="block text-sm">{t('documents.sourceActuality.retrainingDeadline')}<input type="datetime-local" value={retrainingDueAt} onChange={(e) => setRetrainingDueAt(e.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3" /></label>}
                <label className="block text-sm">{t('documents.sourceActuality.reason')}<textarea value={reason} onChange={(e) => setReason(e.target.value)} minLength={20} maxLength={4000} rows={3} className="mt-1 w-full rounded-lg border border-border bg-background p-3" /></label>
                <p className="text-sm text-warning">{t('documents.sourceActuality.noAutoPublish')}</p>
                <button type="button" disabled={dialogBusy || !decision || reason.trim().length < 20} onClick={() => void submitDecision()} className="min-h-11 rounded-lg bg-primary px-4 font-medium text-primary-foreground disabled:opacity-50">{t('documents.sourceActuality.submitDecision')}</button>
              </div>
            </>}
            {review?.status === 'resolved' && <p className="mt-3 text-sm text-muted-foreground">{t('documents.sourceActuality.alreadyDecided')}</p>}
            {dialogError && <p className="mt-3 text-sm text-destructive" role="alert">{t('documents.sourceActuality.actionError')} <button className="underline" onClick={() => void openFamily(active)}>{t('documents.sourceActuality.retry')}</button></p>}
          </div>
        </section>
      </div>}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg bg-muted p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>;
}

function ImpactList({ heading, facts }: { heading: string; facts: FactChange[] }) {
  const { t } = useT();
  return <div className="mt-4"><h4 className="text-sm font-semibold">{heading}</h4>{facts.length ? <ul className="mt-2 max-h-40 space-y-2 overflow-auto">{facts.slice(0, 10).map((fact, index) => <li key={`${fact.subject}-${fact.attribute}-${index}`} className="rounded-lg border border-border p-2 text-sm"><span className="font-medium">{fact.subject}</span> · {fact.attribute}<p className="mt-1 text-xs text-muted-foreground">{fact.old_value || '—'} → {fact.new_value || '—'}</p>{(fact.old_uncertainty !== undefined || fact.new_uncertainty !== undefined) && <p className="mt-1 text-xs text-muted-foreground">{t('documents.sourceActuality.confidenceChanged')}: {fact.old_confidence ?? '—'} → {fact.new_confidence ?? '—'}</p>}</li>)}</ul> : <p className="mt-1 text-sm text-muted-foreground">{t('documents.sourceActuality.none')}</p>}</div>;
}
