import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
const authState = vi.hoisted(() => ({ accessToken: 'token-a' as string | null }));
const authMock = vi.hoisted(() => vi.fn((selector: (state: typeof authState) => unknown) => selector(authState)));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({ useAuthStore: authMock }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: 'en' }) }));

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
    apiMock.put.mockRejectedValue({ response: { status: 409, data: { code: 'revision_conflict' } } });
    render(<RuntimeSettingsControl />);
    const timeout = await screen.findByLabelText('Timeout');
    fireEvent.change(timeout, { target: { value: '45' } });
    fireEvent.change(screen.getByLabelText('Reason for change (required)'), { target: { value: 'keep draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText(/latest values were loaded/);
    expect(screen.getByLabelText('Timeout')).toHaveValue(45);
    expect(apiMock.put).toHaveBeenCalledTimes(1);
  });

  it('offers revision 1 and posts an explicit revert target', async () => {
    render(<RuntimeSettingsControl />);
    await screen.findByText('#2');
    expect(screen.getByText('#1')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Reason for reverting (required)'), { target: { value: 'restore' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Revert' })[0]);
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/runtime-settings/revert', {
      revision: 2,
      target_revision: 1,
      reason: 'restore',
    }));
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
