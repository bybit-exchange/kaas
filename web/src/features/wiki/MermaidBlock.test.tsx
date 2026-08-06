import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// The real mermaid runtime needs a browser layout engine, so the module is
// replaced wholesale — this test is about how MermaidBlock drives it, not about
// mermaid's own output.
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(),
  },
}))

// Import AFTER mocking
import { MermaidBlock } from './MermaidBlock'
import mermaid from 'mermaid'

const mockRender = vi.mocked(mermaid.render)

/** A promise plus its resolvers, for holding a render open mid-test. */
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

describe('MermaidBlock', () => {
  it('injects the rendered diagram into the page', async () => {
    mockRender.mockResolvedValue({ svg: '<svg data-testid="diagram"></svg>' } as never)

    render(<MermaidBlock code="graph TD; A-->B;" />)

    expect(await screen.findByTestId('diagram')).toBeInTheDocument()
    expect(mockRender).toHaveBeenCalledWith(expect.stringMatching(/^mermaid-\d+$/), 'graph TD; A-->B;')
  })

  // A malformed fence is user content, so it must degrade to a readable message
  // instead of an empty box or a thrown render.
  it('shows mermaid’s own message when the diagram will not parse', async () => {
    mockRender.mockRejectedValue(new Error('Parse error on line 2'))

    render(<MermaidBlock code="not a diagram" />)

    expect(await screen.findByText('Parse error on line 2')).toBeInTheDocument()
  })

  it('falls back to a generic message when the failure is not an Error', async () => {
    mockRender.mockRejectedValue('exploded')

    render(<MermaidBlock code="not a diagram" />)

    expect(await screen.findByText('Mermaid render failed')).toBeInTheDocument()
  })

  it('re-renders under a fresh id when the code changes', async () => {
    mockRender.mockResolvedValue({ svg: '<svg data-testid="diagram"></svg>' } as never)

    const { rerender } = render(<MermaidBlock code="graph TD; A-->B;" />)
    await screen.findByTestId('diagram')

    rerender(<MermaidBlock code="graph TD; B-->C;" />)

    await waitFor(() => expect(mockRender).toHaveBeenCalledTimes(2))
    const [firstId] = mockRender.mock.calls[0]
    const [secondId, secondCode] = mockRender.mock.calls[1]
    expect(secondCode).toBe('graph TD; B-->C;')
    // Mermaid keys its generated DOM by id; reusing one would collide with the
    // element the previous render left behind.
    expect(secondId).not.toBe(firstId)
  })

  // Wiki navigation unmounts the article while a render may still be pending.
  it('ignores a render that finishes after unmount', async () => {
    const d = deferred<{ svg: string }>()
    mockRender.mockReturnValue(d.promise as never)

    const { unmount } = render(<MermaidBlock code="graph TD; A-->B;" />)
    unmount()

    d.resolve({ svg: '<svg data-testid="diagram"></svg>' })
    await d.promise

    expect(screen.queryByTestId('diagram')).not.toBeInTheDocument()
  })

  it('ignores a failure that arrives after unmount', async () => {
    const d = deferred<{ svg: string }>()
    mockRender.mockReturnValue(d.promise as never)

    const { unmount } = render(<MermaidBlock code="bad" />)
    unmount()

    d.reject(new Error('Parse error on line 2'))
    await d.promise.catch(() => {})

    expect(screen.queryByText('Parse error on line 2')).not.toBeInTheDocument()
  })
})
