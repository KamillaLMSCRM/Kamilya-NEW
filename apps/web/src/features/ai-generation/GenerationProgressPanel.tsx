import { AsyncOperationStatus, resolveAsyncOperationState } from '@/components/ui/AsyncOperationStatus';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';
import { CheckCircle2 } from 'lucide-react';

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
  onRetry: () => void;
  onCancel: () => void;
}

export function GenerationProgressPanel({
  job, stages, title, labels, retryLabel, checkAgainLabel, cancelLabel, cancelQueuedLabel,
  queueTitle, activeJobs, queuePosition, estimatedWait, queueEstimateHint, onRetry, onCancel,
}: GenerationProgressPanelProps) {
  const state = resolveAsyncOperationState(job);
  const currentStageIndex = stages.findIndex((stage) => stage.key === job.stage);

  return <div className="space-y-6">
    <AsyncOperationStatus
      operation={job}
      title={title}
      stageLabel={stages.find((stage) => stage.key === job.stage)?.label}
      labels={labels}
      retryLabel={state === 'stalled' ? checkAgainLabel : retryLabel}
      cancelLabel={job.status === 'pending' ? cancelQueuedLabel : cancelLabel}
      onRetry={onRetry}
      onCancel={onCancel}
    />

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
        const isActive = !isAllDone && job.stage === stage.key;
        const isDone = isAllDone || index < currentStageIndex;
        const Icon = stage.icon;
        return <div key={stage.key} className={`flex items-center gap-3 rounded-xl border p-3 transition-all ${isActive ? 'border-primary bg-primary/5 shadow-sm' : isDone ? 'border-success/40 bg-success/10' : 'border-border opacity-50'}`}>
          <div className={isDone ? 'text-success' : isActive ? stage.color : 'text-muted-foreground'}>
            {isDone ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-5 h-5" />}
          </div>
          <span className={`text-sm font-medium ${isDone ? 'text-success' : isActive ? 'text-foreground' : 'text-muted-foreground'}`}>{stage.label}</span>
          {isActive && <div className="ml-auto h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />}
        </div>;
      })}
    </div>
  </div>;
}
