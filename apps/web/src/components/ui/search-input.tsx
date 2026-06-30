'use client';

import { useEffect, useState } from 'react';
import { Input } from './input';

/**
 * SearchInput — типизированный input с иконкой 🔍 и debounce.
 *
 * Используется во всех админских списках, где клиент хочет
 * отфильтровать >10 элементов по подстроке. Debounce 250мс —
 * не дёргает бэк на каждое нажатие.
 *
 * Props:
 *   value        — текущее значение (controlled)
 *   onChange     — callback с debounced значением
 *   placeholder  — placeholder text
 *   debounceMs   — задержка (default 250)
 *   className    — дополнительные классы для <Input>
 */
export interface SearchInputProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  debounceMs?: number;
  className?: string;
  autoFocus?: boolean;
}

export function SearchInput({
  value,
  onChange,
  placeholder = 'Поиск…',
  debounceMs = 250,
  className = '',
  autoFocus = false,
}: SearchInputProps) {
  // Локальный state — чтобы печатать без лагов, даже если
  // родитель ререндерит список на каждый onChange.
  const [local, setLocal] = useState(value);

  // Синхронизируем если родитель меняет value программно
  // (например, очистка фильтра извне).
  useEffect(() => {
    setLocal(value);
  }, [value]);

  // Debounced onChange — не чаще раза в debounceMs.
  useEffect(() => {
    if (local === value) return; // ничего не изменилось
    const t = setTimeout(() => onChange(local), debounceMs);
    return () => clearTimeout(t);
  }, [local, debounceMs, onChange, value]);

  return (
    <div className={`relative ${className}`}>
      <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted-foreground text-sm">
        🔍
      </span>
      <Input
        type="search"
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="pl-9 pr-9"
        aria-label="Поиск"
      />
      {local && (
        <button
          type="button"
          onClick={() => {
            setLocal('');
            onChange('');
          }}
          className="absolute inset-y-0 right-2 flex items-center text-muted-foreground hover:text-foreground text-sm"
          aria-label="Очистить"
        >
          ×
        </button>
      )}
    </div>
  );
}
