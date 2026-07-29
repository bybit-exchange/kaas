import { useState, useRef, forwardRef, useImperativeHandle, useEffect, useMemo } from 'react'
import { Send, Square } from 'lucide-react'
import { useT } from '@/i18n'
import { Button } from '@/components/ui/button'

interface MessageInputProps {
  onSend: (content: string) => void
  onStop: () => void
  disabled?: boolean
  streaming?: boolean
  draft?: string
  onDraftChange?: (v: string) => void
}

export interface MessageInputHandle {
  getCurrentDraft(): string
}

export const MessageInput = forwardRef<MessageInputHandle, MessageInputProps>(
  function MessageInput({ onSend, onStop, disabled, streaming, draft, onDraftChange }, ref) {
    const t = useT()
    const [content, setContent] = useState(draft ?? '')
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const composingRef = useRef(false)
    const contentRef = useRef(content)
    contentRef.current = content

    // Sync internal state when draft prop changes externally (session switch)
    useEffect(() => {
      setContent(draft ?? '')
    }, [draft])

    // Throttled onDraftChange (300ms)
    const throttledDraftChange = useMemo(() => {
      let lastCall = 0
      let timerId: ReturnType<typeof setTimeout> | null = null

      const throttled = (value: string) => {
        if (!onDraftChange) return
        const now = Date.now()
        const remaining = 300 - (now - lastCall)

        if (remaining <= 0) {
          if (timerId) {
            clearTimeout(timerId)
            timerId = null
          }
          lastCall = now
          onDraftChange(value)
        } else {
          if (timerId) clearTimeout(timerId)
          timerId = setTimeout(() => {
            lastCall = Date.now()
            timerId = null
            onDraftChange(value)
          }, remaining)
        }
      }

      throttled.flush = () => {
        if (timerId) {
          clearTimeout(timerId)
          timerId = null
        }
      }

      return throttled
    }, [onDraftChange])

    // Cleanup throttle timer on unmount
    useEffect(() => {
      return () => {
        throttledDraftChange.flush()
      }
    }, [throttledDraftChange])

    useImperativeHandle(ref, () => ({
      getCurrentDraft() {
        return contentRef.current
      },
    }))

    function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
      const value = e.target.value
      setContent(value)
      throttledDraftChange(value)
    }

    function handleSubmit(e: React.FormEvent) {
      e.preventDefault()
      const trimmed = content.trim()
      if (!trimmed || disabled) return
      onSend(trimmed)
      setContent('')
      onDraftChange?.('')
      textareaRef.current?.focus()
    }

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
      if (e.key === 'Enter' && !e.shiftKey && !composingRef.current) {
        e.preventDefault()
        handleSubmit(e)
      }
    }

    const canSend = content.trim().length > 0 && !disabled

    return (
      <div className="px-4 pb-3">
        <div className="mx-auto w-full max-w-3xl">
          <form
            onSubmit={handleSubmit}
            className="flex flex-col gap-2"
            aria-label={t('chat.send')}
          >
            <div className="flex items-center gap-2 rounded-xl border bg-background px-4 py-2 focus-within:ring-1 focus-within:ring-ring transition-shadow">
              <label htmlFor="message-input" className="sr-only">
                {t('chat.placeholder')}
              </label>
              <textarea
                id="message-input"
                ref={textareaRef}
                value={content}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                onCompositionStart={() => {
                  composingRef.current = true
                }}
                onCompositionEnd={() => {
                  composingRef.current = false
                }}
                placeholder={t('chat.placeholder')}
                className="max-h-40 min-h-[44px] flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground leading-relaxed"
                rows={1}
                disabled={disabled}
              />
              {streaming ? (
                <Button
                  type="button"
                  size="icon"
                  onClick={onStop}
                  aria-label={t('chat.stop')}
                  className="h-9 w-9 shrink-0"
                >
                  <Square className="h-4 w-4" aria-hidden="true" />
                </Button>
              ) : (
                <Button
                  type="submit"
                  size="icon"
                  disabled={!canSend}
                  aria-label={t('chat.send')}
                  className="h-9 w-9 shrink-0 transition-opacity"
                >
                  <Send className="h-4 w-4" aria-hidden="true" />
                </Button>
              )}
            </div>
          </form>
        </div>
      </div>
    )
  },
)
