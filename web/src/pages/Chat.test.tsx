import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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
import { readChatStream } from '@/features/chat/StreamHandler'
import type { StreamEvent } from '@/features/chat/StreamHandler'
import { listSessions, createSession, deleteSession, renameSession, getMessages } from '@/api/sessions'
import { toast } from 'sonner'
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

const SESSION_TS = { created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }

/** An idle per-session state, with overrides for whatever the test cares about. */
function sessionState(overrides: Record<string, unknown> = {}) {
  return {
    messages: [],
    streamState: {
      streaming: false,
      content: '',
      reasoning: '',
      statusEntries: [],
      phase: 'idle' as const,
      retrievedSources: [],
    },
    inputDraft: '',
    abortController: null,
    messagesLoaded: true,
    error: null,
    ...overrides,
  }
}

/** Seed the store with sessions that are already loaded, so handleSend streams
 *  straight away instead of creating a session first. */
function seedSessions(ids: string[], stateOverrides: Record<string, Record<string, unknown>> = {}) {
  const sessions = ids.map((id) => ({ id, title: `Title ${id}`, ...SESSION_TS }))
  useChatStore.setState({
    sessions,
    activeSessionId: ids[0],
    sessionStates: Object.fromEntries(ids.map((id) => [id, sessionState(stateOverrides[id])])),
    _accessOrder: ids,
  })
  // The page refetches the list on mount and overwrites the store with the
  // result, so the fake backend has to agree with the seed.
  vi.mocked(listSessions).mockResolvedValue(sessions)
}

/** Replace the stream script for exactly one call. */
function streamOnce(events: StreamEvent[]) {
  vi.mocked(readChatStream).mockImplementationOnce((_res, onEvent) => {
    events.forEach((e) => onEvent(e))
    return Promise.resolve()
  })
}

/** Type a query and submit it. */
async function send(user: ReturnType<typeof userEvent.setup>, query = 'what is kaas') {
  await user.type(screen.getByRole('textbox'), query)
  await user.keyboard('{Enter}')
}

/** The clickable row for a session, by its title. */
function sessionRow(title: string): HTMLElement {
  const row = screen.getByText(title).closest('[role="button"]')
  if (!row) throw new Error(`session row ${title} not found`)
  return row as HTMLElement
}

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

  describe('loading a conversation', () => {
    it('warns when the conversation list cannot be fetched', async () => {
      vi.mocked(listSessions).mockRejectedValueOnce(new Error('offline'))

      render(
        <Wrapper>
          <Chat />
        </Wrapper>,
      )

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Failed to load conversations'),
      )
    })

    it('fetches and renders the history of a session opened by URL', async () => {
      vi.mocked(getMessages).mockResolvedValueOnce([
        {
          id: 'm1',
          role: 'user',
          content: 'earlier question',
          created_at: '2026-01-01T00:00:00Z',
        },
        {
          id: 'm2',
          role: 'assistant',
          content: 'earlier answer',
          sources: [{ title: 'Doc', path: 'x.md' }],
          usage: { tokens_prompt: 1, tokens_completion: 2, cost_usd: 0.001 },
          created_at: '2026-01-01T00:00:01Z',
        },
      ] as never)

      render(
        <Wrapper initialEntries={['/chat/session-1']}>
          <Chat />
        </Wrapper>,
      )

      expect(await screen.findByText('earlier question')).toBeInTheDocument()
      expect(screen.getByText('earlier answer')).toBeInTheDocument()
      expect(vi.mocked(getMessages)).toHaveBeenCalledWith('session-1')
    })

    it('does not refetch history that is already in the store', async () => {
      seedSessions(['session-1'], {
        'session-1': { messages: [{ role: 'user', content: 'cached' }] },
      })

      render(
        <Wrapper initialEntries={['/chat/session-1']}>
          <Chat />
        </Wrapper>,
      )

      expect(await screen.findByText('cached')).toBeInTheDocument()
      expect(vi.mocked(getMessages)).not.toHaveBeenCalled()
    })

    // The error is per-session and dismissible, because the user can still send
    // a new message in a session whose history failed to load.
    it('shows a dismissible banner when the history fails to load', async () => {
      vi.mocked(getMessages).mockRejectedValueOnce(new Error('boom'))
      const user = userEvent.setup()

      render(
        <Wrapper initialEntries={['/chat/session-1']}>
          <Chat />
        </Wrapper>,
      )

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent('Failed to load messages')

      await user.click(screen.getByRole('button', { name: 'close' }))

      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })

  describe('managing sessions', () => {
    it('switches to the session that was clicked', async () => {
      const user = userEvent.setup()
      seedSessions(['s1', 's2'])

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )

      await user.click(sessionRow('Title s2'))

      await waitFor(() => expect(sessionRow('Title s2')).toHaveAttribute('aria-current', 'page'))
      expect(sessionRow('Title s1')).not.toHaveAttribute('aria-current')
    })

    it('leaves the current session when starting a new chat', async () => {
      const user = userEvent.setup()
      seedSessions(['s1'])

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )

      await user.click(screen.getByRole('button', { name: /New chat/i }))

      await waitFor(() => expect(sessionRow('Title s1')).not.toHaveAttribute('aria-current'))
    })

    // Whatever has already streamed is worth keeping: abandoning a half-written
    // answer would lose the only copy, since the backend never saw it complete.
    it('keeps the partial answer when a stream is interrupted by a new chat', async () => {
      const user = userEvent.setup()
      seedSessions(['s1'], {
        s1: {
          streamState: {
            streaming: true,
            content: 'half an answer',
            reasoning: '',
            statusEntries: [],
            phase: 'generating',
            retrievedSources: [],
          },
          abortController: new AbortController(),
        },
      })

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )

      await user.click(screen.getByRole('button', { name: /New chat/i }))

      await waitFor(() => {
        const msgs = useChatStore.getState().sessionStates['s1'].messages
        expect(msgs.at(-1)).toMatchObject({ role: 'assistant', content: 'half an answer' })
      })
      expect(useChatStore.getState().sessionStates['s1'].streamState.streaming).toBe(false)
    })

    it('deletes a session and drops it from the list', async () => {
      const user = userEvent.setup()
      seedSessions(['s1', 's2'])

      render(
        <Wrapper initialEntries={['/chat/s2']}>
          <Chat />
        </Wrapper>,
      )

      const buttons = within(sessionRow('Title s1')).getAllByRole('button')
      await user.click(buttons[buttons.length - 1])
      await user.click(screen.getByRole('button', { name: 'Delete' }))

      await waitFor(() => expect(vi.mocked(deleteSession)).toHaveBeenCalledWith('s1'))
      await waitFor(() => expect(screen.queryByText('Title s1')).not.toBeInTheDocument())
    })

    it('keeps the session listed when the delete fails', async () => {
      vi.mocked(deleteSession).mockRejectedValueOnce(new Error('locked'))
      const user = userEvent.setup()
      seedSessions(['s1'])

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )

      const buttons = within(sessionRow('Title s1')).getAllByRole('button')
      await user.click(buttons[buttons.length - 1])
      await user.click(screen.getByRole('button', { name: 'Delete' }))

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Failed to delete conversation'),
      )
      expect(screen.getByText('Title s1')).toBeInTheDocument()
    })

    it('renames a session in place', async () => {
      vi.mocked(renameSession).mockResolvedValueOnce({
        id: 's1',
        title: 'Pricing questions',
        ...SESSION_TS,
      })
      const user = userEvent.setup()
      seedSessions(['s1'])

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )

      await user.dblClick(sessionRow('Title s1'))
      const input = screen.getByDisplayValue('Title s1')
      await user.clear(input)
      await user.type(input, 'Pricing questions{Enter}')

      await waitFor(() =>
        expect(vi.mocked(renameSession)).toHaveBeenCalledWith('s1', 'Pricing questions'),
      )
      expect(await screen.findByText('Pricing questions')).toBeInTheDocument()
    })

    it('reports a rename that the server rejects', async () => {
      vi.mocked(renameSession).mockRejectedValueOnce(new Error('nope'))
      const user = userEvent.setup()
      seedSessions(['s1'])

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )

      await user.dblClick(sessionRow('Title s1'))
      const input = screen.getByDisplayValue('Title s1')
      await user.clear(input)
      await user.type(input, 'New name{Enter}')

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Failed to rename conversation'),
      )
    })

    // Each session keeps its own unsent text, so switching away to check another
    // conversation cannot lose what the user was in the middle of typing.
    it('preserves the unsent draft of the session being left', async () => {
      const user = userEvent.setup()
      seedSessions(['s1', 's2'])

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )

      await user.type(screen.getByRole('textbox'), 'half-typed question')
      await user.click(sessionRow('Title s2'))

      await waitFor(() =>
        expect(useChatStore.getState().sessionStates['s1'].inputDraft).toBe('half-typed question'),
      )
    })
  })

  describe('sending the first message of a conversation', () => {
    it('creates the session before streaming', async () => {
      const user = userEvent.setup()

      render(
        <Wrapper>
          <Chat />
        </Wrapper>,
      )

      await send(user, 'brand new question')

      await waitFor(() =>
        expect(vi.mocked(createSession)).toHaveBeenCalledWith('brand new question'),
      )
      await waitFor(() => expect(streamChat).toHaveBeenCalled())
    })

    it('does not stream when the session cannot be created', async () => {
      vi.mocked(createSession).mockRejectedValueOnce(new Error('quota'))
      const user = userEvent.setup()

      render(
        <Wrapper>
          <Chat />
        </Wrapper>,
      )

      await send(user)

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Failed to create conversation'),
      )
      expect(streamChat).not.toHaveBeenCalled()
    })
  })

  describe('stream events', () => {
    async function renderAndSend(events: StreamEvent[]) {
      const user = userEvent.setup()
      seedSessions(['s1'])
      streamOnce(events)

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )
      await send(user)
      return user
    }

    it('counts the articles a retrieval step found', async () => {
      await renderAndSend([
        { kind: 'status', statusInfo: { type: 'retrieved', count: 3 }, sources: [] },
        { kind: 'delta', content: 'answer' },
      ] as never)

      expect(await screen.findByText(/Retrieved 3 relevant articles/)).toBeInTheDocument()
    })

    it('passes through a status message the backend phrased itself', async () => {
      await renderAndSend([
        { kind: 'status', statusInfo: { type: 'searching', text: 'Refining the query' }, sources: [] },
        { kind: 'delta', content: 'answer' },
      ] as never)

      expect(await screen.findByText(/Refining the query/)).toBeInTheDocument()
    })

    it('accumulates the model’s reasoning', async () => {
      await renderAndSend([
        { kind: 'reasoning', content: 'First I check ' },
        { kind: 'reasoning', content: 'the pricing page.' },
        { kind: 'delta', content: 'answer' },
      ] as never)

      expect(await screen.findByText(/First I check the pricing page\./)).toBeInTheDocument()
    })

    it('starts generating once the assistant role arrives', async () => {
      await renderAndSend([{ kind: 'role' }, { kind: 'delta', content: 'the answer' }] as never)

      expect(await screen.findByText('the answer')).toBeInTheDocument()
      await waitFor(() =>
        expect(useChatStore.getState().sessionStates['s1'].streamState.phase).toBe('generating'),
      )
    })

    it('surfaces an error the backend reported mid-stream', async () => {
      await renderAndSend([{ kind: 'error', message: 'model overloaded' }] as never)

      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('model overloaded'))
      expect(useChatStore.getState().sessionStates['s1'].streamState.streaming).toBe(false)
    })

    it('falls back to a generic message for an unexplained stream error', async () => {
      await renderAndSend([{ kind: 'error', message: '' }] as never)

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Stream error. Please try again.'),
      )
    })

    it('reports a request that fails before any event arrives', async () => {
      const user = userEvent.setup()
      seedSessions(['s1'])
      vi.mocked(streamChat).mockRejectedValueOnce(new Error('connection reset'))

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )
      await send(user)

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Stream error. Please try again.'),
      )
      expect(useChatStore.getState().sessionStates['s1'].streamState.streaming).toBe(false)
    })

    // Stopping is not a failure, so it must not raise a toast — the partial
    // answer has already been saved by the stop handler.
    it('stays quiet when the user aborts the stream', async () => {
      const user = userEvent.setup()
      seedSessions(['s1'])
      vi.mocked(streamChat).mockRejectedValueOnce(
        new DOMException('The operation was aborted.', 'AbortError'),
      )

      render(
        <Wrapper initialEntries={['/chat/s1']}>
          <Chat />
        </Wrapper>,
      )
      await send(user)

      await waitFor(() => expect(streamChat).toHaveBeenCalled())
      expect(toast.error).not.toHaveBeenCalled()
    })
  })
})
