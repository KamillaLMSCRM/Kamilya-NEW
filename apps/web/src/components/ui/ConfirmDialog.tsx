'use client';

import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { AlertTriangle } from 'lucide-react';
import { Modal } from '@/components/ui/modal';
import { useT } from '@/i18n/useT';

export type ConfirmVariant = 'danger' | 'warning' | 'info';

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  title: string;
  /** Optional body message — if absent, only the title is shown. */
  message?: string;
  variant?: ConfirmVariant;
  /** Translation key for confirm button — defaults to `dialogs.delete`. */
  confirmKey?: string;
  /** Translation key for cancel button — defaults to `dialogs.cancel`. */
  cancelKey?: string;
  /** If provided, overrides the i18n key for the confirm button. */
  confirmLabel?: string;
  /** If provided, overrides the i18n key for the cancel button. */
  cancelLabel?: string;
}

const VARIANT_ICON: Record<ConfirmVariant, string> = {
  danger: 'text-destructive',
  warning: 'text-warning',
  info: 'text-primary',
};

const VARIANT_BUTTON: Record<ConfirmVariant, string> = {
  danger: 'bg-destructive hover:bg-destructive/90 text-destructive-foreground',
  warning: 'bg-warning hover:bg-warning/90 text-warning-foreground',
  info: 'bg-primary hover:bg-primary/90 text-primary-foreground',
};

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  variant = 'danger',
  confirmKey,
  cancelKey,
  confirmLabel,
  cancelLabel,
}: ConfirmDialogProps) {
  const { t } = useT();
  const [confirming, setConfirming] = useState(false);

  const handleConfirm = async () => {
    setConfirming(true);
    try {
      await onConfirm();
    } finally {
      setConfirming(false);
    }
  };

  const confirmText = confirmLabel ?? t((confirmKey ?? 'dialogs.delete') as any);
  const cancelText = cancelLabel ?? t((cancelKey ?? 'dialogs.cancel') as any);

  return (
    <Modal open={open} onClose={onClose} title={title}>
      {message && (
        <div className="flex items-start gap-3 mb-5">
          <AlertTriangle
            className={cn('w-5 h-5 shrink-0 mt-0.5', VARIANT_ICON[variant])}
            aria-hidden="true"
          />
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      )}
      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onClose}
          disabled={confirming}
          className="px-4 py-2 text-sm font-medium border border-border rounded-lg text-foreground hover:bg-muted transition-colors disabled:opacity-50"
        >
          {cancelText}
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={confirming}
          className={cn(
            'px-4 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-50 inline-flex items-center gap-2',
            VARIANT_BUTTON[variant]
          )}
        >
          {confirming && (
            <div
              className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
              aria-hidden="true"
            />
          )}
          {confirming ? t('common.saving' as any) : confirmText}
        </button>
      </div>
    </Modal>
  );
}

/**
 * Hook for imperative confirm dialogs.
 *
 * Usage:
 *   const confirm = useConfirm();
 *   <button onClick={async () => {
 *     const ok = await confirm({
 *       title: 'Удалить курс?',
 *       variant: 'danger',
 *     });
 *     if (ok) deleteCourse();
 *   }} />
 */
interface UseConfirmOptions {
  title: string;
  message?: string;
  variant?: ConfirmVariant;
  confirmLabel?: string;
  cancelLabel?: string;
}

export function useConfirm() {
  const [state, setState] = useState<{
    open: boolean;
    opts: UseConfirmOptions | null;
    resolve: ((ok: boolean) => void) | null;
  }>({ open: false, opts: null, resolve: null });

  const confirm = useCallback((opts: UseConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setState({ open: true, opts, resolve });
    });
  }, []);

  const handleClose = useCallback(() => {
    state.resolve?.(false);
    setState({ open: false, opts: null, resolve: null });
  }, [state.resolve]);

  const handleConfirm = useCallback(() => {
    state.resolve?.(true);
    setState({ open: false, opts: null, resolve: null });
  }, [state.resolve]);

  const dialog = state.opts ? (
    <ConfirmDialog
      open={state.open}
      onClose={handleClose}
      onConfirm={handleConfirm}
      title={state.opts.title}
      message={state.opts.message}
      variant={state.opts.variant ?? 'danger'}
      confirmLabel={state.opts.confirmLabel}
      cancelLabel={state.opts.cancelLabel}
    />
  ) : null;

  return { confirm, dialog };
}
