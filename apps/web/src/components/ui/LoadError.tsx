'use client';

import { RefreshCw } from 'lucide-react';
import { Button } from './button';

interface LoadErrorProps {
  title: string;
  message?: string | null;
  retryLabel: string;
  onRetry: () => void;
}

export function LoadError({ title, message, retryLabel, onRetry }: LoadErrorProps) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-center"
    >
      <p className="font-medium text-foreground">{title}</p>
      {message && <p className="mt-1 text-sm text-muted-foreground">{message}</p>}
      <Button type="button" variant="outline" className="mt-4 min-h-11" onClick={onRetry}>
        <RefreshCw className="h-4 w-4" aria-hidden="true" />
        {retryLabel}
      </Button>
    </div>
  );
}
