'use client';

import { useEffect, useRef } from 'react';

export type ReuseReason =
  | 'different_audience'
  | 'different_language'
  | 'different_depth'
  | 'updated_revision'
  | 'recurring_training'
  | 'other';

export interface ReusedSourceCourse {
  id: string;
  title: string;
  status: string;
}

const REUSE_REASONS: Array<{ value: ReuseReason; label: string }> = [
  { value: 'different_audience', label: 'Другая аудитория' },
  { value: 'different_language', label: 'Другой язык' },
  { value: 'different_depth', label: 'Другая глубина материала' },
  { value: 'updated_revision', label: 'Обновлённая редакция источника' },
  { value: 'recurring_training', label: 'Повторное обучение' },
  { value: 'other', label: 'Другая причина' },
];

const COURSE_STATUSES: Record<string, string> = {
  draft: 'Черновик',
  published: 'Опубликован',
  archived: 'Архив',
};

interface SourceReuseDialogProps {
  courses: ReusedSourceCourse[];
  reason: ReuseReason | null;
  submitting: boolean;
  onReasonChange: (reason: ReuseReason) => void;
  onCancel: () => void;
  onConfirm: (reason: ReuseReason) => void;
}

export function SourceReuseDialog({
  courses,
  reason,
  submitting,
  onReasonChange,
  onCancel,
  onConfirm,
}: SourceReuseDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const onCancelRef = useRef(onCancel);
  const submittingRef = useRef(submitting);

  useEffect(() => {
    onCancelRef.current = onCancel;
    submittingRef.current = submitting;
  }, [onCancel, submitting]);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submittingRef.current) {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;

      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus();
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        className="max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-2xl border border-border bg-card shadow-card-lg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="reuse-source-title"
        aria-describedby="reuse-source-description"
      >
        <div className="border-b border-border px-5 py-4">
          <h3 id="reuse-source-title" className="font-bold text-foreground font-display">
            Источник уже использован
          </h3>
          <p id="reuse-source-description" className="mt-1 text-sm text-muted-foreground">
            Создание нового курса не изменит эти курсы, но создаст независимый
            черновик и израсходует AI-лимит.
          </p>
        </div>
        <div className="space-y-4 px-5 py-4">
          <div
            aria-label="Курсы, уже созданные по выбранным источникам"
            className="max-h-36 space-y-2 overflow-y-auto rounded-lg border border-border bg-muted/30 p-3"
          >
            {courses.map((course) => (
              <div key={course.id} className="flex justify-between gap-3 text-sm">
                <span className="min-w-0 truncate text-foreground">{course.title}</span>
                <span className="shrink-0 text-muted-foreground">
                  {COURSE_STATUSES[course.status] ?? course.status}
                </span>
              </div>
            ))}
          </div>
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-foreground">
              Почему нужен ещё один курс?
            </legend>
            <div className="space-y-2">
              {REUSE_REASONS.map((option) => (
                <label
                  key={option.value}
                  className="flex cursor-pointer items-center gap-2 text-sm text-foreground"
                >
                  <input
                    type="radio"
                    name="reuse-reason"
                    value={option.value}
                    checked={reason === option.value}
                    disabled={submitting}
                    onChange={() => onReasonChange(option.value)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded-xl border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted disabled:opacity-50"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={() => reason && onConfirm(reason)}
            disabled={!reason || submitting}
            className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? 'Запуск...' : 'Создать независимый курс'}
          </button>
        </div>
      </div>
    </div>
  );
}
