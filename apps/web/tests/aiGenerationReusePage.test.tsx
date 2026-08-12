import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());
const startJobMock = vi.hoisted(() => vi.fn());
const restoreActiveJobMock = vi.hoisted(() => vi.fn());
const refreshJobMock = vi.hoisted(() => vi.fn());
const cancelJobMock = vi.hoisted(() => vi.fn());
const prepareRetryMock = vi.hoisted(() => vi.fn());

vi.mock('@/lib/api', () => ({
  api: { get: getMock, post: postMock },
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: 'test-token' }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => key,
    tp: (_key: string, count: number) => String(count),
  }),
}));
vi.mock('@/components/ui/Toast', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));
vi.mock('@/features/ai-generation/useGenerationWorkflow', () => ({
  useGenerationWorkflow: () => ({
    currentJob: null,
    step: 'documents',
    restoreActiveJob: restoreActiveJobMock,
    startJob: startJobMock,
    refreshJob: refreshJobMock,
    cancelJob: cancelJobMock,
    prepareRetry: prepareRetryMock,
  }),
}));

import AIGeneratePage from '@/app/ai/generate/page';

describe('AI generation repeated-source page flow', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    startJobMock.mockReset();
    restoreActiveJobMock.mockReset();
    refreshJobMock.mockReset();
    cancelJobMock.mockReset();
    prepareRetryMock.mockReset();
    getMock.mockResolvedValue({
      data: {
        items: [
          {
            id: 'document-1',
            title: 'Правила ИБ',
            filename: 'ib.pdf',
            content_type: 'application/pdf',
            size: 100,
            description: '',
            index: { status: 'ready', message: null },
          },
        ],
        page: { has_more: false },
      },
    });
    postMock.mockImplementation((url: string, body: Record<string, unknown>) => {
      if (url === '/v1/ai/document-compatibility') {
        return Promise.resolve({
          data: {
            status: 'compatible',
            score: 1,
            requires_decision: false,
            clusters: [],
          },
        });
      }
      if (url === '/v1/ai/generate-course' && !body.reuse_reason) {
        return Promise.reject({
          response: {
            status: 409,
            data: {
              details: {
                code: 'source_documents_already_used',
                existing_courses: [
                  { id: 'course-1', title: 'Действующий курс по ИБ', status: 'published' },
                ],
              },
            },
          },
        });
      }
      if (url === '/v1/ai/generate-course') {
        return Promise.resolve({ data: { id: 'job-2', status: 'pending' } });
      }
      throw new Error(`Unexpected POST ${url}`);
    });
  });

  it('retries the 409 generation request only after the methodologist selects a reason', async () => {
    render(<AIGeneratePage />);

    fireEvent.click(await screen.findByRole('checkbox', { name: 'Выбрать документ Правила ИБ' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/ai/document-compatibility', {
        documents: ['document-1'],
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: /ai.generate/ }));
    expect(await screen.findByRole('dialog', { name: 'Источник уже использован' })).toBeInTheDocument();
    expect(screen.getByText('Действующий курс по ИБ')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: 'Другая аудитория' }));
    fireEvent.click(screen.getByRole('button', { name: 'Создать независимый курс' }));

    await waitFor(() => {
      const generationCalls = postMock.mock.calls.filter(
        ([url]) => url === '/v1/ai/generate-course',
      );
      expect(generationCalls).toHaveLength(2);
      expect(generationCalls[1][1]).toMatchObject({
        documents: ['document-1'],
        reuse_reason: 'different_audience',
      });
    });
    expect(startJobMock).toHaveBeenCalledWith({ id: 'job-2', status: 'pending' });
    expect(screen.queryByRole('dialog', { name: 'Источник уже использован' })).not.toBeInTheDocument();
  });
});
