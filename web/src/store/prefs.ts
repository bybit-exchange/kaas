import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'light' | 'dark'
type Lang = 'en' | 'zh'

interface PrefsState {
  theme: Theme
  lang: Lang
  setTheme: (t: Theme) => void
  setLang: (l: Lang) => void
}

/**
 * Apply the dark class to <html> and mirror to localStorage['theme']
 * so the pre-hydration inline script (if any) can read it.
 * We chose to apply the class directly in setTheme rather than via subscribe
 * to keep it synchronous and easy to test.
 */
function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  // Mirror to standalone 'theme' key so web/index.html's pre-hydration inline script
  // can read it and avoid flash-of-unstyled-content before React mounts.
  // Zustand persists the full prefs under 'kaas-prefs' key separately.
  localStorage.setItem('theme', theme)
}

function getDefaultLang(): Lang {
  return navigator.language.startsWith('zh') ? 'zh' : 'en'
}

export const usePrefs = create<PrefsState>()(
  persist(
    (set) => ({
      theme: 'light' as Theme,
      lang: getDefaultLang(),
      setTheme: (t: Theme) => {
        applyTheme(t)
        set({ theme: t })
      },
      setLang: (l: Lang) => set({ lang: l }),
    }),
    {
      name: 'kaas-prefs',
      // On rehydration, apply the persisted theme to the DOM
      onRehydrateStorage: () => (state) => {
        if (state) {
          applyTheme(state.theme)
        }
      },
    },
  ),
)
