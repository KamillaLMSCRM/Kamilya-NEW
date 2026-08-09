import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useParams: () => ({ token: 'opaque' }) }));
import CandidateAssessmentPage from '@/app/candidate-assessment/[token]/page';

describe('candidate assessment public flow', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('requires consent and submits without showing correct answers', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: 'capability', attempt_id: 'a1', title: 'Оценка', instructions: 'Инструкция', assessment: { quizzes: [{ questions: [
        { id: 'q1', text: 'Один ответ', type: 'single_choice', choices: [{ id: 'c1', text: 'Ответ' }] },
        { id: 'q2', text: 'Несколько ответов', type: 'multiple_choice', choices: [{ id: 'c2', text: 'Вариант 1' }, { id: 'c3', text: 'Вариант 2' }] },
      ] }] } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ score_percent: 100, passed: true }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<CandidateAssessmentPage />);
    fireEvent.change(screen.getByLabelText('PIN'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Открыть оценку' }));
    expect(await screen.findByText(/Один ответ/)).toBeInTheDocument();
    expect(screen.queryByText(/правиль/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio'));
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ответы' }));
    await waitFor(() => expect(screen.getByText('Результат: 100%')).toBeInTheDocument());
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe('Bearer capability');
    expect(fetchMock.mock.calls[1][1].body).toContain('"selected_choice_ids":["c2","c3"]');
  });
});
