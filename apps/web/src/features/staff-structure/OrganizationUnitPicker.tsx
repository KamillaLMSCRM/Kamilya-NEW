"use client";

import { useMemo, useState } from 'react';

import {
  flattenOrganizationUnits,
  type FlattenedOrganizationUnit,
  type OrganizationUnitNode,
} from './organizationStructure';

interface OrganizationUnitPickerProps {
  roots: OrganizationUnitNode[];
  value: string;
  onChange: (unit: FlattenedOrganizationUnit | null) => void;
  disabled?: boolean;
  excludeUnitIds?: ReadonlySet<string>;
  selectAriaLabel?: string;
}

export function OrganizationUnitPicker({
  roots,
  value,
  onChange,
  disabled = false,
  excludeUnitIds,
  selectAriaLabel = 'Отдел / подразделение (необязательно)',
}: OrganizationUnitPickerProps) {
  const [query, setQuery] = useState('');
  const options = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return flattenOrganizationUnits(roots).filter((option) => {
      if (excludeUnitIds?.has(option.id)) return false;
      if (!needle) return true;
      return `${option.name} ${option.breadcrumb} ${option.unitType}`.toLocaleLowerCase().includes(needle);
    });
  }, [excludeUnitIds, query, roots]);

  return (
    <div className="space-y-2">
      <input
        type="search"
        aria-label="Поиск подразделения"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        disabled={disabled}
        placeholder="Найти подразделение…"
        className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary"
      />
      <select
        aria-label={selectAriaLabel}
        value={value}
        onChange={(event) => onChange(options.find((option) => option.id === event.target.value) || null)}
        disabled={disabled}
        className="w-full rounded-lg border border-border bg-card px-3 py-2 outline-none focus:border-primary"
      >
        <option value="">Без подразделения</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {`${'  '.repeat(Math.min(option.depth, 8))}${option.name} — ${option.unitType}`}
          </option>
        ))}
      </select>
      {value && (
        <p className="text-xs text-muted-foreground">
          Путь: {options.find((option) => option.id === value)?.breadcrumb || 'подразделение'}
        </p>
      )}
    </div>
  );
}
