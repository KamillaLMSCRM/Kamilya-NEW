'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  Database,
  Eye,
  FileWarning,
  HardDrive,
  RefreshCw,
  Server,
  ShieldAlert,
  Send,
  Trash2,
} from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';

type AgeSeconds = number | null;
type OperationsSummary = {
  generated_at: string;
  ai_jobs: { queued_count: number; running_count: number; failed_count: number; oldest_queued_age_seconds: AgeSeconds; oldest_running_age_seconds: AgeSeconds };
  documents: { indexing_count: number; failed_index_count: number; failed_embedding_count: number; cleanup_pending_count: number; cleanup_failed_count: number; oldest_indexing_age_seconds: AgeSeconds; oldest_cleanup_pending_age_seconds: AgeSeconds };
  database: { pool_class: string; configured_pool_size: number | null; configured_max_overflow: number | null; configured_pool_timeout_seconds: number | null; configured_pool_recycle_seconds: number | null; checked_in: number | null; checked_out: number | null; overflow: number | null; capacity: number | null };
  process: { process_id: number; started_at: string; uptime_seconds: number; python_version: string; cpu_percent: number | null; rss_memory_bytes: number | null };
  host: { cpu_percent: number | null };
  filesystem: { total_bytes: number | null; free_bytes: number | null; used_percent: number | null };
  celery: { status: 'available' | 'unavailable'; reachable: boolean; worker_count: number; registered_required_tasks: string[]; missing_required_tasks: string[] };
  crm_lead_outbox: { pending_count: number; retry_count: number; claimed_count: number; dead_count: number; delivered_count: number; oldest_due_age_seconds: AgeSeconds };
};

type CleanupResult = { tenant_id: string; slug: string; created_at: string; age_hours: number; action: 'would_delete' | 'deleted' | 'skipped' | 'failed'; reason?: string | null };
type CleanupPreview = { dry_run: boolean; min_age_hours: number; allowed_slug_prefixes: string[]; matched_count: number; deleted_count: number; skipped_count: number; failed_count: number; truncated: boolean; results: CleanupResult[] };
type StaleAIJobRecovery = { dry_run: boolean; min_age_hours: number; terminal_status: 'cancelled'; eligible_count: number; queued_count: number; running_count: number; recovered_count: number; skipped_count: number; truncated: boolean; oldest_age_seconds: AgeSeconds; newest_age_seconds: AgeSeconds };
type CRMLeadRequeue = { dry_run: boolean; limit: number; eligible_count: number; requeued_count: number };

const CONFIRM_TOKEN = 'CLEANUP_SYNTHETIC_TENANTS';
const MIN_AGE_HOURS = 24;
const STALE_AI_JOB_CONFIRM_TOKEN = 'RECOVER_STALE_AI_JOBS';
const STALE_AI_JOB_MIN_AGE_HOURS = 24;
const CRM_REQUEUE_CONFIRM_TOKEN = 'REQUEUE_FAILED_CRM_LEADS';
const CRM_REQUEUE_LIMIT = 20;

function formatAge(value: AgeSeconds, never: string, units: { seconds: string; minutes: string; hours: string; days: string }) {
  if (value === null || value === undefined) return never;
  if (value < 60) return `${value} ${units.seconds}`;
  if (value < 3600) return `${Math.floor(value / 60)} ${units.minutes}`;
  if (value < 86_400) return `${Math.floor(value / 3600)} ${units.hours}`;
  return `${Math.floor(value / 86_400)} ${units.days}`;
}

function formatDate(value: string | null, locale: string, fallback: string) {
  if (!value) return fallback;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function formatPercent(value: number | null | undefined, fallback: string) {
  return value === null || value === undefined ? fallback : `${value.toFixed(1)}%`;
}

function formatBytes(value: number | null | undefined, fallback: string) {
  if (value === null || value === undefined) return fallback;
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let scaled = value;
  let unit = 'B';
  for (const nextUnit of units) {
    scaled /= 1024;
    unit = nextUnit;
    if (scaled < 1024 || nextUnit === units[units.length - 1]) break;
  }
  return `${scaled.toFixed(scaled >= 10 ? 0 : 1)} ${unit}`;
}

function responseError(response: Response) {
  return response.json().then((payload) => {
    const detail = payload?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('; ');
    return `HTTP ${response.status}`;
  }).catch(() => `HTTP ${response.status}`);
}

export default function SuperadminOperationsPage() {
  const { t, lang } = useT();
  const token = useAuthStore((state) => state.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const locale = lang === 'en' ? 'en-US' : lang === 'kk' ? 'kk-KZ' : 'ru-KZ';
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [preview, setPreview] = useState<CleanupPreview | null>(null);
  const [staleRecovery, setStaleRecovery] = useState<StaleAIJobRecovery | null>(null);
  const [crmRequeue, setCRMRequeue] = useState<CRMLeadRequeue | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [cleaning, setCleaning] = useState(false);
  const [recoveryConfirmation, setRecoveryConfirmation] = useState('');
  const [recovering, setRecovering] = useState(false);
  const [crmConfirmation, setCRMConfirmation] = useState('');
  const [requeuingCRM, setRequeuingCRM] = useState(false);
  const hasSuccessfulSummary = useRef(false);

  const apiFetch = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`${API_URL}/v1${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(init?.headers || {}) },
    });
    if (!response.ok) throw new Error(await responseError(response));
    return response.json();
  }, [API_URL, token]);

  const loadAll = useCallback(async (manual = false) => {
    if (!token || !API_URL) return;
    if (manual) setRefreshing(true); else setLoading(true);
    setError(null);
    try {
      const [nextSummary, nextPreview, nextCRMRequeue] = await Promise.all([
        apiFetch('/admin/super/operations/summary'),
        apiFetch('/admin/super/operations/cleanup-synthetic', { method: 'POST', body: JSON.stringify({ dry_run: true, min_age_hours: MIN_AGE_HOURS }) }),
        apiFetch('/admin/super/operations/requeue-failed-crm-leads', { method: 'POST', body: JSON.stringify({ dry_run: true, limit: CRM_REQUEUE_LIMIT }) }),
      ]);
      const nextStaleRecovery = await apiFetch('/admin/super/operations/recover-stale-ai-jobs', { method: 'POST', body: JSON.stringify({ dry_run: true, min_age_hours: STALE_AI_JOB_MIN_AGE_HOURS }) });
      setSummary(nextSummary);
      setPreview(nextPreview);
      setStaleRecovery(nextStaleRecovery);
      setCRMRequeue(nextCRMRequeue);
      hasSuccessfulSummary.current = true;
      setLastUpdatedAt(new Date().toISOString());
      setStale(false);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : t('superadmin.operations.loadError');
      setError(message);
      setStale(hasSuccessfulSummary.current);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [API_URL, apiFetch, t, token]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const canCleanup = Boolean(preview && preview.dry_run && preview.matched_count > 0 && !loading && !refreshing && !stale);
  const healthTone = (bad: boolean) => bad ? 'border-red-200 bg-red-50' : 'border-emerald-200 bg-emerald-50';
  const cleanupCounts = useMemo(() => ({
    candidates: preview?.matched_count ?? 0,
    failures: (summary?.documents.failed_index_count ?? 0) + (summary?.documents.failed_embedding_count ?? 0) + (summary?.documents.cleanup_failed_count ?? 0),
  }), [preview, summary]);
  const timeUnits = {
    seconds: t('superadmin.operations.time.seconds'),
    minutes: t('superadmin.operations.time.minutes'),
    hours: t('superadmin.operations.time.hours'),
    days: t('superadmin.operations.time.days'),
  };
  const cleanupActionLabel = (action: CleanupResult['action']) => {
    const labels: Record<CleanupResult['action'], ReturnType<typeof t>> = {
      would_delete: t('superadmin.operations.cleanup.actions.wouldDelete'),
      deleted: t('superadmin.operations.cleanup.actions.deleted'),
      skipped: t('superadmin.operations.cleanup.actions.skipped'),
      failed: t('superadmin.operations.cleanup.actions.failed'),
    };
    return labels[action];
  };

  const executeCleanup = async () => {
    if (confirmation !== CONFIRM_TOKEN || !canCleanup) return;
    setCleaning(true);
    try {
      await apiFetch('/admin/super/operations/cleanup-synthetic', { method: 'POST', body: JSON.stringify({ dry_run: false, min_age_hours: MIN_AGE_HOURS, confirm: true, confirm_token: confirmation }) });
      toast.success(t('superadmin.operations.cleanup.success'));
      setConfirmOpen(false);
      setConfirmation('');
      await loadAll(true);
    } catch (cause) {
      toast.error(t('superadmin.operations.cleanup.error'), { description: cause instanceof Error ? cause.message : undefined });
    } finally { setCleaning(false); }
  };

  const executeStaleRecovery = async () => {
    if (recoveryConfirmation !== STALE_AI_JOB_CONFIRM_TOKEN || !staleRecovery || staleRecovery.eligible_count === 0 || staleRecovery.truncated) return;
    setRecovering(true);
    try {
      await apiFetch('/admin/super/operations/recover-stale-ai-jobs', { method: 'POST', body: JSON.stringify({ dry_run: false, min_age_hours: STALE_AI_JOB_MIN_AGE_HOURS, confirm: true, confirm_token: recoveryConfirmation }) });
      toast.success(t('superadmin.operations.staleRecovery.success'));
      setRecoveryConfirmation('');
      await loadAll(true);
    } catch (cause) {
      toast.error(t('superadmin.operations.staleRecovery.error'), { description: cause instanceof Error ? cause.message : undefined });
    } finally { setRecovering(false); }
  };

  const executeCRMRequeue = async () => {
    if (crmConfirmation !== CRM_REQUEUE_CONFIRM_TOKEN || !crmRequeue || crmRequeue.eligible_count === 0) return;
    setRequeuingCRM(true);
    try {
      await apiFetch('/admin/super/operations/requeue-failed-crm-leads', { method: 'POST', body: JSON.stringify({ dry_run: false, limit: CRM_REQUEUE_LIMIT, confirm: true, confirm_token: crmConfirmation }) });
      toast.success(t('superadmin.operations.crmOutbox.success'));
      setCRMConfirmation('');
      await loadAll(true);
    } catch (cause) {
      toast.error(t('superadmin.operations.crmOutbox.error'), { description: cause instanceof Error ? cause.message : undefined });
    } finally { setRequeuingCRM(false); }
  };

  if (loading && !summary) {
    return <main className="mx-auto max-w-7xl space-y-6 p-6"><div className="flex items-center gap-3 text-muted-foreground"><RefreshCw className="h-5 w-5 animate-spin" />{t('superadmin.operations.loading')}</div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{[1, 2, 3, 4].map((item) => <Card key={item} className="h-36 animate-pulse bg-muted/30"><span className="sr-only">{item}</span></Card>)}</div></main>;
  }

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div><div className="flex items-center gap-2"><Activity className="h-6 w-6 text-primary" /><h1 className="text-3xl font-semibold">{t('superadmin.operations.title')}</h1></div><p className="mt-2 text-muted-foreground">{t('superadmin.operations.description')}</p></div>
        <Button variant="outline" onClick={() => void loadAll(true)} disabled={refreshing} title={t('superadmin.operations.refresh')}><RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />{t('superadmin.operations.refresh')}</Button>
      </header>

      {stale && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-amber-950"><span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4" />{t('superadmin.operations.stale', { date: formatDate(lastUpdatedAt, locale, t('quiz.notAvailable')) })}</span><Button size="sm" variant="outline" onClick={() => void loadAll(true)} disabled={refreshing}><RefreshCw className="mr-2 h-4 w-4" />{t('superadmin.operations.retry')}</Button></div>}
      {error && !summary && <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-950"><span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4" />{t('superadmin.operations.loadError')}</span><Button size="sm" variant="outline" onClick={() => void loadAll(true)}><RefreshCw className="mr-2 h-4 w-4" />{t('superadmin.operations.retry')}</Button></div>}
      {summary && <>
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" aria-label={t('superadmin.operations.summary.title')}>
          <Card className={healthTone(summary.ai_jobs.failed_count > 0)}><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><Bot className="h-5 w-5" />{t('superadmin.operations.aiJobs.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.aiJobs.queued')} value={summary.ai_jobs.queued_count} /><Metric label={t('superadmin.operations.aiJobs.running')} value={summary.ai_jobs.running_count} /><Metric label={t('superadmin.operations.aiJobs.failed')} value={summary.ai_jobs.failed_count} danger={summary.ai_jobs.failed_count > 0} /><Metric label={t('superadmin.operations.aiJobs.oldest')} value={formatAge(summary.ai_jobs.oldest_queued_age_seconds, t('quiz.notAvailable'), timeUnits)} /></CardContent></Card>
          <Card className={healthTone(cleanupCounts.failures > 0)}><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><FileWarning className="h-5 w-5" />{t('superadmin.operations.documents.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.documents.indexing')} value={summary.documents.indexing_count} /><Metric label={t('superadmin.operations.documents.failed')} value={cleanupCounts.failures} danger={cleanupCounts.failures > 0} /><Metric label={t('superadmin.operations.documents.cleanup')} value={summary.documents.cleanup_pending_count} /><Metric label={t('superadmin.operations.documents.oldest')} value={formatAge(summary.documents.oldest_indexing_age_seconds, t('quiz.notAvailable'), timeUnits)} /></CardContent></Card>
          <Card><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><Database className="h-5 w-5" />{t('superadmin.operations.database.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.database.pool')} value={summary.database.pool_class} /><Metric label={t('superadmin.operations.database.connections')} value={summary.database.capacity ?? t('quiz.notAvailable')} /><Metric label={t('superadmin.operations.database.checkedOut')} value={summary.database.checked_out ?? t('quiz.notAvailable')} /><Metric label={t('superadmin.operations.database.overflow')} value={summary.database.overflow ?? t('quiz.notAvailable')} /></CardContent></Card>
          <Card className={healthTone(summary.process.cpu_percent === null || summary.process.rss_memory_bytes === null)}><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><Activity className="h-5 w-5" />{t('superadmin.operations.process.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.process.uptime')} value={formatAge(summary.process.uptime_seconds, t('quiz.notAvailable'), timeUnits)} /><Metric label={t('superadmin.operations.cpu')} value={formatPercent(summary.process.cpu_percent, t('superadmin.operations.unavailable'))} /><Metric label={t('superadmin.operations.rss')} value={formatBytes(summary.process.rss_memory_bytes, t('superadmin.operations.unavailable'))} /><Metric label={t('superadmin.operations.process.pid')} value={summary.process.process_id} /><Metric label={t('superadmin.operations.process.python')} value={summary.process.python_version} /><Metric label={t('superadmin.operations.process.started')} value={formatDate(summary.process.started_at, locale, t('quiz.notAvailable'))} /></CardContent></Card>
          <Card className={healthTone(summary.host.cpu_percent === null)}><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><Cpu className="h-5 w-5" />{t('superadmin.operations.host.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.host.cpu')} value={formatPercent(summary.host.cpu_percent, t('superadmin.operations.unavailable'))} /></CardContent></Card>
          <Card className={healthTone(summary.filesystem.used_percent === null)}><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><HardDrive className="h-5 w-5" />{t('superadmin.operations.filesystem.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.filesystem.used')} value={formatPercent(summary.filesystem.used_percent, t('superadmin.operations.unavailable'))} /><Metric label={t('superadmin.operations.filesystem.total')} value={formatBytes(summary.filesystem.total_bytes, t('superadmin.operations.unavailable'))} /><Metric label={t('superadmin.operations.filesystem.free')} value={formatBytes(summary.filesystem.free_bytes, t('superadmin.operations.unavailable'))} /></CardContent></Card>
          <Card className={healthTone(!summary.celery.reachable || summary.celery.missing_required_tasks.length > 0)}><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><Server className="h-5 w-5" />{t('superadmin.operations.celery.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.celery.status')} value={summary.celery.reachable ? t('superadmin.operations.celery.available') : t('superadmin.operations.celery.unavailable')} danger={!summary.celery.reachable} /><Metric label={t('superadmin.operations.celery.workers')} value={summary.celery.worker_count} /><TaskList label={t('superadmin.operations.celery.registered')} tasks={summary.celery.registered_required_tasks} empty={t('superadmin.operations.none')} /><TaskList label={t('superadmin.operations.celery.missing')} tasks={summary.celery.missing_required_tasks} empty={t('superadmin.operations.none')} danger={summary.celery.missing_required_tasks.length > 0} /></CardContent></Card>
          <Card className={healthTone(summary.crm_lead_outbox.dead_count > 0)}><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-lg"><Send className="h-5 w-5" />{t('superadmin.operations.crmOutbox.title')}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Metric label={t('superadmin.operations.crmOutbox.pending')} value={summary.crm_lead_outbox.pending_count + summary.crm_lead_outbox.retry_count + summary.crm_lead_outbox.claimed_count} /><Metric label={t('superadmin.operations.crmOutbox.delivered')} value={summary.crm_lead_outbox.delivered_count} /><Metric label={t('superadmin.operations.crmOutbox.dead')} value={summary.crm_lead_outbox.dead_count} danger={summary.crm_lead_outbox.dead_count > 0} /><Metric label={t('superadmin.operations.crmOutbox.oldest')} value={formatAge(summary.crm_lead_outbox.oldest_due_age_seconds, t('quiz.notAvailable'), timeUnits)} /></CardContent></Card>
        </section>
        <p className="text-xs text-muted-foreground">{t('superadmin.operations.lastUpdated', { date: formatDate(lastUpdatedAt || summary.generated_at, locale, t('quiz.notAvailable')) })}</p>
      </>}

      <Card className="border-amber-200"><CardHeader><CardTitle className="flex items-center gap-2"><ShieldAlert className="h-5 w-5 text-amber-600" />{t('superadmin.operations.cleanup.title')}</CardTitle><p className="text-sm text-muted-foreground">{t('superadmin.operations.cleanup.description')}</p></CardHeader><CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3"><Badge variant="secondary"><Eye className="mr-1 h-3 w-3" />{t('superadmin.operations.cleanup.previewOnly')}</Badge><span className="text-sm">{t('superadmin.operations.cleanup.candidates', { count: cleanupCounts.candidates })}</span>{preview?.truncated && <Badge variant="destructive">{t('superadmin.operations.cleanup.truncated')}</Badge>}</div>
        <p className="text-xs text-muted-foreground">{t('superadmin.operations.cleanup.prefixes', { prefixes: preview?.allowed_slug_prefixes.join(', ') || t('quiz.notAvailable') })}</p>
        {preview?.results.length ? <div className="overflow-x-auto rounded-md border"><table className="w-full min-w-[620px] text-left text-sm"><thead className="bg-muted/50"><tr><th className="px-3 py-2">{t('superadmin.operations.cleanup.slug')}</th><th className="px-3 py-2">{t('superadmin.operations.cleanup.age')}</th><th className="px-3 py-2">{t('superadmin.operations.cleanup.action')}</th></tr></thead><tbody>{preview.results.map((result) => <tr key={result.tenant_id} className="border-t"><td className="px-3 py-2 font-mono text-xs">{result.slug}</td><td className="px-3 py-2">{result.age_hours} {timeUnits.hours}</td><td className="px-3 py-2">{cleanupActionLabel(result.action)}</td></tr>)}</tbody></table></div> : <p className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">{t('superadmin.operations.cleanup.noCandidates')}</p>}
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-950"><p className="font-medium">{t('superadmin.operations.cleanup.warning')}</p><p className="mt-1">{t('superadmin.operations.cleanup.guard')}</p></div>
        <Button variant="destructive" disabled={!canCleanup} onClick={() => setConfirmOpen(true)}><Trash2 className="mr-2 h-4 w-4" />{t('superadmin.operations.cleanup.openConfirm')}</Button>
        {confirmOpen && <div className="space-y-3 rounded-md border border-red-300 p-4" role="dialog" aria-labelledby="cleanup-confirm-title"><h2 id="cleanup-confirm-title" className="font-semibold">{t('superadmin.operations.cleanup.confirmTitle')}</h2><p className="text-sm text-muted-foreground">{t('superadmin.operations.cleanup.confirmDescription', { token: CONFIRM_TOKEN })}</p><Input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={CONFIRM_TOKEN} aria-label={t('superadmin.operations.cleanup.confirmInput')} autoComplete="off" /><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => { setConfirmOpen(false); setConfirmation(''); }} disabled={cleaning}>{t('superadmin.operations.cleanup.cancel')}</Button><Button variant="destructive" disabled={confirmation !== CONFIRM_TOKEN || cleaning} onClick={() => void executeCleanup()}>{cleaning ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}{t('superadmin.operations.cleanup.confirm')}</Button></div></div>}
      </CardContent></Card>

      <Card className="border-blue-200"><CardHeader><CardTitle className="flex items-center gap-2"><Bot className="h-5 w-5 text-blue-600" />{t('superadmin.operations.staleRecovery.title')}</CardTitle><p className="text-sm text-muted-foreground">{t('superadmin.operations.staleRecovery.description')}</p></CardHeader><CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3"><Badge variant="secondary"><Eye className="mr-1 h-3 w-3" />{t('superadmin.operations.staleRecovery.previewOnly')}</Badge><span className="text-sm">{t('superadmin.operations.staleRecovery.threshold', { hours: STALE_AI_JOB_MIN_AGE_HOURS })}</span>{staleRecovery?.truncated && <Badge variant="destructive">{t('superadmin.operations.staleRecovery.truncated')}</Badge>}</div>
        <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4"><Metric label={t('superadmin.operations.staleRecovery.eligible')} value={staleRecovery?.eligible_count ?? 0} /><Metric label={t('superadmin.operations.staleRecovery.queued')} value={staleRecovery?.queued_count ?? 0} /><Metric label={t('superadmin.operations.staleRecovery.running')} value={staleRecovery?.running_count ?? 0} /><Metric label={t('superadmin.operations.staleRecovery.oldest')} value={formatAge(staleRecovery?.oldest_age_seconds ?? null, t('quiz.notAvailable'), timeUnits)} /></div>
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950"><p className="font-medium">{t('superadmin.operations.staleRecovery.warning')}</p><p className="mt-1">{t('superadmin.operations.staleRecovery.guard')}</p></div>
        <div className="space-y-3 rounded-md border border-blue-300 p-4" role="group" aria-labelledby="stale-recovery-confirm-title"><h2 id="stale-recovery-confirm-title" className="font-semibold">{t('superadmin.operations.staleRecovery.confirmTitle')}</h2><p className="text-sm text-muted-foreground">{t('superadmin.operations.staleRecovery.confirmDescription', { token: STALE_AI_JOB_CONFIRM_TOKEN })}</p><Input value={recoveryConfirmation} onChange={(event) => setRecoveryConfirmation(event.target.value)} placeholder={STALE_AI_JOB_CONFIRM_TOKEN} aria-label={t('superadmin.operations.staleRecovery.confirmInput')} autoComplete="off" /><Button variant="outline" disabled={recoveryConfirmation !== STALE_AI_JOB_CONFIRM_TOKEN || !staleRecovery || staleRecovery.eligible_count === 0 || staleRecovery.truncated || recovering} onClick={() => void executeStaleRecovery()}>{recovering ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <ShieldAlert className="mr-2 h-4 w-4" />}{t('superadmin.operations.staleRecovery.confirm')}</Button></div>
      </CardContent></Card>

      <Card className="border-violet-200"><CardHeader><CardTitle className="flex items-center gap-2"><Send className="h-5 w-5 text-violet-600" />{t('superadmin.operations.crmOutbox.requeueTitle')}</CardTitle><p className="text-sm text-muted-foreground">{t('superadmin.operations.crmOutbox.description')}</p></CardHeader><CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3"><Badge variant="secondary"><Eye className="mr-1 h-3 w-3" />{t('superadmin.operations.crmOutbox.previewOnly')}</Badge><span className="text-sm">{t('superadmin.operations.crmOutbox.eligible', { count: crmRequeue?.eligible_count ?? 0 })}</span></div>
        <div className="rounded-md border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950">{t('superadmin.operations.crmOutbox.guard', { limit: CRM_REQUEUE_LIMIT })}</div>
        <div className="space-y-3 rounded-md border border-violet-300 p-4" role="group" aria-labelledby="crm-requeue-confirm-title"><h2 id="crm-requeue-confirm-title" className="font-semibold">{t('superadmin.operations.crmOutbox.confirmTitle')}</h2><p className="text-sm text-muted-foreground">{t('superadmin.operations.crmOutbox.confirmDescription', { token: CRM_REQUEUE_CONFIRM_TOKEN })}</p><Input value={crmConfirmation} onChange={(event) => setCRMConfirmation(event.target.value)} placeholder={CRM_REQUEUE_CONFIRM_TOKEN} aria-label={t('superadmin.operations.crmOutbox.confirmInput')} autoComplete="off" /><Button variant="outline" disabled={crmConfirmation !== CRM_REQUEUE_CONFIRM_TOKEN || !crmRequeue || crmRequeue.eligible_count === 0 || requeuingCRM} onClick={() => void executeCRMRequeue()}>{requeuingCRM ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}{t('superadmin.operations.crmOutbox.confirm')}</Button></div>
      </CardContent></Card>
    </main>
  );
}

function Metric({ label, value, danger = false }: { label: string; value: string | number; danger?: boolean }) {
  return <div className="flex items-center justify-between gap-3"><span className="text-muted-foreground">{label}</span><strong className={danger ? 'text-red-700' : 'text-foreground'}>{value}</strong></div>;
}

function TaskList({ label, tasks, empty, danger = false }: { label: string; tasks: string[]; empty: string; danger?: boolean }) {
  return <div className="space-y-1"><span className="text-muted-foreground">{label}</span>{tasks.length ? <ul className={`space-y-0.5 break-all font-mono text-xs ${danger ? 'text-red-700' : 'text-foreground'}`}>{tasks.map((task) => <li key={task}>{task}</li>)}</ul> : <p className="text-xs text-muted-foreground">{empty}</p>}</div>;
}
