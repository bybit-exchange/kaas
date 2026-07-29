import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { AppLayout } from './AppLayout'
import { STRINGS } from '@/i18n/strings'

function renderLayout(initialEntries = ['/chat']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <LangProvider>
        <AppLayout />
      </LangProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  // Reset prefs store to defaults before each test
  usePrefs.setState({ theme: 'light', lang: 'en' })
  localStorage.clear()
})

describe('AppLayout nav links', () => {
  it('renders all 4 nav links', () => {
    renderLayout()
    expect(screen.getByRole('link', { name: STRINGS.en['layout.chat'] })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: STRINGS.en['layout.submit'] })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: STRINGS.en['layout.wiki'] })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: STRINGS.en['layout.tasks'] })).toBeInTheDocument()
  })

  it('nav links point to the correct hrefs', () => {
    renderLayout()
    expect(screen.getByRole('link', { name: STRINGS.en['layout.chat'] })).toHaveAttribute('href', '/chat')
    expect(screen.getByRole('link', { name: STRINGS.en['layout.submit'] })).toHaveAttribute('href', '/submit')
    expect(screen.getByRole('link', { name: STRINGS.en['layout.wiki'] })).toHaveAttribute('href', '/wiki')
    expect(screen.getByRole('link', { name: STRINGS.en['layout.tasks'] })).toHaveAttribute('href', '/tasks')
  })
})

describe('AppLayout theme toggle', () => {
  it('flips theme from light to dark on click', async () => {
    const user = userEvent.setup()
    renderLayout()
    expect(usePrefs.getState().theme).toBe('light')
    const toggle = screen.getByRole('button', { name: STRINGS.en['layout.toggleTheme'] })
    await user.click(toggle)
    expect(usePrefs.getState().theme).toBe('dark')
  })

  it('flips theme from dark to light on click', async () => {
    usePrefs.setState({ theme: 'dark', lang: 'en' })
    const user = userEvent.setup()
    renderLayout()
    const toggle = screen.getByRole('button', { name: STRINGS.en['layout.toggleTheme'] })
    await user.click(toggle)
    expect(usePrefs.getState().theme).toBe('light')
  })
})

describe('AppLayout lang toggle', () => {
  it('flips lang from en to zh on click', async () => {
    const user = userEvent.setup()
    renderLayout()
    expect(usePrefs.getState().lang).toBe('en')
    // Chat nav link should show English label initially
    expect(screen.getByRole('link', { name: STRINGS.en['layout.chat'] })).toBeInTheDocument()

    const toggle = screen.getByRole('button', { name: STRINGS.en['layout.toggleLang'] })
    await user.click(toggle)

    expect(usePrefs.getState().lang).toBe('zh')
    // Chat nav link should now show Chinese label
    expect(screen.getByRole('link', { name: STRINGS.zh['layout.chat'] })).toBeInTheDocument()
  })

  it('flips lang from zh to en on click', async () => {
    usePrefs.setState({ theme: 'light', lang: 'zh' })
    const user = userEvent.setup()
    renderLayout()
    expect(screen.getByRole('link', { name: STRINGS.zh['layout.chat'] })).toBeInTheDocument()

    const toggle = screen.getByRole('button', { name: STRINGS.zh['layout.toggleLang'] })
    await user.click(toggle)

    expect(usePrefs.getState().lang).toBe('en')
    expect(screen.getByRole('link', { name: STRINGS.en['layout.chat'] })).toBeInTheDocument()
  })
})
