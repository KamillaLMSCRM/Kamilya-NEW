import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  SourceReuseDialog,
  type ReuseReason,
} from '@/features/ai-generation/SourceReuseDialog';

function renderDialog(overrides?: {
  reason?: ReuseReason | null;
  submitting?: boolean;
  onCancel?: () => void;
  onConfirm?: (reason: ReuseReason) => void;
}) {
  const onReasonChange = vi.fn();
  const onCancel = vi.fn(overrides?.onCancel);
  const onConfirm = vi.fn(overrides?.onConfirm);
  const view = render(
    <SourceReuseDialog
      courses={[{ id: 'course-1', title: 'Курс по ИБ', status: 'published' }]}
      reason={overrides?.reason ?? null}
      submitting={overrides?.submitting ?? false}
      onReasonChange={onReasonChange}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />,
  );
  return { ...view, onReasonChange, onCancel, onConfirm };
}

describe('AI generation source reuse decision', () => {
  it('lists existing courses and requires an explicit reason', () => {
    const { onReasonChange, onConfirm } = renderDialog();

    expect(screen.getByRole('dialog', { name: 'Источник уже использован' })).toBeInTheDocument();
    expect(screen.getByText('Курс по ИБ')).toBeInTheDocument();
    expect(screen.getByText('Опубликован')).toBeInTheDocument();
    expect(screen.getByText(/не изменит эти курсы/)).toBeInTheDocument();
    expect(screen.getByText(/израсходует AI-лимит/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Создать независимый курс' })).toBeDisabled();

    fireEvent.click(screen.getByRole('radio', { name: 'Другая аудитория' }));
    expect(onReasonChange).toHaveBeenCalledWith('different_audience');
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('submits the selected reason and disables actions while starting', () => {
    const ready = renderDialog({ reason: 'different_depth' });
    fireEvent.click(screen.getByRole('button', { name: 'Создать независимый курс' }));
    expect(ready.onConfirm).toHaveBeenCalledWith('different_depth');

    screen.getByRole('button', { name: 'Отмена' }).click();
    expect(ready.onCancel).toHaveBeenCalledOnce();
  });

  it('supports Escape dismissal, focus restoration, and keyboard trapping', () => {
    const opener = document.createElement('button');
    opener.textContent = 'Создать курс';
    document.body.appendChild(opener);
    opener.focus();
    const { onCancel, unmount } = renderDialog({ reason: 'different_audience' });

    expect(screen.getByRole('button', { name: 'Отмена' })).toHaveFocus();
    const firstReason = screen.getByRole('radio', { name: 'Другая аудитория' });
    const confirm = screen.getByRole('button', { name: 'Создать независимый курс' });
    confirm.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(firstReason).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledOnce();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it('constrains the dialog to the mobile viewport and locks controls while submitting', () => {
    renderDialog({ reason: 'different_audience', submitting: true });

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveClass('max-h-[calc(100dvh-2rem)]', 'overflow-y-auto');
    expect(screen.getByRole('button', { name: 'Отмена' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Запуск...' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Другая аудитория' })).toBeDisabled();
  });
});
