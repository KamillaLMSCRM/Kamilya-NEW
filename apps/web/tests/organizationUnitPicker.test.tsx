import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { OrganizationUnitPicker } from '@/features/staff-structure/OrganizationUnitPicker';

const unit = (id: string, name: string, children: any[] = []) => ({
  id,
  name,
  unit_type: 'department',
  children,
  positions: [],
});

describe('OrganizationUnitPicker', () => {
  it('shows the full hierarchy so same-name units are distinguishable before selection', () => {
    render(<OrganizationUnitPicker
      roots={[
        unit('north', 'Север', [unit('sales-north', 'Продажи')]),
        unit('south', 'Юг', [unit('sales-south', 'Продажи')]),
      ]}
      value=""
      onChange={vi.fn()}
    />);

    const select = screen.getByRole('combobox', { name: 'Отдел / подразделение (необязательно)' });
    expect(within(select).getByRole('option', { name: 'Север → Продажи — Отдел' })).toBeInTheDocument();
    expect(within(select).getByRole('option', { name: 'Юг → Продажи — Отдел' })).toBeInTheDocument();
  });
});
