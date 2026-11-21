'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { type CourseLanguage } from './courseLanguages';
import { captionTime, videoPracticeCopy, type VideoPractice } from './videoPractice';
import { useYoutubeTiming, youtubeFrameProps } from './useYoutubeTiming';

export function TimedPracticeVideo({ src, title, practice, language }: {
  src: string; title: string; practice: VideoPractice; language: CourseLanguage;
}) {
  const { frame, frameUrl, playback, unavailable, command } = useYoutubeTiming(src);
  const pausedForAnswer = useRef(false);
  const question = useRef<HTMLParagraphElement>(null);
  const [noticeSide, setNoticeSide] = useState<'top' | 'bottom' | null>(null);
  const [phase, setPhase] = useState<'waiting' | 'offered' | 'answering' | 'closed'>('waiting');
  const [answer, setAnswer] = useState<number>();
  const copy = videoPracticeCopy(language);
  const translated = practice[language === 'kk' ? 'kk' : 'ru'];
  const end = Number(new URL(src).searchParams.get('end'));

  useEffect(() => {
    if (phase === 'waiting' && playback?.playing && playback.seconds >= practice.at && playback.seconds < end) {
      setPhase('offered');
    }
  }, [end, phase, playback, practice.at]);

  const offered = phase === 'offered' || (phase === 'waiting' && unavailable);

  useEffect(() => {
    const player = frame.current;
    if (!offered || !player) return;
    // Place the mobile notice in viewport space clear of the YouTube controls.
    const place = () => {
      const { top, bottom } = player.getBoundingClientRect();
      const visible = bottom > 0 && top < window.innerHeight;
      setNoticeSide(!visible ? null : (
        bottom <= window.innerHeight - 136 ? 'bottom' : top >= 192 ? 'top' : null
      ));
    };
    place();
    window.addEventListener('scroll', place, { passive: true, capture: true });
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [frame, offered]);

  useEffect(() => {
    if (phase === 'answering') question.current?.focus();
  }, [phase]);

  const open = () => {
    pausedForAnswer.current = playback?.playing === true;
    if (pausedForAnswer.current) command('pauseVideo');
    setPhase('answering');
  };

  const close = () => {
    if (pausedForAnswer.current) command('playVideo');
    pausedForAnswer.current = false;
    setPhase('closed');
    frame.current?.focus({ preventScroll: true });
  };

  const noticePlacement = {
    top: 'top-[max(4rem,env(safe-area-inset-top))]',
    bottom: 'bottom-[max(0.75rem,env(safe-area-inset-bottom))]',
  };
  const mobileNotice = offered && noticeSide
    ? 'fixed inset-x-3 z-30 shadow-lg md:static md:shadow-none ' + noticePlacement[noticeSide]
    : '';

  return <div className="space-y-3">
    <iframe ref={frame} title={title} src={frameUrl} {...youtubeFrameProps} />
    {(offered || phase === 'answering') &&
      <section className={'space-y-3 rounded-xl border border-border bg-card p-4 ' + mobileNotice} aria-label={copy.title}>
        <p className="font-semibold" aria-live="polite">{copy.title} · {captionTime(practice.at)}</p>
        {phase !== 'answering' ? <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={open}>{copy.answer}</Button>
          <Button type="button" variant="outline" onClick={close}>{copy.skip}</Button>
        </div> : <>
          <p ref={question} tabIndex={-1} className="font-medium">{translated.question}</p>
          <div className="grid gap-2">
            {translated.choices.map((choice, index) => <Button key={index} type="button"
              className="h-auto justify-start whitespace-normal text-left" variant={answer === index ? 'secondary' : 'outline'}
              disabled={answer !== undefined} onClick={() => setAnswer(index)}>{choice}</Button>)}
          </div>
          {answer !== undefined && <p role="status">
            <strong>{answer === practice.correct_index ? copy.right : copy.wrong}.</strong> {translated.explanation}
          </p>}
          <Button type="button" variant="outline" onClick={close}>{pausedForAnswer.current ? copy.continue : copy.close}</Button>
        </>}
      </section>}
  </div>;
}
