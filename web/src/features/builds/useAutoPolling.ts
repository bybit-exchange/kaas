import { useEffect, useRef, useState } from 'react'

/**
 * Polls `fetchFn` at a fixed interval while `hasActiveItems` is true.
 * Pauses when the document is hidden (Page Visibility API) and resumes
 * with an immediate fetch when the tab becomes visible again.
 * Cleans up the interval and event listener on unmount.
 */
export function useAutoPolling(
  fetchFn: () => Promise<void>,
  hasActiveItems: boolean,
  intervalMs: number = 5000,
): { isPolling: boolean } {
  const [isPolling, setIsPolling] = useState(false)
  const fetchRef = useRef(fetchFn)
  fetchRef.current = fetchFn

  useEffect(() => {
    if (!hasActiveItems) {
      setIsPolling(false)
      return
    }

    let timer: ReturnType<typeof setInterval> | null = null

    function startInterval() {
      stopInterval()
      timer = setInterval(() => {
        fetchRef.current()
      }, intervalMs)
      setIsPolling(true)
    }

    function stopInterval() {
      if (timer !== null) {
        clearInterval(timer)
        timer = null
      }
      setIsPolling(false)
    }

    function handleVisibility() {
      if (document.hidden) {
        stopInterval()
      } else {
        // Immediate fetch on becoming visible, then resume interval
        fetchRef.current()
        startInterval()
      }
    }

    // Start polling immediately
    startInterval()

    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      stopInterval()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [hasActiveItems, intervalMs])

  return { isPolling }
}
