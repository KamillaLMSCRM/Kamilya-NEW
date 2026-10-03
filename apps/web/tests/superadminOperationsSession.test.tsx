import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SuperadminOperationsPage from '@/app/admin/super/operations/page';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));

const summary = {
  generated_at: '2026-10-03T00:00:00Z',
  ai_jobs: { queued_count: 0, running_count: 0, failed_count: 0, oldest_queued_age_seconds: null },
  documents: { indexing_count: 0, failed_index_count: 0, failed_embedding_count: 0, cleanup_pending_count: 0, cleanup_failed_count: 0, oldest_indexing_age_seconds: null },
  database: {}, process: {}, host: {}, filesystem: {},
  celery: { status: 'unavailable', reachable: false, worker_count: 0, registered_required_tasks: [], missing_required_tasks: [] },
  crm_lead_outbox: { pending_count: 0, retry_count: 0, claimed_count: 0, dead_count: 0, delivered_count: 0, oldest_due_age_seconds: null },
};

describe('operations session-aware component transport', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ accessToken: 'expired-synthetic-token' });
    apiMock.get.mockResolvedValue({ data: summary });
    apiMock.post.mockImplementation(async (url: string) => ({ data: url.endsWith('cleanup-synthetic')
      ? { dry_run: true, matched_count: 0, allowed_slug_prefixes: ['synthetic-'], results: [] }
      : { dry_run: true, eligible_count: 0, truncated: false } }));
  });

  it('binds all preview requests to exact v1 paths and does not rerun on token refresh', async () => {
    render(<SuperadminOperationsPage />);
    await screen.findByRole('heading', { name: 'AI-задачи' });
    expect(apiMock.get).toHaveBeenCalledWith('/v1/admin/super/operations/summary');
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(3));
    expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/super/operations/cleanup-synthetic', { dry_run: true, min_age_hours: 24 });
    expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/super/operations/recover-stale-ai-jobs', { dry_run: true, min_age_hours: 24 });
    expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/super/operations/requeue-failed-crm-leads', { dry_run: true, limit: 20 });
    expect(screen.getByRole('button', { name: 'Перейти к удалению' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Отменить зависшие задачи' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Вернуть в очередь' })).toBeDisabled();
    act(() => useAuthStore.setState({ accessToken: 'refreshed-synthetic-token' }));
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    expect(apiMock.post).toHaveBeenCalledTimes(3);
    expect(apiMock.post.mock.calls.every(([, body]) => body.dry_run === true && !body.confirm)).toBe(true);
  });
});
