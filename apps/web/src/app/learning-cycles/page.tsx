'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Badge, Button, Card, CardContent, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { collectPages, correctiveAssignmentUrl, deriveOccurrenceState, isResendEligible, runBounded } from './helpers';

type Rule = { id: string; target_type: 'course' | 'learning_path'; course_id: string | null; learning_path_id: string | null; user_id: string; cadence_days: number; due_days: number; status: string; next_run_at: string | null; last_run_at: string | null };
type Occurrence = { id: string; rule_id: string; user_id: string; target_type: 'course' | 'learning_path'; course_id: string | null; learning_path_id: string | null; enrollment_id: string | null; scheduled_for: string; due_at: string; completed_at: string | null; status: string };
type Course = { id: string; title: string; status?: string; delivery_type?: string };
type LearningPath = { id: string; title?: string; name?: string; status: string; recurrence_mode?: string; recurrence_cadence_days?: number | null; recurrence_due_days?: number | null };
type Learner = { id: string; first_name?: string; last_name?: string; full_name?: string; email?: string; name?: string; employee_number?: string };

function targetName(item: Course | LearningPath) {
  return ('title' in item ? item.title : undefined) || ('name' in item ? item.name : undefined) || '—';
}

function learnerName(learner?: Learner) {
  return learner?.full_name || learner?.name || [learner?.first_name, learner?.last_name].filter(Boolean).join(' ') || learner?.email || '—';
}
function learnerOptionLabel(learner: Learner) {
  const name = learnerName(learner);
  const discriminator = learner.email || learner.employee_number;
  return discriminator && discriminator !== name ? `${name} · ${discriminator}` : name;
}
function message(error: unknown) {
  const value = error as { response?: { data?: { detail?: string } }; message?: string };
  return value.response?.data?.detail || value.message || 'Request failed';
}

export default function LearningCyclesPage() {
  const { t } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const canManage = role === 'methodologist';
  const [rules, setRules] = useState<Rule[]>([]);
  const [occurrences, setOccurrences] = useState<Occurrence[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [paths, setPaths] = useState<LearningPath[]>([]);
  const [learners, setLearners] = useState<Learner[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [targetType, setTargetType] = useState<'course' | 'learning_path'>('course');
  const [targetId, setTargetId] = useState('');
  const [userId, setUserId] = useState('');
  const [cadence, setCadence] = useState('365');
  const [due, setDue] = useState('30');
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkReport, setBulkReport] = useState<{ succeeded: number; failed: { id: string; error: string }[] } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [ruleResponse, occurrenceResponse, courseResponse, pathResponse, userResponse] = await Promise.all([
        api.get<Rule[]>('/v1/learning-cycles'),
        api.get<Occurrence[]>('/v1/learning-cycles/occurrences'),
        collectPages(
          async (page, perPage) => (
            await api.get<Course[]>('/v1/courses', {
              params: { status: 'published', page, per_page: perPage },
            })
          ).data,
          100,
        ),
        api.get<LearningPath[]>('/v1/learning-paths'),
        collectPages(
          async (page, perPage) => (
            await api.get<{ users: Learner[] }>('/v1/users', {
              params: { role: 'student', is_active: true, page, per_page: perPage },
            })
          ).data.users,
          500,
        ),
      ]);
      setRules(ruleResponse.data);
      setOccurrences(occurrenceResponse.data);
      setCourses(courseResponse.filter((course) => course.status === undefined || course.status === 'published').filter((course) => course.delivery_type !== 'scorm'));
      setPaths(pathResponse.data.filter((path) => path.status === 'published' && path.recurrence_mode === 'fixed_interval_after_completion'));
      setLearners(userResponse);
      setSelected(new Set());
    } catch (error) {
      setLoadError(message(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (canManage) void load(); else setLoading(false); }, [canManage, load]);

  const targets = targetType === 'course' ? courses : paths;
  const targetOptions = useMemo(() => {
    const counts = new Map<string, number>();
    targets.forEach((item) => counts.set(targetName(item), (counts.get(targetName(item)) || 0) + 1));
    return targets.map((item) => ({
      ...item,
      optionLabel: counts.get(targetName(item))! > 1
        ? `${targetName(item)} · ${item.id.slice(0, 8)}`
        : targetName(item),
    }));
  }, [targets]);
  const targetLabel = (rule: Rule | Occurrence) => {
    if (rule.target_type === 'course') return courses.find((item) => item.id === rule.course_id)?.title || t('learningCycles.unknownTarget');
    const path = paths.find((item) => item.id === rule.learning_path_id);
    return path?.title || path?.name || t('learningCycles.program');
  };
  const occurrenceByRule = useMemo(() => new Map(occurrences.map((item) => [item.rule_id, item])), [occurrences]);
  const eligible = useMemo(() => occurrences.filter(isResendEligible), [occurrences]);
  const eligibleIds = useMemo(() => new Set(eligible.map((item) => item.id)), [eligible]);

  const createRule = async () => {
    if (!targetId || !userId) return;
    setSaving(true);
    try {
      const body = targetType === 'course'
        ? { course_id: targetId, user_id: userId, cadence_days: Number(cadence), due_days: Number(due) }
        : { learning_path_id: targetId, user_id: userId };
      await api.post('/v1/learning-cycles', body);
      toast.success(t('learningCycles.created'));
      setTargetId('');
      await load();
    } catch (error) {
      toast.error(t('learningCycles.saveFailed'), { description: message(error) });
    } finally { setSaving(false); }
  };

  const setRuleState = async (rule: Rule, action: 'activate' | 'deactivate') => {
    setBusy((current) => new Set(current).add(rule.id));
    try {
      const response = await api.post<Rule>(`/v1/learning-cycles/${rule.id}/${action}`);
      setRules((current) => current.map((item) => item.id === rule.id ? response.data : item));
      toast.success(t(action === 'activate' ? 'learningCycles.activated' : 'learningCycles.deactivated'));
    } catch (error) { toast.error(t('learningCycles.actionFailed'), { description: message(error) }); }
    finally { setBusy((current) => { const next = new Set(current); next.delete(rule.id); return next; }); }
  };

  const resend = async (occurrence: Occurrence) => {
    if (!isResendEligible(occurrence) || !occurrence.enrollment_id) return;
    await api.post(`/v1/courses/enrollments/${occurrence.enrollment_id}/notification/resend`);
  };
  const resendOne = async (occurrence: Occurrence) => {
    setBusy((current) => new Set(current).add(occurrence.id));
    try { await resend(occurrence); toast.success(t('learningCycles.resendQueued')); }
    catch (error) { toast.error(t('learningCycles.resendFailed'), { description: message(error) }); }
    finally { setBusy((current) => { const next = new Set(current); next.delete(occurrence.id); return next; }); }
  };
  const resendSelected = async () => {
    const batch = eligible.filter((item) => selected.has(item.id));
    if (!batch.length) return;
    setBulkReport(null);
    setBusy((current) => new Set([...current, ...batch.map((item) => item.id)]));
    const results = await runBounded(batch, resend, 3);
    const failed = results.filter((item) => !item.ok).map((item) => ({ id: item.item.id, error: message(item.error) }));
    setBulkReport({ succeeded: results.length - failed.length, failed });
    setSelected(new Set());
    setBusy((current) => { const next = new Set(current); batch.forEach((item) => next.delete(item.id)); return next; });
    if (failed.length) toast.error(t('learningCycles.bulkPartial', { succeeded: results.length - failed.length, failed: failed.length }));
    else toast.success(t('learningCycles.bulkComplete', { count: results.length }));
  };

  if (!canManage) return <div className="p-6"><h1 className="text-2xl font-bold">{t('learningCycles.title')}</h1><p className="mt-2 text-sm text-muted-foreground">{t('learningCycles.forbidden')}</p></div>;
  return <main className="mx-auto max-w-7xl space-y-6 p-6">
    <header><h1 className="text-2xl font-bold">{t('learningCycles.title')}</h1><p className="mt-1 text-sm text-muted-foreground">{t('learningCycles.subtitle')}</p></header>
    <Card><CardContent className="space-y-4 p-5">
      <div><h2 className="font-semibold">{t('learningCycles.createTitle')}</h2><p className="text-sm text-muted-foreground">{t('learningCycles.identityHint')}</p></div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="text-sm">{t('learningCycles.targetType')}<select className="mt-1 block w-full rounded border bg-background p-2" value={targetType} onChange={(event) => { const value = event.target.value as 'course' | 'learning_path'; setTargetType(value); setTargetId(''); }}><option value="course">{t('learningCycles.course')}</option><option value="learning_path">{t('learningCycles.program')}</option></select></label>
        <label className="text-sm">{t('learningCycles.target')}<select className="mt-1 block w-full rounded border bg-background p-2" value={targetId} onChange={(event) => setTargetId(event.target.value)}><option value="">{t('learningCycles.selectTarget')}</option>{targetOptions.map((item) => <option key={item.id} value={item.id}>{item.optionLabel}</option>)}</select></label>
        <label className="text-sm">{t('learningCycles.learner')}<select className="mt-1 block w-full rounded border bg-background p-2" value={userId} onChange={(event) => setUserId(event.target.value)}><option value="">{t('learningCycles.selectLearner')}</option>{learners.map((item) => <option key={item.id} value={item.id}>{learnerOptionLabel(item)}</option>)}</select></label>
        {targetType === 'course' && <>
          <div className="text-sm"><label htmlFor="learning-cycle-cadence">{t('learningCycles.cadenceDays')}</label><Input id="learning-cycle-cadence" aria-describedby="learning-cycle-cadence-hint" type="number" min={1} max={3660} value={cadence} onChange={(event) => setCadence(event.target.value)} /><span id="learning-cycle-cadence-hint" className="mt-1 block text-xs text-muted-foreground">{t('learningCycles.cadenceHint')}</span></div>
          <div className="text-sm"><label htmlFor="learning-cycle-due">{t('learningCycles.dueDays')}</label><Input id="learning-cycle-due" aria-describedby="learning-cycle-due-hint" type="number" min={0} max={3650} value={due} onChange={(event) => setDue(event.target.value)} /><span id="learning-cycle-due-hint" className="mt-1 block text-xs text-muted-foreground">{t('learningCycles.dueHint')}</span></div>
        </>}
      </div>
      <div className="flex justify-end"><Button onClick={() => void createRule()} disabled={saving || !targetId || !userId || (targetType === 'course' && (!Number.isInteger(Number(cadence)) || Number(cadence) < 1 || !Number.isInteger(Number(due)) || Number(due) < 0 || Number(due) > Number(cadence)))}>{saving ? t('learningCycles.saving') : t('learningCycles.createDraft')}</Button></div>
    </CardContent></Card>

    <Card><CardContent className="space-y-4 p-5">
      <div><h2 className="font-semibold">{t('learningCycles.rulesTitle')}</h2><p className="text-sm text-muted-foreground">{t('learningCycles.rulesHint')}</p></div>
      {loading ? <p>{t('common.loading')}</p> : loadError ? <div className="space-y-2"><p className="text-sm text-destructive">{loadError}</p><Button variant="outline" onClick={() => void load()}>{t('common.retry')}</Button></div> : rules.length === 0 ? <p className="text-sm text-muted-foreground">{t('learningCycles.emptyRules')}</p> : <div className="space-y-3">{rules.map((rule) => {
        const occurrence = occurrenceByRule.get(rule.id);
        const learner = learners.find((item) => item.id === rule.user_id);
        const state = occurrence ? deriveOccurrenceState(occurrence) : null;
        return <article key={rule.id} className="grid gap-3 rounded-lg border p-4 lg:grid-cols-[1.5fr_1fr_1fr_auto]">
          <div><p className="text-xs font-medium uppercase text-muted-foreground">{t('learningCycles.target')}</p><p className="font-medium">{targetLabel(rule)}</p><p className="mt-2 text-xs font-medium uppercase text-muted-foreground">{t('learningCycles.learner')}</p><p>{learnerName(learner)}</p></div>
          <div className="space-y-1 text-sm"><Badge variant={rule.status === 'active' ? 'default' : 'outline'}>{t(`learningCycles.status.${rule.status}` as never)}</Badge><p>{t('learningCycles.cadenceDue', { cadence: rule.cadence_days, due: rule.due_days })}</p><p className="text-muted-foreground">{t('learningCycles.nextRun')}: {dateText(rule.next_run_at)}</p><p className="text-muted-foreground">{t('learningCycles.lastRun')}: {dateText(rule.last_run_at)}</p></div>
          <div className="text-sm">{occurrence ? <><p className="font-medium">{t('learningCycles.latestOccurrence')}</p><Badge variant={state === 'overdue' || state === 'completed_late' ? 'destructive' : 'secondary'}>{t(`learningCycles.occurrence.${state}` as never)}</Badge><p className="mt-1 text-muted-foreground">{t('learningCycles.dueAt')}: {dateText(occurrence.due_at)}</p>{occurrence.completed_at && <p className="text-muted-foreground">{t('learningCycles.completedAt')}: {dateText(occurrence.completed_at)}</p>}</> : <p className="text-muted-foreground">{t('learningCycles.noOccurrence')}</p>}</div>
          <div className="flex flex-wrap items-start gap-2">{rule.status === 'active' ? <Button size="sm" variant="outline" disabled={busy.has(rule.id)} onClick={() => void setRuleState(rule, 'deactivate')}>{t('learningCycles.deactivate')}</Button> : <Button size="sm" disabled={busy.has(rule.id)} onClick={() => void setRuleState(rule, 'activate')}>{t('learningCycles.activate')}</Button>}</div>
        </article>;
      })}</div>}
    </CardContent></Card>

    <Card><CardContent className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{t('learningCycles.attentionTitle')}</h2><p className="text-sm text-muted-foreground">{t('learningCycles.attentionHint')}</p></div><Button variant="outline" disabled={!selected.size || busy.size > 0} onClick={() => void resendSelected()}>{t('learningCycles.resendSelected', { count: selected.size })}</Button></div>
      {bulkReport && <div role="status" className={`rounded border p-3 text-sm ${bulkReport.failed.length ? 'border-destructive' : 'border-border'}`}><p>{t('learningCycles.bulkSummary', { succeeded: bulkReport.succeeded, failed: bulkReport.failed.length })}</p>{bulkReport.failed.map((item) => <p key={item.id} className="mt-1 text-destructive">{item.id}: {item.error}</p>)}</div>}
      {!eligible.length ? <p className="text-sm text-muted-foreground">{t('learningCycles.noAttention')}</p> : <>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={eligible.length > 0 && eligible.every((item) => selected.has(item.id))} onChange={(event) => setSelected(event.target.checked ? new Set(eligibleIds) : new Set())} />{t('learningCycles.selectAll')}</label>
        <div className="space-y-2">{eligible.map((item) => {
          const learner = learners.find((person) => person.id === item.user_id);
          const url = correctiveAssignmentUrl(item.course_id, item.user_id);
          const state = deriveOccurrenceState(item);
          return <article key={item.id} className="grid items-center gap-3 rounded border p-3 md:grid-cols-[auto_1fr_auto]">
            <input aria-label={t('learningCycles.selectOccurrence', { learner: learnerName(learner) })} type="checkbox" checked={selected.has(item.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(item.id); else next.delete(item.id); return next; })} />
            <div><p className="font-medium">{targetLabel(item)} · {learnerName(learner)}</p><p className="text-sm text-muted-foreground"><Badge variant={state === 'overdue' ? 'destructive' : 'secondary'}>{t(`learningCycles.occurrence.${state}` as never)}</Badge> · {t('learningCycles.dueAt')}: {dateText(item.due_at)}</p></div>
            <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy.has(item.id)} onClick={() => void resendOne(item)}>{t('learningCycles.resend')}</Button>{url && <Link className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90" href={url}>{t('learningCycles.correctiveAssignment')}</Link>}</div>
          </article>;
        })}</div>
      </>}
    </CardContent></Card>
  </main>;
}

function dateText(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—';
}
