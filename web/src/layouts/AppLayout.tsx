import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Sun, Moon, Languages, Bot, MessageSquare, Upload, BookOpen, Activity, type LucideIcon } from 'lucide-react'
import { useT } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/button'

const NAV_ITEMS = [
  { key: 'layout.chat', to: '/chat', icon: MessageSquare },
  { key: 'layout.wiki', to: '/wiki', icon: BookOpen },
  { key: 'layout.submit', to: '/submit', icon: Upload },
  { key: 'layout.tasks', to: '/tasks', icon: Activity },
] as const satisfies readonly { key: string; to: string; icon: LucideIcon }[]

export function AppLayout() {
  const t = useT()
  const { theme, lang, setTheme, setLang } = usePrefs()
  const { pathname } = useLocation()

  function toggleTheme() {
    setTheme(theme === 'light' ? 'dark' : 'light')
  }

  function toggleLang() {
    setLang(lang === 'en' ? 'zh' : 'en')
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="sticky top-0 z-40 border-b bg-background">
        <nav className="flex h-12 items-center px-6">
          <div className="flex flex-1 shrink-0 items-center gap-2">
            <Bot className="h-5 w-5 text-primary" aria-hidden="true" />
            <span className="font-brand text-base font-bold tracking-wide bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
              KaaS
            </span>
          </div>

          <div className="flex min-w-0 items-center gap-1">
            {NAV_ITEMS.map(({ key, to, icon: Icon }) => {
              const isActive = pathname === to || pathname.startsWith(to + '/')
              return (
                <NavLink
                  key={to}
                  to={to}
                  className={cn(
                    'flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    'hover:bg-accent hover:text-accent-foreground',
                    isActive
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground',
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {t(key)}
                </NavLink>
              )
            })}
          </div>

          <div className="flex flex-1 shrink-0 items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="icon"
              aria-label={t('layout.toggleTheme')}
              onClick={toggleTheme}
            >
              {theme === 'light' ? (
                <Moon className="h-4 w-4" />
              ) : (
                <Sun className="h-4 w-4" />
              )}
            </Button>

            <Button
              variant="ghost"
              size="icon"
              aria-label={t('layout.toggleLang')}
              onClick={toggleLang}
            >
              <Languages className="h-4 w-4" />
            </Button>
          </div>
        </nav>
      </header>

      <main className="flex flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
