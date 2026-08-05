import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface KBState {
  /** Selected derived-KB slug, or null for the root knowledge base. */
  kb: string | null
  setKB: (slug: string | null) => void
}

/**
 * Which knowledge base the wiki tree and chat read from.
 *
 * A store rather than component state because the wiki tree and the chat panel
 * both need the same value and are not in a parent/child relationship. Persisted
 * so a reload does not silently move the user back to the root corpus.
 */
export const useKB = create<KBState>()(
  persist(
    (set) => ({
      kb: null,
      setKB: (slug: string | null) => set({ kb: slug }),
    }),
    { name: 'kaas-kb' },
  ),
)
