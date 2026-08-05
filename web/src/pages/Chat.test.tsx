import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { useChatStore } from '@/store/chat'
import { useKB } from '@/store/kb'

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: { error: vi.fn() },
}))

// Mock sessions API
vi.mock('@/api/sessions', () => ({
  listSessions: vi.fn().mockResolvedValue([]),
  createSession: vi.fn().mockResolvedValue({
    id: 'session-1',
    title: 'Test session',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }),
  deleteSession: vi.fn().mockResolvedValue(undefined),
  renameSession: vi.fn().mockResolvedValue({ id: 'session-1', title: 'Renamed', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }),
  getMessages: vi.fn().mockResolvedValue([]),
}))

// Mock streamChat to return a dummy Response
vi.mock('@/api/chat', () => ({
  streamChat: vi.fn().mockResolvedValue(new Response()),
}))

// Mock readChatStream to synchronously call onEvent with the scenario
vi.mock('@/features/chat/StreamHandler', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/chat/StreamHandler')>()
  return {
    ...actual,
    readChatStream: vi.fn().mockImplementation(
      (_res: Response, onEvent: (e: import('@/features/chat/StreamHandler').StreamEvent) => void) => {
        onEvent({ kind: 'status', sources: [{ title: 'Doc', path: 'x.md' }] })
        onEvent({ kind: 'delta', content: 'Hello ' })
        onEvent({ kind: 'delta', content: '[1]' })
        onEvent({
          kind: 'done',
          citedSources: [{ title: 'Doc', path: 'x.md' }],
          retrievedSources: [],
          usage: { tokens_prompt: 5, tokens_completion: 7, cost_usd: 0.01 },
        })
        return Promise.resolve()
      },
    ),
  }
})

// Import AFTER mocking
import { streamChat } from '@/api/chat'
import { Chat } from './Chat'

function Wrapper({ children, initialEntries = ['/chat'] }: { children: React.ReactNode; initialEntries?: string[] }) {
  return (
    <MemoryRouter initialEntries={initialEntries}>
      <LangProvider>
        <Routes>
          <Route path="/chat" element={children} />
          <Route path="/chat/:sessionId" element={children} />
        </Routes>
      </LangProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  // Reset stores to clean state
  useChatStore.setState({
    sessions: [],
    activeSessionId: null,
    sessionStates: {},
    _accessOrder: [],
  })
  usePrefs.setState({ theme: 'light', lang: 'en' })
  useKB.setState({ kb: null })
  vi.clearAllMocks()
})

describe('Chat page', () => {
  it('streams answer, shows citation marker, source panel with Doc, and usage', async () => {
    const user = userEvent.setup()

    // Pre-setup: render at /chat/session-1 with session already in store
    // so that handleSend bypasses session creation and streams directly.
    useChatStore.setState({
      sessions: [{ id: 'session-1', title: 'Test', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }],
      activeSessionId: 'session-1',
      sessionStates: {
        'session-1': {
          messages: [],
          streamState: { streaming: false, content: '', reasoning: '', statusEntries: [], phase: 'idle', retrievedSources: [] },
          inputDraft: '',
          abortController: null,
          messagesLoaded: true,
          error: null,
        },
      },
      _accessOrder: ['session-1'],
    })

    render(
      <Wrapper initialEntries={['/chat/session-1']}>
        <Chat />
      </Wrapper>,
    )

    // Find the textarea and type a query
    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'what is kaas')

    // Submit via Enter
    await user.keyboard('{Enter}')

    // Wait for the streamed text to appear
    await waitFor(() => {
      expect(screen.getByText(/Hello/)).toBeInTheDocument()
    })

    // Citation marker [1] should be rendered as a button
    await waitFor(() => {
      const citeButtons = screen.getAllByRole('button', { name: /Jump to source 1/i })
      expect(citeButtons.length).toBeGreaterThan(0)
    })

    // Source panel shows Doc
    await waitFor(() => {
      expect(screen.getByText('Doc')).toBeInTheDocument()
    })

    // Source panel link links to the wiki route
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /Doc/ })
      expect(link).toHaveAttribute('href', '/wiki/x.md')
    })

    // Usage is shown (tokens + cost)
    await waitFor(() => {
      const usageEl = screen.getByTestId('usage')
      expect(usageEl).toHaveTextContent('12 tokens')
      expect(usageEl).toHaveTextContent('USD')
    })
  })

  it('resets store state between tests (session list is empty)', () => {
    expect(useChatStore.getState().sessions).toHaveLength(0)
    expect(useChatStore.getState().activeSessionId).toBeNull()
    expect(useChatStore.getState().sessionStates).toEqual({})
  })

  it('maintains per-session state when switching sessions', () => {
    const store = useChatStore.getState()

    // Set up two sessions
    store.setSessions([
      { id: 's1', title: 'Session 1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      { id: 's2', title: 'Session 2', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ])

    // Activate s1 and add messages
    store.setActiveSession('s1')
    store.setMessages('s1', [{ role: 'user', content: 'Hello from s1' }])
    store.setMessagesLoaded('s1', true)

    // Activate s2 and add different messages
    store.setActiveSession('s2')
    store.setMessages('s2', [{ role: 'user', content: 'Hello from s2' }])
    store.setMessagesLoaded('s2', true)

    // Switch back to s1 — it should retain its messages
    store.setActiveSession('s1')
    const s1State = useChatStore.getState().sessionStates['s1']
    expect(s1State.messages).toHaveLength(1)
    expect(s1State.messages[0].content).toBe('Hello from s1')

    // s2 should still have its messages
    const s2State = useChatStore.getState().sessionStates['s2']
    expect(s2State.messages).toHaveLength(1)
    expect(s2State.messages[0].content).toBe('Hello from s2')
  })

  it('supports parallel streams in different sessions', () => {
    const store = useChatStore.getState()

    store.setSessions([
      { id: 's1', title: 'Session 1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      { id: 's2', title: 'Session 2', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ])

    // Start streams in both sessions
    store.setActiveSession('s1')
    const c1 = new AbortController()
    store.beginStream('s1', c1)

    store.setActiveSession('s2')
    const c2 = new AbortController()
    store.beginStream('s2', c2)

    // Both sessions should be streaming independently
    const state = useChatStore.getState()
    expect(state.sessionStates['s1'].streamState.streaming).toBe(true)
    expect(state.sessionStates['s2'].streamState.streaming).toBe(true)

    // Update s1 content
    store.updateStreamState('s1', { content: 'partial answer s1', phase: 'generating' })

    // Update s2 content
    store.updateStreamState('s2', { content: 'partial answer s2', phase: 'generating' })

    // Verify both have independent content
    const updatedState = useChatStore.getState()
    expect(updatedState.sessionStates['s1'].streamState.content).toBe('partial answer s1')
    expect(updatedState.sessionStates['s2'].streamState.content).toBe('partial answer s2')

    // End s1 stream — s2 should continue
    store.endStream('s1')
    const afterEnd = useChatStore.getState()
    expect(afterEnd.sessionStates['s1'].streamState.streaming).toBe(false)
    expect(afterEnd.sessionStates['s2'].streamState.streaming).toBe(true)
  })

  it('scopes the chat stream to the selected knowledge base', async () => {
    const user = userEvent.setup()
    useKB.setState({ kb: 'pricing' })
    useChatStore.setState({
      sessions: [{ id: 'session-1', title: 'Test', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }],
      activeSessionId: 'session-1',
      sessionStates: {
        'session-1': {
          messages: [],
          streamState: { streaming: false, content: '', reasoning: '', statusEntries: [], phase: 'idle', retrievedSources: [] },
          inputDraft: '',
          abortController: null,
          messagesLoaded: true,
          error: null,
        },
      },
      _accessOrder: ['session-1'],
    })

    render(
      <Wrapper initialEntries={['/chat/session-1']}>
        <Chat />
      </Wrapper>,
    )

    await user.type(screen.getByRole('textbox'), 'what is kaas')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(streamChat).toHaveBeenCalledWith(
        expect.objectContaining({ query: 'what is kaas' }),
        expect.anything(),
        'pricing',
      )
    })
  })
})
