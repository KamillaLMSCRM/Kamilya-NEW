import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DateInput } from '@/components/ui/date-input';
import { displayDateToIso, isoDateToDisplay, maskDisplayDate } from '@/lib/dateInput';
import fs from 'node:fs';
import path from 'node:path';

describe('date input format', () => {
  it('converts valid dates without timezone shifts', () => {
    expect(displayDateToIso('29/07/2026')).toBe('2026-07-29');
    expect(displayDateToIso('29/02/2024')).toBe('2024-02-29');
    expect(displayDateToIso('29/02/2025')).toBeNull();
    expect(isoDateToDisplay('2026-07-29')).toBe('29/07/2026');
  });

  it('masks digits and accepts pasted ISO dates', () => {
    expect(maskDisplayDate('29072026')).toBe('29/07/2026');
    expect(maskDisplayDate('29.07.2026')).toBe('29/07/2026');
    expect(maskDisplayDate('2026-07-29')).toBe('29/07/2026');
  });

  it('emits ISO only for a complete valid date', () => {
    const onChange = vi.fn();
    render(<DateInput value="" onChange={onChange} aria-label="Дата" />);

    const input = screen.getByLabelText('Дата');
    fireEvent.change(input, { target: { value: '29072026' } });
    expect(input).toHaveValue('29/07/2026');
    expect(onChange).toHaveBeenLastCalledWith('2026-07-29');

    fireEvent.change(input, { target: { value: '31022026' } });
    fireEvent.blur(input);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveValue('31/02/2026');
  });

  it('uses the shared formatted control on every date-entry screen', () => {
    const dateScreens = [
      'src/app/admin/training-log/page.tsx',
      'src/app/learning-paths/page.tsx',
      'src/app/admin/super/tenants/page.tsx',
      'src/app/admin/super/tenants/[id]/page.tsx',
    ];

    dateScreens.forEach((file) => {
      const source = fs.readFileSync(path.join(process.cwd(), file), 'utf8');
      expect(source).toContain('<DateInput');
      expect(source).not.toContain('type="date"');
    });
  });
});
