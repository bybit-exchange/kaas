import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { MarkdownRenderer, isInternalWikiLink, resolveWikiPath } from './MarkdownRenderer'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

function Wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Unit tests: isInternalWikiLink
// ---------------------------------------------------------------------------

describe('isInternalWikiLink', () => {
  it('returns true for /wiki/a.md', () => {
    expect(isInternalWikiLink('/wiki/a.md')).toBe(true)
  })

  it('returns true for /wiki/team/guide.md', () => {
    expect(isInternalWikiLink('/wiki/team/guide.md')).toBe(true)
  })

  it('returns true for /wiki?path=team/guide.md', () => {
    expect(isInternalWikiLink('/wiki?path=team/guide.md')).toBe(true)
  })

  it('returns true for wiki/guide.md (relative)', () => {
    expect(isInternalWikiLink('wiki/guide.md')).toBe(true)
  })

  it('returns false for https://google.com', () => {
    expect(isInternalWikiLink('https://google.com')).toBe(false)
  })

  it('returns false for /tasks', () => {
    expect(isInternalWikiLink('/tasks')).toBe(false)
  })

  it('returns false for /chat/123', () => {
    expect(isInternalWikiLink('/chat/123')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Unit tests: resolveWikiPath
// ---------------------------------------------------------------------------

describe('resolveWikiPath', () => {
  it('returns /wiki/team/guide.md for /wiki/team/guide.md (canonical)', () => {
    expect(resolveWikiPath('/wiki/team/guide.md')).toBe('/wiki/team/guide.md')
  })

  it('converts /wiki?path=team/guide.md to /wiki/team/guide.md', () => {
    expect(resolveWikiPath('/wiki?path=team/guide.md')).toBe('/wiki/team/guide.md')
  })

  it('prepends / to wiki/guide.md (relative)', () => {
    expect(resolveWikiPath('wiki/guide.md')).toBe('/wiki/guide.md')
  })
})

// ---------------------------------------------------------------------------
// Integration tests: MarkdownRenderer component
// ---------------------------------------------------------------------------

describe('MarkdownRenderer', () => {
  it('renders a mid-sentence citation within a SINGLE paragraph', () => {
    const { container } = render(
      <Wrapper>
        <MarkdownRenderer
          content="The answer is X [1], which derives from Y [2]."
          onCitationClick={vi.fn()}
        />
      </Wrapper>,
    )

    // Exactly one <p> element — the prose is NOT split into multiple paragraphs.
    const paragraphs = container.querySelectorAll('p')
    expect(paragraphs).toHaveLength(1)

    const p = paragraphs[0]

    // The paragraph's text includes both prose fragments.
    expect(p.textContent).toContain('The answer is X')
    expect(p.textContent).toContain('which derives from Y')

    // Two citation buttons are present inside that paragraph.
    const buttons = p.querySelectorAll('button[aria-label]')
    expect(buttons).toHaveLength(2)
    expect(buttons[0]).toHaveAttribute('aria-label', 'Jump to source 1')
    expect(buttons[1]).toHaveAttribute('aria-label', 'Jump to source 2')
  })

  it('does NOT convert a markdown link [text](url) into a citation', () => {
    const { container } = render(
      <Wrapper>
        <MarkdownRenderer
          content="See [the docs](http://example.com) for details."
          onCitationClick={vi.fn()}
        />
      </Wrapper>,
    )

    // No citation buttons should appear.
    const buttons = container.querySelectorAll('button[aria-label]')
    expect(buttons).toHaveLength(0)

    // The markdown link is rendered as an anchor.
    expect(screen.getByRole('link', { name: 'the docs' })).toBeInTheDocument()
  })

  it('renders plain markdown without citations unchanged', () => {
    const { container } = render(
      <Wrapper>
        <MarkdownRenderer content="**bold** and _italic_." />
      </Wrapper>,
    )

    const strong = container.querySelector('strong')
    expect(strong).toBeInTheDocument()
    expect(strong?.textContent).toBe('bold')

    const em = container.querySelector('em')
    expect(em?.textContent).toBe('italic')
  })

  it('fires onCitationClick with the correct index', async () => {
    const handleClick = vi.fn()
    render(
      <Wrapper>
        <MarkdownRenderer
          content="Hello [3] world."
          onCitationClick={handleClick}
        />
      </Wrapper>,
    )

    const btn = screen.getByRole('button', { name: 'Jump to source 3' })
    btn.click()
    expect(handleClick).toHaveBeenCalledWith(3)
  })

  it('navigates via useNavigate when clicking a wiki link', () => {
    render(
      <Wrapper>
        <MarkdownRenderer
          content="Read [the guide](/wiki/team/guide.md) now."
        />
      </Wrapper>,
    )

    const link = screen.getByRole('link', { name: 'the guide' })
    fireEvent.click(link)
    expect(mockNavigate).toHaveBeenCalledWith('/wiki/team/guide.md')
  })

  it('renders external link with target="_blank"', () => {
    render(
      <Wrapper>
        <MarkdownRenderer
          content="Visit [Google](https://google.com) for search."
        />
      </Wrapper>,
    )

    const link = screen.getByRole('link', { name: 'Google' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })
})
