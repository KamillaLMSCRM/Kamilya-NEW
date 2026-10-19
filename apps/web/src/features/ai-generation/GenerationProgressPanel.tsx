import { AsyncOperationStatus, resolveAsyncOperationState } from '@/components/ui/AsyncOperationStatus';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';

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
  terminalResult?: {
    stageKey: string;
    title: string;
    detail: string;
    summaryItems: string[];
  };
  onRetry: () => void;
  onCancel: () => void;
}

export function GenerationProgressPanel({
  job, stages, title, labels, retryLabel, checkAgainLabel, cancelLabel, cancelQueuedLabel,
  queueTitle, activeJobs, queuePosition, estimatedWait, queueEstimateHint, completedUnitsLabel,
  terminalResult,
  onRetry, onCancel,
}: GenerationProgressPanelProps) {
  const state = resolveAsyncOperationState(job);
  const displayedStageKey = terminalResult?.stageKey ?? job.stage;
  const currentStageIndex = stages.findIndex((stage) => stage.key === displayedStageKey);
  const hasExactUnits = (
    Number.isInteger(job.progress_current)
    && Number.isInteger(job.progress_total)
    && (job.progress_current ?? -1) >= 0
    && (job.progress_total ?? 0) > 0
    && (job.progress_current ?? 0) <= (job.progress_total ?? 0)
  );

  return <div className="space-y-6">
    <AsyncOperationStatus
      operation={terminalResult ? { ...job, message: null } : job}
      title={title}
      stageLabel={stages.find((stage) => stage.key === displayedStageKey)?.label}
      progressScopeLabel={stages.find((stage) => stage.key === displayedStageKey)?.label}
      labels={labels}
      retryLabel={state === 'stalled' ? checkAgainLabel : retryLabel}
      cancelLabel={job.status === 'pending' ? cancelQueuedLabel : cancelLabel}
      onRetry={onRetry}
      onCancel={onCancel}
    />

    {terminalResult && (
      <section
        className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-foreground"
        data-testid="partial-generation-result"
        aria-live="polite"
      >
        <h3 className="text-sm font-semibold">{terminalResult.title}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{terminalResult.detail}</p>
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
          {hasExactUnits && (
            <div className="rounded-lg border border-warning/30 bg-background/70 px-3 py-2">
              <p className="text-muted-foreground">
                {completedUnitsLabel}: <span className="font-semibold tabular-nums text-foreground">{job.progress_current} / {job.progress_total}</span>
              </p>
            </div>
          )}
          {terminalResult.summaryItems.map((item) => (
            <div key={item} className="rounded-lg border border-warning/30 bg-background/70 px-3 py-2 font-semibold tabular-nums text-foreground">
              {item}
            </div>
          ))}
        </div>
      </section>
    )}

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

    <div className="space-y-2">
      {stages.map((stage, index) => {
        const isAllDone = job.stage === 'completed' || job.status === 'completed';
        const isTerminalStage = Boolean(terminalResult && terminalResult.stageKey === stage.key);
        const isActive = !terminalResult && !isAllDone && job.stage === stage.key;
        const isDone = isAllDone || index < currentStageIndex;
        const stageState = isDone ? 'done' : isTerminalStage ? 'terminal' : isActive ? 'active' : 'pending';
        const Icon = stage.icon;
        return <div key={stage.key} data-generation-stage={stage.key} data-stage-state={stageState} className={`flex items-center gap-3 rounded-xl border p-3 transition-all ${isActive ? 'border-primary bg-primary/5 shadow-sm' : isTerminalStage ? 'border-warning/40 bg-warning/10' : isDone ? 'border-success/40 bg-success/10' : 'border-border opacity-50'}`}>
          <div className={isDone ? 'text-success' : isTerminalStage ? 'text-warning' : isActive ? stage.color : 'text-muted-foreground'}>
            {isDone ? <CheckCircle2 className="w-5 h-5" /> : isTerminalStage ? <AlertTriangle className="w-5 h-5" /> : <Icon className="w-5 h-5" />}
          </div>
          <span className={`text-sm font-medium ${isDone ? 'text-success' : isTerminalStage ? 'text-warning' : isActive ? 'text-foreground' : 'text-muted-foreground'}`}>{stage.label}</span>
          {isActive && <div className="ml-auto h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />}
        </div>;
      })}
    </div>
  </div>;
}
