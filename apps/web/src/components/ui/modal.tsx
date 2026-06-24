'use client';

import { useEffect, useId, useRef, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { X } from 'lucide-react';
import { useT } from '@/i18n/useT';

interface ModalProps {
  open: boolean;
  onClose?: () => void;
  onOpenChange?: (open: boolean) => void;
  title?: string;
  /** Optional description for aria-describedby. */
  description?: string;
  children: React.ReactNode;
  className?: string;
  /** Allow closing with ESC and backdrop click. Default: true. */
  dismissable?: boolean;
  /** Element that triggered the modal — focus restores here on close. */
  initialFocusRef?: React.RefObject<HTMLElement>;
}

// Selector for elements that can receive focus.
const FOCUSABLE = [
  'a[href]',
  'area[href]',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'button:not([disabled])',
  'iframe',
  'object',
  'embed',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',');

function getFocusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute('aria-hidden') && el.offsetParent !== null
  );
}

export function Modal({
  open,
  onClose,
  onOpenChange,
  title,
  description,
  children,
  className,
  dismissable = true,
  initialFocusRef,
}: ModalProps) {
  const { t } = useT();
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const handleClose = useCallback(() => {
    onClose?.();
    onOpenChange?.(false);
  }, [onClose, onOpenChange]);

  // Body scroll lock + focus capture/restore
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const previousActive = document.activeElement as HTMLElement | null;
    document.body.style.overflow = 'hidden';
    restoreFocusRef.current = previousActive;

    // Move focus to the modal
    const focusTarget = initialFocusRef?.current ?? panelRef.current;
    // Wait for the DOM to be visible
    const t = window.setTimeout(() => {
      focusTarget?.focus();
    }, 0);

    return () => {
      window.clearTimeout(t);
      document.body.style.overflow = previousOverflow;
      // Restore focus to the element that opened the modal
      restoreFocusRef.current?.focus?.();
    };
  }, [open, initialFocusRef]);

  // ESC to close + focus trap on Tab
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (!panelRef.current) return;
      if (e.key === 'Escape' && dismissable) {
        e.stopPropagation();
        handleClose();
        return;
      }
      if (e.key === 'Tab') {
        const focusables = getFocusable(panelRef.current);
        if (focusables.length === 0) {
          // No focusables — keep focus on the panel itself
          e.preventDefault();
          panelRef.current.focus();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, dismissable, handleClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="fixed inset-0 bg-black/50"
        onClick={dismissable ? handleClose : undefined}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          'relative bg-background rounded-lg shadow-lg p-6 z-10 w-full max-w-lg outline-none',
          className
        )}
      >
        {title && (
          <div className="flex items-center justify-between mb-4">
            <h2 id={titleId} className="text-xl font-semibold">
              {title}
            </h2>
            {dismissable && (
              <button
                type="button"
                onClick={handleClose}
                className="text-muted-foreground hover:text-foreground p-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={t('a11y.closeDialog')}
              >
                <X className="w-5 h-5" aria-hidden="true" />
              </button>
            )}
          </div>
        )}
        {description && (
          <p id={descriptionId} className="text-sm text-muted-foreground mb-3">
            {description}
          </p>
        )}
        {children}
      </div>
    </div>
  );
}
