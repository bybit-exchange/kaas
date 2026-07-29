import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Loader2, Search } from 'lucide-react'
import { MarkdownRenderer } from './MarkdownRenderer'
import { cn } from '@/lib/cn'
import { useT } from '@/i18n'
import type { StreamPhase } from './StreamHandler'

export interface ThinkingBlockProps {
  statusEntries: string[]
  reasoning: string
  phase: StreamPhase
  isStreaming: boolean
  defaultExpanded?: boolean
  /** Truncate when entry count exceeds this threshold (default: 50) */
  truncateThreshold?: number
  /** Max visible entries when truncated (default: 30) */
  maxVisibleEntries?: number
}

export function ThinkingBlock({
  statusEntries,
  reasoning,
  phase,
  isStreaming,
  defaultExpanded = false,
  truncateThreshold = 50,
  maxVisibleEntries = 30,
}: ThinkingBlockProps) {
  const t = useT()

  // --- All hooks unconditionally at the top ---
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [showAll, setShowAll] = useState(false)
  const userToggledRef = useRef(false)
  const prevIsStreamingRef = useRef(isStreaming)
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isStreaming && !prevIsStreamingRef.current) {
      userToggledRef.current = false
      setExpanded(true)
    }
    prevIsStreamingRef.current = isStreaming
  }, [isStreaming])

  useEffect(() => {
    if (!isStreaming && !userToggledRef.current) {
      setExpanded(false)
    }
  }, [isStreaming])

  useEffect(() => {
    if (isStreaming && expanded && contentRef.current) {
      contentRef.current.scrollTo({ top: contentRef.current.scrollHeight })
    }
  }, [statusEntries, reasoning, isStreaming, expanded])

  const handleToggle = useCallback(() => {
    userToggledRef.current = true
    setExpanded((prev) => !prev)
  }, [])

  // --- Conditional return AFTER all hooks ---
  if (statusEntries.length === 0 && !reasoning) {
    return null
  }

  const shouldTruncate = statusEntries.length > truncateThreshold && !showAll
  const visibleEntries = shouldTruncate
    ? statusEntries.slice(-maxVisibleEntries)
    : statusEntries

  const isIterating = isStreaming && phase === 'iterating'

  return (
    <div data-testid="thinking-block" className="mb-3">
      {/* Header */}
      <button
        type="button"
        onClick={handleToggle}
        aria-expanded={expanded}
        data-testid="thinking-block-toggle"
        className="group flex items-center gap-1.5 text-xs text-muted-foreground/80 hover:text-muted-foreground transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 transition-transform" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform" />
        )}
        {isIterating ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>{t('chat.thinkingProcess')}</span>
          </>
        ) : (
          <span>{expanded ? t('chat.thinkingProcess') : t('chat.thinkingCollapsed')}</span>
        )}
      </button>

      {/* Expandable content */}
      <div
        className={cn(
          'grid transition-[grid-template-rows,opacity] duration-300 ease-out',
          expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div
            ref={contentRef}
            data-testid="thinking-block-content"
            className="mt-2 ml-5 max-h-60 overflow-y-auto border-l-2 border-border/50 pl-3"
          >
            {/* Status entries */}
            {visibleEntries.length > 0 && (
              <div className="space-y-1">
                {shouldTruncate && (
                  <button
                    type="button"
                    data-testid="thinking-block-show-all"
                    className="text-xs text-primary/70 hover:text-primary hover:underline transition-colors"
                    onClick={() => setShowAll(true)}
                  >
                    {t('chat.thinkingShowAll', { count: statusEntries.length })}
                  </button>
                )}
                {visibleEntries.map((entry, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 text-xs text-muted-foreground/70"
                  >
                    <Search className="h-3 w-3 shrink-0 text-muted-foreground/50" />
                    <span>{entry}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Reasoning */}
            {reasoning && (
              <div className={cn('text-sm text-muted-foreground', statusEntries.length > 0 && 'mt-2')}>
                <MarkdownRenderer content={reasoning} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
