import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PositionsPage from '@/app/positions/page';
import { api } from '@/lib/api';

vi.mock('@/i18n/useT', () => {
  const t = (key: string) => key;
  const tp = (key: string, count: number) => `${key}:${count}`;
  return { useT: () => ({ t, tp, lang: 'en' }) };
});

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('@/components/ui/Toast', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const getMock = vi.mocked(api.get);
const postMock = vi.mocked(api.post);

const legacyRootId = '11111111-1111-4111-8111-111111111111';
const branchId = '22222222-2222-4222-8222-222222222222';
const nestedUnitId = '33333333-3333-4333-8333-333333333333';
const projectedPositionId = '44444444-4444-4444-8444-444444444444';

const tree = {
  roots: [
    {
      id: legacyRootId,
      name: 'Учебный отдел',
      unit_type: 'department',
      legacy_root: true,
      children: [],
      positions: [{ id: projectedPositionId, name: 'Проекция должности', employee_count: 0, employees: [] }],
    },
    {
      id: branchId,
      name: 'Учебный филиал',
      unit_type: 'branch',
      children: [
        {
          id: nestedUnitId,
          name: 'Учебный отдел',
          unit_type: 'department',
          parent_id: branchId,
          children: [],
          positions: [],
        },
      ],
      positions: [],
    },
  ],
  legacy_roots: [],
  unassigned_legacy_positions: [{ id: projectedPositionId, name: 'Проекция должности', employee_count: 0, employees: [] }],
};

beforeEach(() => {
  vi.clearAllMocks();
  getMock.mockImplementation(async (url: string) => {
    if (url === '/v1/positions') return { data: [] } as never;
    if (url === '/v1/organization-units/tree') return { data: tree } as never;
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockResolvedValue({ data: {} } as never);
});

describe('position canonical unit selection', () => {
  it('submits the selected nested unit UUID instead of a free-form department name', async () => {
    render(<PositionsPage />);

    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/v1/organization-units/tree'));
    fireEvent.click(screen.getByRole('button', { name: 'authenticatedUi.positions.create' }));
    const dialog = screen.getByRole('dialog');
    const unitSelect = within(dialog).getByRole('combobox', { name: 'authenticatedUi.positions.department' });

    expect(within(unitSelect).getByRole('option', { name: 'Учебный отдел — Отдел' })).toHaveValue(legacyRootId);
    expect(within(unitSelect).getByRole('option', { name: 'Учебный филиал → Учебный отдел — Отдел' })).toHaveValue(nestedUnitId);
    expect(within(unitSelect).queryByRole('option', { name: /Проекция должности/ })).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText('authenticatedUi.positions.name'), {
      target: { value: 'Учебный специалист' },
    });
    fireEvent.change(unitSelect, { target: { value: nestedUnitId } });
    fireEvent.submit(within(dialog).getByRole('button', { name: 'authenticatedUi.positions.create' }).closest('form')!);

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/positions',
      expect.objectContaining({
        name: 'Учебный специалист',
        department_id: nestedUnitId,
      }),
    ));
    const payload = postMock.mock.calls[0][1] as Record<string, unknown>;
    expect(payload).not.toHaveProperty('department');
  });

  it('shows a hierarchy error, blocks accidental unassigned creation, and retries', async () => {
    let treeAttempts = 0;
    getMock.mockImplementation(async (url: string) => {
      if (url === '/v1/positions') return { data: [] } as never;
      if (url === '/v1/organization-units/tree') {
        treeAttempts += 1;
        if (treeAttempts === 1) throw new Error('tree unavailable');
        return { data: tree } as never;
      }
      throw new Error(`unexpected GET ${url}`);
    });

    render(<PositionsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'authenticatedUi.positions.create' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('authenticatedUi.positions.name'), {
      target: { value: 'Учебный специалист' },
    });

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('authenticatedUi.positions.loadError');
    expect(within(dialog).getByRole('button', { name: 'authenticatedUi.positions.create' })).toBeDisabled();
    expect(postMock).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'authenticatedUi.positions.retry' }));
    await waitFor(() => expect(within(dialog).getByRole('combobox', { name: 'authenticatedUi.positions.department' })).toBeEnabled());
    expect(within(dialog).getByRole('button', { name: 'authenticatedUi.positions.create' })).toBeEnabled();
  });

  it('allows an explicit no-department choice after the hierarchy load fails', async () => {
    getMock.mockImplementation(async (url: string) => {
      if (url === '/v1/positions') return { data: [] } as never;
      if (url === '/v1/organization-units/tree') throw new Error('tree unavailable');
      throw new Error(`unexpected GET ${url}`);
    });

    render(<PositionsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'authenticatedUi.positions.create' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('authenticatedUi.positions.name'), {
      target: { value: 'Должность без отдела' },
    });
    await within(dialog).findByRole('alert');
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'authenticatedUi.positions.noDepartment' }));
    fireEvent.submit(within(dialog).getByRole('button', { name: 'authenticatedUi.positions.create' }).closest('form')!);

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/positions',
      expect.objectContaining({
        name: 'Должность без отдела',
        department_id: null,
      }),
    ));
  });
});
