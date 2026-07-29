'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { CalendarDays } from 'lucide-react';
import { Input } from './input';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n/useT';
import { displayDateToIso, isoDateToDisplay, maskDisplayDate } from '@/lib/dateInput';

interface DateInputProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
  className?: string;
  id?: string;
  min?: string;
  max?: string;
  'aria-label'?: string;
}

export function DateInput({
  value,
  onChange,
  disabled,
  required,
  className,
  id,
  min,
  max,
  'aria-label': ariaLabel,
}: DateInputProps) {
  const { t } = useT();
  const generatedId = useId();
  const inputId = id || `date-${generatedId.replace(/:/g, '')}`;
  const errorId = `${inputId}-error`;
  const pickerRef = useRef<HTMLInputElement>(null);
  const focusedRef = useRef(false);
  const [displayValue, setDisplayValue] = useState(() => isoDateToDisplay(value));
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    if (!focusedRef.current) {
      setDisplayValue(isoDateToDisplay(value));
      setInvalid(false);
    }
  }, [value]);

  const updateDisplay = (rawValue: string) => {
    const nextDisplay = maskDisplayDate(rawValue);
    setDisplayValue(nextDisplay);

    if (!nextDisplay) {
      setInvalid(false);
      onChange('');
      return;
    }

    const isoValue = displayDateToIso(nextDisplay);
    if (isoValue) {
      setInvalid(false);
      onChange(isoValue);
    } else {
      setInvalid(nextDisplay.length === 10);
    }
  };

  const openPicker = () => {
    if (disabled) return;
    const picker = pickerRef.current;
    if (!picker) return;
    if (typeof picker.showPicker === 'function') picker.showPicker();
    else picker.click();
  };

  return (
    <div className={cn('relative', className)}>
      <Input
        id={inputId}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder={t('common.date.placeholder')}
        value={displayValue}
        disabled={disabled}
        required={required}
        maxLength={10}
        aria-label={ariaLabel}
        aria-invalid={invalid}
        aria-describedby={invalid ? errorId : undefined}
        className="pr-11 tabular-nums"
        onFocus={() => {
          focusedRef.current = true;
        }}
        onChange={(event) => updateDisplay(event.target.value)}
        onBlur={() => {
          focusedRef.current = false;
          setInvalid(Boolean(displayValue) && displayDateToIso(displayValue) === null);
        }}
      />
      <button
        type="button"
        className="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        aria-label={t('common.date.select')}
        title={t('common.date.select')}
        disabled={disabled}
        onClick={openPicker}
      >
        <CalendarDays className="h-4 w-4" aria-hidden="true" />
      </button>
      <input
        ref={pickerRef}
        type="date"
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(event) => {
          onChange(event.target.value);
          setDisplayValue(isoDateToDisplay(event.target.value));
          setInvalid(false);
        }}
      />
      {invalid && (
        <p id={errorId} className="mt-1 text-xs text-destructive">
          {t('common.date.invalid')}
        </p>
      )}
    </div>
  );
}
