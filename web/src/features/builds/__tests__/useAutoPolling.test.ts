import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAutoPolling } from '../useAutoPolling'

describe('useAutoPolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('calls fetchFn at interval when hasActiveItems is true', async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined)
    renderHook(() => useAutoPolling(fetchFn, true, 1000))

    // Initially no call — first call happens after 1 interval tick
    expect(fetchFn).not.toHaveBeenCalled()

    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(1)

    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(2)
  })

  it('does not call fetchFn when hasActiveItems is false', async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined)
    renderHook(() => useAutoPolling(fetchFn, false, 1000))

    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('returns isPolling true when active, false when inactive', () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined)
    const { result, rerender } = renderHook(
      ({ active }) => useAutoPolling(fetchFn, active, 1000),
      { initialProps: { active: true } },
    )

    expect(result.current.isPolling).toBe(true)

    rerender({ active: false })
    expect(result.current.isPolling).toBe(false)
  })

  it('pauses when document becomes hidden', async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined)
    renderHook(() => useAutoPolling(fetchFn, true, 1000))

    // Advance one tick to confirm polling works
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // Simulate tab becoming hidden
    await act(async () => {
      Object.defineProperty(document, 'hidden', {
        value: true,
        writable: true,
        configurable: true,
      })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    // Advance more time — should NOT call fetchFn while hidden
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // Restore visibility
    Object.defineProperty(document, 'hidden', {
      value: false,
      writable: true,
      configurable: true,
    })
  })

  it('resumes with an immediate fetch when document becomes visible', async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined)
    renderHook(() => useAutoPolling(fetchFn, true, 1000))

    // Go hidden
    await act(async () => {
      Object.defineProperty(document, 'hidden', {
        value: true,
        writable: true,
        configurable: true,
      })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    fetchFn.mockClear()

    // Come back visible
    await act(async () => {
      Object.defineProperty(document, 'hidden', {
        value: false,
        writable: true,
        configurable: true,
      })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    // Immediate fetch on becoming visible
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // Then resumes interval
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(2)
  })

  it('cleans up on unmount', async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined)
    const { unmount } = renderHook(() => useAutoPolling(fetchFn, true, 1000))

    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(1)

    unmount()

    // No more calls after unmount
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })

  it('stops polling when hasActiveItems transitions from true to false', async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined)
    const { rerender } = renderHook(
      ({ active }) => useAutoPolling(fetchFn, active, 1000),
      { initialProps: { active: true } },
    )

    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(1)

    rerender({ active: false })

    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })
})
