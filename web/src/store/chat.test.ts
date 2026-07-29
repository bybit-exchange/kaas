/**
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore, INITIAL_STREAM_STATE } from './chat'
import type { Session } from '@/api/sessions'
import type { ChatMessage } from '@/features/chat/MessageList'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSession(id: string, title = `Session ${id}`): Session {
  return {
    id,
    title,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  }
}

function makeMessage(role: 'user' | 'assistant', content: string): ChatMessage {
  return { role, content }
}

function resetStore() {
  useChatStore.setState({
    sessions: [],
    activeSessionId: null,
    sessionStates: {},
    _accessOrder: [],
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useChatStore', () => {
  beforeEach(() => {
    resetStore()
  })

  // =========================================================================
  // CRUD
  // =========================================================================

  describe('CRUD', () => {
    it('setSessions replaces sessions list', () => {
      const sessions = [makeSession('1'), makeSession('2')]
      useChatStore.getState().setSessions(sessions)
      expect(useChatStore.getState().sessions).toEqual(sessions)
    })

    it('addSession prepends to sessions list', () => {
      const s1 = makeSession('1')
      const s2 = makeSession('2')
      useChatStore.getState().setSessions([s1])
      useChatStore.getState().addSession(s2)
      expect(useChatStore.getState().sessions[0]).toEqual(s2)
      expect(useChatStore.getState().sessions[1]).toEqual(s1)
    })

    it('removeSession removes from sessions list', () => {
      useChatStore.getState().setSessions([makeSession('1'), makeSession('2')])
      useChatStore.getState().removeSession('1')
      expect(useChatStore.getState().sessions).toHaveLength(1)
      expect(useChatStore.getState().sessions[0].id).toBe('2')
    })

    it('removeSession clears activeSessionId if removed session was active', () => {
      useChatStore.getState().setSessions([makeSession('1')])
      useChatStore.getState().setActiveSession('1')
      useChatStore.getState().removeSession('1')
      expect(useChatStore.getState().activeSessionId).toBeNull()
    })

    it('removeSession does not clear activeSessionId if different session is active', () => {
      useChatStore.getState().setSessions([makeSession('1'), makeSession('2')])
      useChatStore.getState().setActiveSession('2')
      useChatStore.getState().removeSession('1')
      expect(useChatStore.getState().activeSessionId).toBe('2')
    })

    it('updateSessionTitle updates the title of a session', () => {
      useChatStore.getState().setSessions([makeSession('1', 'Old')])
      useChatStore.getState().updateSessionTitle('1', 'New')
      expect(useChatStore.getState().sessions[0].title).toBe('New')
    })
  })

  // =========================================================================
  // setActiveSession + LRU
  // =========================================================================

  describe('setActiveSession + LRU', () => {
    it('sets activeSessionId', () => {
      useChatStore.getState().setActiveSession('abc')
      expect(useChatStore.getState().activeSessionId).toBe('abc')
    })

    it('creates session state lazily when setting active', () => {
      useChatStore.getState().setActiveSession('abc')
      const ss = useChatStore.getState().sessionStates['abc']
      expect(ss).toBeDefined()
      expect(ss.messages).toEqual([])
      expect(ss.streamState).toEqual(INITIAL_STREAM_STATE)
      expect(ss.abortController).toBeNull()
    })

    it('does not overwrite existing session state when re-activating', () => {
      useChatStore.getState().setActiveSession('abc')
      useChatStore.getState().setMessages('abc', [makeMessage('user', 'hello')])
      useChatStore.getState().setActiveSession('abc')
      expect(useChatStore.getState().sessionStates['abc'].messages).toHaveLength(1)
    })

    it('updates _accessOrder on setActiveSession', () => {
      useChatStore.getState().setActiveSession('a')
      useChatStore.getState().setActiveSession('b')
      useChatStore.getState().setActiveSession('a')
      const order = useChatStore.getState()._accessOrder
      expect(order[order.length - 1]).toBe('a')
      expect(order[order.length - 2]).toBe('b')
    })

    it('setActiveSession(null) sets activeSessionId to null without affecting state', () => {
      useChatStore.getState().setActiveSession('a')
      useChatStore.getState().setActiveSession(null)
      expect(useChatStore.getState().activeSessionId).toBeNull()
      // session state should still exist
      expect(useChatStore.getState().sessionStates['a']).toBeDefined()
    })
  })

  // =========================================================================
  // updateStreamState isolation
  // =========================================================================

  describe('updateStreamState isolation', () => {
    it('updating session A stream state does not affect session B', () => {
      useChatStore.getState().setActiveSession('a')
      useChatStore.getState().setActiveSession('b')

      useChatStore.getState().updateStreamState('a', { content: 'hello from A' })

      const stateA = useChatStore.getState().sessionStates['a'].streamState
      const stateB = useChatStore.getState().sessionStates['b'].streamState

      expect(stateA.content).toBe('hello from A')
      expect(stateB.content).toBe('')
    })

    it('updating session B stream state does not affect session A', () => {
      useChatStore.getState().setActiveSession('a')
      useChatStore.getState().setActiveSession('b')

      useChatStore.getState().updateStreamState('a', { streaming: true, phase: 'generating' })
      useChatStore.getState().updateStreamState('b', { streaming: true, phase: 'iterating' })

      expect(useChatStore.getState().sessionStates['a'].streamState.phase).toBe('generating')
      expect(useChatStore.getState().sessionStates['b'].streamState.phase).toBe('iterating')
    })
  })

  // =========================================================================
  // Ghost write guard
  // =========================================================================

  describe('ghost write guard', () => {
    it('appendMessage on a non-existent session is a no-op', () => {
      const before = useChatStore.getState().sessionStates
      useChatStore.getState().appendMessage('deleted', makeMessage('user', 'ghost'))
      const after = useChatStore.getState().sessionStates
      expect(after).toEqual(before)
    })

    it('updateStreamState on a deleted session is a no-op', () => {
      useChatStore.getState().setActiveSession('x')
      useChatStore.getState().removeSession('x')
      useChatStore.getState().updateStreamState('x', { content: 'ghost' })
      expect(useChatStore.getState().sessionStates['x']).toBeUndefined()
    })

    it('setMessages on a non-existent session is a no-op', () => {
      useChatStore.getState().setMessages('ghost', [makeMessage('user', 'hi')])
      expect(useChatStore.getState().sessionStates['ghost']).toBeUndefined()
    })

    it('setInputDraft on a deleted session is a no-op', () => {
      useChatStore.getState().setActiveSession('y')
      useChatStore.getState().removeSession('y')
      useChatStore.getState().setInputDraft('y', 'draft')
      expect(useChatStore.getState().sessionStates['y']).toBeUndefined()
    })
  })

  // =========================================================================
  // removeSession auto-abort
  // =========================================================================

  describe('removeSession auto-abort', () => {
    it('calls abortController.abort() when removing a streaming session', () => {
      useChatStore.getState().setActiveSession('s1')
      const abortFn = vi.fn()
      const controller = { abort: abortFn, signal: {} } as unknown as AbortController
      useChatStore.getState().beginStream('s1', controller)

      useChatStore.getState().removeSession('s1')

      expect(abortFn).toHaveBeenCalledTimes(1)
    })

    it('cleans up session state after abort on remove', () => {
      useChatStore.getState().setActiveSession('s1')
      const controller = { abort: vi.fn(), signal: {} } as unknown as AbortController
      useChatStore.getState().beginStream('s1', controller)

      useChatStore.getState().removeSession('s1')

      expect(useChatStore.getState().sessionStates['s1']).toBeUndefined()
      expect(useChatStore.getState()._accessOrder).not.toContain('s1')
    })

    it('does not call abort if session has no active controller', () => {
      useChatStore.getState().setActiveSession('s2')
      // No beginStream → abortController is null
      useChatStore.getState().removeSession('s2')
      // No error thrown, test passes
      expect(useChatStore.getState().sessionStates['s2']).toBeUndefined()
    })
  })

  // =========================================================================
  // Multi-session parallel stream
  // =========================================================================

  describe('multi-session parallel stream', () => {
    it('beginStream on session A and B simultaneously, both work independently', () => {
      useChatStore.getState().setActiveSession('a')
      useChatStore.getState().setActiveSession('b')

      const ctrlA = { abort: vi.fn(), signal: {} } as unknown as AbortController
      const ctrlB = { abort: vi.fn(), signal: {} } as unknown as AbortController

      useChatStore.getState().beginStream('a', ctrlA)
      useChatStore.getState().beginStream('b', ctrlB)

      expect(useChatStore.getState().sessionStates['a'].streamState.streaming).toBe(true)
      expect(useChatStore.getState().sessionStates['b'].streamState.streaming).toBe(true)
      expect(useChatStore.getState().sessionStates['a'].abortController).toBe(ctrlA)
      expect(useChatStore.getState().sessionStates['b'].abortController).toBe(ctrlB)
    })

    it('endStream on A does not affect B', () => {
      useChatStore.getState().setActiveSession('a')
      useChatStore.getState().setActiveSession('b')

      const ctrlA = { abort: vi.fn(), signal: {} } as unknown as AbortController
      const ctrlB = { abort: vi.fn(), signal: {} } as unknown as AbortController

      useChatStore.getState().beginStream('a', ctrlA)
      useChatStore.getState().beginStream('b', ctrlB)
      useChatStore.getState().endStream('a')

      expect(useChatStore.getState().sessionStates['a'].streamState.streaming).toBe(false)
      expect(useChatStore.getState().sessionStates['a'].abortController).toBeNull()
      expect(useChatStore.getState().sessionStates['b'].streamState.streaming).toBe(true)
      expect(useChatStore.getState().sessionStates['b'].abortController).toBe(ctrlB)
    })

    it('abortStream on A calls abort and does not affect B', () => {
      useChatStore.getState().setActiveSession('a')
      useChatStore.getState().setActiveSession('b')

      const ctrlA = { abort: vi.fn(), signal: {} } as unknown as AbortController
      const ctrlB = { abort: vi.fn(), signal: {} } as unknown as AbortController

      useChatStore.getState().beginStream('a', ctrlA)
      useChatStore.getState().beginStream('b', ctrlB)
      useChatStore.getState().abortStream('a')

      expect(ctrlA.abort).toHaveBeenCalledTimes(1)
      expect(ctrlB.abort).not.toHaveBeenCalled()
      expect(useChatStore.getState().sessionStates['b'].streamState.streaming).toBe(true)
    })
  })

  // =========================================================================
  // _evictLRU
  // =========================================================================

  describe('_evictLRU', () => {
    it('evicts the oldest non-streaming session when more than 10 are cached', () => {
      // Activate 11 sessions → oldest should be evicted
      for (let i = 1; i <= 11; i++) {
        useChatStore.getState().setActiveSession(`s${i}`)
      }

      const state = useChatStore.getState()
      // s1 was accessed first and should have been evicted
      expect(state.sessionStates['s1']).toBeUndefined()
      expect(state._accessOrder).not.toContain('s1')
      // s2 through s11 should remain (10 sessions)
      expect(Object.keys(state.sessionStates)).toHaveLength(10)
    })

    it('evicts multiple sessions when many exceed the limit', () => {
      for (let i = 1; i <= 13; i++) {
        useChatStore.getState().setActiveSession(`s${i}`)
      }

      const state = useChatStore.getState()
      expect(state.sessionStates['s1']).toBeUndefined()
      expect(state.sessionStates['s2']).toBeUndefined()
      expect(state.sessionStates['s3']).toBeUndefined()
      expect(Object.keys(state.sessionStates)).toHaveLength(10)
    })

    it('skips sessions with active stream (abortController !== null)', () => {
      // Create 11 sessions. The first one has an active stream.
      useChatStore.getState().setActiveSession('s1')
      const ctrl = { abort: vi.fn(), signal: {} } as unknown as AbortController
      useChatStore.getState().beginStream('s1', ctrl)

      for (let i = 2; i <= 11; i++) {
        useChatStore.getState().setActiveSession(`s${i}`)
      }

      const state = useChatStore.getState()
      // s1 should NOT be evicted because it has an active stream
      expect(state.sessionStates['s1']).toBeDefined()
      expect(state.sessionStates['s1'].abortController).toBe(ctrl)
      // s2 should be evicted instead (oldest without active stream)
      expect(state.sessionStates['s2']).toBeUndefined()
    })

    it('does not evict when at or below the limit', () => {
      for (let i = 1; i <= 10; i++) {
        useChatStore.getState().setActiveSession(`s${i}`)
      }

      const state = useChatStore.getState()
      expect(Object.keys(state.sessionStates)).toHaveLength(10)
      // All should be present
      for (let i = 1; i <= 10; i++) {
        expect(state.sessionStates[`s${i}`]).toBeDefined()
      }
    })
  })
})
