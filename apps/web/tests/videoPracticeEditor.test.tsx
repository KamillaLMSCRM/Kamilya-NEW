import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { VideoPracticeEditor } from '@/features/course-authoring/VideoPracticeEditor';
import { parseCaptionTime, type PracticeState } from '@/features/course-authoring/videoPractice';

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock('@/lib/api', () => ({ api }));

const player = vi.hoisted(() => ({ seconds: 180 }));
vi.mock('@/features/course-authoring/useYoutubeTiming', () => ({
  youtubeFrameProps: {},
  useYoutubeTiming: (src: string) => ({ frameUrl: src, playback: { seconds: player.seconds, playing: false } }),
}));
const fixture: PracticeState = {
  clip: { video_id: 'fzSDieqvIyk', start: 100, end: 180 },
  revision: 4, pending: false, proposal: null, error: null,
  approved: {
    at: 130, correct_index: 1,
    ru: { question: 'Что измеряют?', choices: ['Расход', 'Давление', 'Ток'], explanation: 'Показание манометра.' },
    kk: { question: 'Нені өлшейді?', choices: ['Шығын', 'Қысым', 'Ток'], explanation: 'Манометрдің көрсеткіші.' },
  },
};

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  player.seconds = 180;
});

describe('video practice authoring', () => {
  it('preserves the draft on language switching and saves the exact preview time within the clip', async () => {
    api.get.mockResolvedValue({ data: fixture });
    api.put.mockResolvedValue({ data: fixture });
    const editor = <VideoPracticeEditor courseId="course" lessonId="lesson" lang="ru" disabled={false} />;
    const { rerender } = render(editor);
    const input = await screen.findByLabelText('Таймкод (мин:сек)');
    const takeTime = screen.getByRole('button', { name: 'Взять текущий момент' });
    const save = screen.getByRole('button', { name: 'Показать в уроке' });
    expect(input).toHaveValue('2:10');
    expect(takeTime).toBeDisabled();
    player.seconds = 145.8;
    rerender(<VideoPracticeEditor courseId="course" lessonId="lesson" lang="ru" disabled={false} />);
    expect(takeTime).toBeEnabled();
    fireEvent.click(takeTime);
    expect(input).toHaveValue('2:25');

    fireEvent.change(screen.getByLabelText('Вопрос'), { target: { value: 'Что измеряет манометр?' } });
    fireEvent.change(screen.getByLabelText('Язык вопроса'), { target: { value: 'kk' } });
    expect(screen.getByLabelText('Вопрос')).toHaveValue('Нені өлшейді?');
    fireEvent.change(input, { target: { value: '3:00' } });
    expect(save).toBeDisabled();
    fireEvent.change(input, { target: { value: '2:25' } });
    fireEvent.click(save);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      '/v1/courses/course/lessons/lesson/video-practice/editor',
      { clip: fixture.clip, revision: 4, practice: {
        ...fixture.approved, at: 145, ru: { ...fixture.approved?.ru, question: 'Что измеряет манометр?' },
      } },
    ));
    expect(api.post).not.toHaveBeenCalled();
  });

  it('creates and cancels a manual draft without calling the model or altering stored practice', async () => {
    api.get.mockResolvedValue({ data: { ...fixture, approved: null } });
    render(<VideoPracticeEditor courseId="course" lessonId="lesson" lang="ru" disabled={false} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Добавить вопрос' }));
    const input = screen.getByLabelText('Таймкод (мин:сек)');
    expect(input).toHaveValue('');
    fireEvent.change(input, { target: { value: '2:25' } });
    expect(screen.getByRole('button', { name: 'Показать в уроке' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(screen.queryByTitle('Предпросмотр видео')).not.toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('accepts elapsed minutes beyond one hour and rejects invalid timecodes', () => {
    expect(parseCaptionTime(' 65:02 ')).toBe(3902);
    expect(parseCaptionTime('1:60')).toBeNull();
    expect(parseCaptionTime('2:5')).toBeNull();
  });
});
