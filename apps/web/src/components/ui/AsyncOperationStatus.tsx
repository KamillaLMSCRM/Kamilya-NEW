'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  RotateCw,
  Upload,
  XCircle,
} from 'lucide-react';

export type AsyncOperationState =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'stalled';

export interface AsyncOperation {
  status: string;
  progress?: number | null;
  stage?: string | null;
  message?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  errors?: Array<{ code: string; message?: string | null } | string> | null;
}

export const resolveAsyncOperationState = (
  operation: AsyncOperation,
  now = Date.now(),
  stalledAfterMs = 120_000,
): AsyncOperationState => {
  if (operation.status === 'completed') return 'completed';
  if (operation.status === 'failed') return 'failed';
  if (operation.status === 'cancelled') return 'cancelled';

  const lastUpdate = operation.updated_at || operation.created_at;
  if (
    (operation.status === 'pending' || operation.status === 'running')
    && lastUpdate
    && now - new Date(lastUpdate).getTime() >= stalledAfterMs
  ) {
    return 'stalled';
  }
  return operation.status === 'pending' ? 'queued' : 'running';
};

interface AsyncOperationStatusProps {
  operation: AsyncOperation;
  title: string;
  stageLabel?: string;
  labels: Record<AsyncOperationState, string>;
  retryLabel?: string;
  cancelLabel?: string;
  onRetry?: () => void;
  onCancel?: () => void;
  stalledAfterMs?: number;
  retryIcon?: 'retry' | 'upload';
}

const stateStyles: Record<AsyncOperationState, string> = {
  queued: 'border-border bg-muted/30 text-foreground',
  running: 'border-primary/30 bg-primary/5 text-foreground',
  completed: 'border-success/30 bg-success/10 text-success',
  failed: 'border-destructive/30 bg-destructive/10 text-destructive',
  cancelled: 'border-border bg-muted text-muted-foreground',
  stalled: 'border-warning/40 bg-warning/10 text-warning',
};

export function AsyncOperationStatus({
  operation,
  title,
  stageLabel,
  labels,
  retryLabel,
  cancelLabel,
  onRetry,
  onCancel,
  stalledAfterMs = 120_000,
  retryIcon = 'retry',
}: AsyncOperationStatusProps) {
  const [now, setNow] = useState(() => Date.now());
  const state = useMemo(
    () => resolveAsyncOperationState(operation, now, stalledAfterMs),
    [operation, now, stalledAfterMs],
  );
  const active = state === 'queued' || state === 'running' || state === 'stalled';
  const progress = Math.max(0, Math.min(100, operation.progress ?? 0));

  useEffect(() => {
    setNow(Date.now());
  }, [operation.status, operation.updated_at]);

  useEffect(() => {
    if (!active || !operation.updated_at) return;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [active, operation.updated_at]);

  const Icon = state === 'completed'
    ? CheckCircle2
    : state === 'failed' || state === 'cancelled'
      ? XCircle
      : state === 'stalled'
        ? AlertTriangle
        : state === 'queued'
          ? Clock3
          : Loader2;
  const RetryIcon = retryIcon === 'upload' ? Upload : RotateCw;

  return (
    <section
      className={`rounded-lg border p-4 ${stateStyles[state]}`}
      aria-live="polite"
      data-operation-state={state}
    >
      <div className="flex items-start gap-3">
        <Icon
          className={`mt-0.5 h-5 w-5 shrink-0 ${state === 'running' ? 'animate-spin' : ''}`}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">{title}</h3>
            <span className="text-xs font-medium">{labels[state]}</span>
          </div>
          {(stageLabel || operation.message) && (
            <p className="mt-1 text-xs opacity-80">
              {[stageLabel, operation.message].filter(Boolean).join(' · ')}
            </p>
          )}
          {active && operation.progress !== undefined && operation.progress !== null && (
            <div className="mt-3">
              <div className="h-2 overflow-hidden rounded-full bg-background/70">
                <div
                  className="h-full rounded-full bg-current transition-[width] duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="mt-1 text-right text-xs tabular-nums">{progress}%</p>
            </div>
          )}
          {(onRetry || onCancel) && (
            <div className="mt-3 flex flex-wrap gap-2">
              {onRetry && (state === 'failed' || state === 'cancelled' || state === 'stalled') && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="inline-flex min-h-10 items-center gap-2 rounded-md border border-current/30 px-3 py-2 text-sm font-medium hover:bg-background/60"
                >
                  <RetryIcon className="h-4 w-4" aria-hidden="true" />
                  {retryLabel}
                </button>
              )}
              {onCancel && (state === 'queued' || state === 'running' || state === 'stalled') && (
                <button
                  type="button"
                  onClick={onCancel}
                  className="inline-flex min-h-10 items-center gap-2 rounded-md border border-current/30 px-3 py-2 text-sm font-medium hover:bg-background/60"
                >
                  <XCircle className="h-4 w-4" aria-hidden="true" />
                  {cancelLabel}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
