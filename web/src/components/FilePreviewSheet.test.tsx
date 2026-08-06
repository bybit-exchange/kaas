import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { LangProvider } from '@/i18n'

vi.mock('@/api/tasks', () => ({
  getTaskContent: vi.fn(),
}))

// Import AFTER mocking
import { FilePreviewSheet } from './FilePreviewSheet'
import { getTaskContent } from '@/api/tasks'

const mockGetTaskContent = vi.mocked(getTaskContent)

function renderSheet(props: Partial<Parameters<typeof FilePreviewSheet>[0]> = {}) {
  const merged = {
    open: true,
    onOpenChange: vi.fn(),
    taskId: 't1',
    ...props,
  }
  const view = render(
    <LangProvider>
      <FilePreviewSheet {...merged} />
    </LangProvider>,
  )
  const rerender = (next: Partial<typeof merged>) =>
    view.rerender(
      <LangProvider>
        <FilePreviewSheet {...merged} {...next} />
      </LangProvider>,
    )
  return { ...view, rerender }
}

/** A promise plus its resolvers, for holding a fetch open mid-test. */
function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('FilePreviewSheet', () => {
  it('renders each line of the fetched content with a line number', async () => {
    mockGetTaskContent.mockResolvedValue({ content: 'alpha\nbeta\ngamma', size: 16, truncated: false })

    renderSheet()

    expect(await screen.findByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('gamma')).toBeInTheDocument()
    // Line numbers are rendered as their own gutter cells.
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('3 lines')).toBeInTheDocument()
  })

  it('shows a spinner until the content arrives', async () => {
    const d = deferred<{ content: string; size: number; truncated: boolean }>()
    mockGetTaskContent.mockReturnValue(d.promise)

    renderSheet()

    expect(await screen.findByText('Loading file…')).toBeInTheDocument()

    d.resolve({ content: 'done', size: 4, truncated: false })

    await waitFor(() => expect(screen.queryByText('Loading file…')).not.toBeInTheDocument())
    expect(screen.getByText('done')).toBeInTheDocument()
  })

  it('warns that the content is incomplete when the server truncated it', async () => {
    mockGetTaskContent.mockResolvedValue({ content: 'partial', size: 2_000_000, truncated: true })

    renderSheet()

    expect(
      await screen.findByText('File is larger than 1 MB — content has been truncated.'),
    ).toBeInTheDocument()
  })

  it('hides the truncation warning for a complete file', async () => {
    mockGetTaskContent.mockResolvedValue({ content: 'whole', size: 5, truncated: false })

    renderSheet()

    await screen.findByText('whole')
    expect(
      screen.queryByText('File is larger than 1 MB — content has been truncated.'),
    ).not.toBeInTheDocument()
  })

  // A deleted task and a broken backend look the same to the user here, but they
  // take different branches, so both are pinned.
  it.each([
    ['a missing file', new Error('request failed: 404')],
    ['any other failure', new Error('network down')],
  ])('reports an error for %s', async (_label, err) => {
    mockGetTaskContent.mockRejectedValue(err)

    renderSheet()

    expect(await screen.findByText('Failed to load file content')).toBeInTheDocument()
    expect(screen.queryByText('Loading file…')).not.toBeInTheDocument()
  })

  it('does not fetch while closed', () => {
    renderSheet({ open: false })

    expect(mockGetTaskContent).not.toHaveBeenCalled()
  })

  it('does not fetch without a task id', () => {
    renderSheet({ taskId: null })

    expect(mockGetTaskContent).not.toHaveBeenCalled()
  })

  it('drops the content when the sheet closes, so reopening cannot flash the previous file', async () => {
    mockGetTaskContent.mockResolvedValue({ content: 'first file', size: 10, truncated: false })

    const { rerender } = renderSheet()
    await screen.findByText('first file')

    rerender({ open: false })

    await waitFor(() => expect(screen.queryByText('first file')).not.toBeInTheDocument())
  })

  // The abort matters: without it a slow first response could land after the
  // second and leave the sheet showing the wrong file's content under the new
  // title.
  it('aborts the in-flight request when the task id changes', async () => {
    const first = deferred<{ content: string; size: number; truncated: boolean }>()
    mockGetTaskContent.mockReturnValueOnce(first.promise)
    mockGetTaskContent.mockResolvedValue({ content: 'second file', size: 11, truncated: false })

    const { rerender } = renderSheet({ taskId: 'a' })
    await screen.findByText('Loading file…')

    rerender({ taskId: 'b' })

    const firstSignal = mockGetTaskContent.mock.calls[0][1] as AbortSignal
    expect(firstSignal.aborted).toBe(true)

    // The stale response resolving must not overwrite the new file's content.
    first.resolve({ content: 'first file', size: 10, truncated: false })
    expect(await screen.findByText('second file')).toBeInTheDocument()
    expect(screen.queryByText('first file')).not.toBeInTheDocument()
  })

  it('prefers the caller-supplied title over the generic fallback', async () => {
    mockGetTaskContent.mockResolvedValue({ content: 'x', size: 1, truncated: false })

    renderSheet({ displayTitle: 'notes.md' })

    expect(await screen.findByText('notes.md')).toBeInTheDocument()
    expect(screen.queryByText('File Content')).not.toBeInTheDocument()
  })

  it('falls back to the generic title when the task has no display title', async () => {
    mockGetTaskContent.mockResolvedValue({ content: 'x', size: 1, truncated: false })

    renderSheet({ displayTitle: undefined })

    expect(await screen.findByText('File Content')).toBeInTheDocument()
  })
})
