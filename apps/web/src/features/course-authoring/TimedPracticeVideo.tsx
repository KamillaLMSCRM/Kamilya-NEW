'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { type CourseLanguage } from './courseLanguages';
import { captionTime, videoPracticeCopy, type VideoPractice } from './videoPractice';

const youtubeOrigin = 'https://www.youtube-nocookie.com';

export const youtubeFrameProps = {
  className: 'block aspect-video min-h-[200px] w-full rounded-lg border border-border bg-black',
  allow: 'fullscreen; picture-in-picture; encrypted-media',
  referrerPolicy: 'strict-origin-when-cross-origin',
} as const;

export function TimedPracticeVideo({ src, title, practice, language }: {
  src: string; title: string; practice: VideoPractice; language: CourseLanguage;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const playerState = useRef<number>();
  const channel = useId();
  const pausedForAnswer = useRef(false);
  const [phase, setPhase] = useState<'waiting' | 'offered' | 'answering' | 'closed'>('waiting');
  const [answer, setAnswer] = useState<number>();
  const [unavailable, setUnavailable] = useState(false);
  const copy = videoPracticeCopy(language);
  const translated = practice[language === 'kk' ? 'kk' : 'ru'];
  const at = practice.at;
  const target = new URL(src);
  target.searchParams.set('enablejsapi', '1');
  if (typeof window !== 'undefined') target.searchParams.set('origin', window.location.origin);

  useEffect(() => {
    // Keep player code inside the existing third-party iframe. If its widget
    // messaging changes or is blocked, the optional question can open manually.
    let connected = false;
    const listen = () => {
      if (!connected) frame.current?.contentWindow?.postMessage(
        JSON.stringify({ event: 'listening', id: channel, channel: 'widget' }), youtubeOrigin,
      );
    };
    const receive = (event: MessageEvent) => {
      if (event.origin !== youtubeOrigin || event.source !== frame.current?.contentWindow || typeof event.data !== 'string') return;
      let payload;
      try { payload = JSON.parse(event.data); } catch { return; }
      if (!payload || (payload.event !== 'infoDelivery' && payload.event !== 'initialDelivery')) return;
      const { currentTime, playerState: currentState } = payload.info ?? {};
      if (typeof currentState === 'number') playerState.current = currentState;
      if (!connected) { connected = true; setUnavailable(false); }
      if (playerState.current === 1 && typeof currentTime === 'number' && Number.isFinite(currentTime) && currentTime >= at) {
        setPhase(value => value === 'waiting' ? 'offered' : value);
      }
    };
    window.addEventListener('message', receive);
    const handshake = window.setInterval(listen, 300);
    const deadline = window.setTimeout(() => {
      if (!connected) setUnavailable(true);
      window.clearInterval(handshake);
    }, 12000);
    listen();
    return () => {
      window.removeEventListener('message', receive);
      window.clearTimeout(deadline);
      window.clearInterval(handshake);
    };
  }, [at, channel, src]);

  const command = (func: 'pauseVideo' | 'playVideo') => frame.current?.contentWindow?.postMessage(
    JSON.stringify({ event: 'command', func, args: [], id: channel, channel: 'widget' }), youtubeOrigin,
  );
  const open = () => {
    pausedForAnswer.current = playerState.current === 1;
    if (pausedForAnswer.current) command('pauseVideo');
    setPhase('answering');
  };
  const close = () => {
    if (pausedForAnswer.current) command('playVideo');
    pausedForAnswer.current = false;
    setPhase('closed');
  };

  return <div className="space-y-3">
    <iframe ref={frame} title={title} src={target.href} {...youtubeFrameProps} />
    {(phase === 'offered' || phase === 'answering' || (phase === 'waiting' && unavailable)) &&
      <section className="space-y-3 rounded-xl border border-border bg-card p-4" aria-label={copy.title}>
        <p className="font-semibold" aria-live="polite">{copy.title} · {captionTime(at)}</p>
        {phase !== 'answering' ? <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={open}>{copy.answer}</Button>
          <Button type="button" variant="outline" onClick={close}>{copy.skip}</Button>
        </div> : <>
          <p className="font-medium">{translated.question}</p>
          <div className="grid gap-2">
            {translated.choices.map((choice, index) => <Button key={index} type="button"
              className="h-auto justify-start whitespace-normal text-left" variant={answer === index ? 'secondary' : 'outline'}
              disabled={answer !== undefined} onClick={() => setAnswer(index)}>{choice}</Button>)}
          </div>
          {answer !== undefined && <p role="status">
            <strong>{answer === practice.correct_index ? copy.right : copy.wrong}.</strong> {translated.explanation}
          </p>}
          <Button type="button" variant="outline" onClick={close}>{copy.continue}</Button>
        </>}
      </section>}
  </div>;
}
