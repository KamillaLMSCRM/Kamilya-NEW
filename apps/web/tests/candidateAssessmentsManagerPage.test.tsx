import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));
import CandidateAssessmentsPage from '@/app/candidate-assessments/page';

describe('candidate assessments manager page', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    apiMock.get.mockImplementation((url: string) => Promise.resolve({ data: url.includes('/courses?')
      ? [{ id: 'c1', title: 'Кассовая дисциплина', status: 'published', current_release_id: 'r1' }, { id: 'c2', title: 'Черновик', status: 'published', current_release_id: null }]
      : [{ id: 'campaign', title: 'Кассир', status: 'active', expires_at: '2030-01-01T00:00:00Z' }] }));
    apiMock.post.mockResolvedValue({ data: { access_url: 'https://app.test/candidate-assessment/token', temporary_pin: '123456' } });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it('uses a released course selector and permits manual name-only invitation', async () => {
    render(<CandidateAssessmentsPage />);
    expect(await screen.findByRole('option', { name: 'Кассовая дисциплина' })).toHaveValue('r1');
    expect(screen.queryByRole('option', { name: 'Черновик' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/ID опубликованного релиза/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Имя кандидата'), { target: { value: 'Алия Садыкова' } });
    fireEvent.click(screen.getByRole('button', { name: 'Пригласить' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/candidate-assessments/campaign/candidates', {
      first_name: 'Алия', last_name: 'Садыкова', email: null, phone: null,
    }));
    expect(await screen.findByText(/PIN: 123456/)).toBeInTheDocument();
  });

  it('explains when the selected published release has no approved questions', async () => {
    apiMock.post.mockRejectedValueOnce({
      response: { data: { message: 'Release has no approved assessment questions' } },
    });
    render(<CandidateAssessmentsPage />);
    await screen.findByRole('option', { name: 'Кассовая дисциплина' });
    fireEvent.change(screen.getByLabelText('Название кампании'), { target: { value: 'Проверка кассира' } });
    fireEvent.change(screen.getByLabelText('Опубликованный курс'), { target: { value: 'r1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'В опубликованной версии курса нет одобренных вопросов. Проверьте тесты и опубликуйте новую версию курса.',
    );
  });
});
