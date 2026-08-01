import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { MessageList, type ChatMessage } from './MessageList'

function renderList(props: Partial<React.ComponentProps<typeof MessageList>> = {}) {
  return render(
    <LangProvider>
      <MessageList messages={[]} {...props} />
    </LangProvider>,
  )
}

const USER_MSG: ChatMessage = { role: 'user', content: 'What is KaaS?' }
const ASSISTANT_MSG: ChatMessage = { role: 'assistant', content: 'It is a service.' }

/**
 * The standalone "waiting" spinner of the streaming bubble. It cannot be found
 * by its label because ThinkingBlock's own header uses the same "Thinking…"
 * text; the h-4/w-4 spinner class is what distinguishes it.
 */
function waitingSpinner(container: HTMLElement): Element | null {
  return container.querySelector('.animate-spin.h-4.w-4')
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  // jsdom implements neither scrollIntoView nor Element.scrollTo
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.scrollTo = vi.fn()
})

describe('MessageList', () => {
  describe('empty state', () => {
    it('shows the welcome prompt when there is nothing to display', () => {
      renderList()

      expect(screen.getByText('Ask anything about the knowledge base')).toBeInTheDocument()
      expect(screen.queryByRole('log')).not.toBeInTheDocument()
    })

    it('shows the transcript instead of the welcome prompt once streaming starts', () => {
      renderList({ isStreaming: true })

      expect(
        screen.queryByText('Ask anything about the knowledge base'),
      ).not.toBeInTheDocument()
      expect(screen.getByRole('log')).toBeInTheDocument()
    })
  })

  describe('message rendering', () => {
    it('renders user text verbatim and assistant text as markdown', () => {
      renderList({
        messages: [USER_MSG, { role: 'assistant', content: 'Answer with **bold**.' }],
      })

      expect(screen.getByText('What is KaaS?')).toBeInTheDocument()
      const strong = screen.getByRole('log').querySelector('strong')
      expect(strong?.textContent).toBe('bold')
    })

    it('renders the cited sources panel only for messages that have sources', () => {
      renderList({
        messages: [
          { ...ASSISTANT_MSG, citedSources: [{ title: 'Guide', path: 'guide.md' }] },
          { role: 'assistant', content: 'No sources here.' },
        ],
      })

      expect(screen.getByRole('link', { name: 'Guide' })).toBeInTheDocument()
      expect(screen.getAllByLabelText('Sources')).toHaveLength(1)
    })

    it('renders the thinking block for a message that carries status entries', () => {
      renderList({
        messages: [{ ...ASSISTANT_MSG, statusEntries: ['Searching docs'] }],
      })

      expect(screen.getByTestId('thinking-block')).toBeInTheDocument()
    })

    it('omits the thinking block for a plain assistant message', () => {
      renderList({ messages: [ASSISTANT_MSG] })

      expect(screen.queryByTestId('thinking-block')).not.toBeInTheDocument()
    })
  })

  describe('usage footer', () => {
    it('sums prompt and completion tokens and shows the cost with 4 decimals', () => {
      renderList({
        messages: [
          {
            ...ASSISTANT_MSG,
            usage: { tokens_prompt: 120, tokens_completion: 80, cost_usd: 0.01234567 },
          },
        ],
      })

      expect(screen.getByTestId('usage')).toHaveTextContent('200 tokens · 0.0123 USD')
    })

    it('omits the cost when it is zero', () => {
      renderList({
        messages: [
          {
            ...ASSISTANT_MSG,
            usage: { tokens_prompt: 5, tokens_completion: 5, cost_usd: 0 },
          },
        ],
      })

      expect(screen.getByTestId('usage')).toHaveTextContent('10 tokens')
      expect(screen.getByTestId('usage').textContent).not.toContain('USD')
    })

    it('renders no usage footer when the message has no usage data', () => {
      renderList({ messages: [ASSISTANT_MSG] })

      expect(screen.queryByTestId('usage')).not.toBeInTheDocument()
    })
  })

  describe('citation clicks', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    it('reports the clicked citation index and briefly highlights the source row', () => {
      vi.useFakeTimers()
      const onCitationClick = vi.fn()
      renderList({
        messages: [
          {
            role: 'assistant',
            content: 'Derived from the guide [1].',
            citedSources: [{ title: 'Guide', path: 'guide.md' }],
          },
        ],
        onCitationClick,
      })

      fireEvent.click(screen.getByRole('button', { name: 'Jump to source 1' }))

      expect(onCitationClick).toHaveBeenCalledWith(1)
      const sourceRow = document.getElementById('source-1')!
      expect(sourceRow.classList.contains('bg-primary/10')).toBe(true)

      act(() => {
        vi.advanceTimersByTime(1500)
      })

      expect(sourceRow.classList.contains('bg-primary/10')).toBe(false)
    })

    it('does not throw when the cited source has no matching row', () => {
      const onCitationClick = vi.fn()
      renderList({
        messages: [{ role: 'assistant', content: 'Missing source [9].' }],
        onCitationClick,
      })

      fireEvent.click(screen.getByRole('button', { name: 'Jump to source 9' }))

      expect(onCitationClick).toHaveBeenCalledWith(9)
    })

    it('tolerates a citation click with no handler attached', () => {
      renderList({ messages: [{ role: 'assistant', content: 'Cited [1].' }] })

      fireEvent.click(screen.getByRole('button', { name: 'Jump to source 1' }))

      expect(screen.getByRole('button', { name: 'Jump to source 1' })).toBeInTheDocument()
    })
  })

  describe('streaming placeholders', () => {
    it('shows the thinking spinner while waiting with nothing to show yet', () => {
      const { container } = renderList({ isStreaming: true })

      expect(screen.getByText('Thinking…')).toBeInTheDocument()
      expect(waitingSpinner(container)).not.toBeNull()
      expect(screen.queryByTestId('thinking-block')).not.toBeInTheDocument()
    })

    it('renders the partial answer instead of the spinner once tokens arrive', () => {
      const { container } = renderList({ isStreaming: true, streamingContent: 'Partial answer' })

      expect(screen.getByText('Partial answer')).toBeInTheDocument()
      expect(waitingSpinner(container)).toBeNull()
    })

    it('shows a blinking caret rather than the spinner while generating empty content', () => {
      const { container } = renderList({ isStreaming: true, streamingPhase: 'generating' })

      expect(waitingSpinner(container)).toBeNull()
      expect(container.querySelector('.animate-pulse')).not.toBeNull()
    })

    it('replaces the spinner with the live thinking block once status entries arrive', () => {
      const { container } = renderList({
        isStreaming: true,
        streamingStatusEntries: ['Searching docs'],
      })

      expect(screen.getByTestId('thinking-block')).toBeInTheDocument()
      expect(screen.getByText('Searching docs')).toBeInTheDocument()
      expect(waitingSpinner(container)).toBeNull()
    })

    it('shows the streamed reasoning in the thinking block', () => {
      const { container } = renderList({
        isStreaming: true,
        streamingReasoning: 'Weighing the options',
      })

      expect(screen.getByTestId('thinking-block')).toBeInTheDocument()
      expect(screen.getByText('Weighing the options')).toBeInTheDocument()
      expect(waitingSpinner(container)).toBeNull()
    })

    it('keeps the streaming bubble when only a status line is present', () => {
      const { container } = renderList({ messages: [], streamingStatus: 'Retrieving…' })

      expect(screen.getByRole('log')).toBeInTheDocument()
      expect(waitingSpinner(container)).not.toBeNull()
    })
  })

  describe('autoscroll', () => {
    it('scrolls to the bottom when a new message arrives', () => {
      const { rerender } = renderList({ messages: [USER_MSG] })
      vi.mocked(Element.prototype.scrollIntoView).mockClear()

      rerender(
        <LangProvider>
          <MessageList messages={[USER_MSG, ASSISTANT_MSG]} />
        </LangProvider>,
      )

      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth' })
    })

    it('stops autoscrolling after the user scrolls up, and resumes at the bottom', () => {
      const { rerender } = renderList({ messages: [USER_MSG] })
      const log = screen.getByRole('log')

      // Simulate a tall, scrolled-up container.
      Object.defineProperty(log, 'scrollHeight', { value: 1000, configurable: true })
      Object.defineProperty(log, 'clientHeight', { value: 200, configurable: true })
      Object.defineProperty(log, 'scrollTop', { value: 0, configurable: true, writable: true })
      fireEvent.scroll(log)

      vi.mocked(Element.prototype.scrollIntoView).mockClear()
      rerender(
        <LangProvider>
          <MessageList messages={[USER_MSG, ASSISTANT_MSG]} />
        </LangProvider>,
      )
      expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()

      // Scrolling back to the bottom re-arms autoscroll.
      Object.defineProperty(log, 'scrollTop', { value: 800, configurable: true, writable: true })
      fireEvent.scroll(log)

      rerender(
        <LangProvider>
          <MessageList messages={[USER_MSG, ASSISTANT_MSG, USER_MSG]} />
        </LangProvider>,
      )
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    })
  })
})
