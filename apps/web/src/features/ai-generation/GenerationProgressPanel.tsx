import { AsyncOperationStatus, resolveAsyncOperationState } from '@/components/ui/AsyncOperationStatus';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';
import { CheckCircle2 } from 'lucide-react';
import Link from 'next/link';
import { workspaceCopy } from '@/features/learning-workspace/copy';
import { WorkspacePanel } from '@/features/workspace-design';

export interface GenerationStage {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
}

interface GenerationProgressPanelProps {
  job: AIGenerationJob;
  stages: GenerationStage[];
  title: string;
  labels: Parameters<typeof AsyncOperationStatus>[0]['labels'];
  retryLabel: string;
  checkAgainLabel: string;
  cancelLabel: string;
  cancelQueuedLabel: string;
  queueTitle: string;
  activeJobs: string;
  queuePosition: string;
  estimatedWait: string;
  queueEstimateHint: string;
  completedUnitsLabel: string;
  onRetry: () => void;
  onCancel: () => void;
  lang?: string;
}

export function GenerationProgressPanel({
  job, stages, title, labels, retryLabel, checkAgainLabel, cancelLabel, cancelQueuedLabel,
  queueTitle, activeJobs, queuePosition, estimatedWait, queueEstimateHint, completedUnitsLabel,
  onRetry, onCancel, lang = 'ru',
}: GenerationProgressPanelProps) {
  const m = workspaceCopy(lang);
  const state = resolveAsyncOperationState(job);
  const currentStageIndex = stages.findIndex((stage) => stage.key === job.stage);
  const hasExactUnits = (
    Number.isInteger(job.progress_current)
    && Number.isInteger(job.progress_total)
    && (job.progress_current ?? -1) >= 0
    && (job.progress_total ?? 0) > 0
    && (job.progress_current ?? 0) <= (job.progress_total ?? 0)
  );

  return <div className="grid min-w-0 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.65fr)]" data-generation-workspace>
    <div className="min-w-0 space-y-4">
    {(job.status === 'interrupted' || state === 'stalled' || state === 'failed') && (
      <section className="rounded-2xl border border-primary/20 bg-primary/5 p-5 sm:p-6" aria-label={m.generationTitle}>
        <h3 className="text-lg font-semibold text-foreground">{m.generationTitle}</h3>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground">{m.generationHint}</p>
        <p className="mt-2 text-xs leading-6 text-foreground">{m.resumeHint}</p>
        {job.course_id && <div className="mt-4 rounded-xl border border-border bg-card p-4">
          <p className="text-sm text-foreground">{m.savedDraft}</p>
          <Link href={`/courses/${encodeURIComponent(job.course_id)}/edit`} className="mt-3 inline-flex min-h-10 items-center rounded-lg border border-border px-3 text-sm font-medium text-primary hover:bg-muted">{m.openDraft}</Link>
        </div>}
      </section>
    )}
    <AsyncOperationStatus
      operation={job}
      title={title}
      stageLabel={stages.find((stage) => stage.key === job.stage)?.label}
      progressScopeLabel={stages.find((stage) => stage.key === job.stage)?.label}
      labels={labels}
      retryLabel={state === 'stalled' ? checkAgainLabel : retryLabel}
      cancelLabel={job.status === 'pending' ? cancelQueuedLabel : cancelLabel}
      onRetry={onRetry}
      onCancel={onCancel}
    />

    {job.status === 'completed' && hasExactUnits && (
      <p className="text-xs tabular-nums text-muted-foreground" role="status">
        {completedUnitsLabel}: {job.progress_current} / {job.progress_total}
      </p>
    )}

    {state === 'queued' && <div className="rounded-lg border border-border bg-muted/20 p-4" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{queueTitle}</h3>
        {(job.tenant_active_limit ?? 0) > 0 && <span className="text-xs text-muted-foreground">{activeJobs}</span>}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        {job.queue_position != null && <span>{queuePosition}</span>}
        {job.estimated_wait_seconds != null && <span>{estimatedWait}</span>}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{queueEstimateHint}</p>
    </div>}

    </div>
    <WorkspacePanel description={m.stepsHint} bodyClassName="space-y-2">
      {stages.map((stage, index) => {
        const isAllDone = job.stage === 'completed' || job.status === 'completed';
        const isActive = !isAllDone && job.stage === stage.key;
        const isDone = isAllDone || index < currentStageIndex;
        const Icon = stage.icon;
        return <div key={stage.key} aria-current={isActive ? 'step' : undefined} className={`flex items-center gap-3 rounded-xl border p-3 transition-all ${isActive ? 'border-primary bg-primary/5 shadow-sm' : isDone ? 'border-success/40 bg-success/5' : 'border-transparent bg-muted/30'}`}>
          <div className={isDone ? 'text-success' : isActive ? stage.color : 'text-muted-foreground'}>
            {isDone ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-5 h-5" />}
          </div>
          <span className={`text-sm font-medium ${isDone ? 'text-success' : isActive ? 'text-foreground' : 'text-muted-foreground'}`}>{stage.label}</span>
          {isActive && <div className="ml-auto h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />}
        </div>;
      })}
    </WorkspacePanel>
  </div>;
}
