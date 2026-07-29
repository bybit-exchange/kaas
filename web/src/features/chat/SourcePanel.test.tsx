import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { SourcePanel } from './SourcePanel'

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
})

describe('SourcePanel', () => {
  it('renders a link to /wiki/{path} with target="_blank" showing index 1 and title', () => {
    render(
      <LangProvider>
        <SourcePanel sources={[{ title: 'Doc', path: 'team/x.md' }]} />
      </LangProvider>,
    )

    // Badge shows index 1
    expect(screen.getByText('1')).toBeInTheDocument()

    // Title is shown
    expect(screen.getByText('Doc')).toBeInTheDocument()

    // Link uses RESTful wiki path and opens in new tab
    const link = screen.getByRole('link', { name: /Doc/ })
    expect(link).toHaveAttribute('href', '/wiki/team/x.md')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('renders nothing when sources is empty', () => {
    const { container } = render(
      <LangProvider>
        <SourcePanel sources={[]} />
      </LangProvider>,
    )
    expect(container.firstChild).toBeNull()
  })
})
