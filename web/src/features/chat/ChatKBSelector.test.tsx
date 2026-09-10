import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { usePrefs } from '@/store/prefs'
import { useKB } from '@/store/kb'
import * as derivedApi from '@/api/derived'
import { ChatKBSelector } from './ChatKBSelector'

vi.mock('@/api/derived')

/** Renders the selector, opens the dropdown and returns its options. */
async function openOptions(): Promise<HTMLElement[]> {
  render(<ChatKBSelector />)
  await userEvent.click(await screen.findByRole('combobox'))
  return screen.findAllByRole('option')
}

describe('ChatKBSelector', () => {
  beforeEach(() => {
    // Radix Select drives its trigger through the Pointer Events API and scrolls
    // the highlighted item into view; jsdom implements neither.
    Element.prototype.hasPointerCapture = vi.fn(() => false)
    Element.prototype.setPointerCapture = vi.fn()
    Element.prototype.releasePointerCapture = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()

    usePrefs.setState({ theme: 'light', lang: 'en' })
    useKB.setState({ kb: null, chatKB: null })
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

  it('writes the selection into chatKB in the store', async () => {
    await openOptions()
    await userEvent.click(screen.getByRole('option', { name: /pricing and fees/ }))
    await waitFor(() => expect(useKB.getState().chatKB).toBe('pricing'))
  })

  it('goes back to the root knowledge base', async () => {
    useKB.setState({ chatKB: 'pricing' })
    await openOptions()
    await userEvent.click(screen.getByRole('option', { name: 'All articles' }))
    await waitFor(() => expect(useKB.getState().chatKB).toBeNull())
  })

  it('does not affect the wiki KB store field', async () => {
    useKB.setState({ kb: 'compliance' })
    await openOptions()
    await userEvent.click(screen.getByRole('option', { name: /pricing and fees/ }))
    await waitFor(() => expect(useKB.getState().chatKB).toBe('pricing'))
    // Wiki KB untouched
    expect(useKB.getState().kb).toBe('compliance')
  })

  it('fires the onChange callback on selection change', async () => {
    const onChange = vi.fn()
    render(<ChatKBSelector onChange={onChange} />)
    await userEvent.click(await screen.findByRole('combobox'))
    await userEvent.click(screen.getByRole('option', { name: /pricing and fees/ }))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
  })

  it('shows only the root option when nothing has been derived', async () => {
    vi.mocked(derivedApi.listDerived).mockResolvedValue({ kbs: [] })
    const options = await openOptions()
    expect(options.map((o) => o.textContent)).toEqual(['All articles'])
  })

  it('still renders when the list cannot be loaded', async () => {
    vi.mocked(derivedApi.listDerived).mockRejectedValue(new Error('offline'))
    render(<ChatKBSelector />)
    await waitFor(() => expect(screen.getByRole('combobox')).toBeInTheDocument())
  })
})
