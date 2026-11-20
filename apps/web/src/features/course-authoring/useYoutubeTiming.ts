'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';

const youtubeOrigin = 'https://www.youtube-nocookie.com';

export const youtubeFrameProps = {
  className: 'block aspect-video min-h-[200px] w-full rounded-lg border border-border bg-black',
  allow: 'fullscreen; picture-in-picture; encrypted-media',
  referrerPolicy: 'strict-origin-when-cross-origin',
} as const;

type Playback = { seconds: number; playing: boolean };

export function useYoutubeTiming(src: string) {
  const frame = useRef<HTMLIFrameElement>(null);
  const channel = useId();
  const [origin, setOrigin] = useState<string>();
  const [playback, setPlayback] = useState<Playback>();
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => { setOrigin(window.location.origin); }, []);
  const frameUrl = useMemo(() => {
    if (!origin) return undefined;
    const url = new URL(src);
    url.searchParams.set('enablejsapi', '1');
    url.searchParams.set('origin', origin);
    return url.href;
  }, [src, origin]);

  useEffect(() => {
    if (!origin) return;
    let connected = false;
    let playerState: number | undefined;
    let currentTime: number | undefined;
    const listen = () => frame.current?.contentWindow?.postMessage(
      JSON.stringify({ event: 'listening', id: channel, channel: 'widget' }), youtubeOrigin,
    );
    const receive = (event: MessageEvent) => {
      if (event.origin !== youtubeOrigin || event.source !== frame.current?.contentWindow || typeof event.data !== 'string') return;
      let payload;
      try { payload = JSON.parse(event.data); } catch { return; }
      if (payload?.event !== 'infoDelivery' && payload?.event !== 'initialDelivery') return;
      const { currentTime: seconds, playerState: state } = payload.info ?? {};
      if (typeof state === 'number') playerState = state;
      if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds >= 0) currentTime = seconds;
      if (currentTime === undefined || playerState === undefined) return;
      if (!connected) {
        connected = true;
        window.clearInterval(handshake);
        setUnavailable(false);
      }
      setPlayback({ seconds: currentTime, playing: playerState === 1 });
    };
    setPlayback(undefined);
    setUnavailable(false);
    window.addEventListener('message', receive);
    const handshake = window.setInterval(listen, 300);
    const deadline = window.setTimeout(() => {
      if (!connected) setUnavailable(true);
      window.clearInterval(handshake);
    }, 12000);
    listen();
    return () => {
      window.removeEventListener('message', receive);
      window.clearInterval(handshake);
      window.clearTimeout(deadline);
    };
  }, [channel, frameUrl, origin]);

  const command = (func: 'pauseVideo' | 'playVideo') => frame.current?.contentWindow?.postMessage(
    JSON.stringify({ event: 'command', func, args: [], id: channel, channel: 'widget' }), youtubeOrigin,
  );

  return { frame, frameUrl, playback, unavailable, command };
}
