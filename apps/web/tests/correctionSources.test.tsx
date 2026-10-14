import { StrictMode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const load = vi.hoisted(() => vi.fn());
vi.mock('@/lib/lessonCorrection', () => ({ loadCorrectionSourceFile: load }));
import CorrectionSources from '@/features/methodologist-workbench/CorrectionSources';

const id = '11111111-1111-4111-8111-111111111111';
const citations = [{ document_id: id, locator: 'fact:1', evidence_hash: 'a'.repeat(64) }, { document_id: id, locator: 'fact:2', evidence_hash: 'b'.repeat(64) }];
const file = { blob: new Blob(['%PDF'], { type: 'application/pdf' }), filename: 'Инструкция.pdf', title: 'Инструкция склада' };
const createUrl = vi.fn(() => 'blob:synthetic');
const revokeUrl = vi.fn();
const click = () => fireEvent.click(screen.getByRole('button', { name: 'Подготовить скачивание документа 1' }));

describe('correction source navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks(); load.mockResolvedValue(file);
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revokeUrl }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('is lazy, groups a document while retaining both locators, and labels fragment hashes accurately', () => {
    render(<CorrectionSources citations={citations} locale="ru" />);
    expect(load).not.toHaveBeenCalled(); expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByText('fact:1')).toBeInTheDocument(); expect(screen.getByText('fact:2')).toBeInTheDocument();
    expect(screen.getAllByText(/^Хеш фрагмента: SHA256/)).toHaveLength(2);
    expect(screen.getByText(/Текущий файл может отличаться/)).toBeInTheDocument();
  });

  it('prepares a manual download with filename, not a remote link or embedded file', async () => {
    const view = render(<CorrectionSources citations={citations} locale="ru" />); click();
    const link = await screen.findByRole('link', { name: 'Скачать Инструкция.pdf' });
    expect(link).toHaveAttribute('href', 'blob:synthetic'); expect(link).toHaveAttribute('download', 'Инструкция.pdf');
    expect(screen.getByText('Инструкция склада')).toBeInTheDocument();
    expect(view.container.querySelector('iframe, object, embed')).toBeNull();
    expect(load).toHaveBeenCalledWith(id, expect.any(AbortSignal));
  });

  it('allows only one pending request and cannot issue a second one by double click', async () => {
    let resolve!: (value: typeof file) => void; load.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<CorrectionSources citations={citations} locale="ru" />); click(); click();
    expect(load).toHaveBeenCalledTimes(1); expect(screen.getByRole('button')).toBeDisabled();
    await act(async () => resolve(file)); expect(screen.getByRole('link')).toBeInTheDocument();
  });

  it.each([[403, /Нет доступа/], [401, /Нет доступа/], [404, /Документ или файл недоступен/], [503, /Не удалось подготовить/]])('shows a safe actionable HTTP %s error without raw detail', async (status, message) => {
    load.mockRejectedValue({ response: { status, data: { detail: 'secret-bucket-key' } } });
    render(<CorrectionSources citations={citations} locale="ru" />); click();
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByText(/secret-bucket/)).not.toBeInTheDocument(); expect(screen.getByRole('button')).toBeEnabled();
    expect(createUrl).not.toHaveBeenCalled();
  });

  it('supports an explicit retry after a network error, without automatic retries', async () => {
    load.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(file);
    render(<CorrectionSources citations={citations} locale="ru" />); click(); await screen.findByRole('alert');
    expect(load).toHaveBeenCalledTimes(1); click(); await screen.findByRole('link'); expect(load).toHaveBeenCalledTimes(2);
  });

  it('suppresses abort-resistant completion on unmount and cancels the old signal', async () => {
    let resolve!: (value: typeof file) => void; load.mockReturnValue(new Promise((r) => { resolve = r; }));
    const view = render(<CorrectionSources citations={citations} locale="ru" />); click();
    const signal = load.mock.calls[0][1]; view.unmount(); expect(signal.aborted).toBe(true);
    await act(async () => resolve(file)); expect(createUrl).not.toHaveBeenCalled();
  });

  it('revokes a ready URL on context remount and never displays the old file', async () => {
    const view = render(<CorrectionSources key="old" citations={citations} locale="ru" />); click(); await screen.findByRole('link');
    view.rerender(<CorrectionSources key="new" citations={citations} locale="ru" />);
    expect(revokeUrl).toHaveBeenCalledWith('blob:synthetic'); expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('retains only one file URL and revokes it before preparing another document', async () => {
    render(<CorrectionSources citations={[...citations, { ...citations[0], document_id: '22222222-2222-4222-8222-222222222222' }]} locale="ru" />);
    click(); await screen.findByRole('link'); fireEvent.click(screen.getByRole('button', { name: 'Подготовить скачивание документа 2' }));
    expect(revokeUrl).toHaveBeenCalledOnce(); await screen.findByRole('link'); expect(load).toHaveBeenCalledTimes(2);
  });

  it('remains usable after StrictMode setup/cleanup/setup', async () => {
    render(<StrictMode><CorrectionSources citations={citations} locale="ru" /></StrictMode>); click();
    await screen.findByRole('link'); expect(createUrl).toHaveBeenCalledOnce();
  });

  it.each([['kk', '1-құжатты жүктеуге дайындау', /Ағымдағы файл/], ['en', 'Prepare document 1 download', /current file may differ/i]])('localizes the action and revision warning for %s', (locale, button, warning) => {
    render(<CorrectionSources citations={citations} locale={locale as 'kk' | 'en'} />);
    expect(screen.getByRole('button', { name: button })).toBeInTheDocument(); expect(screen.getByText(warning)).toBeInTheDocument();
  });
});
