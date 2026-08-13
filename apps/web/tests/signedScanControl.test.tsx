import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api';
import { SignedScanControl, useSignedScanLedgers } from '@/features/training-evidence/SignedScanControl';

const apiMock = vi.mocked(api);
const eventId = '11111111-1111-1111-1111-111111111111';

function SignedScanHarness() {
  const state = useSignedScanLedgers([eventId], true);
  return (
    <SignedScanControl
      eventId={eventId}
      ledger={state.ledgers[eventId]}
      loading={state.loadingEventIds.has(eventId)}
      uploading={state.uploadingEventIds.has(eventId)}
      error={state.errors[eventId]}
      onRetry={() => void state.refresh(eventId)}
      onUpload={(file) => state.upload(eventId, file)}
    />
  );
}

describe('signed scan control', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads an awaiting status and refreshes it to received after a valid PDF upload', async () => {
    apiMock.get
      .mockResolvedValueOnce({ data: { event_id: eventId, status: 'awaiting_signed_copy', scans: [] } } as any)
      .mockResolvedValueOnce({
        data: {
          event_id: eventId,
          status: 'received',
          scans: [{ id: 'scan-1', original_filename: 'signed.pdf' }],
        },
      } as any);
    apiMock.post.mockResolvedValue({ data: { id: 'scan-1' } } as any);

    const { container } = render(<SignedScanHarness />);

    expect(await screen.findByText('Ожидается подписанный экземпляр')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith(`/v1/training-evidence/events/${eventId}/signed-scans`);

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: { files: [new File(['%PDF-1.7'], 'signed.pdf', { type: 'application/pdf' })] },
    });

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      `/v1/training-evidence/events/${eventId}/signed-scans`,
      expect.any(FormData),
      { headers: { 'Content-Type': 'multipart/form-data' } },
    ));
    expect(await screen.findByText('Подписанный экземпляр получен')).toBeInTheDocument();
  });

  it('blocks a file outside the accepted PDF/JPEG/PNG under-10-MB contract before upload', async () => {
    apiMock.get.mockResolvedValue({ data: { event_id: eventId, status: 'awaiting_signed_copy', scans: [] } } as any);

    const { container } = render(<SignedScanHarness />);
    await screen.findByText('Ожидается подписанный экземпляр');
    const input = container.querySelector('input[type="file"]');
    fireEvent.change(input!, {
      target: { files: [new File(['plain text'], 'signed.txt', { type: 'text/plain' })] },
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('Выберите PDF, JPEG или PNG размером до 10 МБ.');
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('blocks a PDF over the 10-MB limit before upload', async () => {
    apiMock.get.mockResolvedValue({ data: { event_id: eventId, status: 'awaiting_signed_copy', scans: [] } } as any);

    const { container } = render(<SignedScanHarness />);
    await screen.findByText('Ожидается подписанный экземпляр');
    const input = container.querySelector('input[type="file"]');
    fireEvent.change(input!, {
      target: {
        files: [new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'too-large.pdf', { type: 'application/pdf' })],
      },
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('Выберите PDF, JPEG или PNG размером до 10 МБ.');
    expect(apiMock.post).not.toHaveBeenCalled();
  });
});
