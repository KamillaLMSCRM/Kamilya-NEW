import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useIdleTimeout } from '@/lib/useIdleTimeout';

describe('useIdleTimeout', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('warns before expiry and calls timeout once at the deadline', () => {
    vi.useFakeTimers();
    const onTimeout = vi.fn();
    const { result } = renderHook(() => useIdleTimeout({
      idleMs: 5_000,
      warningMs: 1_000,
      onTimeout,
    }));

    act(() => vi.advanceTimersByTime(4_000));
    expect(result.current.warningSeconds).toBe(1);
    expect(onTimeout).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1_000));
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });

  it('resets the deadline after user activity', () => {
    vi.useFakeTimers();
    const onTimeout = vi.fn();
    renderHook(() => useIdleTimeout({ idleMs: 5_000, warningMs: 1_000, onTimeout }));

    act(() => vi.advanceTimersByTime(4_500));
    act(() => window.dispatchEvent(new Event('pointerdown')));
    act(() => vi.advanceTimersByTime(4_999));
    expect(onTimeout).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });
});
