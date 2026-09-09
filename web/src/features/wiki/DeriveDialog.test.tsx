import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { usePrefs } from '@/store/prefs'
import * as derivedApi from '@/api/derived'
import { DeriveDialog } from './DeriveDialog'

vi.mock('@/api/derived')

/** Opens the dialog, types a topic and clicks Start. */
async function start(topic = 'pricing') {
  render(
    <MemoryRouter>
      <DeriveDialog />
    </MemoryRouter>,
  )
  await userEvent.click(screen.getByRole('button', { name: /derive/i }))
  if (topic) await userEvent.type(await screen.findByLabelText('Topic'), topic)
  await userEvent.click(screen.getByRole('button', { name: /^start$/i }))
}

describe('DeriveDialog', () => {
  beforeEach(() => {
    usePrefs.setState({ theme: 'light', lang: 'en' })
    vi.clearAllMocks()
    vi.mocked(derivedApi.startDerive).mockResolvedValue({ job_id: 'j1', slug: 'pricing' })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts a derive with the typed topic', async () => {
    await start('  pricing  ')
    await waitFor(() =>
      expect(derivedApi.startDerive).toHaveBeenCalledWith({ topic: 'pricing' }),
    )
  })

  // The engine owns the default, so the form omits select_from when it shows the
  // default rather than sending "articles" the UI invented. One rule across every
  // layer: absent means engine default.
  it('filters over compiled articles by default, without naming it', async () => {
    render(
      <MemoryRouter>
        <DeriveDialog />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    expect(await screen.findByRole('radio', { name: /compiled articles/i })).toBeChecked()

    await userEvent.type(await screen.findByLabelText('Topic'), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /^start$/i }))
    await waitFor(() =>
      expect(derivedApi.startDerive).toHaveBeenCalledWith({ topic: 'pricing' }),
    )
  })

  it('filters over raw documents when asked', async () => {
    render(
      <MemoryRouter>
        <DeriveDialog />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(await screen.findByLabelText('Topic'), 'pricing')
    await userEvent.click(screen.getByRole('radio', { name: /raw documents/i }))
    await userEvent.click(screen.getByRole('button', { name: /^start$/i }))

    await waitFor(() =>
      expect(derivedApi.startDerive).toHaveBeenCalledWith({
        topic: 'pricing',
        select_from: 'documents',
      }),
    )
  })

  it('will not start with an empty topic', async () => {
    await start('')
    expect(screen.getByRole('button', { name: /^start$/i })).toBeDisabled()
    expect(derivedApi.startDerive).not.toHaveBeenCalled()
  })

  it('wires the trigger to the dialog for assistive tech', () => {
    render(
      <MemoryRouter>
        <DeriveDialog />
      </MemoryRouter>,
    )
    const trigger = screen.getByRole('button', { name: /derive/i })
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows success message and link to Builds after starting', async () => {
    await start()
    expect(await screen.findByText('Derive job started successfully')).toBeInTheDocument()
    const link = screen.getByText(/View in Builds/)
    expect(link).toBeInTheDocument()
    expect(link.closest('a')).toHaveAttribute('href', '/builds/derive')
  })

  it('locks the form after a successful start', async () => {
    await start()
    await waitFor(() =>
      expect(screen.getByLabelText('Topic')).toBeDisabled(),
    )
    expect(screen.getByRole('radio', { name: /raw documents/i })).toBeDisabled()
    // Start button should be hidden (not present)
    expect(screen.queryByRole('button', { name: /^start$/i })).not.toBeInTheDocument()
  })

  it('forgets a finished run when the dialog is reopened', async () => {
    await start()
    expect(await screen.findByText('Derive job started successfully')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))

    expect(await screen.findByLabelText('Topic')).toBeInTheDocument()
    expect(screen.queryByText('Derive job started successfully')).not.toBeInTheDocument()
  })

  it('surfaces a rejected start', async () => {
    vi.mocked(derivedApi.startDerive).mockRejectedValue(new Error('already exists'))
    await start()
    expect(await screen.findByText('already exists')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
  })

  it('does not call getDeriveJob after starting', async () => {
    await start()
    await waitFor(() =>
      expect(screen.getByText('Derive job started successfully')).toBeInTheDocument(),
    )
    expect(derivedApi.getDeriveJob).not.toHaveBeenCalled()
  })
})
