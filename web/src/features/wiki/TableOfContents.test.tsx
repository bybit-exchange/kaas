import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { TableOfContents } from './TableOfContents'

function renderTOC(content: string) {
  return render(
    <MemoryRouter>
      <LangProvider>
        <TableOfContents content={content} />
      </LangProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
})

describe('TableOfContents', () => {
  it('renders two TOC entries with slugified ids for h2 and h3', () => {
    renderTOC('## Alpha\n\n### Beta')
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
    // h2 link: href="#alpha", h3 link: href="#beta"
    expect(screen.getByRole('link', { name: 'Alpha' })).toHaveAttribute('href', '#alpha')
    expect(screen.getByRole('link', { name: 'Beta' })).toHaveAttribute('href', '#beta')
  })

  it('returns null when no headings', () => {
    const { container } = renderTOC('No headings here')
    expect(container.firstChild).toBeNull()
  })
})
