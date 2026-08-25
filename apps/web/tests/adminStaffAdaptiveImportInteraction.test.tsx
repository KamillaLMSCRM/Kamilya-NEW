import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AdminStaffPage from '@/app/admin/staff/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: (url: string) => window.history.replaceState({}, '', url),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const getMock = vi.mocked(api.get);
const postMock = vi.mocked(api.post);
const patchMock = vi.mocked(api.patch);

const user = {
  user_id: 'methodologist-1',
  tenant_id: 'tenant-1',
  tenant: { id: 'tenant-1', name: 'Сандык' },
  telegram_id: '',
  role: 'methodologist',
  roles: ['methodologist'],
  full_name: 'Методист',
  email: 'methodologist@example.com',
};

const proposal = {
  branches: [{ branch_id: 'branch-1', branch_name: 'Филиал Павлодар', external_key: 'branch-1', action: 'create', confidence: 'high', evidence: [{ claim: 'Строка филиала' }] }],
  departments: [{ department_id: 'dept-1', department_name: 'Бухгалтерия', external_key: 'dept-1', branch_external_key: 'branch-1', action: 'create', confidence: 'high', evidence: [] }],
  positions: [{ position_id: 'position-1', position_name: 'Кассир', external_key: 'position-1', branch_external_key: 'branch-1', department_external_key: 'dept-1', action: 'create', confidence: 'high', evidence: [] }],
  staff: [{ external_key: 'staff-101', personnel_number: '101', first_name: 'Айдана', last_name: 'Сейтова', position_external_key: 'position-1', branch_external_key: 'branch-1', department_external_key: 'dept-1', action: 'create', confidence: 'high', evidence: [] }],
  conflicts: [],
};

const needsMapping = {
  id: 'session-1',
  state: 'needs_mapping',
  mode: 'ADD_OR_UPDATE',
  source_file_name: 'штатка.xlsx',
  source_file_sha256: 'a'.repeat(64),
  source_format: 'xlsx',
  workbook_analysis: {
    parser: {
      raw_columns: ['Код', 'Имя', 'Фамилия', 'Филиал', 'Отдел', 'Должность'],
      suggested_mapping: { first_name: 'Имя', last_name: 'Фамилия', department: 'Отдел', position: 'Должность' },
      missing_required_columns: ['personnel_number'],
      selected_sheet: 'Сотрудники',
      header_row: 2,
    },
  },
  mapping_json: null,
  proposal: null,
  proposal_revision: null,
  expires_at: null,
  result_summary: null,
};

const ready = { ...needsMapping, state: 'ready_for_approval', mapping_json: { personnel_number: 'Код', first_name: 'Имя', last_name: 'Фамилия', department: 'Отдел', position: 'Должность' }, proposal, proposal_revision: 'revision-1' };
const approved = { ...ready, state: 'approved' };
const committed = { ...approved, state: 'committed' };
const needsCorrection = {
  ...ready,
  state: 'needs_correction',
  proposal: {
    ...proposal,
    conflicts: [{ id: 'conflict-1', blocking: true, message: 'Проверьте связь с филиалом', evidence: ['Строка 8'] }],
  },
};

const tree = {
  branches: [{
    id: 'branch-1',
    name: 'Филиал Павлодар',
    unit_type: 'branch',
    employee_count: 1,
    positions: [{
      id: 'position-direct-1',
      name: 'Региональный директор',
      department: 'Филиал Павлодар',
      department_slug: 'branch-1',
      employee_count: 1,
      employees: [{ id: 'employee-direct-1', full_name: 'Айдана Сейтова', personnel_number: '101', is_active: true }],
    }],
    children: [{ id: 'dept-1', name: 'Бухгалтерия', unit_type: 'department', children: [] }],
  }],
  legacy_roots: [],
  summary: { total_branches: 1, total_departments: 1, legacy_roots: 0 },
};

function setMethodologist() {
  useAuthStore.setState({ accessToken: 'test-token', user });
}

beforeEach(() => {
  setMethodologist();
  window.history.replaceState({}, '', '/');
  window.sessionStorage.clear();
  vi.stubGlobal('crypto', { randomUUID: () => 'idempotency-1' });
  getMock.mockImplementation(async (url: string) => {
    if (url.includes('/import/mappings')) return { data: [] } as any;
    if (url.includes('/organization-units/tree')) return { data: tree } as any;
    if (url.includes('/import/sessions/session-1')) return { data: needsMapping } as any;
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockReset();
  patchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('adaptive staff import interactions', () => {
  it('edits mapping, resumes the same session and keeps only its id in sessionStorage', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Импорт/i }));
    const file = new File(['workbook'], 'штатка.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    fireEvent.change(await screen.findByLabelText(/штатного расписания для анализа/i), { target: { files: [file] } });
    postMock.mockResolvedValueOnce({ data: needsMapping } as any);
    fireEvent.click(screen.getByRole('button', { name: /Запустить анализ файла/i }));

    expect(await screen.findByText(/Нужно сопоставить колонки/i)).toBeInTheDocument();
    expect(screen.queryByText(/"raw_columns"/i)).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem('kamilya-adaptive-import-session-id')).toBe('session-1');
    expect(Object.keys(window.sessionStorage)).toEqual(['kamilya-adaptive-import-session-id']);

    fireEvent.change(screen.getByRole('combobox', { name: 'Табельный номер' }), { target: { value: 'Код' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Имя' }), { target: { value: 'Имя' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Фамилия' }), { target: { value: 'Фамилия' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Отдел' }), { target: { value: 'Отдел' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Должность' }), { target: { value: 'Должность' } });

    postMock.mockResolvedValueOnce({ data: ready } as any);
    fireEvent.click(screen.getByRole('button', { name: /Сохранить сопоставление и продолжить/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/admin/staff/import/sessions/session-1/mapping',
      expect.objectContaining({ mapping_json: expect.objectContaining({ personnel_number: 'Код' }), sheet_name: 'Сотрудники' }),
    ));
    expect(await screen.findByText(/Предлагаемая структура/i)).toBeInTheDocument();

    // The resume path is a GET against the same id and never exposes workbook JSON.
    fireEvent.click(screen.getByRole('button', { name: /Обновить анализ/i }));
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/v1/admin/staff/import/sessions/session-1'));
  });

  it('accepts branch-only mapping and submits methodologist hierarchy corrections', async () => {
    const branchOnly = {
      ...needsMapping,
      workbook_analysis: {
        parser: {
          ...needsMapping.workbook_analysis.parser,
          raw_columns: ['Код', 'ФИО', 'Филиал', 'Должность'],
          suggested_mapping: { full_name: 'ФИО', branch: 'Филиал', position: 'Должность' },
          missing_required_columns: ['personnel_number'],
        },
      },
    };
    postMock.mockResolvedValueOnce({ data: branchOnly } as any);
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Импорт/i }));
    fireEvent.change(await screen.findByLabelText(/штатного расписания для анализа/i), { target: { files: [new File(['x'], 'branch.xlsx')] } });
    fireEvent.click(screen.getByRole('button', { name: /Запустить анализ файла/i }));
    await screen.findByText(/Нужно сопоставить колонки/i);
    fireEvent.change(screen.getByRole('combobox', { name: 'Табельный номер' }), { target: { value: 'Код' } });
    expect(screen.getByRole('button', { name: /Сохранить сопоставление/i })).toBeEnabled();

    postMock.mockResolvedValueOnce({ data: ready } as any);
    fireEvent.click(screen.getByRole('button', { name: /Сохранить сопоставление/i }));
    await screen.findByText(/Предлагаемая структура/i);
    fireEvent.click(screen.getByRole('button', { name: /Редактировать структуру/i }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Название филиала 1' }), { target: { value: 'Филиал Север' } });
    postMock.mockResolvedValueOnce({ data: { ...ready, proposal_revision: 'revision-2' } } as any);
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/admin/staff/import/sessions/session-1/corrections',
      expect.objectContaining({
        revision: 'revision-1',
        corrections: expect.arrayContaining([expect.objectContaining({ kind: 'branch', external_key: 'branch-1', name: 'Филиал Север' })]),
      }),
    ));
  });

  it('keeps branch-only positions linked to their branch in correction payload', async () => {
    postMock.mockResolvedValueOnce({ data: needsCorrection } as any);
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Импорт/i }));
    fireEvent.change(await screen.findByLabelText(/штатного расписания для анализа/i), { target: { files: [new File(['x'], 'correction.xlsx')] } });
    fireEvent.click(screen.getByRole('button', { name: /Запустить анализ файла/i }));

    await screen.findByText(/Предлагаемая структура/i);
    fireEvent.click(screen.getByRole('button', { name: /Редактировать структуру/i }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Подразделение должности 1' }), { target: { value: 'legacy:root' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Название должности 1' }), { target: { value: 'Старший кассир' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Должность сотрудника 1' }), { target: { value: 'position-1' } });
    postMock.mockResolvedValueOnce({ data: { ...needsCorrection, proposal_revision: 'revision-2' } } as any);
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/i }));

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/admin/staff/import/sessions/session-1/corrections',
      expect.objectContaining({
        revision: 'revision-1',
        corrections: expect.arrayContaining([
          expect.objectContaining({ kind: 'position', external_key: 'position-1', name: 'Старший кассир', branch_external_key: 'branch-1', department_external_key: 'legacy:root' }),
          expect.objectContaining({ kind: 'staff', external_key: 'staff-101', position_external_key: 'position-1', branch_external_key: 'branch-1', department_external_key: 'legacy:root' }),
        ]),
      }),
    ));
  });
});

describe('organization structure interactions', () => {
  it('renders positions and employees assigned directly to a branch', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Структура/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^Филиал Павлодар/ }));
    const position = await screen.findByRole('button', { name: /Региональный директор/ });
    expect(screen.getByRole('link', { name: /Профиль и обучение/i })).toHaveAttribute('href', '/positions/position-direct-1?tab=training');
    fireEvent.click(position);
    expect(await screen.findByText('Айдана Сейтова')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Назначить обучение/i })).toHaveAttribute('href', '/assignments?user_id=employee-direct-1');
  });

  it('renders nested branch and department labels and submits a new department', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Структура/i }));
    expect(await screen.findByText('Филиал Павлодар')).toBeInTheDocument();
    expect(screen.getByText('Филиалов')).toBeInTheDocument();
    expect(screen.getByText('Отделов')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Добавить отдел/i }));
    const dialog = await screen.findByRole('dialog');
    const name = within(dialog).getByPlaceholderText(/Отдел внутреннего контроля/i);
    expect(name).toHaveFocus();
    fireEvent.change(name, { target: { value: 'Отдел контроля' } });
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Добавить отдел/i }));
    const secondDepartmentDialog = await screen.findByRole('dialog');
    const secondDepartmentName = within(secondDepartmentDialog).getByPlaceholderText(/Отдел внутреннего контроля/i);
    expect(secondDepartmentName).toHaveValue('');
    fireEvent.change(secondDepartmentName, { target: { value: 'Отдел контроля' } });
    postMock.mockResolvedValueOnce({ data: { id: 'dept-2' } } as any);
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/organization-units', { name: 'Отдел контроля', unit_type: 'department', parent_id: 'branch-1' }));

    fireEvent.click(screen.getByRole('button', { name: /Добавить филиал/i }));
    const branchDialog = await screen.findByRole('dialog');
    const branchName = within(branchDialog).getByPlaceholderText(/Филиал Павлодар/i);
    expect(branchName).toHaveFocus();
    fireEvent.change(branchName, { target: { value: 'Филиал Петропавловск' } });
    postMock.mockResolvedValueOnce({ data: { id: 'branch-2' } } as any);
    fireEvent.click(within(branchDialog).getByRole('button', { name: 'Создать' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/organization-units', { name: 'Филиал Петропавловск', unit_type: 'branch', parent_id: null }));
  });

  it('renames and archives a unit, and keeps legacy unassigned positions visible', async () => {
    getMock.mockImplementation(async (url: string) => {
      if (url.includes('/import/mappings')) return { data: [] } as any;
      if (url.includes('/organization-units/tree')) {
        return {
          data: {
            branches: [],
            legacy_roots: [],
            unassigned_legacy_positions: [{ id: 'legacy-position-1', name: 'Старый кассир', department: 'Неуказанный отдел', employee_count: 2 }],
            summary: { total_branches: 0, total_departments: 0, total_positions: 1, total_employees: 2 },
          },
        } as any;
      }
      throw new Error(`unexpected GET ${url}`);
    });
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Структура/i }));
    expect(await screen.findByText('Старый кассир')).toBeInTheDocument();
    expect(screen.getByText(/Требуют распределения/i)).toBeInTheDocument();
  });

  it('sends an explicit rename and archive request for a branch', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Структура/i }));
    expect(await screen.findByText('Филиал Павлодар')).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: 'Переименовать' })[0]);
    const renameDialog = await screen.findByRole('dialog');
    const renameInput = within(renameDialog).getByDisplayValue('Филиал Павлодар');
    fireEvent.change(renameInput, { target: { value: 'Филиал Север' } });
    patchMock.mockResolvedValueOnce({ data: { id: 'branch-1', name: 'Филиал Север' } } as any);
    fireEvent.click(within(renameDialog).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/v1/organization-units/branch-1', { name: 'Филиал Север' }));

    vi.stubGlobal('confirm', vi.fn(() => true));
    fireEvent.click(screen.getAllByRole('button', { name: 'Архивировать' })[0]);
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/organization-units/branch-1/archive',
      { reason: 'Архивировано методистом через раздел структуры' },
    ));
  });
});
