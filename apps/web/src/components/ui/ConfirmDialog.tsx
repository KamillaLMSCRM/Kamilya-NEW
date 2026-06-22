'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import { X, AlertTriangle } from 'lucide-react';

interface ModalDialogProps {
  open: boolean;
  onClose?: () => void;
  onOpenChange?: (open: boolean) => void;
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export function ModalDialog({ open, onClose, onOpenChange, title, children, className }: ModalDialogProps) {
  const handleClose = () => {
    onClose?.();
    onOpenChange?.(false);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="fixed inset-0 bg-black/50"
        onClick={handleClose}
        aria-hidden="true"
      />
      <div className={cn('relative bg-background rounded-lg shadow-lg p-6 z-10 w-full max-w-lg', className)}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">{title}</h2>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning';
}

export function ConfirmDialog({ open, onClose, onConfirm, title, message, confirmText = 'OK', cancelText = 'Отмена', variant = 'danger' }: ConfirmDialogProps) {
  const [confirming, setConfirming] = useState(false);

  const handleConfirm = async () => {
    setConfirming(true);
    try {
      await onConfirm();
    } finally {
      setConfirming(false);
    }
  };

  return (
    <ModalDialog open={open} onClose={onClose} title={title} className="max-w-md">
      <div className="flex items-start gap-3 mb-4">
        <AlertTriangle className={cn(
          "w-5 h-5 shrink-0 mt-1",
          variant === 'danger' ? 'text-red-500' : 'text-amber-500'
        )} />
        <p className="text-sm text-gray-600">{message}</p>
      </div>
      <div className="flex gap-2 justify-end">
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          {cancelText}
        </button>
        <button
          onClick={handleConfirm}
          disabled={confirming}
          className={cn(
            "px-4 py-2 text-sm text-white rounded-lg transition-colors disabled:opacity-50",
            variant === 'danger' ? 'bg-red-600 hover:bg-red-700' : 'bg-amber-600 hover:bg-amber-700'
          )}
        >
          {confirming ? '...' : confirmText}
        </button>
      </div>
    </ModalDialog>
  );
}
