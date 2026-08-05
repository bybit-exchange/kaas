import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { usePrefs } from '@/store/prefs'
import { useKB } from '@/store/kb'
import * as derivedApi from '@/api/derived'
import { KBSelector } from './KBSelector'

vi.mock('@/api/derived')

/** Renders the selector, opens the dropdown and returns its options. */
async function openOptions(): Promise<HTMLElement[]> {
  render(<KBSelector />)
  await userEvent.click(await screen.findByRole('combobox'))
  return screen.findAllByRole('option')
}

describe('KBSelector', () => {
  beforeEach(() => {
    // Radix Select drives its trigger through the Pointer Events API and scrolls
    // the highlighted item into view; jsdom implements neither.
    Element.prototype.hasPointerCapture = vi.fn(() => false)
    Element.prototype.setPointerCapture = vi.fn()
    Element.prototype.releasePointerCapture = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()

    usePrefs.setState({ theme: 'light', lang: 'en' })
    useKB.setState({ kb: null })
    vi.clearAllMocks()
    vi.mocked(derivedApi.listDerived).mockResolvedValue({
      kbs: [
        { slug: 'pricing', topic: 'pricing and fees', created_at: '2026-08-04', article_count: 7 },
        { slug: 'compliance', topic: 'compliance', created_at: '2026-08-04', article_count: 3 },
      ],
    })
  })

  it('lists the root knowledge base plus each derived one, with article counts', async () => {
    const options = await openOptions()
    expect(options.map((o) => o.textContent)).toEqual([
      'All articles',
      'pricing and fees 7 articles',
      'compliance 3 articles',
    ])
  })

  it('falls back to the slug when a manifest carries no topic', async () => {
    vi.mocked(derivedApi.listDerived).mockResolvedValue({
      kbs: [{ slug: 'pricing', topic: '', created_at: '2026-08-04', article_count: 4 }],
    })
    const options = await openOptions()
    expect(options.map((o) => o.textContent)).toEqual(['All articles', 'pricing 4 articles'])
  })

  it('writes the selection into the store', async () => {
    await openOptions()
    await userEvent.click(screen.getByRole('option', { name: /pricing and fees/ }))
    await waitFor(() => expect(useKB.getState().kb).toBe('pricing'))
  })

  it('goes back to the root knowledge base', async () => {
    useKB.setState({ kb: 'pricing' })
    await openOptions()
    await userEvent.click(screen.getByRole('option', { name: 'All articles' }))
    await waitFor(() => expect(useKB.getState().kb).toBeNull())
  })

  it('shows only the root option when nothing has been derived', async () => {
    vi.mocked(derivedApi.listDerived).mockResolvedValue({ kbs: [] })
    const options = await openOptions()
    expect(options.map((o) => o.textContent)).toEqual(['All articles'])
  })

  it('falls back to the root when the list cannot be loaded', async () => {
    vi.mocked(derivedApi.listDerived).mockRejectedValue(new Error('offline'))
    render(<KBSelector />)
    await waitFor(() => expect(screen.getByRole('combobox')).toBeInTheDocument())
    expect(useKB.getState().kb).toBeNull()
  })

  it('resets a selection whose knowledge base no longer exists', async () => {
    useKB.setState({ kb: 'gone' })
    render(<KBSelector />)
    await waitFor(() => expect(useKB.getState().kb).toBeNull())
  })

  it('keeps a selection that is still in the list', async () => {
    useKB.setState({ kb: 'pricing' })
    render(<KBSelector />)
    await waitFor(() => expect(derivedApi.listDerived).toHaveBeenCalled())
    expect(useKB.getState().kb).toBe('pricing')
  })

  it('loads the list once, not again on every switch', async () => {
    await openOptions()
    await userEvent.click(screen.getByRole('option', { name: /pricing and fees/ }))
    await waitFor(() => expect(useKB.getState().kb).toBe('pricing'))
    expect(derivedApi.listDerived).toHaveBeenCalledTimes(1)
  })
})
