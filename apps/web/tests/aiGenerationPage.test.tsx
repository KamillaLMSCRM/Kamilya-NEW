import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AIGeneratePage from '@/app/ai/generate/page';
import { api } from '@/lib/api';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

const apiMock = vi.mocked(api);
const activeJob = {
  id: 'job-1', status: 'running', course_id: 'course-1', created_at: '2026-08-07T08:00:00Z',
  updated_at: new Date().toISOString(), progress: 35, stage: 'content_generation', message: '',
  queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: null, tenant_active_limit: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  localStorage.setItem('ai_active_job_id', activeJob.id);
  apiMock.get.mockImplementation(async (url: string) => {
    if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
    if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: activeJob } as any;
    throw new Error(`Unexpected GET ${url}`);
  });
  apiMock.post.mockResolvedValue({ data: {} } as any);
});

describe('/ai/generate job workflow parity', () => {
  it('restores an active job and returns to the documents view after cancellation', async () => {
    render(<AIGeneratePage />);

    expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/jobs/job-1/cancel'));
    await waitFor(() => expect(screen.queryByText('Прогресс генерации')).not.toBeInTheDocument());
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
    expect(screen.getByText(/Перетащите документы/)).toBeInTheDocument();
  });
});
