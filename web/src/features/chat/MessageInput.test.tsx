import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createRef } from 'react'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { MessageInput, type MessageInputHandle } from './MessageInput'

interface Handlers {
  onSend: ReturnType<typeof vi.fn>
  onStop: ReturnType<typeof vi.fn>
  onDraftChange: ReturnType<typeof vi.fn>
}

function makeHandlers(): Handlers {
  return { onSend: vi.fn(), onStop: vi.fn(), onDraftChange: vi.fn() }
}

function renderInput(
  props: Partial<{
    disabled: boolean
    streaming: boolean
    draft: string
    onDraftChange: (v: string) => void
  }> = {},
  handlers: Handlers = makeHandlers(),
  ref?: React.Ref<MessageInputHandle>,
) {
  const view = render(
    <LangProvider>
      <MessageInput
        ref={ref}
        onSend={handlers.onSend}
        onStop={handlers.onStop}
        {...props}
      />
    </LangProvider>,
  )
  return { ...view, handlers }
}

function textarea(): HTMLTextAreaElement {
  return screen.getByRole('textbox') as HTMLTextAreaElement
}

function type(value: string) {
  fireEvent.change(textarea(), { target: { value } })
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  vi.clearAllMocks()
})

describe('MessageInput', () => {
  describe('send affordance', () => {
    it('keeps Send disabled until the draft has non-whitespace content', () => {
      renderInput()
      const send = screen.getByRole('button', { name: 'Send' })

      expect(send).toBeDisabled()

      type('   ')
      expect(send).toBeDisabled()

      type('hello')
      expect(send).toBeEnabled()
    })

    it('keeps Send disabled while the input is disabled even with content', () => {
      renderInput({ disabled: true })

      type('hello')

      expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
      expect(textarea()).toBeDisabled()
    })
  })

  describe('submitting', () => {
    it('sends the trimmed draft and empties the textarea', () => {
      const { handlers } = renderInput({ onDraftChange: makeHandlers().onDraftChange })

      type('  hello world  ')
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))

      expect(handlers.onSend).toHaveBeenCalledWith('hello world')
      expect(textarea().value).toBe('')
    })

    it('clears the persisted draft after sending', () => {
      const handlers = makeHandlers()
      renderInput({ onDraftChange: handlers.onDraftChange }, handlers)

      type('question')
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))

      expect(handlers.onDraftChange).toHaveBeenLastCalledWith('')
    })

    it('submits on Enter', () => {
      const { handlers } = renderInput()

      type('hi')
      fireEvent.keyDown(textarea(), { key: 'Enter' })

      expect(handlers.onSend).toHaveBeenCalledWith('hi')
    })

    it('inserts a newline instead of sending on Shift+Enter', () => {
      const { handlers } = renderInput()

      type('line one')
      fireEvent.keyDown(textarea(), { key: 'Enter', shiftKey: true })

      expect(handlers.onSend).not.toHaveBeenCalled()
      expect(textarea().value).toBe('line one')
    })

    it('does not send on Enter while an IME composition is active', () => {
      const { handlers } = renderInput()

      type('中文')
      fireEvent.compositionStart(textarea())
      fireEvent.keyDown(textarea(), { key: 'Enter' })

      expect(handlers.onSend).not.toHaveBeenCalled()

      // Once the composition ends, Enter sends normally.
      fireEvent.compositionEnd(textarea())
      fireEvent.keyDown(textarea(), { key: 'Enter' })

      expect(handlers.onSend).toHaveBeenCalledWith('中文')
    })

    it('does not send a whitespace-only draft on Enter', () => {
      const { handlers } = renderInput()

      type('   ')
      fireEvent.keyDown(textarea(), { key: 'Enter' })

      expect(handlers.onSend).not.toHaveBeenCalled()
    })

    it('does not send while disabled', () => {
      const { handlers } = renderInput({ disabled: true })

      type('hi')
      fireEvent.keyDown(textarea(), { key: 'Enter' })

      expect(handlers.onSend).not.toHaveBeenCalled()
      expect(textarea().value).toBe('hi')
    })
  })

  describe('streaming', () => {
    it('swaps Send for Stop and reports the stop request', () => {
      const { handlers } = renderInput({ streaming: true })

      expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Stop' }))

      expect(handlers.onStop).toHaveBeenCalledTimes(1)
    })
  })

  describe('draft syncing', () => {
    it('prefills from the draft prop', () => {
      renderInput({ draft: 'saved draft' })

      expect(textarea().value).toBe('saved draft')
    })

    it('replaces the textarea content when the draft prop changes (session switch)', () => {
      const handlers = makeHandlers()
      const { rerender } = renderInput({ draft: 'session A draft' }, handlers)

      rerender(
        <LangProvider>
          <MessageInput
            onSend={handlers.onSend}
            onStop={handlers.onStop}
            draft="session B draft"
          />
        </LangProvider>,
      )

      expect(textarea().value).toBe('session B draft')
    })

    it('exposes the live draft through the imperative handle', () => {
      const ref = createRef<MessageInputHandle>()
      renderInput({}, makeHandlers(), ref)

      type('unsent text')

      expect(ref.current?.getCurrentDraft()).toBe('unsent text')
    })
  })

  describe('throttled draft persistence', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('persists the first keystroke immediately', () => {
      const handlers = makeHandlers()
      renderInput({ onDraftChange: handlers.onDraftChange }, handlers)

      type('a')

      expect(handlers.onDraftChange).toHaveBeenCalledTimes(1)
      expect(handlers.onDraftChange).toHaveBeenCalledWith('a')
    })

    it('collapses a burst of keystrokes into one trailing call with the latest value', () => {
      const handlers = makeHandlers()
      renderInput({ onDraftChange: handlers.onDraftChange }, handlers)

      type('a')
      expect(handlers.onDraftChange).toHaveBeenCalledTimes(1)

      type('ab')
      type('abc')
      // Still throttled — nothing extra yet.
      expect(handlers.onDraftChange).toHaveBeenCalledTimes(1)

      act(() => {
        vi.advanceTimersByTime(300)
      })

      expect(handlers.onDraftChange).toHaveBeenCalledTimes(2)
      expect(handlers.onDraftChange).toHaveBeenLastCalledWith('abc')
    })

    it('persists again once the throttle window has elapsed', () => {
      const handlers = makeHandlers()
      renderInput({ onDraftChange: handlers.onDraftChange }, handlers)

      type('a')
      act(() => {
        vi.advanceTimersByTime(400)
      })
      type('ab')

      expect(handlers.onDraftChange).toHaveBeenCalledTimes(2)
      expect(handlers.onDraftChange).toHaveBeenLastCalledWith('ab')
    })

    it('cancels the pending persist when a keystroke lands after the window elapsed', () => {
      const handlers = makeHandlers()
      renderInput({ onDraftChange: handlers.onDraftChange }, handlers)

      type('a')
      type('ab') // queues a trailing persist ~300ms out
      // Move the clock past the throttle window without letting the timer run.
      vi.setSystemTime(Date.now() + 400)
      type('abc')

      // 'abc' persisted immediately and the queued 'ab' was dropped.
      expect(handlers.onDraftChange).toHaveBeenCalledTimes(2)
      expect(handlers.onDraftChange).toHaveBeenLastCalledWith('abc')

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(handlers.onDraftChange).toHaveBeenCalledTimes(2)
    })

    it('drops the pending persist when the input unmounts', () => {
      const handlers = makeHandlers()
      const { unmount } = renderInput({ onDraftChange: handlers.onDraftChange }, handlers)

      type('a')
      type('ab')
      unmount()

      act(() => {
        vi.advanceTimersByTime(500)
      })

      // Only the immediate first call landed; the trailing one was cancelled.
      expect(handlers.onDraftChange).toHaveBeenCalledTimes(1)
      expect(handlers.onDraftChange).toHaveBeenCalledWith('a')
    })

    it('does nothing on change when no draft handler is supplied', () => {
      renderInput()

      type('a')
      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(textarea().value).toBe('a')
    })
  })
})
