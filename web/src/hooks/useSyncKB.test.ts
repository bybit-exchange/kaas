import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import * as derivedApi from '@/api/derived'
import { useKB } from '@/store/kb'
import { useSyncKB } from './useSyncKB'

vi.mock('@/api/derived')

const KBS: derivedApi.DerivedKB[] = [
  { slug: 'pricing', topic: 'pricing and fees', created_at: '2026-08-04', article_count: 7 },
]

beforeEach(() => {
  localStorage.clear()
  useKB.setState({ kb: null })
  vi.clearAllMocks()
  vi.mocked(derivedApi.listDerived).mockResolvedValue({ kbs: KBS })
})

describe('useSyncKB', () => {
  it('clears a persisted selection whose knowledge base no longer exists', async () => {
    useKB.setState({ kb: 'gone' })

    renderHook(() => useSyncKB())

    await waitFor(() => expect(useKB.getState().kb).toBeNull())
  })

  it('keeps a selection that is still in the list', async () => {
    useKB.setState({ kb: 'pricing' })

    renderHook(() => useSyncKB())

    await waitFor(() => expect(derivedApi.listDerived).toHaveBeenCalled())
    expect(useKB.getState().kb).toBe('pricing')
  })

  it('leaves the selection untouched when the list cannot be loaded', async () => {
    vi.mocked(derivedApi.listDerived).mockRejectedValue(new Error('offline'))
    useKB.setState({ kb: 'pricing' })

    renderHook(() => useSyncKB())

    await waitFor(() => expect(derivedApi.listDerived).toHaveBeenCalled())
    expect(useKB.getState().kb).toBe('pricing')
  })

  it('does not refetch when the selection changes', async () => {
    useKB.setState({ kb: 'pricing' })
    const { rerender } = renderHook(() => useSyncKB())
    await waitFor(() => expect(derivedApi.listDerived).toHaveBeenCalledTimes(1))

    useKB.getState().setKB(null)
    rerender()

    expect(derivedApi.listDerived).toHaveBeenCalledTimes(1)
  })

  it('ignores a list that lands after unmount', async () => {
    let resolveList: (r: { kbs: derivedApi.DerivedKB[] }) => void = () => {}
    vi.mocked(derivedApi.listDerived).mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve
      }),
    )
    useKB.setState({ kb: 'gone' })

    const { unmount } = renderHook(() => useSyncKB())
    unmount()
    resolveList({ kbs: KBS })
    await Promise.resolve()

    expect(useKB.getState().kb).toBe('gone')
  })
})
