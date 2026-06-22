import { renderHook, act } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"

import { useDebounce } from "@/lib/useDebounce"

describe("useDebounce", () => {
  it("returns initial value immediately", () => {
    const { result } = renderHook(() => useDebounce("hello", 300))
    expect(result.current).toBe("hello")
  })

  it("update returns new value immediately (no debouncing of return)", () => {
    const { result, rerender } = renderHook(
      ({ value, delay }: { value: string; delay: number }) => useDebounce(value, delay),
      { initialProps: { value: "first", delay: 300 } }
    )
    expect(result.current).toBe("first")

    rerender({ value: "second", delay: 300 })
    expect(result.current).toBe("first") // still old value
  })

  it("debounces changes — after delay returns new value", async () => {
    vi.useFakeTimers()

    const { result, rerender } = renderHook(
      ({ value, delay }: { value: string; delay: number }) => useDebounce(value, delay),
      { initialProps: { value: "first", delay: 300 } }
    )
    expect(result.current).toBe("first")

    rerender({ value: "updated", delay: 300 })
    expect(result.current).toBe("first") // unchanged

    await act(async () => { vi.advanceTimersByTime(300) })
    expect(result.current).toBe("updated")

    vi.useRealTimers()
  })

  it("resets timer on rapid updates", async () => {
    vi.useFakeTimers()

    const { result, rerender } = renderHook(
      ({ value, delay }: { value: string; delay: number }) => useDebounce(value, delay),
      { initialProps: { value: "first", delay: 300 } }
    )

    rerender({ value: "second", delay: 300 })
    await act(async () => { vi.advanceTimersByTime(150) })
    expect(result.current).toBe("first")

    rerender({ value: "third", delay: 300 })
    await act(async () => { vi.advanceTimersByTime(150) })
    expect(result.current).toBe("first") // not yet updated

    await act(async () => { vi.advanceTimersByTime(150) })
    expect(result.current).toBe("third")

    vi.useRealTimers()
  })

  it("debounces numbers correctly", async () => {
    vi.useFakeTimers()

    const { result, rerender } = renderHook(
      ({ value, delay }: { value: number; delay: number }) => useDebounce(value, delay),
      { initialProps: { value: 10, delay: 200 } }
    )
    expect(result.current).toBe(10)

    rerender({ value: 20, delay: 200 })
    await act(async () => { vi.advanceTimersByTime(200) })
    expect(result.current).toBe(20)

    vi.useRealTimers()
  })
})
