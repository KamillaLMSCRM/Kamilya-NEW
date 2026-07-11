'use client';

import { useEffect, useRef, useState } from 'react';

interface IdleTimeoutOptions {
  enabled?: boolean;
  idleMs?: number;
  warningMs?: number;
  onTimeout: () => void;
}

/**
 * Shared-device timeout. Activity listeners are stable and transient timer
 * values stay in refs, so typing or moving the pointer does not rerender the
 * whole learning screen.
 */
export function useIdleTimeout({
  enabled = true,
  idleMs = 5 * 60 * 1000,
  warningMs = 60 * 1000,
  onTimeout,
}: IdleTimeoutOptions) {
  const onTimeoutRef = useRef(onTimeout);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const warningTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [warningSeconds, setWarningSeconds] = useState<number | null>(null);

  useEffect(() => {
    onTimeoutRef.current = onTimeout;
  }, [onTimeout]);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;

    const clearTimers = () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      if (warningTimeoutRef.current) clearTimeout(warningTimeoutRef.current);
      if (intervalRef.current) clearInterval(intervalRef.current);
      timeoutRef.current = null;
      warningTimeoutRef.current = null;
      intervalRef.current = null;
      setWarningSeconds(null);
    };

    const start = () => {
      clearTimers();
      const warningDelay = Math.max(0, idleMs - warningMs);
      warningTimeoutRef.current = setTimeout(() => {
        const deadline = Date.now() + warningMs;
        const tick = () => {
          const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
          setWarningSeconds(seconds);
        };
        tick();
        intervalRef.current = setInterval(tick, 1000);
      }, warningDelay);
      timeoutRef.current = setTimeout(() => {
        clearTimers();
        onTimeoutRef.current();
      }, idleMs);
    };

    const activityEvents: Array<keyof WindowEventMap> = [
      'pointerdown',
      'keydown',
      'touchstart',
      'focus',
    ];
    activityEvents.forEach((event) => window.addEventListener(event, start, { passive: true }));
    document.addEventListener('visibilitychange', start);
    start();

    return () => {
      activityEvents.forEach((event) => window.removeEventListener(event, start));
      document.removeEventListener('visibilitychange', start);
      clearTimers();
    };
  }, [enabled, idleMs, warningMs]);

  return { warningSeconds };
}
