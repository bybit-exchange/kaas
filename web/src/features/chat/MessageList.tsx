import { useCallback, useEffect, useRef } from 'react'
import { Loader2 } from 'lucide-react'
import { useT } from '@/i18n'
import type { ChatSource, ChatUsage, StreamPhase } from './StreamHandler'
import { SourcePanel } from './SourcePanel'
import { MarkdownRenderer } from './MarkdownRenderer'
import { ThinkingBlock } from './ThinkingBlock'
import { cn } from '@/lib/cn'

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  citedSources?: ChatSource[]
  usage?: ChatUsage
  created_at?: string
  reasoning?: string
  statusEntries?: string[]
}

interface MessageListProps {
  messages: ChatMessage[]
  streamingContent?: string
  streamingStatus?: string | null
  streamingReasoning?: string
  streamingStatusEntries?: string[]
  streamingPhase?: StreamPhase
  isStreaming?: boolean
  onCitationClick?: (index: number) => void
}

const SCROLL_THRESHOLD = 100

export function MessageList({
  messages,
  streamingContent,
  streamingStatus,
  streamingReasoning,
  streamingStatusEntries,
  streamingPhase,
  isStreaming,
  onCitationClick,
}: MessageListProps) {
  const t = useT()
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const isAtBottomRef = useRef(true)

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    isAtBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
  }, [])

  useEffect(() => {
    if (isAtBottomRef.current && typeof bottomRef.current?.scrollIntoView === 'function') {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages.length, streamingContent, streamingStatus, streamingReasoning, streamingStatusEntries])

  const handleCitationClick = useCallback(
    (index: number) => {
      onCitationClick?.(index)
      const el = document.getElementById(`source-${index}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        el.classList.add('bg-primary/10')
        setTimeout(() => el.classList.remove('bg-primary/10'), 1500)
      }
    },
    [onCitationClick],
  )

  if (messages.length === 0 && !streamingContent && !streamingStatus && !isStreaming) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-4 text-muted-foreground">
        <p className="text-lg font-medium text-foreground">{t('chat.welcome')}</p>
      </div>
    )
  }

  return (
    <div
      ref={scrollContainerRef}
      onScroll={handleScroll}
      className="flex flex-1 flex-col overflow-y-auto px-4 py-6"
      role="log"
      aria-live="polite"
    >
      <div className="mx-auto w-full max-w-3xl space-y-6">
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}
          >
            <div
              className={cn(
                'max-w-[100%]',
                msg.role === 'user'
                  ? 'rounded-2xl px-4 py-2 bg-primary text-primary-foreground'
                  : 'px-1',
              )}
            >
              {msg.role === 'assistant' ? (
                <>
                  {(msg.reasoning || msg.statusEntries?.length) && (
                    <ThinkingBlock
                      statusEntries={msg.statusEntries ?? []}
                      reasoning={msg.reasoning ?? ''}
                      phase="idle"
                      isStreaming={false}
                      defaultExpanded={false}
                    />
                  )}
                  <MarkdownRenderer
                    content={msg.content}
                    onCitationClick={handleCitationClick}
                  />
                  {msg.citedSources && msg.citedSources.length > 0 && (
                    <SourcePanel sources={msg.citedSources} />
                  )}
                  {msg.usage && (
                    <p className="mt-2 text-[11px] text-muted-foreground/70" data-testid="usage">
                      {[
                        (msg.usage.tokens_prompt + msg.usage.tokens_completion) + ' tokens',
                        msg.usage.cost_usd
                          ? msg.usage.cost_usd.toFixed(4) + ' USD'
                          : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                  )}
                </>
              ) : (
                <p className="whitespace-pre-wrap text-[0.9375rem] leading-7">{msg.content}</p>
              )}
            </div>
          </div>
        ))}

        {(streamingContent || streamingStatus || isStreaming) && (
          <div className="flex justify-start" aria-live="polite" aria-atomic="false">
            <div className="max-w-[100%] px-1">
              {/* Upper: ThinkingBlock */}
              {((streamingStatusEntries && streamingStatusEntries.length > 0) || streamingReasoning) && (
                <ThinkingBlock
                  statusEntries={streamingStatusEntries ?? []}
                  reasoning={streamingReasoning ?? ''}
                  phase={streamingPhase ?? 'idle'}
                  isStreaming={true}
                  defaultExpanded={true}
                />
              )}
              {/* Lower: Content */}
              {streamingContent ? (
                <MarkdownRenderer
                  content={streamingContent}
                  onCitationClick={handleCitationClick}
                />
              ) : streamingPhase === 'generating' ? (
                <span className="inline-block h-4 w-0.5 animate-pulse bg-foreground/60" />
              ) : !(streamingStatusEntries?.length) && !streamingReasoning ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>{t('chat.thinking')}</span>
                </div>
              ) : null}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
