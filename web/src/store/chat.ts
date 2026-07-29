import { create } from 'zustand'
import type { StreamPhase, ChatSource } from '@/features/chat/StreamHandler'
import type { ChatMessage } from '@/features/chat/MessageList'
import type { Session } from '@/api/sessions'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionStreamState {
  streaming: boolean
  content: string
  reasoning: string
  statusEntries: string[]
  phase: StreamPhase
  retrievedSources: ChatSource[]
}

export const INITIAL_STREAM_STATE: SessionStreamState = {
  streaming: false,
  content: '',
  reasoning: '',
  statusEntries: [],
  phase: 'idle',
  retrievedSources: [],
}

export const EMPTY_MESSAGES: readonly ChatMessage[] = [] as const

export interface SessionState {
  messages: ChatMessage[]
  streamState: SessionStreamState
  inputDraft: string
  abortController: AbortController | null
  messagesLoaded: boolean
  error: string | null
}

export interface ChatStoreState {
  // Global
  sessions: Session[]
  activeSessionId: string | null

  // Per-session state cache
  sessionStates: Record<string, SessionState>

  // LRU tracking
  _accessOrder: string[]

  // Session list management
  setSessions: (sessions: Session[]) => void
  addSession: (session: Session) => void
  removeSession: (id: string) => void
  updateSessionTitle: (id: string, title: string) => void

  // Active session
  setActiveSession: (id: string | null) => void

  // Per-session state access
  getOrCreateSessionState: (id: string) => SessionState

  // Per-session stream lifecycle
  beginStream: (sessionId: string, controller: AbortController) => void
  endStream: (sessionId: string) => void
  abortStream: (sessionId: string) => void

  // Per-session state mutations (with ghost write guard)
  setMessages: (sessionId: string, messages: ChatMessage[]) => void
  appendMessage: (sessionId: string, msg: ChatMessage) => void
  updateStreamState: (sessionId: string, partial: Partial<SessionStreamState>) => void
  resetStreamState: (sessionId: string) => void
  setInputDraft: (sessionId: string, draft: string) => void
  setMessagesLoaded: (sessionId: string, loaded: boolean) => void
  setSessionError: (sessionId: string, error: string | null) => void

  // Cleanup
  clearSessionState: (sessionId: string) => void
  _evictLRU: () => void
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_CACHED_SESSIONS = 10

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createInitialSessionState(): SessionState {
  return {
    messages: [],
    streamState: { ...INITIAL_STREAM_STATE },
    inputDraft: '',
    abortController: null,
    messagesLoaded: false,
    error: null,
  }
}

/**
 * Move `id` to the end of `order` (most recently used).
 * Returns a new array.
 */
function touchAccessOrder(order: string[], id: string): string[] {
  const filtered = order.filter((x) => x !== id)
  filtered.push(id)
  return filtered
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useChatStore = create<ChatStoreState>()((set, get) => ({
  sessions: [],
  activeSessionId: null,
  sessionStates: {},
  _accessOrder: [],

  // ----- Session list management -----

  setSessions: (sessions) => set({ sessions }),

  addSession: (session) =>
    set((state) => ({ sessions: [session, ...state.sessions] })),

  removeSession: (id) => {
    const { sessionStates } = get()
    const ss = sessionStates[id]
    if (ss?.abortController) {
      ss.abortController.abort()
    }
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== id),
      activeSessionId: state.activeSessionId === id ? null : state.activeSessionId,
      sessionStates: Object.fromEntries(
        Object.entries(state.sessionStates).filter(([k]) => k !== id),
      ),
      _accessOrder: state._accessOrder.filter((x) => x !== id),
    }))
  },

  updateSessionTitle: (id, title) =>
    set((state) => ({
      sessions: state.sessions.map((s) => (s.id === id ? { ...s, title } : s)),
    })),

  // ----- Active session -----

  setActiveSession: (id) => {
    set((state) => {
      const next: Partial<ChatStoreState> = { activeSessionId: id }
      if (id) {
        // Ensure session state exists
        if (!state.sessionStates[id]) {
          next.sessionStates = {
            ...state.sessionStates,
            [id]: createInitialSessionState(),
          }
        }
        next._accessOrder = touchAccessOrder(state._accessOrder, id)
      }
      return next as ChatStoreState
    })
    // Evict after setting (outside the set call to avoid recursion)
    get()._evictLRU()
  },

  // ----- Per-session state access -----

  getOrCreateSessionState: (id) => {
    const { sessionStates } = get()
    if (sessionStates[id]) return sessionStates[id]
    const initial = createInitialSessionState()
    set((state) => ({
      sessionStates: { ...state.sessionStates, [id]: initial },
      _accessOrder: touchAccessOrder(state._accessOrder, id),
    }))
    return initial
  },

  // ----- Per-session stream lifecycle -----

  beginStream: (sessionId, controller) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            abortController: controller,
            streamState: { ...INITIAL_STREAM_STATE, streaming: true },
            error: null,
          },
        },
      }
    }),

  endStream: (sessionId) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            abortController: null,
            streamState: {
              ...state.sessionStates[sessionId].streamState,
              streaming: false,
              phase: 'idle',
            },
          },
        },
      }
    }),

  abortStream: (sessionId) => {
    const { sessionStates } = get()
    const ss = sessionStates[sessionId]
    if (ss?.abortController) {
      ss.abortController.abort()
    }
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            abortController: null,
            streamState: {
              ...state.sessionStates[sessionId].streamState,
              streaming: false,
              phase: 'idle',
            },
          },
        },
      }
    })
  },

  // ----- Per-session state mutations (ghost write guard) -----

  setMessages: (sessionId, messages) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            messages,
          },
        },
      }
    }),

  appendMessage: (sessionId, msg) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            messages: [...state.sessionStates[sessionId].messages, msg],
          },
        },
      }
    }),

  updateStreamState: (sessionId, partial) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            streamState: {
              ...state.sessionStates[sessionId].streamState,
              ...partial,
            },
          },
        },
      }
    }),

  resetStreamState: (sessionId) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            streamState: { ...INITIAL_STREAM_STATE },
          },
        },
      }
    }),

  setInputDraft: (sessionId, draft) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            inputDraft: draft,
          },
        },
      }
    }),

  setMessagesLoaded: (sessionId, loaded) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            messagesLoaded: loaded,
          },
        },
      }
    }),

  setSessionError: (sessionId, error) =>
    set((state) => {
      if (!state.sessionStates[sessionId]) return state
      return {
        sessionStates: {
          ...state.sessionStates,
          [sessionId]: {
            ...state.sessionStates[sessionId],
            error,
          },
        },
      }
    }),

  // ----- Cleanup -----

  clearSessionState: (sessionId) =>
    set((state) => ({
      sessionStates: Object.fromEntries(
        Object.entries(state.sessionStates).filter(([k]) => k !== sessionId),
      ),
      _accessOrder: state._accessOrder.filter((x) => x !== sessionId),
    })),

  _evictLRU: () => {
    const { _accessOrder, sessionStates } = get()
    if (_accessOrder.length <= MAX_CACHED_SESSIONS) return

    const toEvict: string[] = []
    for (const id of _accessOrder) {
      if (_accessOrder.length - toEvict.length <= MAX_CACHED_SESSIONS) break
      const ss = sessionStates[id]
      // Skip sessions with active streams
      if (ss?.abortController !== null) continue
      toEvict.push(id)
    }

    if (toEvict.length === 0) return

    set((state) => {
      const evictSet = new Set(toEvict)
      return {
        sessionStates: Object.fromEntries(
          Object.entries(state.sessionStates).filter(([k]) => !evictSet.has(k)),
        ),
        _accessOrder: state._accessOrder.filter((x) => !evictSet.has(x)),
      }
    })
  },
}))
