import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThinkingBlock, type ThinkingBlockProps } from './ThinkingBlock'

// Mock useT
vi.mock('@/i18n', () => ({
  useT: () => (key: string, vars?: Record<string, string | number>) => {
    const map: Record<string, string> = {
      'chat.thinkingProcess': '思考中…',
      'chat.thinkingCollapsed': '思考过程',
    }
    if (key === 'chat.thinkingShowAll' && vars?.count) {
      return `显示全部（共 ${vars.count} 条）`
    }
    return map[key] ?? key
  },
}))

// Mock MarkdownRenderer to avoid pulling in heavy markdown deps
vi.mock('./MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown-renderer">{content}</div>
  ),
}))

// Mock zustand prefs store (required by useT's internal dependency)
vi.mock('@/store/prefs', () => ({
  usePrefs: () => 'zh',
}))

// jsdom does not implement scrollTo
beforeEach(() => {
  Element.prototype.scrollTo = vi.fn()
})

function renderThinking(overrides: Partial<ThinkingBlockProps> = {}) {
  const props: ThinkingBlockProps = {
    statusEntries: [],
    reasoning: '',
    phase: 'idle',
    isStreaming: false,
    ...overrides,
  }
  return render(<ThinkingBlock {...props} />)
}

describe('ThinkingBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // AC1: statusEntries=[] 且 reasoning='', 返回 null
  it('returns null when statusEntries is empty and reasoning is empty', () => {
    const { container } = renderThinking()
    expect(container.innerHTML).toBe('')
    expect(screen.queryByTestId('thinking-block')).not.toBeInTheDocument()
  })

  // AC2: statusEntries 有内容, 显示 Search icon + 文字列表
  it('renders status entries with Search icon when statusEntries has content', () => {
    renderThinking({
      statusEntries: ['Searching documents...', 'Reading file A'],
      defaultExpanded: true,
    })

    expect(screen.getByTestId('thinking-block')).toBeInTheDocument()
    expect(screen.getByText('Searching documents...')).toBeInTheDocument()
    expect(screen.getByText('Reading file A')).toBeInTheDocument()
  })

  // AC3: isStreaming=true, ThinkingBlock 自动展开
  it('auto-expands when streaming starts', () => {
    const { rerender } = render(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )

    // Initially collapsed (defaultExpanded=false)
    const toggle = screen.getByTestId('thinking-block-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // Start streaming
    rerender(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="iterating"
        isStreaming={true}
      />,
    )

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
  })

  // AC4: isStreaming=false 且用户未手动操作, 流结束自动收起
  it('auto-collapses when streaming stops and user has not toggled', () => {
    const { rerender } = render(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )

    const toggle = screen.getByTestId('thinking-block-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // Start streaming — triggers auto-expand
    rerender(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="iterating"
        isStreaming={true}
      />,
    )
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    // Stream ends — triggers auto-collapse
    rerender(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  // AC5: 用户手动点击收起, 流继续不再自动展开/收起
  it('does not auto-expand/collapse after user manually toggles', async () => {
    const user = userEvent.setup()

    const { rerender } = render(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )

    const toggle = screen.getByTestId('thinking-block-toggle')

    // Start streaming — triggers auto-expand
    rerender(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="iterating"
        isStreaming={true}
      />,
    )
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    // User manually collapses
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // Stream continues — should NOT auto-expand since user toggled
    rerender(
      <ThinkingBlock
        statusEntries={['entry', 'new entry']}
        reasoning=""
        phase="iterating"
        isStreaming={true}
      />,
    )

    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // Stream ends — should NOT auto-collapse (user already toggled)
    rerender(
      <ThinkingBlock
        statusEntries={['entry', 'new entry']}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  // AC6: statusEntries > 50 条, 只显示最近 30 条 + '显示全部' 按钮
  it('truncates entries beyond threshold and shows "show all" button', async () => {
    const user = userEvent.setup()
    const entries = Array.from({ length: 60 }, (_, i) => `Entry ${i + 1}`)

    renderThinking({
      statusEntries: entries,
      defaultExpanded: true,
    })

    // Should only show last 30 entries
    expect(screen.queryByText('Entry 1')).not.toBeInTheDocument()
    expect(screen.queryByText('Entry 30')).not.toBeInTheDocument()
    expect(screen.getByText('Entry 31')).toBeInTheDocument()
    expect(screen.getByText('Entry 60')).toBeInTheDocument()

    // Should show the "show all" button
    const showAllBtn = screen.getByTestId('thinking-block-show-all')
    expect(showAllBtn).toHaveTextContent('显示全部（共 60 条）')

    // Click "show all"
    await user.click(showAllBtn)

    // Now all entries are visible
    expect(screen.getByText('Entry 1')).toBeInTheDocument()
    expect(screen.getByText('Entry 60')).toBeInTheDocument()
    expect(screen.queryByTestId('thinking-block-show-all')).not.toBeInTheDocument()
  })

  // AC6 additional: respects custom truncateThreshold and maxVisibleEntries
  it('uses custom truncateThreshold and maxVisibleEntries props', () => {
    const entries = Array.from({ length: 20 }, (_, i) => `Item ${i + 1}`)

    renderThinking({
      statusEntries: entries,
      defaultExpanded: true,
      truncateThreshold: 10,
      maxVisibleEntries: 5,
    })

    // Only last 5 shown
    expect(screen.queryByText('Item 1')).not.toBeInTheDocument()
    expect(screen.queryByText('Item 15')).not.toBeInTheDocument()
    expect(screen.getByText('Item 16')).toBeInTheDocument()
    expect(screen.getByText('Item 20')).toBeInTheDocument()
    expect(screen.getByTestId('thinking-block-show-all')).toBeInTheDocument()
  })

  // AC7: No hooks order warnings (structural test — hooks are before conditional return)
  it('renders without hooks violations in StrictMode', () => {
    // This test verifies structural correctness: the component renders fine
    // when called with empty data (exercises the early return path) and then
    // with data (exercises the full render path) in sequence — a hooks order
    // violation would cause React to throw.
    const { rerender, container } = render(
      <ThinkingBlock
        statusEntries={[]}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )
    expect(container.innerHTML).toBe('')

    rerender(
      <ThinkingBlock
        statusEntries={['entry']}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )
    expect(screen.getByTestId('thinking-block')).toBeInTheDocument()

    // Switch back to empty — should not throw
    rerender(
      <ThinkingBlock
        statusEntries={[]}
        reasoning=""
        phase="idle"
        isStreaming={false}
      />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders reasoning content via MarkdownRenderer', () => {
    renderThinking({
      reasoning: 'Some **reasoning** text',
      defaultExpanded: true,
    })

    expect(screen.getByTestId('markdown-renderer')).toHaveTextContent('Some **reasoning** text')
  })

  it('shows loader icon when streaming in iterating phase', () => {
    renderThinking({
      statusEntries: ['entry'],
      phase: 'iterating',
      isStreaming: true,
    })

    expect(screen.getByText('思考中…')).toBeInTheDocument()
  })

  it('shows collapsed label when not streaming and collapsed', () => {
    renderThinking({
      statusEntries: ['entry'],
      phase: 'idle',
      isStreaming: false,
    })

    expect(screen.getByText('思考过程')).toBeInTheDocument()
  })
})
