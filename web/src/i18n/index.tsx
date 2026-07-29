/**
 * Zero-dependency i18n shim.
 *
 * Design:
 * - `LangProvider` is a thin wrapper that provides a stable React context. It
 *   does NOT carry string data itself — `useT` reads `lang` directly from the
 *   zustand `usePrefs` store so the component re-renders whenever the language
 *   changes, without needing a separate context value.
 * - `useT()` returns a translator function `(key, vars?) => string`.
 *   Interpolation uses `{{varName}}` tokens; missing keys return the key itself.
 * - No new npm package required — React context + zustand covers everything.
 */
import { createContext, useCallback, useContext, type ReactNode } from 'react'
import { usePrefs } from '@/store/prefs'
import { STRINGS } from './strings'

// Context exists only to allow future extension (e.g. namespace injection).
// Its value is intentionally empty for now.
const I18nContext = createContext<null>(null)

export function LangProvider({ children }: { children: ReactNode }) {
  return <I18nContext.Provider value={null}>{children}</I18nContext.Provider>
}

/**
 * Returns a translator function bound to the current language.
 * Automatically re-renders on language change via the zustand subscription.
 */
export function useT(): (key: string, vars?: Record<string, string | number>) => string {
  // Consume context so the hook is scoped inside LangProvider (guard against
  // accidental usage outside the tree — currently a no-op, kept for future use).
  useContext(I18nContext)
  const lang = usePrefs((s) => s.lang)
  const dict = STRINGS[lang] ?? STRINGS.en

  return useCallback(
    function t(key: string, vars?: Record<string, string | number>): string {
      let str = dict[key] ?? key
      if (vars) {
        for (const [name, val] of Object.entries(vars)) {
          str = str.replaceAll(`{{${name}}}`, String(val))
        }
      }
      return str
    },
    [dict],
  )
}
