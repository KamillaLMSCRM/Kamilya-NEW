import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
  createObjectURL: vi.fn(() => 'blob:certificate'),
  revokeObjectURL: vi.fn(),
  t: (key: string) => key,
}));

vi.mock('next/link', () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) => selector({ accessToken: 'test-token' }),
}));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: 'en-US', t: mocks.t }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: mocks.error, success: mocks.success } }));

import CertificatesPage from '@/app/certificates/page';

const certificate = {
  id: 'cert-1',
  course_id: 'course-1',
  certificate_number: 'KML-2026-41482FABAE33',
  issued_at: '2026-10-12T00:00:00Z',
  expires_at: null,
  status: 'active',
  user_name: 'Learner',
  course_title: 'Warehouse safety',
};

describe('certificate download', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test');
    vi.stubGlobal('fetch', mocks.fetch);
    Object.defineProperty(window.URL, 'createObjectURL', { configurable: true, value: mocks.createObjectURL });
    Object.defineProperty(window.URL, 'revokeObjectURL', { configurable: true, value: mocks.revokeObjectURL });
    mocks.fetch.mockImplementation((input: string) => {
      if (input.endsWith('/v1/certificates')) return Promise.resolve({ ok: true, json: async () => [certificate] });
      return Promise.resolve({ ok: true, blob: async () => new Blob(['%PDF-1.7'], { type: 'application/pdf' }) });
    });
  });

  it('requests direct PDF bytes and creates a download only after success', async () => {
    const blob = new Blob(['%PDF-1.7'], { type: 'application/pdf' });
    mocks.fetch.mockImplementation((input: string) =>
      input.endsWith('/v1/certificates')
        ? Promise.resolve({ ok: true, json: async () => [certificate] })
        : Promise.resolve({ ok: true, blob: async () => blob }),
    );
    render(<CertificatesPage />);
    const button = await screen.findByRole('button', { name: 'common.download' });

    fireEvent.click(button);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2));
    expect(mocks.fetch.mock.calls[1][0]).toBe(
      'https://api.example.test/v1/certificates/cert-1/download?direct=true',
    );
    expect(mocks.fetch.mock.calls[1][1]).toEqual({ headers: { Authorization: 'Bearer test-token' } });
    expect(mocks.createObjectURL).toHaveBeenCalledWith(blob);
    expect(mocks.success).toHaveBeenCalledWith('certificates.downloaded');
  });

  it('keeps the download retryable and does not create a file on failure', async () => {
    mocks.fetch.mockImplementation((input: string) =>
      input.endsWith('/v1/certificates')
        ? Promise.resolve({ ok: true, json: async () => [certificate] })
        : Promise.resolve({ ok: false, status: 500 }),
    );
    render(<CertificatesPage />);
    const button = await screen.findByRole('button', { name: 'common.download' });

    fireEvent.click(button);
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith('certificates.downloadFailed'));
    expect(mocks.createObjectURL).not.toHaveBeenCalled();
    expect(button).not.toBeDisabled();
  });
});
