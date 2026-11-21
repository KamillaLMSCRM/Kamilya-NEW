'use client';

import { ArrowDown, ArrowUp } from 'lucide-react';

export function orderingCopy(language: string) {
  if (language === 'kk') return {
    type: 'Әрекеттер реті', format: 'Қадамдарды дұрыс ретпен енгізіңіз.', step: 'Қадам',
    up: 'Жоғары жылжыту', down: 'Төмен жылжыту', arrange: 'Әрекеттерді дұрыс ретке қойыңыз.',
    confirm: 'Ретті растау', confirmed: 'Рет расталды', correct: 'Дұрыс рет',
  };
  if (language === 'en') return {
    type: 'Order the steps', format: 'Enter the steps in the correct order.', step: 'Step',
    up: 'Move up', down: 'Move down', arrange: 'Put the steps in the correct order.',
    confirm: 'Confirm order', confirmed: 'Order confirmed', correct: 'Correct order',
  };
  return {
    type: 'Порядок действий', format: 'Введите шаги в правильном порядке.', step: 'Шаг',
    up: 'Переместить выше', down: 'Переместить ниже', arrange: 'Расположите действия в правильном порядке.',
    confirm: 'Подтвердить порядок', confirmed: 'Порядок подтверждён', correct: 'Правильный порядок',
  };
}

export function moveOrderingStep<T>(steps: readonly T[], index: number, offset: -1 | 1): T[] {
  const next = [...steps];
  const destination = index + offset;
  if (index < 0 || index >= next.length || destination < 0 || destination >= next.length) return next;
  [next[index], next[destination]] = [next[destination], next[index]];
  return next;
}

export function OrderingButtons({ index, count, label, lang, onMove, disabled = false }: {
  index: number;
  count: number;
  label: string;
  lang: string;
  onMove: (offset: -1 | 1) => void;
  disabled?: boolean;
}) {
  const copy = orderingCopy(lang);
  const style = 'inline-flex h-11 w-11 items-center justify-center rounded-md border border-border hover:bg-muted disabled:opacity-40';
  return (
    <div className="flex shrink-0 gap-1">
      <button type="button" className={style} aria-label={`${copy.up}: ${label}`}
        disabled={disabled || index === 0} onClick={() => onMove(-1)}><ArrowUp className="h-4 w-4" aria-hidden /></button>
      <button type="button" className={style} aria-label={`${copy.down}: ${label}`}
        disabled={disabled || index === count - 1} onClick={() => onMove(1)}><ArrowDown className="h-4 w-4" aria-hidden /></button>
    </div>
  );
}

type Step = { id: string; text: string };

export function OrderingAnswer({ steps, selected, language, onChange, disabled = false }: {
  steps: readonly Step[];
  selected: readonly string[] | undefined;
  language: string;
  onChange: (order: string[]) => void;
  disabled?: boolean;
}) {
  const copy = orderingCopy(language);
  const byId = new Map(steps.map((step) => [step.id, step]));
  const validSelection = selected?.length === steps.length
    && new Set(selected).size === steps.length && selected.every((id) => byId.has(id));
  const order = validSelection ? selected : steps.map((step) => step.id);
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{copy.arrange}</p>
      <ol className="space-y-2">
        {order.map((id, index) => {
          const text = byId.get(id)?.text ?? '';
          return (
            <li key={id} className="flex min-w-0 items-center gap-2 rounded-lg border border-border p-2 sm:gap-3">
              <span className="shrink-0 text-sm tabular-nums text-muted-foreground">{index + 1}.</span>
              <span className="min-w-0 flex-1 break-words text-sm">{text}</span>
              <OrderingButtons index={index} count={order.length} label={text} lang={language} disabled={disabled}
                onMove={(offset) => onChange(moveOrderingStep(order, index, offset))} />
            </li>
          );
        })}
      </ol>
      {!validSelection && <button type="button" className="min-h-11 rounded-lg border border-primary px-3 text-sm text-primary hover:bg-muted"
        disabled={disabled} onClick={() => onChange([...order])}>{copy.confirm}</button>}
      {validSelection && <p role="status" className="text-sm text-muted-foreground">{copy.confirmed}</p>}
    </div>
  );
}
