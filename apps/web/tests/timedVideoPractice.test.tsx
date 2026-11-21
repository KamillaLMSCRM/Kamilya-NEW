import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TimedPracticeVideo } from '@/features/course-authoring/TimedPracticeVideo';
import type { VideoPractice } from '@/features/course-authoring/videoPractice';

const origin = 'https://www.youtube-nocookie.com';
const src = origin + '/embed/fzSDieqvIyk?start=100&end=180';
const practice: VideoPractice = {
  at: 130,
  correct_index: 1,
  ru: { question: 'Что регулирует преобразователь?', choices: ['Давление', 'Частоту', 'Трубу'], explanation: 'Частоту вращения.' },
  kk: { question: 'Түрлендіргіш нені реттейді?', choices: ['Қысымды', 'Жиілікті', 'Құбырды'], explanation: 'Айналу жиілігін.' },
};

function playback(currentTime: number, emitter: Window, reportedOrigin = origin, playerState = 1) {
  act(() => {
    window.dispatchEvent(new MessageEvent('message', {
      origin: reportedOrigin, source: emitter,
      data: JSON.stringify({ event: 'infoDelivery', info: { currentTime, playerState } }),
    }));
  });
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('optional practice in a timed YouTube lesson', () => {
  it('opens on playback time without pausing, then preserves the answer when the language changes', () => {
    const component = render(<TimedPracticeVideo src={src} title="Video" practice={practice} language="ru" />);
    const source = (screen.getByTitle('Video') as HTMLIFrameElement).contentWindow!;
    const send = vi.spyOn(source, 'postMessage');
    playback(130, window);
    playback(130, source, 'https://example.test');
    playback(129, source);
    expect(screen.queryByRole('button', { name: 'Ответить' })).not.toBeInTheDocument();
    playback(130, source);
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Ответить' }));
    expect(send).toHaveBeenCalledWith(expect.stringContaining('pauseVideo'), origin);
    fireEvent.click(screen.getByRole('button', { name: 'Частоту' }));
    expect(screen.getByRole('status')).toHaveTextContent('Верно. Частоту вращения.');
    component.rerender(<TimedPracticeVideo src={src} title="Бейне" practice={practice} language="kk" />);
    expect(screen.getByText(practice.kk.question)).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Дұрыс. Айналу жиілігін.');
    fireEvent.click(screen.getByRole('button', { name: 'Бейнені жалғастыру' }));
    expect(send).toHaveBeenLastCalledWith(expect.stringContaining('playVideo'), origin);
    playback(140, source);
    expect(screen.queryByRole('button', { name: 'Жауап беру' })).not.toBeInTheDocument();
  });

  it('offers during forward playback after a seek and skip sends no player commands', () => {
    render(<TimedPracticeVideo src={src} title="Video" practice={practice} language="ru" />);
    const source = (screen.getByTitle('Video') as HTMLIFrameElement).contentWindow!;
    const send = vi.spyOn(source, 'postMessage');
    playback(140, source, origin, 2);
    playback(180, source);
    expect(screen.queryByRole('button', { name: 'Ответить' })).not.toBeInTheDocument();
    playback(140, source);
    fireEvent.click(screen.getByRole('button', { name: 'Пропустить' }));
    expect(send).not.toHaveBeenCalled();
    playback(150, source);
    expect(screen.queryByRole('button', { name: 'Ответить' })).not.toBeInTheDocument();
  });

  it('offers a manual, skippable question when the iframe supplies no timing', () => {
    vi.useFakeTimers();
    render(<TimedPracticeVideo src={src} title="Video" practice={practice} language="ru" />);
    act(() => vi.advanceTimersByTime(12000));
    fireEvent.click(screen.getByRole('button', { name: 'Пропустить' }));
    expect(screen.queryByRole('button', { name: 'Ответить' })).not.toBeInTheDocument();
  });
});
