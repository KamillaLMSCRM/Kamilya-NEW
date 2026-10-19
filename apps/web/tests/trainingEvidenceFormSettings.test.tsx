import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
  createObjectURL: vi.fn(() => 'blob:preview'),
  revokeObjectURL: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: { get: mocks.get, post: mocks.post, put: mocks.put } }));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: mocks.error, success: mocks.success } }));
vi.mock('@/components/PdfPreview', () => ({
  default: () => <div data-testid="pdf-preview" />,
}));

import TrainingEvidenceFormSettingsPage from '@/app/admin/training-evidence/settings/page';

const catalog = {
  fields: [
    { id: 'employee_name', label: 'Имя сотрудника', group: 'Сотрудник', required: true },
    { id: 'department', label: 'Подразделение', group: 'Сотрудник', required: false },
    { id: 'course_title', label: 'Название курса', group: 'Курс', required: true },
    { id: 'test_results', label: 'Итог каждой попытки', group: 'Тестирование', required: true },
  ],
  default_selected_fields: ['employee_name', 'course_title', 'test_results'],
};

const settings = {
  template_version: 1,
  organization_name: 'Kamilya LMS',
  title: 'Подтверждение прохождения курса',
  intro_text: 'Intro',
  confirmation_text: 'Confirmation',
  employee_signature_label: 'Подпись сотрудника',
  employee_date_label: 'Дата',
  representative_signature_label: 'Подпись представителя',
  representative_date_label: 'Дата проверки',
  representative_name: '',
  representative_title: '',
  footer_note: '',
  selected_fields: null as string[] | null,
};

const pdf = () => new Blob(['%PDF-1.7\npreview'], { type: 'application/pdf' });

function configureApi(overrides: { selected_fields?: string[] | null } = {}) {
  mocks.get.mockImplementation((url: string) => url.endsWith('/form-fields')
    ? Promise.resolve({ data: catalog })
    : Promise.resolve({ data: { ...settings, ...overrides } }));
  mocks.post.mockResolvedValue({ data: pdf() });
  mocks.put.mockImplementation((_url: string, value: unknown) => Promise.resolve({ data: value }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('URL', { createObjectURL: mocks.createObjectURL, revokeObjectURL: mocks.revokeObjectURL });
  configureApi();
});

describe('training evidence form field builder', () => {
  it('keeps a legacy null template until the administrator configures fields', async () => {
    render(<TrainingEvidenceFormSettingsPage />);

    expect(await screen.findByRole('button', { name: 'Настроить поля' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Настроить поля' }));
    expect(screen.getByRole('checkbox', { name: 'Имя сотрудника' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Имя сотрудника' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Название курса' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Подразделение' })).not.toBeChecked();
  });

  it('includes an optional field in the saved selected_fields list', async () => {
    render(<TrainingEvidenceFormSettingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Настроить поля' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Подразделение' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ selected_fields: ['employee_name', 'course_title', 'test_results', 'department'] });
  });

  it('renders and saves distinct quiz result texts alongside the course form', async () => {
    render(<TrainingEvidenceFormSettingsPage />);

    const title = await screen.findByLabelText('Заголовок результата теста');
    const intro = screen.getByLabelText('Вводный текст результата теста');
    const confirmation = screen.getByLabelText('Текст подтверждения результата теста');
    expect(title).toHaveValue('Результат отдельного теста');
    expect(intro).toHaveValue('Документ фиксирует результат отдельного теста и не подтверждает завершение курса.');
    expect(confirmation).toHaveValue('Подтверждаю самостоятельное выполнение указанного теста. Результат приведён в документе.');

    fireEvent.change(title, { target: { value: 'Мой результат теста' } });
    fireEvent.change(intro, { target: { value: 'Только отдельный тест.' } });
    fireEvent.change(confirmation, { target: { value: 'Подтверждаю тест.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    expect(mocks.put.mock.calls[0][1]).toMatchObject({
      quiz_title: 'Мой результат теста',
      quiz_intro_text: 'Только отдельный тест.',
      quiz_confirmation_text: 'Подтверждаю тест.',
    });
  });

  it('requests a separate-test preview when that preview mode is selected', async () => {
    render(<TrainingEvidenceFormSettingsPage />);
    await screen.findByLabelText('Заголовок результата теста');
    fireEvent.click(screen.getByRole('button', { name: 'Отдельный тест' }));

    expect(screen.getByText(/Название теста и ID попытки отображаются всегда/)).toBeInTheDocument();

    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
      '/v1/training-evidence/form-settings/preview?activity=quiz',
      expect.anything(),
      expect.objectContaining({ responseType: 'blob' }),
    ));
  });

  it('shows a retry state and keeps save disabled when catalog loading fails', async () => {
    let failed = true;
    mocks.get.mockImplementation((url: string) => {
      if (url.endsWith('/form-fields') && failed) return Promise.reject({ config: { url } });
      return url.endsWith('/form-fields') ? Promise.resolve({ data: catalog }) : Promise.resolve({ data: settings });
    });
    render(<TrainingEvidenceFormSettingsPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Редактирование и сохранение отключены');
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    failed = false;
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
    expect(await screen.findByRole('button', { name: 'Настроить поля' })).toBeInTheDocument();
  });

  it('does not enable download from a preview that belongs to an older draft', async () => {
    let resolvePreview!: (value: { data: Blob }) => void;
    mocks.post.mockImplementation(() => new Promise((resolve) => { resolvePreview = resolve; }));
    render(<TrainingEvidenceFormSettingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Настроить поля' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('checkbox', { name: 'Подразделение' }));
    const download = screen.getByRole('button', { name: /Скачать/ });
    expect(download).toBeDisabled();
    resolvePreview({ data: pdf() });
    await waitFor(() => expect(download).toBeDisabled());
    expect(mocks.createObjectURL).not.toHaveBeenCalled();
  });
});
