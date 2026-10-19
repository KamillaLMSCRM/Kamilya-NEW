import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
const authState = vi.hoisted(() => ({ accessToken: 'token-a' as string | null }));
const authMock = vi.hoisted(() => vi.fn((selector: (state: typeof authState) => unknown) => selector(authState)));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({ useAuthStore: authMock }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: 'en', t: (key: string) => key }) }));

import { RuntimeSettingsControl } from '@/components/admin/RuntimeSettingsControl';

const snapshot = (revision = 2) => ({
  revision,
  settings: [
    { key: 'model.primary', label: 'Основная модель', kind: 'model', value: 'deepseek-v4-flash', default: 'deepseek-v4-flash', overridden: false, choices: ['deepseek-v4-flash', 'gpt-5.6-luna'] },
    { key: 'timeout.seconds', label: 'Timeout', kind: 'number', value: 30, default: 30, overridden: false, minimum: 1, maximum: 90 },
  ],
  updated_at: '2026-10-16T08:00:00Z',
  propagation: 'next_operation',
  cache_seconds: 0,
});

const history = [{
  revision: 2,
  before: { 'timeout.seconds': 20 },
  after: { 'timeout.seconds': 30 },
  reason: 'initial change',
  created_at: '2026-10-16T08:00:00Z',
  actor_id: 'actor-1',
}];

function setupApi() {
  apiMock.get.mockImplementation((url: string) => {
    if (url === '/v1/admin/runtime-settings') return Promise.resolve({ data: snapshot() });
    if (url === '/v1/admin/runtime-settings/history') return Promise.resolve({ data: history });
    throw new Error(`Unexpected GET ${url}`);
  });
  apiMock.put.mockResolvedValue({ data: snapshot(3) });
  apiMock.post.mockResolvedValue({ data: snapshot(3) });
}

describe('runtime settings control', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.accessToken = 'token-a';
    setupApi();
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('renders model choices as a select and numeric settings as numeric inputs', async () => {
    render(<RuntimeSettingsControl />);
    expect(await screen.findByLabelText('Основная модель')).toBeInstanceOf(HTMLSelectElement);
    expect(screen.getByLabelText('Timeout')).toHaveAttribute('type', 'number');
    expect(screen.getByText('timeout.seconds · timeout')).toBeInTheDocument();
  });

  it('requires a 3..240 character reason and sends revision plus changed values', async () => {
    render(<RuntimeSettingsControl />);
    const timeout = await screen.findByLabelText('Timeout');
    fireEvent.change(timeout, { target: { value: '45' } });
    const reason = screen.getByLabelText('Reason for change (required)');
    const save = screen.getByRole('button', { name: 'Save changes' });
    fireEvent.change(reason, { target: { value: 'ab' } });
    expect(save).toBeDisabled();
    fireEvent.change(reason, { target: { value: 'abc' } });
    fireEvent.click(save);
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/v1/admin/runtime-settings', {
      revision: 2,
      changes: { 'timeout.seconds': 45 },
      reason: 'abc',
    }));
  });

  it('sends null for an explicit reset to default', async () => {
    render(<RuntimeSettingsControl />);
    const timeout = await screen.findByLabelText('Timeout');
    fireEvent.change(timeout, { target: { value: '45' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Reset to default' })[1]);
    fireEvent.change(screen.getByLabelText('Reason for change (required)'), { target: { value: 'reset' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/v1/admin/runtime-settings', {
      revision: 2,
      changes: { 'timeout.seconds': null },
      reason: 'reset',
    }));
  });

  it('preserves a draft after 409 and does not replay the save automatically', async () => {
    let settingReads = 0;
    apiMock.get.mockImplementation((url: string) => Promise.resolve({
      data: url === '/v1/admin/runtime-settings' ? snapshot(++settingReads === 1 ? 2 : 3) : history,
    }));
    apiMock.put.mockRejectedValue({ response: { status: 409, data: { code: 'revision_conflict' } } });
    render(<RuntimeSettingsControl />);
    const timeout = await screen.findByLabelText('Timeout');
    fireEvent.change(timeout, { target: { value: '45' } });
    fireEvent.change(screen.getByLabelText('Reason for change (required)'), { target: { value: 'keep draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText(/latest values were loaded/);
    expect(screen.getByLabelText('Timeout')).toHaveValue(45);
    expect(apiMock.put).toHaveBeenCalledTimes(1);
    const saveButton = screen.getByRole('button', { name: 'Save changes' });
    await waitFor(() => expect(saveButton).toBeEnabled());
    apiMock.put.mockResolvedValueOnce({ data: snapshot(4) });
    fireEvent.click(saveButton);
    await screen.findByText('Runtime settings saved.');
    expect(apiMock.put).toHaveBeenLastCalledWith('/v1/admin/runtime-settings', {
      revision: 3, changes: { 'timeout.seconds': 45 }, reason: 'keep draft',
    });
    expect(apiMock.put).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/latest values were loaded/)).not.toBeInTheDocument();
  });

  it('opens a controlled revert confirmation and does not write on cancel', async () => {
    render(<RuntimeSettingsControl />);
    await screen.findByText('#2');
    expect(screen.getByText('#1')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'restore' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
    expect(await screen.findByRole('dialog')).toHaveTextContent('Revert this snapshot?');
    expect(apiMock.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('posts the selected revision only after explicit confirmation', async () => {
    const nativeConfirm = vi.mocked(confirm);
    render(<RuntimeSettingsControl />);
    await screen.findByText('#2');
    fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'restore' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm revert' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/runtime-settings/revert', {
      revision: 2,
      target_revision: 1,
      reason: 'restore',
    }));
    expect(nativeConfirm).not.toHaveBeenCalled();
  });

  it('freezes the current revision, target revision, and reason when confirmation opens', async () => {
    render(<RuntimeSettingsControl />);
    await screen.findByText('#2');
    fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'first reason' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
    expect(await screen.findByText('Reason: first reason')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'changed after open' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm revert' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/runtime-settings/revert', {
      revision: 2,
      target_revision: 1,
      reason: 'first reason',
    }));
  });

  it('does not replay a revision conflict and permits an explicit retry', async () => {
    apiMock.post.mockRejectedValueOnce({ response: { status: 409, data: { code: 'revision_conflict' } } });
    render(<RuntimeSettingsControl />);
    await screen.findByText('#2');
    fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'retry restore' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm revert' }));
    await screen.findByText(/latest values were loaded/);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm revert' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(2));
  });

  it('disables duplicate revert confirmation while the request is pending', async () => {
    let resolvePost: ((value: unknown) => void) | undefined;
    apiMock.post.mockImplementationOnce(() => new Promise((resolve) => { resolvePost = resolve; }));
    render(<RuntimeSettingsControl />);
    await screen.findByText('#2');
    fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'restore' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
    const dialog = await screen.findByRole('dialog');
    const confirmButton = within(dialog).getByRole('button', { name: 'Confirm revert' });
    fireEvent.click(confirmButton);
    expect(confirmButton).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
    fireEvent.click(confirmButton);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(document.querySelector('[data-modal-backdrop="true"]') as Element);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    resolvePost?.({ data: snapshot(3) });
  });

  it.each(['save', 'revert'] as const)('ignores a delayed stale %s failure across an A-to-B-to-A token transition', async (operation) => {
    let rejectPost: ((reason?: unknown) => void) | undefined;
    apiMock[operation === 'save' ? 'put' : 'post'].mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectPost = reject; }));
    const view = render(<RuntimeSettingsControl />);
    await screen.findByText('#2');
    if (operation === 'revert') {
      fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'restore' } });
      fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
      fireEvent.click(await screen.findByRole('button', { name: 'Confirm revert' }));
    } else {
      fireEvent.change(screen.getByLabelText('Timeout'), { target: { value: '45' } });
      fireEvent.change(screen.getByLabelText('Reason for change (required)'), { target: { value: 'check' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    }
    authState.accessToken = 'token-b';
    view.rerender(<RuntimeSettingsControl />);
    authState.accessToken = 'token-a';
    view.rerender(<RuntimeSettingsControl />);
    await act(async () => {
      rejectPost?.(new Error('stale failure'));
      await Promise.resolve();
    });
    expect(screen.queryByText(`Could not ${operation === 'save' ? 'save' : 'revert'} runtime settings.`)).not.toBeInTheDocument();
  });

  it('shows load errors and retries without inventing a successful state', async () => {
    apiMock.get.mockRejectedValueOnce({ response: { status: 503 } });
    render(<RuntimeSettingsControl />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load runtime settings.');
    apiMock.get.mockImplementation((url: string) => url === '/v1/admin/runtime-settings' ? Promise.resolve({ data: snapshot() }) : Promise.resolve({ data: history }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Runtime settings')).toBeInTheDocument();
  });
});
