import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  AsyncOperationStatus,
  resolveAsyncOperationState,
} from '@/components/ui/AsyncOperationStatus';

const labels = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  stalled: 'Stalled',
};

describe('AsyncOperationStatus', () => {
  it('marks an active operation as stalled from its last backend update', () => {
    expect(resolveAsyncOperationState(
      {
        status: 'running',
        updated_at: '2026-07-27T10:00:00.000Z',
      },
      new Date('2026-07-27T10:02:01.000Z').getTime(),
    )).toBe('stalled');
  });

  it('does not override terminal backend states with stalled', () => {
    expect(resolveAsyncOperationState(
      {
        status: 'completed',
        updated_at: '2026-07-27T10:00:00.000Z',
      },
      new Date('2026-07-27T11:00:00.000Z').getTime(),
    )).toBe('completed');
  });

  it('offers retry for a failed operation', () => {
    const retry = vi.fn();
    render(
      <AsyncOperationStatus
        operation={{ status: 'failed', message: 'Provider unavailable' }}
        title="Course generation"
        labels={labels}
        retryLabel="Retry"
        onRetry={retry}
      />,
    );

    expect(screen.getByText('Failed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
