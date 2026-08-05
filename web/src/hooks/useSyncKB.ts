import { useEffect } from 'react'
import { listDerived } from '@/api/derived'
import { useKB } from '@/store/kb'

/**
 * Drops a persisted knowledge-base selection that the backend no longer knows.
 *
 * The selection outlives the browser session, so it can point at a derived KB
 * that was removed on disk, or at one that belongs to a different backend's
 * kb_dir than the one this origin now talks to. Every scoped read then fails,
 * including chat — which is the landing route — so this has to run on every
 * route rather than only where the selector is mounted.
 *
 * A failed load leaves the selection alone: a transient blip must not silently
 * move the reader to a different corpus. Reads the store imperatively so a
 * switch between existing knowledge bases does not refetch the list.
 */
export function useSyncKB(): void {
  useEffect(() => {
    let cancelled = false
    listDerived()
      .then(({ kbs }) => {
        if (cancelled) return
        const { kb, setKB } = useKB.getState()
        if (kb && !kbs.some((k) => k.slug === kb)) setKB(null)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])
}
