import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import type { Session } from '@/api/sessions'
import { SessionList, type SessionListProps } from './SessionList'

const DAY = 86400000

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * DAY).toISOString()
}

function makeSession(id: string, title: string, daysAgo = 0): Session {
  return {
    id,
    title,
    created_at: isoDaysAgo(daysAgo),
    updated_at: isoDaysAgo(daysAgo),
  }
}

interface Handlers {
  onNewChat: ReturnType<typeof vi.fn>
  onSelect: ReturnType<typeof vi.fn>
  onDelete: ReturnType<typeof vi.fn>
  onRename: ReturnType<typeof vi.fn>
}

function renderList(overrides: Partial<SessionListProps> = {}) {
  const handlers: Handlers = {
    onNewChat: vi.fn(),
    onSelect: vi.fn(),
    onDelete: vi.fn(),
    onRename: vi.fn(),
  }
  const view = render(
    <LangProvider>
      <SessionList
        sessions={[makeSession('s1', 'Session A')]}
        {...handlers}
        {...overrides}
      />
    </LangProvider>,
  )
  return { ...view, handlers }
}

/** The clickable session row (role="button") carrying the given label. */
function row(name: string): HTMLElement {
  return screen.getByRole('button', { name })
}

/** [renameButton, deleteButton] of a row; the row itself is excluded. */
function rowActions(name: string): HTMLElement[] {
  return within(row(name)).getAllByRole('button')
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
})

describe('SessionList', () => {
  describe('rendering', () => {
    it('groups sessions under date headings, newest group first', () => {
      renderList({
        sessions: [
          makeSession('old', 'Old one', 10),
          makeSession('new', 'Fresh one', 0),
          makeSession('mid', 'Mid one', 3),
        ],
      })

      const headings = ['Today', 'Last 7 days', 'Last 30 days'].map((label) =>
        screen.getByText(label),
      )
      expect(headings).toHaveLength(3)
      expect(screen.getByText('Fresh one')).toBeInTheDocument()
      expect(screen.getByText('Mid one')).toBeInTheDocument()
      expect(screen.getByText('Old one')).toBeInTheDocument()

      // Headings appear in chronological order in the DOM.
      const text = document.body.textContent ?? ''
      expect(text.indexOf('Today')).toBeLessThan(text.indexOf('Last 7 days'))
      expect(text.indexOf('Last 7 days')).toBeLessThan(text.indexOf('Last 30 days'))
    })

    it('falls back to a default label for an untitled session', () => {
      renderList({ sessions: [makeSession('s1', '')] })

      expect(screen.getByText('New conversation')).toBeInTheDocument()
    })

    it('marks the active session with aria-current', () => {
      renderList({
        sessions: [makeSession('s1', 'Session A'), makeSession('s2', 'Session B')],
        activeSessionId: 's2',
      })

      expect(row('Session B')).toHaveAttribute('aria-current', 'page')
      expect(row('Session A')).not.toHaveAttribute('aria-current')
    })

    it('renders no date headings when there are no sessions', () => {
      renderList({ sessions: [] })

      expect(screen.queryByText('Today')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'New chat' })).toBeInTheDocument()
    })
  })

  describe('selection', () => {
    it('reports a click on a session row', () => {
      const { handlers } = renderList()

      fireEvent.click(row('Session A'))

      expect(handlers.onSelect).toHaveBeenCalledWith('s1')
    })

    it('reports Enter and Space on a focused session row', () => {
      const { handlers } = renderList()

      fireEvent.keyDown(row('Session A'), { key: 'Enter' })
      fireEvent.keyDown(row('Session A'), { key: ' ' })

      expect(handlers.onSelect).toHaveBeenCalledTimes(2)
      expect(handlers.onSelect).toHaveBeenCalledWith('s1')
    })

    it('ignores other keys on a session row', () => {
      const { handlers } = renderList()

      fireEvent.keyDown(row('Session A'), { key: 'ArrowDown' })

      expect(handlers.onSelect).not.toHaveBeenCalled()
    })

    it('starts a new chat from the header button', () => {
      const { handlers } = renderList()

      fireEvent.click(screen.getByRole('button', { name: 'New chat' }))

      expect(handlers.onNewChat).toHaveBeenCalledTimes(1)
    })
  })

  describe('renaming', () => {
    it('opens an editor prefilled with the current title on double click', () => {
      renderList()

      fireEvent.doubleClick(row('Session A'))

      expect(screen.getByRole('textbox')).toHaveValue('Session A')
    })

    it('prefills the default label when renaming an untitled session', () => {
      renderList({ sessions: [makeSession('s1', '')] })

      fireEvent.doubleClick(row('New conversation'))

      expect(screen.getByRole('textbox')).toHaveValue('New conversation')
    })

    it('opens the editor from the pencil button without selecting the session', () => {
      const { handlers } = renderList()

      fireEvent.click(rowActions('Session A')[0])

      expect(screen.getByRole('textbox')).toBeInTheDocument()
      expect(handlers.onSelect).not.toHaveBeenCalled()
    })

    it('commits the trimmed new title on Enter', () => {
      const { handlers } = renderList()

      fireEvent.doubleClick(row('Session A'))
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: '  Renamed  ' } })
      fireEvent.keyDown(input, { key: 'Enter' })

      expect(handlers.onRename).toHaveBeenCalledTimes(1)
      expect(handlers.onRename).toHaveBeenCalledWith('s1', 'Renamed')
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    })

    it('commits on blur', () => {
      const { handlers } = renderList()

      fireEvent.doubleClick(row('Session A'))
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: 'Blurred title' } })
      fireEvent.blur(input)

      expect(handlers.onRename).toHaveBeenCalledWith('s1', 'Blurred title')
    })

    it('does not commit on Enter while an IME composition is active', () => {
      const { handlers } = renderList()

      fireEvent.doubleClick(row('Session A'))
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: '中文标题' } })
      fireEvent.compositionStart(input)
      fireEvent.keyDown(input, { key: 'Enter' })

      expect(handlers.onRename).not.toHaveBeenCalled()
      expect(screen.getByRole('textbox')).toBeInTheDocument()

      fireEvent.compositionEnd(input)
      fireEvent.keyDown(input, { key: 'Enter' })

      expect(handlers.onRename).toHaveBeenCalledWith('s1', '中文标题')
    })

    it('discards the edit on Escape', () => {
      const { handlers } = renderList()

      fireEvent.doubleClick(row('Session A'))
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: 'Discarded' } })
      fireEvent.keyDown(input, { key: 'Escape' })

      expect(handlers.onRename).not.toHaveBeenCalled()
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      expect(screen.getByText('Session A')).toBeInTheDocument()
    })

    it('ignores a blank title and leaves the session untouched', () => {
      const { handlers } = renderList()

      fireEvent.doubleClick(row('Session A'))
      const input = screen.getByRole('textbox')
      fireEvent.change(input, { target: { value: '   ' } })
      fireEvent.keyDown(input, { key: 'Enter' })

      expect(handlers.onRename).not.toHaveBeenCalled()
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    })

    it('does not select the session when clicking inside the editor', () => {
      const { handlers } = renderList()

      fireEvent.doubleClick(row('Session A'))
      fireEvent.click(screen.getByRole('textbox'))

      expect(handlers.onSelect).not.toHaveBeenCalled()
    })

    it('hides the pencil button while editing so only delete remains', () => {
      renderList()

      expect(rowActions('Session A')).toHaveLength(2)

      fireEvent.doubleClick(row('Session A'))

      const editingRow = screen.getByRole('textbox').closest('[role="button"]')!
      expect(within(editingRow as HTMLElement).getAllByRole('button')).toHaveLength(1)
    })
  })

  describe('deleting', () => {
    it('asks for confirmation before deleting', () => {
      const { handlers } = renderList()

      fireEvent.click(rowActions('Session A')[1])

      expect(screen.getByText('Delete conversation')).toBeInTheDocument()
      expect(handlers.onDelete).not.toHaveBeenCalled()
    })

    it('deletes the session once confirmed and closes the dialog', () => {
      const { handlers } = renderList()

      fireEvent.click(rowActions('Session A')[1])
      fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

      expect(handlers.onDelete).toHaveBeenCalledWith('s1')
      expect(screen.queryByText('Delete conversation')).not.toBeInTheDocument()
    })

    it('keeps the session when the confirmation is cancelled', () => {
      const { handlers } = renderList()

      fireEvent.click(rowActions('Session A')[1])
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

      expect(handlers.onDelete).not.toHaveBeenCalled()
      expect(screen.queryByText('Delete conversation')).not.toBeInTheDocument()
    })

    it('deletes the session the button belongs to, not the active one', () => {
      const { handlers } = renderList({
        sessions: [makeSession('s1', 'Session A'), makeSession('s2', 'Session B')],
        activeSessionId: 's1',
      })

      fireEvent.click(rowActions('Session B')[1])
      fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

      expect(handlers.onDelete).toHaveBeenCalledWith('s2')
    })

    it('does not select the session when clicking its delete button', () => {
      const { handlers } = renderList()

      fireEvent.click(rowActions('Session A')[1])

      expect(handlers.onSelect).not.toHaveBeenCalled()
    })
  })
})
