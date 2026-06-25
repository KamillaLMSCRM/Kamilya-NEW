'use client';

import { Toaster as SonnerToaster, toast as sonnerToast } from 'sonner';
import { CheckCircle2, AlertTriangle, Info, XCircle, X } from 'lucide-react';
import type { ReactNode } from 'react';

/**
 * Toast notifications — wrapper around `sonner` with project-specific defaults.
 *
 * Usage:
 *   import { toast } from '@/components/ui/Toast';
 *   toast.success('Сохранено');
 *   toast.error('Не удалось сохранить');
 *
 * Mount once in app/layout.tsx: <Toaster />
 */

type ToastVariant = 'success' | 'error' | 'warning' | 'info';

interface ToastOptions {
  description?: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

const ICONS: Record<ToastVariant, ReactNode> = {
  success: <CheckCircle2 className="w-5 h-5 text-success" />,
  error: <XCircle className="w-5 h-5 text-destructive" />,
  warning: <AlertTriangle className="w-5 h-5 text-warning" />,
  info: <Info className="w-5 h-5 text-primary" />,
};

class Toast {
  private base(variant: ToastVariant, message: string, opts: ToastOptions = {}) {
    return sonnerToast(message, {
      description: opts.description,
      duration: opts.duration ?? 4000,
      icon: ICONS[variant],
      action: opts.action
        ? {
            label: opts.action.label,
            onClick: opts.action.onClick,
          }
        : undefined,
    });
  }

  success(message: string, opts?: ToastOptions) {
    return this.base('success', message, opts);
  }

  error(message: string, opts?: ToastOptions) {
    return this.base('error', message, opts);
  }

  warning(message: string, opts?: ToastOptions) {
    return this.base('warning', message, opts);
  }

  info(message: string, opts?: ToastOptions) {
    return this.base('info', message, opts);
  }

  /** Promise-based toast: shows loading → success/error */
  promise<T>(promise: Promise<T>, messages: { loading: string; success: string; error: string }) {
    return sonnerToast.promise(promise, {
      loading: messages.loading,
      success: messages.success,
      error: messages.error,
    });
  }

  dismiss(id?: string | number) {
    return sonnerToast.dismiss(id);
  }
}

export const toast = new Toast();

export function Toaster() {
  return (
    <SonnerToaster
      position="top-right"
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast: 'group toast group-[.toaster]:bg-card group-[.toaster]:text-card-foreground group-[.toaster]:border-border group-[.toaster]:shadow-card-lg',
          description: 'group-[.toast]:text-muted-foreground',
          actionButton: 'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground',
          cancelButton: 'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground',
          closeButton: 'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground',
        },
      }}
      icons={{
        close: <X className="w-4 h-4" />,
      }}
    />
  );
}
