import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// MermaidBlock pulls in the mermaid runtime, which needs a real browser to
// render. The article only has to hand it the fence body.
vi.mock('./MermaidBlock', () => ({
  MermaidBlock: ({ code }: { code: string }) => <div data-testid="mermaid">{code}</div>,
}))

import { MarkdownArticle } from './MarkdownArticle'

function renderArticle(content: string) {
  return render(<MarkdownArticle content={content} />)
}

describe('MarkdownArticle', () => {
  describe('wiki link syntax', () => {
    it('renders [[Page]] as bold page text', () => {
      renderArticle('See [[Onboarding]] first.')

      const strong = screen.getByText('Onboarding')
      expect(strong.tagName).toBe('STRONG')
    })

    it('prefers the display label in [[Page|Display]]', () => {
      renderArticle('See [[team/onboarding.md|the onboarding guide]] first.')

      const strong = screen.getByText('the onboarding guide')
      expect(strong.tagName).toBe('STRONG')
      expect(screen.queryByText(/team\/onboarding\.md/)).not.toBeInTheDocument()
    })

    it('converts every wiki link in the document', () => {
      renderArticle('[[One]] and [[Two]] and [[Three]]')

      expect(screen.getByText('One').tagName).toBe('STRONG')
      expect(screen.getByText('Two').tagName).toBe('STRONG')
      expect(screen.getByText('Three').tagName).toBe('STRONG')
    })

    it('leaves ordinary bracketed text alone', () => {
      const { container } = renderArticle('An [array] index and [a link](http://x.dev)')

      expect(container.querySelector('strong')).toBeNull()
      expect(screen.getByRole('link', { name: 'a link' })).toBeInTheDocument()
    })
  })

  describe('heading anchors', () => {
    it('gives h2 and h3 slugified ids so the TOC can link to them', () => {
      renderArticle('## Getting Started\n\n### Local Setup\n')

      expect(screen.getByRole('heading', { level: 2, name: 'Getting Started' })).toHaveAttribute(
        'id',
        'getting-started',
      )
      expect(screen.getByRole('heading', { level: 3, name: 'Local Setup' })).toHaveAttribute(
        'id',
        'local-setup',
      )
    })

    it('drops punctuation from the slug', () => {
      renderArticle('## What is KaaS?\n')

      expect(screen.getByRole('heading', { level: 2 })).toHaveAttribute('id', 'what-is-kaas')
    })

    it('slugifies headings that contain inline markup', () => {
      renderArticle('## Setup **Guide**\n')

      expect(screen.getByRole('heading', { level: 2 })).toHaveAttribute('id', 'setup-guide')
    })
  })

  describe('code rendering', () => {
    it('renders inline code without a language chrome bar', () => {
      const { container } = renderArticle('Run `npm test` now.')

      const code = screen.getByText('npm test')
      expect(code.tagName).toBe('CODE')
      expect(container.querySelector('pre')).toBeNull()
    })

    it('renders a fenced block with syntax highlighting applied', () => {
      const { container } = renderArticle('```ts\nconst a = 1\n```\n')

      const code = container.querySelector('pre code')
      expect(code?.className).toContain('language-ts')
      expect(code?.textContent).toContain('const a = 1')
    })

    // rehype-highlight rewrites the <code> className to "hljs language-ts", so the
    // label must be extracted rather than prefix-stripped, or "hljs " leaks through.
    it('labels a fenced block with only its language name', () => {
      renderArticle('```ts\nconst a = 1\n```\n')

      expect(screen.getByText('ts')).toBeInTheDocument()
      expect(screen.queryByText('hljs ts')).not.toBeInTheDocument()
    })

    it('labels an unfenced-language block as plain text', () => {
      renderArticle('```\nsome output\n```\n')

      expect(screen.getByText('plain text')).toBeInTheDocument()
      expect(screen.getByText('some output')).toBeInTheDocument()
    })

    it('routes a mermaid fence to the diagram renderer with the trimmed source', async () => {
      renderArticle('```mermaid\ngraph TD;\n  A-->B;\n```\n')

      const diagram = await screen.findByTestId('mermaid')
      expect(diagram).toHaveTextContent('graph TD;')
      expect(diagram.textContent?.startsWith('graph')).toBe(true)
    })
  })

  describe('tables and links', () => {
    it('renders a GFM table with header and body cells', () => {
      renderArticle('| Name | Role |\n| --- | --- |\n| Ada | Engineer |\n')

      expect(screen.getByRole('table')).toBeInTheDocument()
      expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument()
      expect(screen.getByRole('columnheader', { name: 'Role' })).toBeInTheDocument()
      expect(screen.getByRole('cell', { name: 'Ada' })).toBeInTheDocument()
      expect(screen.getByRole('cell', { name: 'Engineer' })).toBeInTheDocument()
    })

    it('opens links in a new tab with a safe rel', () => {
      renderArticle('Visit [the docs](https://docs.dev).')

      const link = screen.getByRole('link', { name: 'the docs' })
      expect(link).toHaveAttribute('href', 'https://docs.dev')
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    })
  })
})
