import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import type { WikiTreeNode } from '@/api/wiki'
import { FileTree } from './FileTree'

function renderFileTree(nodes: WikiTreeNode[], activePath?: string | null, searchQuery?: string) {
  return render(
    <MemoryRouter>
      <LangProvider>
        <FileTree nodes={nodes} activePath={activePath} searchQuery={searchQuery} />
      </LangProvider>
    </MemoryRouter>,
  )
}

const sampleTree: WikiTreeNode[] = [
  {
    name: 'guide',
    path: 'guide',
    isDir: true,
    fileCount: 3,
    children: [
      { name: 'intro.md', path: 'guide/intro.md', title: '入门指南', isDir: false, tags: ['getting-started', 'tutorial'] },
      { name: 'advanced.md', path: 'guide/advanced.md', title: '高级用法', isDir: false, tags: ['advanced'] },
    ],
  },
  {
    name: 'faq',
    path: 'faq',
    isDir: true,
    fileCount: 1,
    children: [
      { name: 'general.md', path: 'faq/general.md', title: '常见问题', isDir: false, tags: ['faq', 'support'] },
    ],
  },
  { name: 'readme.md', path: 'readme.md', title: '项目说明', isDir: false, tags: ['overview'] },
]

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
})

describe('FileTree', () => {
  it('renders all directories expanded by default', () => {
    renderFileTree(sampleTree)
    // All file nodes should be visible since dirs are expanded
    expect(screen.getByText('入门指南')).toBeInTheDocument()
    expect(screen.getByText('高级用法')).toBeInTheDocument()
    expect(screen.getByText('常见问题')).toBeInTheDocument()
    expect(screen.getByText('项目说明')).toBeInTheDocument()
  })

  it('collapses directory when clicked and hides children', async () => {
    const user = userEvent.setup()
    renderFileTree(sampleTree)

    // Click the 'guide' directory button to collapse
    const guideBtn = screen.getByRole('button', { name: /guide/ })
    await user.click(guideBtn)

    // Children of 'guide' should be hidden
    expect(screen.queryByText('入门指南')).not.toBeInTheDocument()
    expect(screen.queryByText('高级用法')).not.toBeInTheDocument()

    // Other dir's children should still be visible
    expect(screen.getByText('常见问题')).toBeInTheDocument()
  })

  it('re-expands directory when clicked again', async () => {
    const user = userEvent.setup()
    renderFileTree(sampleTree)

    const guideBtn = screen.getByRole('button', { name: /guide/ })
    // Collapse
    await user.click(guideBtn)
    expect(screen.queryByText('入门指南')).not.toBeInTheDocument()

    // Expand again
    await user.click(guideBtn)
    expect(screen.getByText('入门指南')).toBeInTheDocument()
  })

  it('displays fileCount badge for directory nodes', () => {
    renderFileTree(sampleTree)
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('displays title as link text for file nodes', () => {
    renderFileTree(sampleTree)
    const link = screen.getByRole('link', { name: /入门指南/ })
    expect(link).toBeInTheDocument()
  })

  it('navigates to /wiki/<path> for file nodes', () => {
    renderFileTree(sampleTree)
    const link = screen.getByRole('link', { name: /入门指南/ })
    expect(link).toHaveAttribute('href', '/wiki/guide/intro.md')
  })

  it('highlights active file with bg-muted font-medium styling', () => {
    renderFileTree(sampleTree, 'guide/intro.md')
    const link = screen.getByRole('link', { name: /入门指南/ })
    expect(link).toHaveClass('bg-muted')
    expect(link).toHaveClass('font-medium')
    expect(link).toHaveClass('text-foreground')
  })

  it('does not highlight inactive file nodes', () => {
    renderFileTree(sampleTree, 'guide/intro.md')
    const link = screen.getByRole('link', { name: /高级用法/ })
    expect(link).not.toHaveClass('font-medium')
    expect(link).toHaveClass('text-muted-foreground')
  })

  it('maintains independent expand/collapse state for dirs with same name at different paths', async () => {
    const user = userEvent.setup()
    const tree: WikiTreeNode[] = [
      {
        name: 'docs',
        path: 'a/docs',
        isDir: true,
        fileCount: 1,
        children: [{ name: 'one.md', path: 'a/docs/one.md', title: 'One', isDir: false }],
      },
      {
        name: 'docs',
        path: 'b/docs',
        isDir: true,
        fileCount: 1,
        children: [{ name: 'two.md', path: 'b/docs/two.md', title: 'Two', isDir: false }],
      },
    ]

    renderFileTree(tree)

    // Both expanded initially
    expect(screen.getByText('One')).toBeInTheDocument()
    expect(screen.getByText('Two')).toBeInTheDocument()

    // Collapse first 'docs' directory
    const docsBtns = screen.getAllByRole('button', { name: /docs/ })
    await user.click(docsBtns[0])

    // First collapsed, second still expanded
    expect(screen.queryByText('One')).not.toBeInTheDocument()
    expect(screen.getByText('Two')).toBeInTheDocument()
  })

  // --- Search/filter tests ---

  it('renders full tree when no searchQuery is provided', () => {
    renderFileTree(sampleTree)
    expect(screen.getByText('入门指南')).toBeInTheDocument()
    expect(screen.getByText('高级用法')).toBeInTheDocument()
    expect(screen.getByText('常见问题')).toBeInTheDocument()
    expect(screen.getByText('项目说明')).toBeInTheDocument()
    // Directories should also be visible
    expect(screen.getByRole('button', { name: /guide/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /faq/ })).toBeInTheDocument()
  })

  it('filters by title match', () => {
    renderFileTree(sampleTree, null, '入门')
    expect(screen.getByText('入门指南')).toBeInTheDocument()
    // Other files should not be visible
    expect(screen.queryByText('高级用法')).not.toBeInTheDocument()
    expect(screen.queryByText('常见问题')).not.toBeInTheDocument()
    expect(screen.queryByText('项目说明')).not.toBeInTheDocument()
    // Directories should not appear in search results
    expect(screen.queryByRole('button', { name: /guide/ })).not.toBeInTheDocument()
  })

  it('filters by tag match', () => {
    renderFileTree(sampleTree, null, 'tutorial')
    expect(screen.getByText('入门指南')).toBeInTheDocument()
    expect(screen.queryByText('高级用法')).not.toBeInTheDocument()
    expect(screen.queryByText('常见问题')).not.toBeInTheDocument()
    expect(screen.queryByText('项目说明')).not.toBeInTheDocument()
  })

  it('filters by path match', () => {
    renderFileTree(sampleTree, null, 'faq/general')
    expect(screen.getByText('常见问题')).toBeInTheDocument()
    expect(screen.queryByText('入门指南')).not.toBeInTheDocument()
    expect(screen.queryByText('高级用法')).not.toBeInTheDocument()
    expect(screen.queryByText('项目说明')).not.toBeInTheDocument()
  })

  it('shows empty state when no match', () => {
    renderFileTree(sampleTree, null, 'nonexistent')
    expect(screen.getByText('No matching articles')).toBeInTheDocument()
    expect(screen.queryByText('入门指南')).not.toBeInTheDocument()
  })

  it('search is case-insensitive', () => {
    renderFileTree(sampleTree, null, 'TUTORIAL')
    expect(screen.getByText('入门指南')).toBeInTheDocument()
    expect(screen.queryByText('高级用法')).not.toBeInTheDocument()
  })

  it('highlights active file in search results', () => {
    renderFileTree(sampleTree, 'guide/intro.md', '入门')
    const link = screen.getByRole('link', { name: /入门指南/ })
    expect(link).toHaveClass('bg-muted')
    expect(link).toHaveClass('font-medium')
  })

  it('whitespace-only search shows full tree', () => {
    renderFileTree(sampleTree, null, '   ')
    expect(screen.getByText('入门指南')).toBeInTheDocument()
    expect(screen.getByText('高级用法')).toBeInTheDocument()
    expect(screen.getByText('常见问题')).toBeInTheDocument()
    expect(screen.getByText('项目说明')).toBeInTheDocument()
    // Directories should be visible (full tree mode)
    expect(screen.getByRole('button', { name: /guide/ })).toBeInTheDocument()
  })
})
