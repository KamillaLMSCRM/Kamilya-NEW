import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), error: vi.fn(),
  t: (key: string) => key,
  create: vi.fn(() => 'blob:validated-pdf'), revoke: vi.fn(),
}));
vi.mock('@/lib/api', () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: mocks.t }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: mocks.error, success: vi.fn() } }));
vi.mock('@/components/PdfPreview', () => ({
  default: ({ blob, title }: { blob: Blob; title: string }) => <div data-testid="pdf-canvas-preview" data-type={blob.type} aria-label={title} />,
}));
import CertificateSettingsPage from '@/app/admin/certificates/settings/page';
import TrainingEvidenceFormSettingsPage from '@/app/admin/training-evidence/settings/page';

describe.each([
  ['certificate', CertificateSettingsPage, '/v1/certificates/settings/preview'],
  ['training evidence', TrainingEvidenceFormSettingsPage, '/v1/training-evidence/form-settings/preview'],
] as const)('%s admin preview', (_, Page, endpoint) => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: {} });
    mocks.post.mockResolvedValue({ data: new Blob(['%PDF-1.7\npreview'], { type: 'application/pdf' }) });
    vi.stubGlobal('URL', { createObjectURL: mocks.create, revokeObjectURL: mocks.revoke });
  });

  it('passes a validated PDF from the actual endpoint to the canvas preview, never an iframe', async () => {
    const { container } = render(<Page />);
    await waitFor(() => expect(mocks.post.mock.calls.some(([path]) => path === endpoint)).toBe(true));
    await waitFor(() => expect(screen.getByTestId('pdf-canvas-preview')).toHaveAttribute('data-type', 'application/pdf'));
    expect(container.querySelector('iframe')).toBeNull();
  });

  it('does not create an iframe URL for an HTML response with a PDF MIME type', async () => {
    mocks.post.mockResolvedValue({ data: new Blob(['<html>upstream error</html>'], { type: 'application/pdf' }) });
    const { container } = render(<Page />);
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    await waitFor(() => {
      expect(screen.queryByText('certificateSettings.previewFailed') || mocks.error.mock.calls.length).toBeTruthy();
    });
    expect(mocks.create).not.toHaveBeenCalled();
    expect(container.querySelector('iframe')).toBeNull();
  });
});
