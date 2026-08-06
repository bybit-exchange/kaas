import { useCallback, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useShallow } from 'zustand/shallow'
import { useT } from '@/i18n'
import { streamChat } from '@/api/chat'
import { listSessions, createSession, deleteSession, renameSession, getMessages } from '@/api/sessions'
import { readChatStream } from '@/features/chat/StreamHandler'
import { useChatStore, INITIAL_STREAM_STATE, EMPTY_MESSAGES } from '@/store/chat'
import { useKB } from '@/store/kb'
import { MessageList } from '@/features/chat/MessageList'
import type { ChatMessage } from '@/features/chat/MessageList'
import { MessageInput } from '@/features/chat/MessageInput'
import type { MessageInputHandle } from '@/features/chat/MessageInput'
import { SessionList } from '@/features/chat/SessionList'

export function Chat() {
  const t = useT()
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const inputRef = useRef<MessageInputHandle>(null)
  const prevSessionIdRef = useRef<string | undefined>(sessionId)
  // Answers come from the knowledge base the wiki view has selected.
  const kb = useKB((s) => s.kb)

  // --- Store selectors ---
  const sessions = useChatStore((state) => state.sessions)
  const streamState = useChatStore(
    useShallow((state) => {
      const id = state.activeSessionId
      const ss = id ? state.sessionStates[id] : null
      return ss ? ss.streamState : INITIAL_STREAM_STATE
    }),
  )
  const messages = useChatStore(
    useShallow((state) => {
      const id = state.activeSessionId
      return id
        ? (state.sessionStates[id]?.messages ?? (EMPTY_MESSAGES as unknown as ChatMessage[]))
        : (EMPTY_MESSAGES as unknown as ChatMessage[])
    }),
  )
  const sessionError = useChatStore((state) => {
    const id = state.activeSessionId
    return id ? (state.sessionStates[id]?.error ?? null) : null
  })
  const inputDraft = useChatStore((state) => {
    const id = state.activeSessionId
    return id ? (state.sessionStates[id]?.inputDraft ?? '') : ''
  })

  // --- Load session list on mount ---
  useEffect(() => {
    listSessions()
      .then((s) => useChatStore.getState().setSessions(s))
      .catch(() => {
        toast.error(t('chat.errorLoadSessions'))
      })
  }, [t])

  // --- Sync activeSessionId + load messages when sessionId changes ---
  useEffect(() => {
    const store = useChatStore.getState()

    // Save current draft from previous session before switching
    const prevId = prevSessionIdRef.current
    if (prevId && prevId !== sessionId) {
      const currentDraft = inputRef.current?.getCurrentDraft() ?? ''
      store.setInputDraft(prevId, currentDraft)
    }
    prevSessionIdRef.current = sessionId

    store.setActiveSession(sessionId ?? null)

    if (sessionId) {
      const ss = store.sessionStates[sessionId]
      if (!ss || !ss.messagesLoaded) {
        getMessages(sessionId)
          .then((msgs) => {
            const mapped: ChatMessage[] = msgs.map((m) => ({
              id: m.id,
              role: m.role,
              content: m.content,
              citedSources: m.sources,
              usage: m.usage,
              created_at: m.created_at,
            }))
            useChatStore.getState().setMessages(sessionId, mapped)
            useChatStore.getState().setMessagesLoaded(sessionId, true)
          })
          .catch(() => {
            useChatStore.getState().setSessionError(sessionId, t('chat.errorLoadMessages'))
          })
      }
    }
  }, [sessionId, t])

  // --- Abort all active streams on page unload ---
  useEffect(() => {
    return () => {
      const { sessionStates } = useChatStore.getState()
      Object.entries(sessionStates).forEach(([, ss]) => {
        ss.abortController?.abort()
      })
    }
  }, [])

  const handleStop = useCallback(() => {
    if (!sessionId) return
    const store = useChatStore.getState()
    const ss = store.sessionStates[sessionId]
    // Save partial content before aborting
    if (ss?.streamState.content) {
      store.appendMessage(sessionId, {
        role: 'assistant' as const,
        content: ss.streamState.content,
      })
    }
    store.resetStreamState(sessionId)
    store.abortStream(sessionId)
  }, [sessionId])

  const handleNewChat = useCallback(() => {
    handleStop()
    navigate('/chat')
  }, [handleStop, navigate])

  const handleSelectSession = useCallback(
    (id: string) => {
      navigate('/chat/' + id)
    },
    [navigate],
  )

  const handleDeleteSession = useCallback(
    async (id: string) => {
      try {
        await deleteSession(id)
        useChatStore.getState().removeSession(id)
        if (sessionId === id) {
          navigate('/chat')
        }
      } catch {
        toast.error(t('chat.errorDeleteSession'))
      }
    },
    [sessionId, navigate, t],
  )

  const handleRenameSession = useCallback(
    async (id: string, title: string) => {
      try {
        const updated = await renameSession(id, title)
        useChatStore.getState().updateSessionTitle(id, updated.title)
      } catch {
        toast.error(t('chat.errorRenameSession'))
      }
    },
    [t],
  )

  const handleSend = useCallback(
    async (query: string) => {
      const store = useChatStore.getState()

      // Determine or create session
      let currentSessionId = sessionId
      if (!currentSessionId) {
        try {
          const session = await createSession(query.slice(0, 100))
          store.addSession(session)
          currentSessionId = session.id
          // Mark messages as loaded so we don't refetch on navigate
          store.setMessages(currentSessionId, [])
          store.setMessagesLoaded(currentSessionId, true)
          navigate('/chat/' + session.id)
        } catch {
          toast.error(t('chat.errorCreateSession'))
          return
        }
      }

      // Capture sessionId in closure for stream callbacks
      const targetSessionId = currentSessionId

      // Abort any in-flight stream for this session
      const currentSS = store.sessionStates[targetSessionId]
      if (currentSS?.abortController) {
        store.abortStream(targetSessionId)
      }

      // Clear error
      store.setSessionError(targetSessionId, null)

      // Create new AbortController
      const controller = new AbortController()
      store.beginStream(targetSessionId, controller)

      // Optimistic user message
      const userMsg: ChatMessage = { role: 'user', content: query }
      store.appendMessage(targetSessionId, userMsg)

      // Build history for context (exclude current user msg — backend gets query separately)
      const currentMessages =
        useChatStore.getState().sessionStates[targetSessionId]?.messages ?? []
      const history = currentMessages
        .filter((m) => m !== userMsg)
        .map((m) => ({ role: m.role, content: m.content }))

      // Local content accumulator for the stream closure
      let contentAcc = ''
      let reasoningAcc = ''
      const statusEntriesAcc: string[] = []

      try {
        const res = await streamChat(
          { query, messages: history, include_sources: true, session_id: targetSessionId },
          controller.signal,
          kb,
        )

        await readChatStream(res, (event) => {
          switch (event.kind) {
            case 'status': {
              if (event.statusInfo) {
                let text: string
                if (event.statusInfo.type === 'retrieved') {
                  text = t('chat.statusRetrieved', { count: event.statusInfo.count })
                } else {
                  text = event.statusInfo.text
                }
                statusEntriesAcc.push(text)
              }
              useChatStore.getState().updateStreamState(targetSessionId, {
                statusEntries: [...statusEntriesAcc],
                retrievedSources: event.sources,
              })
              break
            }
            case 'reasoning': {
              reasoningAcc += event.content
              useChatStore.getState().updateStreamState(targetSessionId, {
                reasoning: reasoningAcc,
              })
              break
            }
            case 'role': {
              useChatStore.getState().updateStreamState(targetSessionId, {
                phase: 'generating',
              })
              break
            }
            case 'delta': {
              contentAcc += event.content
              useChatStore.getState().updateStreamState(targetSessionId, {
                content: contentAcc,
                phase: 'generating',
                streaming: true,
              })
              break
            }
            case 'done': {
              const assistantMsg: ChatMessage = {
                role: 'assistant' as const,
                content: contentAcc,
                citedSources: event.citedSources,
                usage: event.usage,
              }
              const s = useChatStore.getState()
              s.appendMessage(targetSessionId, assistantMsg)
              s.resetStreamState(targetSessionId)
              s.endStream(targetSessionId)
              // Refresh session list (title may have been updated by backend)
              listSessions()
                .then((sessions) => useChatStore.getState().setSessions(sessions))
                .catch(() => {})
              break
            }
            case 'error': {
              toast.error(event.message || t('chat.errorStream'))
              const s = useChatStore.getState()
              s.resetStreamState(targetSessionId)
              s.endStream(targetSessionId)
              break
            }
          }
        })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          // User-initiated stop — partial content already saved by handleStop
          return
        }
        toast.error(t('chat.errorStream'))
        const s = useChatStore.getState()
        s.resetStreamState(targetSessionId)
        s.endStream(targetSessionId)
      }
    },
    [sessionId, navigate, t, kb],
  )

  return (
    <div className="flex flex-1 overflow-hidden">
      <SessionList
        sessions={sessions}
        activeSessionId={sessionId}
        onNewChat={handleNewChat}
        onSelect={handleSelectSession}
        onDelete={handleDeleteSession}
        onRename={handleRenameSession}
      />
      <div className="flex flex-1 flex-col overflow-hidden">
        {sessionError && (
          <div
            className="mx-4 mt-2 rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive"
            role="alert"
          >
            <div className="flex items-center justify-between">
              <span>{sessionError}</span>
              <button
                onClick={() => {
                  if (sessionId) {
                    useChatStore.getState().setSessionError(sessionId, null)
                  }
                }}
                className="ml-2 text-destructive/70 hover:text-destructive"
                aria-label="close"
              >
                &times;
              </button>
            </div>
          </div>
        )}

        <MessageList
          messages={messages}
          streamingContent={streamState.streaming ? streamState.content : undefined}
          streamingStatus={streamState.streaming && streamState.phase === 'iterating' ? t('chat.thinking') : null}
          streamingReasoning={streamState.streaming ? streamState.reasoning : undefined}
          streamingStatusEntries={streamState.streaming ? streamState.statusEntries : undefined}
          streamingPhase={streamState.phase}
          isStreaming={streamState.streaming}
        />

        <MessageInput
          ref={inputRef}
          onSend={handleSend}
          onStop={handleStop}
          streaming={streamState.streaming}
          disabled={streamState.streaming}
          draft={inputDraft}
          onDraftChange={(v) => {
            if (sessionId) {
              useChatStore.getState().setInputDraft(sessionId, v)
            }
          }}
        />
      </div>
    </div>
  )
}
