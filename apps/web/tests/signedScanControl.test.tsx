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
      reviewingScanIds={state.reviewingScanIds}
      onReview={(scanId, action, reason) => state.review(eventId, scanId, action, reason)}
    />
  );
}

describe('signed scan control', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads an awaiting status and refreshes it to pending review after a valid PDF upload', async () => {
    apiMock.get
      .mockResolvedValueOnce({ data: { event_id: eventId, status: 'awaiting_return', scans: [] } } as any)
      .mockResolvedValueOnce({
        data: {
          event_id: eventId,
          status: 'uploaded_pending_review',
          scans: [{ id: 'scan-1', original_filename: 'signed.pdf', content_type: 'application/pdf', uploaded_at: '2026-09-16T10:00:00Z', status: 'uploaded_pending_review' }],
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
    expect(await screen.findByText('Загружен — ожидает проверки')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Принять' })).toBeInTheDocument();
  });

  it('blocks a file outside the accepted PDF/JPEG/PNG under-10-MB contract before upload', async () => {
    apiMock.get.mockResolvedValue({ data: { event_id: eventId, status: 'awaiting_return', scans: [] } } as any);

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
    apiMock.get.mockResolvedValue({ data: { event_id: eventId, status: 'awaiting_return', scans: [] } } as any);

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

  it('lets a methodologist accept a pending scan and refreshes the ledger', async () => {
    const pendingScan = {
      id: 'scan-1',
      original_filename: 'signed.pdf',
      content_type: 'application/pdf',
      uploaded_at: '2026-09-16T10:00:00Z',
      status: 'uploaded_pending_review',
    };
    apiMock.get
      .mockResolvedValueOnce({ data: { event_id: eventId, status: 'uploaded_pending_review', scans: [pendingScan] } } as any)
      .mockResolvedValueOnce({ data: { event_id: eventId, status: 'accepted', scans: [{ ...pendingScan, status: 'accepted' }] } } as any);
    apiMock.post.mockResolvedValue({ data: { status: 'accepted' } } as any);

    render(<SignedScanHarness />);
    fireEvent.click(await screen.findByRole('button', { name: 'Принять' }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      `/v1/training-evidence/events/${eventId}/signed-scans/scan-1/review`,
      { action: 'accept', reason: null },
    ));
    expect(await screen.findByText('Подписанный экземпляр принят')).toBeInTheDocument();
  });
});
