'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  Info,
  Lock,
  Plus,
  Save,
  Search,
  Send,
  Users,
  X,
} from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Badge, Button, Card, CardContent, DateInput, Input } from '@/components/ui';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { PROGRAM_SCENARIOS, type ProgramScenarioId } from '@/features/learning-programs/programScenarios';

type ProgramStatus = 'draft' | 'published' | 'archived';
type SequencingMode = 'linear' | 'open';
type CertificateMode = 'none' | 'final_course';
type RecurrenceMode = 'none' | 'fixed_interval_after_completion';
type Stage = 'basic' | 'content' | 'audience' | 'review';
type AudienceTab = 'learners' | 'cohorts' | 'departments' | 'positions';

type CourseStep = {
  course_id: string;
  title: string;
  order_index?: number;
  required: boolean;
};

type PathSummary = {
  id: string;
  family_id?: string | null;
  title: string;
  description?: string;
  status: ProgramStatus;
  version?: number;
  sequencing_mode?: SequencingMode;
  course_count: number;
  assignment_count?: number;
  created_at?: string;
  published_at?: string | null;
  scenario?: string | null;
  responsible_user_id?: string | null;
  default_due_days?: number | null;
  certificate_mode?: CertificateMode | null;
  certificate_validity_months?: number | null;
  recurrence_mode?: RecurrenceMode | null;
  recurrence_cadence_days?: number | null;
  recurrence_due_days?: number | null;
};

type PathDetail = PathSummary & { courses: CourseStep[] };

type Course = { id: string; title: string; status?: string };
type AudienceOption = {
  id: string;
  name?: string;
  full_name?: string;
  first_name?: string;
  last_name?: string;
  title?: string;
  email?: string;
};
type Assignment = {
  id: string;
  user_id?: string;
  user_name?: string;
  user_email?: string;
  status?: 'active' | 'completed' | 'cancelled';
  starts_at?: string;
  due_at?: string;
};

type LearnerStep = CourseStep & { state: 'locked' | 'available' | 'completed' };
type LearnerProgram = {
  id: string;
  title: string;
  description?: string;
  version?: number;
  sequencing_mode?: SequencingMode;
  current_course_id?: string | null;
  progress_percent?: number;
  completed_required_courses?: number;
  total_required_courses?: number;
  completed_courses?: number;
  total_courses?: number;
  courses?: LearnerStep[];
  steps?: LearnerStep[];
};

const MANAGER_ROLE = 'methodologist';
const STAGES: Stage[] = ['basic', 'content', 'audience', 'review'];
const AUDIENCE_TABS: AudienceTab[] = ['learners', 'cohorts', 'departments', 'positions'];

function asList<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const key of ['items', 'users', 'cohorts', 'departments', 'positions']) {
      if (Array.isArray(record[key])) return record[key] as T[];
    }
  }
  return [];
}

function errorDescription(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined;
  const candidate = error as {
    response?: { data?: { detail?: unknown; message?: unknown; details?: unknown } };
    message?: string;
  };
  const data = candidate.response?.data;
  for (const value of [data?.detail, data?.message, data?.details]) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return candidate.message;
}

function optionLabel(option: AudienceOption): string {
  const personName = [option.first_name, option.last_name].filter(Boolean).join(' ').trim();
  const primary = option.full_name || personName || option.name || option.title;
  if (primary && option.email) return `${primary} · ${option.email}`;
  return primary || option.email || option.id;
}

function dateLabel(value?: string | null): string {
  if (!value) return '';
  return new Intl.DateTimeFormat(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(value));
}

function normalizeScenario(value: unknown): ProgramScenarioId | null {
  if (value === 'custom') return null;
  return PROGRAM_SCENARIOS.some((item) => item.id === value)
    ? (value as ProgramScenarioId)
    : null;
}

export default function LearningPathsPage() {
  const { t, tp } = useT();
  const { confirm, dialog } = useConfirm();
  const role = useAuthStore((state) => state.user?.role);
  const canManage = role === MANAGER_ROLE;
  const isLearner = role === 'student';

  const [paths, setPaths] = useState<PathSummary[]>([]);
  const [learnerPrograms, setLearnerPrograms] = useState<LearnerProgram[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [audience, setAudience] = useState<Record<AudienceTab, AudienceOption[]>>({ learners: [], cohorts: [], departments: [], positions: [] });
  const [methodologists, setMethodologists] = useState<AudienceOption[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [selected, setSelected] = useState<PathDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [stage, setStage] = useState<Stage>('basic');
  const [scenario, setScenario] = useState<ProgramScenarioId | null>(null);
  const [audienceTab, setAudienceTab] = useState<AudienceTab>('learners');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [sequencingMode, setSequencingMode] = useState<SequencingMode>('linear');
  const [steps, setSteps] = useState<CourseStep[]>([]);
  const [courseSearch, setCourseSearch] = useState('');
  const [audienceSearch, setAudienceSearch] = useState('');
  const [selectedAudience, setSelectedAudience] = useState<Record<AudienceTab, string[]>>({ learners: [], cohorts: [], departments: [], positions: [] });
  const [startsAt, setStartsAt] = useState('');
  const [dueAt, setDueAt] = useState('');
  const [responsibleUserId, setResponsibleUserId] = useState('');
  const [defaultDueDays, setDefaultDueDays] = useState('');
  const [certificateMode, setCertificateMode] = useState<CertificateMode>('none');
  const [certificateValidityMonths, setCertificateValidityMonths] = useState('');
  const [recurrenceMode, setRecurrenceMode] = useState<RecurrenceMode>('none');
  const [recurrenceCadenceDays, setRecurrenceCadenceDays] = useState('');
  const [recurrenceDueDays, setRecurrenceDueDays] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [contextualProgramId, setContextualProgramId] = useState<string | null>(null);
  const contextualProgramApplied = useRef<string | null>(null);

  useEffect(() => {
    if (selected) setScenario(normalizeScenario(selected.scenario));
  }, [selected]);

  useEffect(() => {
    const programId = new URLSearchParams(window.location.search).get('program_id')?.trim();
    setContextualProgramId(programId || null);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (canManage) {
        const supportingData = Promise.allSettled([
          api.get<Course[]>('/v1/courses?status=published&per_page=100'),
          api.get<AudienceOption[]>('/v1/users?role=student&is_active=true&per_page=500'),
          api.get<AudienceOption[]>('/v1/cohorts'),
          api.get<AudienceOption[]>('/v1/departments'),
          api.get<AudienceOption[]>('/v1/positions'),
          api.get<AudienceOption[]>('/v1/users?role=methodologist&is_active=true&per_page=500'),
        ]);
        const pathsResponse = await api.get<PathSummary[]>('/v1/learning-paths');
        setPaths(asList<PathSummary>(pathsResponse.data));
        setLoading(false);
        const [coursesResponse, learnersResponse, cohortsResponse, departmentsResponse, positionsResponse, methodologistsResponse] = await supportingData;
        if (coursesResponse.status === 'fulfilled') setCourses(asList<Course>(coursesResponse.value.data));
        setAudience({
          learners: learnersResponse.status === 'fulfilled' ? asList<AudienceOption>(learnersResponse.value.data) : [],
          cohorts: cohortsResponse.status === 'fulfilled' ? asList<AudienceOption>(cohortsResponse.value.data) : [],
          departments: departmentsResponse.status === 'fulfilled' ? asList<AudienceOption>(departmentsResponse.value.data) : [],
          positions: positionsResponse.status === 'fulfilled' ? asList<AudienceOption>(positionsResponse.value.data) : [],
        });
        setMethodologists(methodologistsResponse.status === 'fulfilled' ? asList<AudienceOption>(methodologistsResponse.value.data) : []);
      } else if (isLearner) {
        const response = await api.get<LearnerProgram[]>('/v1/learning-paths/my');
        setLearnerPrograms(asList<LearnerProgram>(response.data));
      }
    } catch (error) {
      toast.error(t('learningPaths.loadFailed'), { description: errorDescription(error) });
    } finally {
      setLoading(false);
    }
  }, [canManage, isLearner, t]);

  useEffect(() => { load(); }, [load]);

  const resetEditor = () => {
    setSelected(null);
    setEditing(true);
    setScenario(null);
    setStage('basic');
    setTitle('');
    setDescription('');
    setSequencingMode('linear');
    setSteps([]);
    setAssignments([]);
    setSelectedAudience({ learners: [], cohorts: [], departments: [], positions: [] });
    setStartsAt('');
    setDueAt('');
    setResponsibleUserId('');
    setDefaultDueDays('');
    setCertificateMode('none');
    setCertificateValidityMonths('');
    setRecurrenceMode('none');
    setRecurrenceCadenceDays('');
    setRecurrenceDueDays('');
  };

  const applyDetail = (detail: PathDetail) => {
    setSelected(detail);
    setTitle(detail.title);
    setDescription(detail.description || '');
    setSequencingMode(detail.sequencing_mode || 'linear');
    setSteps((detail.courses || []).sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0)));
    setResponsibleUserId(detail.responsible_user_id || '');
    setDefaultDueDays(detail.default_due_days == null ? '' : String(detail.default_due_days));
    setCertificateMode(detail.certificate_mode === 'final_course' ? 'final_course' : 'none');
    setCertificateValidityMonths(detail.certificate_validity_months == null ? '' : String(detail.certificate_validity_months));
    setRecurrenceMode(detail.recurrence_mode === 'fixed_interval_after_completion' ? 'fixed_interval_after_completion' : 'none');
    setRecurrenceCadenceDays(detail.recurrence_cadence_days == null ? '' : String(detail.recurrence_cadence_days));
    setRecurrenceDueDays(detail.recurrence_due_days == null ? '' : String(detail.recurrence_due_days));
  };

  const selectPath = useCallback(async (summary: PathSummary) => {
    setSaving(true);
    try {
      const [detailResponse, assignmentResponse] = await Promise.all([
        api.get<PathDetail>(`/v1/learning-paths/${summary.id}`),
        api.get<Assignment[]>(`/v1/learning-paths/${summary.id}/assignments`),
      ]);
      applyDetail(detailResponse.data);
      setAssignments(asList<Assignment>(assignmentResponse.data));
      setEditing(true);
      setStage('basic');
    } catch (error) {
      toast.error(t('learningPaths.loadFailed'), { description: errorDescription(error) });
    } finally {
      setSaving(false);
    }
  }, [t]);

  useEffect(() => {
    if (!canManage || loading || !contextualProgramId || contextualProgramApplied.current === contextualProgramId) return;
    const contextualProgram = paths.find((path) => path.id === contextualProgramId);
    if (!contextualProgram || contextualProgram.status === 'archived') return;
    contextualProgramApplied.current = contextualProgramId;
    setScenario(null);
    void selectPath(contextualProgram);
  }, [canManage, contextualProgramId, loading, paths, selectPath]);

  const updatePathList = (detail: PathDetail) => {
    setPaths((items) => {
      const summary: PathSummary = { ...detail, course_count: detail.courses.length };
      const exists = items.some((item) => item.id === summary.id);
      return exists ? items.map((item) => item.id === summary.id ? { ...item, ...summary } : item) : [summary, ...items];
    });
  };

  const persistDraft = async (
    options: { notify?: boolean } = {},
  ): Promise<string | null> => {
    if (!title.trim()) return null;
    const parsedDueDays = defaultDueDays.trim() ? Number(defaultDueDays) : null;
    if (parsedDueDays !== null && (!Number.isInteger(parsedDueDays) || parsedDueDays < 1 || parsedDueDays > 3650)) {
      toast.error(t('learningPaths.defaultDueDaysInvalid' as never));
      return null;
    }
    const parsedCertificateValidity = certificateMode === 'final_course' && certificateValidityMonths.trim() ? Number(certificateValidityMonths) : null;
    if (parsedCertificateValidity !== null && (!Number.isInteger(parsedCertificateValidity) || parsedCertificateValidity < 1 || parsedCertificateValidity > 120)) {
      toast.error(t('learningPaths.certificateValidityInvalid' as never));
      return null;
    }
    const parsedRecurrenceCadence = recurrenceMode === 'fixed_interval_after_completion' && recurrenceCadenceDays.trim() ? Number(recurrenceCadenceDays) : null;
    const parsedRecurrenceDue = recurrenceMode === 'fixed_interval_after_completion' && recurrenceDueDays.trim() ? Number(recurrenceDueDays) : null;
    if (
      recurrenceMode === 'fixed_interval_after_completion'
      && (parsedRecurrenceCadence === null || parsedRecurrenceDue === null
        || !Number.isInteger(parsedRecurrenceCadence) || !Number.isInteger(parsedRecurrenceDue)
        || parsedRecurrenceCadence < 1 || parsedRecurrenceCadence > 3650
        || parsedRecurrenceDue < 1 || parsedRecurrenceDue > 3650
        || parsedRecurrenceDue > parsedRecurrenceCadence)
    ) {
      toast.error(t('learningPaths.recurrenceInvalid' as never));
      return null;
    }
    const policyPayload = {
      certificate_mode: certificateMode,
      certificate_validity_months: certificateMode === 'final_course' ? parsedCertificateValidity : null,
      recurrence_mode: recurrenceMode,
      recurrence_cadence_days: recurrenceMode === 'fixed_interval_after_completion' ? parsedRecurrenceCadence : null,
      recurrence_due_days: recurrenceMode === 'fixed_interval_after_completion' ? parsedRecurrenceDue : null,
    };
    setSaving(true);
    try {
      let id = selected?.id;
      if (!id) {
        const response = await api.post<PathSummary>('/v1/learning-paths', {
          title: title.trim(),
          description: description.trim(),
          sequencing_mode: sequencingMode,
          scenario: scenario ?? 'custom',
          responsible_user_id: responsibleUserId || null,
          default_due_days: parsedDueDays,
          ...policyPayload,
        });
        const summary = response.data;
        id = summary.id;
        const detail: PathDetail = { ...summary, status: 'draft', course_count: 0, courses: [] };
        applyDetail(detail);
        updatePathList(detail);
      } else {
        await api.patch(`/v1/learning-paths/${id}`, {
          title: title.trim(),
          description: description.trim(),
          sequencing_mode: sequencingMode,
          scenario: scenario ?? 'custom',
          responsible_user_id: responsibleUserId || null,
          default_due_days: parsedDueDays,
          ...policyPayload,
        });
      }
      const response = await api.put<PathDetail>(`/v1/learning-paths/${id}/curriculum`, {
        steps: steps.map(({ course_id, required }) => ({ course_id, required })),
      });
      if (response.data) {
        applyDetail(response.data);
        updatePathList(response.data);
      }
      if (options.notify !== false) {
        toast.success(t('learningPaths.saved'));
      }
      return id;
    } catch (error) {
      toast.error(t('learningPaths.saveFailed'), { description: errorDescription(error) });
      return null;
    } finally {
      setSaving(false);
    }
  };

  const assignmentPayload = () => ({
    user_ids: selectedAudience.learners,
    cohort_ids: selectedAudience.cohorts,
    department_ids: selectedAudience.departments,
    position_ids: selectedAudience.positions,
    starts_at: startsAt ? new Date(`${startsAt}T00:00:00`).toISOString() : null,
    due_at: dueAt ? new Date(`${dueAt}T23:59:59`).toISOString() : null,
  });

  const assignAudience = async (pathId: string) => {
    await api.post(`/v1/learning-paths/${pathId}/assignments`, assignmentPayload());
    const response = await api.get<Assignment[]>(`/v1/learning-paths/${pathId}/assignments`);
    setAssignments(asList<Assignment>(response.data));
    setSelectedAudience({ learners: [], cohorts: [], departments: [], positions: [] });
  };

  const publish = async () => {
    if (!title.trim() || steps.length === 0 || !steps.some((step) => step.required)) return;
    const id = await persistDraft({ notify: false });
    if (!id) return;
    setSaving(true);
    try {
      const response = await api.post<PathDetail>(`/v1/learning-paths/${id}/publish`);
      if (response.data) {
        applyDetail(response.data);
        updatePathList(response.data);
      } else {
        setSelected((current) => current ? { ...current, status: 'published', published_at: new Date().toISOString() } : current);
        setPaths((items) => items.map((item) => item.id === id ? { ...item, status: 'published', published_at: new Date().toISOString() } : item));
      }
      if (totalSelectedAudience > 0) {
        try {
          await assignAudience(id);
          toast.success(t('learningPaths.publishedAndAssigned'));
        } catch (error) {
          setStage('audience');
          toast.error(t('learningPaths.publishedButAssignmentFailed'), {
            description: errorDescription(error),
          });
        }
      } else {
        toast.success(t('learningPaths.published'));
      }
    } catch (error) {
      toast.error(t('learningPaths.publishFailed'), { description: errorDescription(error) });
    } finally {
      setSaving(false);
    }
  };

  const createVersion = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const response = await api.post<PathDetail | PathSummary>(`/v1/learning-paths/${selected.id}/versions`);
      const data = response.data as PathDetail | PathSummary;
      if ('courses' in data && data.courses) {
        applyDetail(data);
        updatePathList(data);
      } else {
        await selectPath(data);
      }
      setStage('basic');
      toast.success(t('learningPaths.versionCreated'));
    } catch (error) {
      toast.error(t('learningPaths.saveFailed'), { description: errorDescription(error) });
    } finally {
      setSaving(false);
    }
  };

  const toggleStep = (course: Course) => {
    setSteps((current) => current.some((step) => step.course_id === course.id)
      ? current.filter((step) => step.course_id !== course.id)
      : [...current, { course_id: course.id, title: course.title, required: true }]);
  };

  const moveStep = (index: number, direction: -1 | 1) => {
    setSteps((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  };

  const toggleAudience = (id: string) => {
    setSelectedAudience((current) => ({
      ...current,
      [audienceTab]: current[audienceTab].includes(id)
        ? current[audienceTab].filter((item) => item !== id)
        : [...current[audienceTab], id],
    }));
  };

  const assign = async () => {
    if (!selected || selected.status !== 'published') return;
    setSaving(true);
    try {
      await assignAudience(selected.id);
      toast.success(t('learningPaths.assigned'));
    } catch (error) {
      toast.error(t('learningPaths.assignFailed'), { description: errorDescription(error) });
    } finally {
      setSaving(false);
    }
  };

  const cancelAssignment = async (assignmentId: string) => {
    if (!selected) return;
    const accepted = await confirm({
      title: t('learningPaths.cancelConfirmTitle'),
      message: t('learningPaths.cancelConfirmMessage'),
      variant: 'warning',
      confirmLabel: t('learningPaths.cancelAssignment'),
    });
    if (!accepted) return;
    setSaving(true);
    try {
      await api.post(`/v1/learning-paths/assignments/${assignmentId}/cancel`);
      setAssignments((current) => current.map((assignment) => (
        assignment.id === assignmentId ? { ...assignment, status: 'cancelled' } : assignment
      )));
    } catch (error) {
      toast.error(t('learningPaths.assignFailed'), { description: errorDescription(error) });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-6 text-muted-foreground">{t('common.loading')}</div>;
  if (!canManage && !isLearner) return <ForbiddenState t={t} />;
  if (isLearner) return <LearnerView programs={learnerPrograms} t={t} tp={tp} />;

  const isDraft = !selected || selected.status === 'draft';
  const canPublish = Boolean(
    title.trim()
    && steps.length > 0
    && steps.some((step) => step.required)
    && (!selected || selected.status === 'draft'),
  );
  const filteredCourses = courses.filter((course) => course.title.toLowerCase().includes(courseSearch.toLowerCase()));
  const currentAudience = audience[audienceTab].filter((item) => optionLabel(item).toLowerCase().includes(audienceSearch.toLowerCase()));
  const totalSelectedAudience = Object.values(selectedAudience).reduce((total, ids) => total + ids.length, 0);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t('learningPaths.title')}</h1>
          <p className="mt-1 max-w-2xl text-muted-foreground">{t('learningPaths.managerDescription')}</p>
        </div>
        {(paths.length > 0 || editing) && (
          <Button className="gap-2 self-start" onClick={resetEditor}>
            <Plus className="h-4 w-4" aria-hidden="true" />{t('learningPaths.new')}
          </Button>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="rounded-lg border bg-background p-3" aria-label={t('learningPaths.programList')}>
          <div className="mb-3 flex items-center justify-between px-1">
            <h2 className="font-semibold">{t('learningPaths.programs')}</h2>
            <span className="text-xs text-muted-foreground">{paths.length}</span>
          </div>
          <div className="space-y-2">
            {paths.map((path) => (
              <button
                key={path.id}
                type="button"
                aria-pressed={selected?.id === path.id}
                onClick={() => selectPath(path)}
                className={`w-full rounded-md border p-3 text-left transition-colors hover:bg-muted/50 ${selected?.id === path.id ? 'border-primary bg-primary/5' : 'border-border'}`}
              >
                <div className="truncate font-medium">{path.title}</div>
                <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                  <Badge variant={path.status === 'published' ? 'default' : 'secondary'}>{t(`learningPaths.status.${path.status}` as never)}</Badge>
                  <span>v{path.version || 1}</span>
                  <span>{tp('common.counts.course', path.course_count)}</span>
                  <span>
                    {path.assignment_count == null
                      ? '—'
                      : tp('common.counts.learner', path.assignment_count)}
                  </span>
                </div>
              </button>
            ))}
          </div>
          {!paths.length && <p className="px-1 py-4 text-sm text-muted-foreground">{t('learningPaths.empty')}</p>}
        </aside>

        {!editing ? (
          <EmptyManagerState onCreate={resetEditor} t={t} />
        ) : (
          <section className="min-w-0 rounded-lg border bg-background p-4 sm:p-6" aria-label={t('learningPaths.editor')}>
            <div className="mb-6 flex flex-col gap-3 border-b pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate text-xl font-semibold">{title || t('learningPaths.new')}</h2>
                  {selected && <Badge variant={selected.status === 'published' ? 'default' : 'secondary'}>{t(`learningPaths.status.${selected.status}` as never)}</Badge>}
                </div>
                {selected && <p className="mt-1 text-sm text-muted-foreground">v{selected.version || 1} · {tp('common.counts.course', selected.course_count)} · {selected.assignment_count == null ? '—' : tp('common.counts.learner', selected.assignment_count)}</p>}
              </div>
              {selected?.status === 'published' && <Button variant="outline" onClick={createVersion} disabled={saving}>{t('learningPaths.newVersion')}</Button>}
            </div>

            <nav className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label={t('learningPaths.stages')}>
              {STAGES.map((item, index) => (
                <button key={item} type="button" role="tab" aria-selected={stage === item} onClick={() => setStage(item)} className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${stage === item ? 'border-primary bg-primary/5 text-primary' : 'border-border text-muted-foreground hover:bg-muted/50'}`}>
                  <span className="mr-2 font-semibold">{index + 1}</span>{t(`learningPaths.stage.${item}` as never)}
                </button>
              ))}
            </nav>

            {stage === 'basic' && <><BasicStage scenario={scenario} setScenario={setScenario} title={title} description={description} sequencingMode={sequencingMode} responsibleUserId={responsibleUserId} setResponsibleUserId={setResponsibleUserId} defaultDueDays={defaultDueDays} setDefaultDueDays={setDefaultDueDays} methodologists={methodologists} disabled={!isDraft} setTitle={setTitle} setDescription={setDescription} setSequencingMode={setSequencingMode} t={t} /><BasicSettings responsibleUserId={responsibleUserId} setResponsibleUserId={setResponsibleUserId} defaultDueDays={defaultDueDays} setDefaultDueDays={setDefaultDueDays} certificateMode={certificateMode} setCertificateMode={setCertificateMode} certificateValidityMonths={certificateValidityMonths} setCertificateValidityMonths={setCertificateValidityMonths} recurrenceMode={recurrenceMode} setRecurrenceMode={setRecurrenceMode} recurrenceCadenceDays={recurrenceCadenceDays} setRecurrenceCadenceDays={setRecurrenceCadenceDays} recurrenceDueDays={recurrenceDueDays} setRecurrenceDueDays={setRecurrenceDueDays} methodologists={methodologists} disabled={!isDraft} t={t} /></>}
            {stage === 'content' && selected?.status === 'draft' && <div className="mb-5 flex flex-col gap-3 rounded-md border border-primary/20 bg-primary/5 p-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium">{t('learningPaths.createCourseFromMaterials' as never)}</p><p className="mt-1 text-sm text-muted-foreground">{t('learningPaths.createCourseFromMaterialsHint' as never)}</p></div><Link href={`/ai/generate?program_id=${encodeURIComponent(selected.id)}`} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-md border border-primary bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"><Plus className="h-4 w-4" aria-hidden="true" />{t('learningPaths.createCourseFromMaterialsAction' as never)}</Link></div>}
            {stage === 'content' && <ContentStage courses={filteredCourses} steps={steps} search={courseSearch} setSearch={setCourseSearch} onToggle={toggleStep} onRemove={(id) => setSteps((current) => current.filter((step) => step.course_id !== id))} onMove={moveStep} onRequired={(id, required) => setSteps((current) => current.map((step) => step.course_id === id ? { ...step, required } : step))} disabled={!isDraft} t={t} tp={tp} />}
            {stage === 'audience' && <AudienceStage selected={selected} audienceTab={audienceTab} setAudienceTab={setAudienceTab} options={currentAudience} selectedIds={selectedAudience[audienceTab]} search={audienceSearch} setSearch={setAudienceSearch} onToggle={toggleAudience} startsAt={startsAt} dueAt={dueAt} setStartsAt={setStartsAt} setDueAt={setDueAt} assignments={assignments} onCancel={cancelAssignment} onAssign={assign} saving={saving} totalSelected={totalSelectedAudience} t={t} />}
            {stage === 'review' && <ReviewStage selected={selected} title={title} description={description} sequencingMode={sequencingMode} steps={steps} totalSelectedAudience={totalSelectedAudience} canPublish={canPublish} onPublish={publish} saving={saving} t={t} />}

            <div className="mt-8 flex flex-col-reverse gap-3 border-t pt-5 sm:flex-row sm:items-center sm:justify-between">
              <Button variant="ghost" onClick={() => setEditing(false)}>{t('learningPaths.closeEditor')}</Button>
              <div className="flex flex-col gap-3 sm:flex-row">
                {isDraft && <Button variant="outline" onClick={() => void persistDraft()} disabled={saving || !title.trim()} className="gap-2"><Save className="h-4 w-4" aria-hidden="true" />{t('learningPaths.saveDraft')}</Button>}
                {stage !== 'basic' && <Button variant="ghost" onClick={() => setStage(STAGES[STAGES.indexOf(stage) - 1])}>{t('learningPaths.back')}</Button>}
                {stage !== 'review' && <Button onClick={() => setStage(STAGES[STAGES.indexOf(stage) + 1])}>{t('learningPaths.next')}</Button>}
              </div>
            </div>
          </section>
        )}
      </div>
      {dialog}
    </div>
  );
}

function EmptyManagerState({ onCreate, t }: { onCreate: () => void; t: (key: never, params?: Record<string, string | number>) => string }) {
  return <div className="flex min-h-[360px] items-center justify-center rounded-lg border border-dashed p-8 text-center"><div className="max-w-md"><BookOpen className="mx-auto mb-4 h-10 w-10 text-primary" aria-hidden="true" /><h2 className="text-xl font-semibold">{t('learningPaths.emptyTitle' as never)}</h2><p className="mt-2 text-sm text-muted-foreground">{t('learningPaths.emptyDescription' as never)}</p><Button className="mt-6 gap-2" onClick={onCreate}><Plus className="h-4 w-4" aria-hidden="true" />{t('learningPaths.new' as never)}</Button></div></div>;
}

function ForbiddenState({ t }: { t: (key: never, params?: Record<string, string | number>) => string }) {
  return <div className="mx-auto max-w-3xl p-6"><Card><CardContent className="p-8 text-center"><Info className="mx-auto mb-3 h-8 w-8 text-muted-foreground" aria-hidden="true" /><h1 className="text-xl font-semibold">{t('learningPaths.forbidden' as never)}</h1></CardContent></Card></div>;
}

function BasicStage({ scenario, setScenario, title, description, sequencingMode, responsibleUserId, setResponsibleUserId, defaultDueDays, setDefaultDueDays, methodologists, disabled, setTitle, setDescription, setSequencingMode, t }: { scenario: ProgramScenarioId | null; setScenario: (value: ProgramScenarioId | null) => void; title: string; description: string; sequencingMode: SequencingMode; responsibleUserId: string; setResponsibleUserId: (value: string) => void; defaultDueDays: string; setDefaultDueDays: (value: string) => void; methodologists: AudienceOption[]; disabled: boolean; setTitle: (value: string) => void; setDescription: (value: string) => void; setSequencingMode: (value: SequencingMode) => void; t: (key: never, params?: Record<string, string | number>) => string }) {
  const selectedScenario = PROGRAM_SCENARIOS.find((item) => item.id === scenario);
  return <div className="space-y-6"><div><h3 className="text-lg font-semibold">{t('learningPaths.stage.basic' as never)}</h3><p className="mt-1 text-sm text-muted-foreground">{t('learningPaths.basicHint' as never)}</p></div><fieldset disabled={disabled} className="space-y-3"><legend className="text-sm font-medium">{t('learningPaths.scenarioTitle' as never)}</legend><p className="text-sm text-muted-foreground">{t('learningPaths.scenarioHint' as never)}</p><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><label className={`cursor-pointer rounded-md border p-4 ${scenario === null ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'}`}><input className="sr-only" type="radio" name="program-scenario" checked={scenario === null} onChange={() => setScenario(null)} /><span className="font-medium">{t('learningPaths.scenarioOptional' as never)}</span><span className="mt-1 block text-sm text-muted-foreground">{t('learningPaths.scenarioOptionalHint' as never)}</span></label>{PROGRAM_SCENARIOS.map((item) => <label key={item.id} className={`cursor-pointer rounded-md border p-4 ${scenario === item.id ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'}`}><input className="sr-only" type="radio" name="program-scenario" checked={scenario === item.id} onChange={() => setScenario(item.id)} /><span className="font-medium">{t(item.titleKey as never)}</span><span className="mt-1 block text-sm text-muted-foreground">{t(item.descriptionKey as never)}</span></label>)}</div>{selectedScenario && <div className="rounded-md border border-primary/20 bg-primary/5 p-4 text-sm"><p className="font-medium">{t('learningPaths.scenarioGuidanceLabel' as never)}</p><p className="mt-1 text-muted-foreground">{t(selectedScenario.guidanceKey as never)}</p><p className="mt-3 text-muted-foreground"><span className="font-medium text-foreground">{t('learningPaths.scenarioSuggestedPurpose' as never)}</span> {t(selectedScenario.descriptionKey as never)}</p></div>}</fieldset><div className="grid gap-5 md:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('learningPaths.name' as never)}<Input name="program-name" autoComplete="off" value={title} onChange={(event) => setTitle(event.target.value)} placeholder={selectedScenario ? t(selectedScenario.titlePlaceholderKey as never) : t('learningPaths.namePlaceholder' as never)} disabled={disabled} /></label><label className="space-y-2 text-sm font-medium">{t('learningPaths.purpose' as never)}<Input name="program-purpose" autoComplete="off" value={description} onChange={(event) => setDescription(event.target.value)} placeholder={selectedScenario ? t(selectedScenario.descriptionPlaceholderKey as never) : t('learningPaths.descriptionPlaceholder' as never)} disabled={disabled} /></label></div><fieldset disabled={disabled}><legend className="mb-2 text-sm font-medium">{t('learningPaths.sequencingMode' as never)}</legend><div className="grid gap-3 sm:grid-cols-2"><label className={`cursor-pointer rounded-md border p-4 ${sequencingMode === 'linear' ? 'border-primary bg-primary/5' : 'border-border'}`}><input className="sr-only" type="radio" name="sequencing-mode" checked={sequencingMode === 'linear'} onChange={() => setSequencingMode('linear')} /><span className="font-medium">{t('learningPaths.sequential' as never)}</span><span className="mt-1 block text-sm text-muted-foreground">{t('learningPaths.sequentialHint' as never)}</span></label><label className={`cursor-pointer rounded-md border p-4 ${sequencingMode === 'open' ? 'border-primary bg-primary/5' : 'border-border'}`}><input className="sr-only" type="radio" name="sequencing-mode" checked={sequencingMode === 'open'} onChange={() => setSequencingMode('open')} /><span className="font-medium">{t('learningPaths.freeOrder' as never)}</span><span className="mt-1 block text-sm text-muted-foreground">{t('learningPaths.freeOrderHint' as never)}</span></label></div></fieldset>{disabled && <p className="text-sm text-muted-foreground">{t('learningPaths.publishedImmutable' as never)}</p>}</div>;
}

function BasicSettings({ responsibleUserId, setResponsibleUserId, defaultDueDays, setDefaultDueDays, certificateMode, setCertificateMode, certificateValidityMonths, setCertificateValidityMonths, recurrenceMode, setRecurrenceMode, recurrenceCadenceDays, setRecurrenceCadenceDays, recurrenceDueDays, setRecurrenceDueDays, methodologists, disabled, t }: { responsibleUserId: string; setResponsibleUserId: (value: string) => void; defaultDueDays: string; setDefaultDueDays: (value: string) => void; certificateMode: CertificateMode; setCertificateMode: (value: CertificateMode) => void; certificateValidityMonths: string; setCertificateValidityMonths: (value: string) => void; recurrenceMode: RecurrenceMode; setRecurrenceMode: (value: RecurrenceMode) => void; recurrenceCadenceDays: string; setRecurrenceCadenceDays: (value: string) => void; recurrenceDueDays: string; setRecurrenceDueDays: (value: string) => void; methodologists: AudienceOption[]; disabled: boolean; t: (key: never, params?: Record<string, string | number>) => string }) {
  return <div className="space-y-5 rounded-md border p-4"><div className="grid gap-5 md:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('learningPaths.responsibleMethodologist' as never)}<select aria-label={t('learningPaths.responsibleMethodologist' as never)} className="flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm" value={responsibleUserId} onChange={(event) => setResponsibleUserId(event.target.value)} disabled={disabled}><option value="">{t('learningPaths.responsibleMethodologistEmpty' as never)}</option>{methodologists.map((user) => <option key={user.id} value={user.id}>{optionLabel(user)}</option>)}</select><span className="block text-xs font-normal text-muted-foreground">{t('learningPaths.responsibleMethodologistHint' as never)}</span></label><label className="space-y-2 text-sm font-medium">{t('learningPaths.defaultDueDays' as never)}<Input type="number" min={1} max={3650} step={1} value={defaultDueDays} onChange={(event) => setDefaultDueDays(event.target.value)} placeholder={t('learningPaths.defaultDueDaysPlaceholder' as never)} disabled={disabled} /><span className="block text-xs font-normal text-muted-foreground">{t('learningPaths.defaultDueDaysHint' as never)}</span></label></div><div className="grid gap-5 border-t pt-5 md:grid-cols-2"><div className="space-y-3"><label className="space-y-2 text-sm font-medium">{t('learningPaths.certificatePolicy' as never)}<select aria-label={t('learningPaths.certificatePolicy' as never)} className="flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm" value={certificateMode} onChange={(event) => setCertificateMode(event.target.value as CertificateMode)} disabled={disabled}><option value="none">{t('learningPaths.certificateOff' as never)}</option><option value="final_course">{t('learningPaths.certificateAfterProgram' as never)}</option></select><span className="block text-xs font-normal text-muted-foreground">{t('learningPaths.certificatePolicyHint' as never)}</span></label>{certificateMode === 'final_course' && <label className="space-y-2 text-sm font-medium">{t('learningPaths.certificateValidity' as never)}<Input type="number" min={1} max={120} step={1} value={certificateValidityMonths} onChange={(event) => setCertificateValidityMonths(event.target.value)} placeholder={t('learningPaths.certificateValidityPlaceholder' as never)} disabled={disabled} /><span className="block text-xs font-normal text-muted-foreground">{t('learningPaths.certificateValidityHint' as never)}</span></label>}</div><div className="space-y-3"><label className="space-y-2 text-sm font-medium">{t('learningPaths.knowledgeRefresh' as never)}<select aria-label={t('learningPaths.knowledgeRefresh' as never)} className="flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm" value={recurrenceMode} onChange={(event) => setRecurrenceMode(event.target.value as RecurrenceMode)} disabled={disabled}><option value="none">{t('learningPaths.knowledgeRefreshOff' as never)}</option><option value="fixed_interval_after_completion">{t('learningPaths.knowledgeRefreshPeriodic' as never)}</option></select><span className="block text-xs font-normal text-muted-foreground">{t('learningPaths.knowledgeRefreshHint' as never)}</span></label>{recurrenceMode === 'fixed_interval_after_completion' && <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-2 text-sm font-medium">{t('learningPaths.refreshEveryDays' as never)}<Input type="number" min={1} max={3650} step={1} value={recurrenceCadenceDays} onChange={(event) => setRecurrenceCadenceDays(event.target.value)} placeholder={t('learningPaths.refreshEveryDaysPlaceholder' as never)} disabled={disabled} /></label><label className="space-y-2 text-sm font-medium">{t('learningPaths.refreshDueDays' as never)}<Input type="number" min={1} max={3650} step={1} value={recurrenceDueDays} onChange={(event) => setRecurrenceDueDays(event.target.value)} placeholder={t('learningPaths.refreshDueDaysPlaceholder' as never)} disabled={disabled} /></label></div>}</div></div></div>;
}

function ContentStage({ courses, steps, search, setSearch, onToggle, onRemove, onMove, onRequired, disabled, t, tp }: { courses: Course[]; steps: CourseStep[]; search: string; setSearch: (value: string) => void; onToggle: (course: Course) => void; onRemove: (id: string) => void; onMove: (index: number, direction: -1 | 1) => void; onRequired: (id: string, required: boolean) => void; disabled: boolean; t: (key: never, params?: Record<string, string | number>) => string; tp: (key: never, count: number, params?: Record<string, string | number>) => string }) {
  const selectedIds = new Set(steps.map((step) => step.course_id));
  return <div className="space-y-5"><div><h3 className="text-lg font-semibold">{t('learningPaths.stage.content' as never)}</h3><p className="mt-1 text-sm text-muted-foreground">{t('learningPaths.contentHint' as never)}</p></div><div className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]"><div className="min-w-0 rounded-md border p-4"><div className="mb-3 flex items-center justify-between gap-3"><h4 className="font-medium">{t('learningPaths.availableCourses' as never)}</h4><span className="text-xs text-muted-foreground">{tp('common.counts.course' as never, courses.length)}</span></div><div className="relative mb-3"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" /><Input className="pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('learningPaths.searchCourses' as never)} aria-label={t('learningPaths.searchCourses' as never)} /></div><div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">{courses.map((course) => <div key={course.id} className="flex min-w-0 items-center justify-between gap-3 rounded-md border p-3"><span className="min-w-0 truncate text-sm" title={course.title}>{course.title}</span><Button type="button" size="sm" variant={selectedIds.has(course.id) ? 'secondary' : 'outline'} onClick={() => onToggle(course)} disabled={disabled} className="shrink-0 gap-1">{selectedIds.has(course.id) ? <Check className="h-4 w-4" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />} {selectedIds.has(course.id) ? t('learningPaths.added' as never) : t('learningPaths.add' as never)}</Button></div>)}{!courses.length && <p className="py-6 text-sm text-muted-foreground">{t('learningPaths.noCourses' as never)}</p>}</div></div><div className="min-w-0 rounded-md border p-4"><div className="mb-3 flex items-center justify-between gap-3"><h4 className="font-medium">{t('learningPaths.sequence' as never)}</h4><span className="text-xs text-muted-foreground">{tp('common.counts.course' as never, steps.length)}</span></div>{steps.length ? <ol className="space-y-2">{steps.map((step, index) => <li key={step.course_id} className="flex min-w-0 items-center gap-3 rounded-md border p-3"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{index + 1}</span><div className="min-w-0 flex-1"><div className="truncate font-medium" title={step.title}>{step.title}</div><label className="mt-1 inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={step.required} onChange={(event) => onRequired(step.course_id, event.target.checked)} disabled={disabled} />{t('learningPaths.required' as never)}</label></div><div className="flex shrink-0 items-center gap-1"><Button type="button" variant="ghost" size="icon" onClick={() => onMove(index, -1)} disabled={disabled || index === 0} title={t('learningPaths.moveUp' as never)} aria-label={t('learningPaths.moveUp' as never)}><ArrowUp className="h-4 w-4" aria-hidden="true" /></Button><Button type="button" variant="ghost" size="icon" onClick={() => onMove(index, 1)} disabled={disabled || index === steps.length - 1} title={t('learningPaths.moveDown' as never)} aria-label={t('learningPaths.moveDown' as never)}><ArrowDown className="h-4 w-4" aria-hidden="true" /></Button><Button type="button" variant="ghost" size="icon" onClick={() => onRemove(step.course_id)} disabled={disabled} title={t('learningPaths.remove' as never)} aria-label={t('learningPaths.remove' as never)}><X className="h-4 w-4" aria-hidden="true" /></Button></div></li>)}</ol> : <div className="flex min-h-[180px] items-center justify-center rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">{t('learningPaths.sequenceEmpty' as never)}</div>}</div></div></div>;
}

function AudienceStage({ selected, audienceTab, setAudienceTab, options, selectedIds, search, setSearch, onToggle, startsAt, dueAt, setStartsAt, setDueAt, assignments, onCancel, onAssign, saving, totalSelected, t }: { selected: PathDetail | null; audienceTab: AudienceTab; setAudienceTab: (value: AudienceTab) => void; options: AudienceOption[]; selectedIds: string[]; search: string; setSearch: (value: string) => void; onToggle: (id: string) => void; startsAt: string; dueAt: string; setStartsAt: (value: string) => void; setDueAt: (value: string) => void; assignments: Assignment[]; onCancel: (id: string) => void; onAssign: () => void; saving: boolean; totalSelected: number; t: (key: never, params?: Record<string, string | number>) => string }) {
  const published = selected?.status === 'published';
  const canSelectAudience = !selected || selected.status !== 'archived';

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-lg font-semibold">{t('learningPaths.stage.audience' as never)}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('learningPaths.audienceBuilderHint' as never)}</p>
      </div>
      {!published && (
        <div className="flex gap-3 rounded-md border border-primary/25 bg-primary/5 p-4 text-sm text-foreground">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span>{t('learningPaths.assignmentAfterPublishHint' as never)}</span>
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0">
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4" role="tablist">
            {AUDIENCE_TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={audienceTab === tab}
                onClick={() => {
                  setAudienceTab(tab);
                  setSearch('');
                }}
                className={`rounded-md border px-3 py-2 text-sm ${
                  audienceTab === tab
                    ? 'border-primary bg-primary/5 text-primary'
                    : 'border-border text-muted-foreground'
                }`}
              >
                {t(`learningPaths.audience.${tab}` as never)}
              </button>
            ))}
          </div>
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <Input
              className="pl-9"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('learningPaths.searchAudience' as never)}
              aria-label={t('learningPaths.searchAudience' as never)}
              disabled={!canSelectAudience}
            />
          </div>
          <div className="max-h-[320px] space-y-2 overflow-y-auto pr-1">
            {options.map((option) => (
              <label
                key={option.id}
                className={`flex min-w-0 items-center gap-3 rounded-md border p-3 ${
                  canSelectAudience ? 'cursor-pointer hover:bg-muted/40' : 'cursor-not-allowed opacity-60'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedIds.includes(option.id)}
                  onChange={() => onToggle(option.id)}
                  disabled={!canSelectAudience}
                />
                <span className="min-w-0 truncate text-sm" title={optionLabel(option)}>
                  {optionLabel(option)}
                </span>
              </label>
            ))}
            {!options.length && (
              <p className="py-6 text-sm text-muted-foreground">{t('learningPaths.noAudience' as never)}</p>
            )}
          </div>
        </div>
        <aside className="rounded-md border p-4">
          <h4 className="font-medium">{t('learningPaths.assignmentSettings' as never)}</h4>
          <div className="mt-4 space-y-3">
            <label className="block space-y-1 text-sm">
              {t('learningPaths.startsAt' as never)}
              <DateInput
                value={startsAt}
                onChange={setStartsAt}
                disabled={!canSelectAudience}
              />
            </label>
            <label className="block space-y-1 text-sm">
              {t('learningPaths.dueAt' as never)}
              <DateInput
                value={dueAt}
                onChange={setDueAt}
                disabled={!canSelectAudience}
              />
            </label>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            {t('learningPaths.selectedAudience' as never, { count: totalSelected })}
          </p>
          {published ? (
            <Button
              className="mt-4 w-full gap-2"
              onClick={onAssign}
              disabled={saving || totalSelected === 0}
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              {t('learningPaths.assign' as never)}
            </Button>
          ) : (
            <p className="mt-4 rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
              {t('learningPaths.assignmentQueuedHint' as never)}
            </p>
          )}
        </aside>
      </div>
      {published && (
        <div className="border-t pt-5">
          <h4 className="mb-3 font-medium">{t('learningPaths.currentAssignments' as never)}</h4>
          {assignments.length ? (
            <div className="space-y-2">
              {assignments.map((assignment) => (
                <div
                  key={assignment.id}
                  className="flex flex-col gap-3 rounded-md border p-3 text-sm sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">
                      {assignment.user_name || assignment.user_email || assignment.user_id || assignment.id}
                    </div>
                    {assignment.user_name && assignment.user_email && (
                      <div className="truncate text-xs text-muted-foreground">{assignment.user_email}</div>
                    )}
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant={assignment.status === 'active' ? 'default' : 'secondary'}>
                        {t(`learningPaths.assignmentStatus.${assignment.status || 'active'}` as never)}
                      </Badge>
                      {assignment.due_at && (
                        <span>{t('learningPaths.until' as never)} {dateLabel(assignment.due_at)}</span>
                      )}
                    </div>
                  </div>
                  {assignment.status === 'active' && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => onCancel(assignment.id)}
                      disabled={saving}
                    >
                      {t('learningPaths.cancelAssignment' as never)}
                    </Button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t('learningPaths.noAssignments' as never)}</p>
          )}
        </div>
      )}
    </div>
  );
}

function ReviewStage({ selected, title, description, sequencingMode, steps, totalSelectedAudience, canPublish, onPublish, saving, t }: { selected: PathDetail | null; title: string; description: string; sequencingMode: SequencingMode; steps: CourseStep[]; totalSelectedAudience: number; canPublish: boolean; onPublish: () => void; saving: boolean; t: (key: never, params?: Record<string, string | number>) => string }) {
  const checks = [{ label: t('learningPaths.validation.name' as never), valid: Boolean(title.trim()) }, { label: t('learningPaths.validation.courses' as never), valid: steps.length > 0 }, { label: t('learningPaths.validationRequired' as never), valid: steps.some((step) => step.required) }, { label: t('learningPaths.validation.order' as never), valid: steps.length > 0 }];
  const publishLabel = totalSelectedAudience > 0
    ? t('learningPaths.publishAndAssign' as never)
    : t('learningPaths.publish' as never);
  return <div className="space-y-6"><div><h3 className="text-lg font-semibold">{t('learningPaths.stage.review' as never)}</h3><p className="mt-1 text-sm text-muted-foreground">{t('learningPaths.reviewHint' as never)}</p></div><div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]"><div className="space-y-4"><div><p className="text-sm text-muted-foreground">{t('learningPaths.name' as never)}</p><p className="font-medium">{title || t('learningPaths.notSet' as never)}</p></div><div><p className="text-sm text-muted-foreground">{t('learningPaths.purpose' as never)}</p><p>{description || t('learningPaths.notSet' as never)}</p></div><div><p className="text-sm text-muted-foreground">{t('learningPaths.sequencingMode' as never)}</p><p>{t(`learningPaths.${sequencingMode === 'linear' ? 'sequential' : 'freeOrder'}` as never)}</p></div><div><p className="text-sm text-muted-foreground">{t('learningPaths.sequence' as never)}</p><ol className="mt-2 space-y-2">{steps.map((step, index) => <li key={step.course_id} className="flex items-center gap-3 rounded-md border p-3"><span className="font-semibold text-primary">{index + 1}</span><span className="min-w-0 truncate">{step.title}</span><span className="ml-auto text-xs text-muted-foreground">{step.required ? t('learningPaths.required' as never) : t('learningPaths.optional' as never)}</span></li>)}</ol></div></div><aside className="rounded-md border p-4"><h4 className="font-medium">{t('learningPaths.readyToPublish' as never)}</h4><ul className="mt-3 space-y-3 text-sm">{checks.map((check) => <li key={check.label} className="flex items-center gap-2">{check.valid ? <CheckCircle2 className="h-4 w-4 text-green-600" aria-hidden="true" /> : <Circle className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}<span>{check.label}</span></li>)}<li className="flex items-center gap-2 text-muted-foreground"><Users className="h-4 w-4" aria-hidden="true" />{t('learningPaths.selectedAudience' as never, { count: totalSelectedAudience })}</li></ul>{selected?.status === 'published' ? <p className="mt-5 text-sm text-muted-foreground">{t('learningPaths.publishedImmutable' as never)}</p> : <Button className="mt-5 w-full gap-2" onClick={onPublish} disabled={!canPublish || saving}><Send className="h-4 w-4" aria-hidden="true" />{publishLabel}</Button>}</aside></div></div>;
}

function LearnerView({ programs, t, tp }: { programs: LearnerProgram[]; t: (key: never, params?: Record<string, string | number>) => string; tp: (key: never, count: number, params?: Record<string, string | number>) => string }) {
  return <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6"><header><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t('learningPaths.title' as never)}</h1><p className="mt-1 text-muted-foreground">{t('learningPaths.learnerDescription' as never)}</p></header>{!programs.length ? <div className="rounded-lg border border-dashed p-10 text-center"><BookOpen className="mx-auto mb-3 h-8 w-8 text-muted-foreground" aria-hidden="true" /><p className="text-muted-foreground">{t('learningPaths.learnerEmpty' as never)}</p></div> : <div className="space-y-5">{programs.map((program) => { const steps = program.steps || program.courses || []; const requiredCompleted = program.completed_required_courses ?? 0; const requiredTotal = program.total_required_courses ?? steps.filter((step) => step.required).length; const progress = program.progress_percent ?? (requiredTotal ? Math.round((requiredCompleted / requiredTotal) * 100) : 0); return <article key={program.id} className="rounded-lg border p-4 sm:p-6"><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div className="min-w-0"><div className="flex items-center gap-2"><BookOpen className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" /><h2 className="truncate text-lg font-semibold">{program.title}</h2></div>{program.description && <p className="mt-1 text-sm text-muted-foreground">{program.description}</p>}</div><span className="shrink-0 text-sm font-medium text-primary">{progress}%</span></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} /></div><p className="mt-2 text-xs text-muted-foreground">{requiredCompleted} из {tp('common.counts.courseTotal' as never, requiredTotal)} · {t('learningPaths.required' as never)}</p><ol className="mt-5 space-y-2">{steps.map((step, index) => { const available = step.state === 'available' || step.state === 'completed'; const completed = step.state === 'completed'; return <li key={step.course_id} className={`flex min-w-0 items-center gap-3 rounded-md border p-3 ${step.state === 'locked' ? 'bg-muted/30' : ''}`}><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold">{completed ? <CheckCircle2 className="h-4 w-4 text-green-600" aria-label={t('learningPaths.completed' as never)} /> : step.state === 'locked' ? <Lock className="h-4 w-4 text-muted-foreground" aria-label={t('learningPaths.locked' as never)} /> : <span>{index + 1}</span>}</span><div className="min-w-0 flex-1"><div className="truncate font-medium" title={step.title}>{step.title}</div><p className="text-xs text-muted-foreground">{step.required ? t('learningPaths.required' as never) : t('learningPaths.optional' as never)} · {t(`learningPaths.stepState.${step.state}` as never)}</p></div>{available ? <Link href={`/courses/${step.course_id}`}><Button size="sm" variant={completed ? 'outline' : 'default'}>{completed ? t('learningPaths.reviewCourse' as never) : t('learningPaths.startCourse' as never)}</Button></Link> : <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground"><Clock3 className="h-4 w-4" aria-hidden="true" />{t('learningPaths.lockedHint' as never)}</span>}</li>; })}</ol></article>; })}</div>}</div>;
}
