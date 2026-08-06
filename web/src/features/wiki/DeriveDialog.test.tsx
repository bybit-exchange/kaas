import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { usePrefs } from '@/store/prefs'
import * as derivedApi from '@/api/derived'
import type { DeriveJob, DeriveResult } from '@/api/derived'
import { DeriveDialog } from './DeriveDialog'

vi.mock('@/api/derived')

function job(over: Partial<DeriveJob>): DeriveJob {
  return {
    id: 'j1',
    slug: 'pricing',
    topic: 'pricing',
    status: 'running',
    stage: 'compile',
    created_at: 1,
    updated_at: 2,
    ...over,
  }
}

const RESULT: DeriveResult = {
  selected: 9,
  documents: 6,
  bytes: 4096,
  offtopic: 2,
  filter_batches: 1,
  compiled: true,
  cost: { total_cost_usd: 1.2345 },
}

/** Opens the dialog, types a topic and clicks Start. */
async function start(topic = 'pricing') {
  render(<DeriveDialog />)
  await userEvent.click(screen.getByRole('button', { name: /derive/i }))
  if (topic) await userEvent.type(await screen.findByLabelText('Topic'), topic)
  await userEvent.click(screen.getByRole('button', { name: /^start$/i }))
}

describe('DeriveDialog', () => {
  beforeEach(() => {
    usePrefs.setState({ theme: 'light', lang: 'en' })
    vi.clearAllMocks()
    vi.mocked(derivedApi.startDerive).mockResolvedValue({ job_id: 'j1', slug: 'pricing' })
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(job({}))
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
    render(<DeriveDialog />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    expect(await screen.findByRole('radio', { name: /compiled articles/i })).toBeChecked()

    await userEvent.type(await screen.findByLabelText('Topic'), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /^start$/i }))
    await waitFor(() =>
      expect(derivedApi.startDerive).toHaveBeenCalledWith({ topic: 'pricing' }),
    )
  })

  it('filters over raw documents when asked', async () => {
    render(<DeriveDialog />)
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

  // Same reason the topic input is disabled mid-run: the choice is already on the
  // queued job, so an input that still moves claims it affects a run it cannot.
  it('locks the catalog choice while a derive runs', async () => {
    await start()
    expect(await screen.findByText('Stage: compile')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /raw documents/i })).toBeDisabled()
  })

  it('will not start with an empty topic', async () => {
    await start('')
    expect(screen.getByRole('button', { name: /^start$/i })).toBeDisabled()
    expect(derivedApi.startDerive).not.toHaveBeenCalled()
  })

  it('wires the trigger to the dialog for assistive tech', () => {
    render(<DeriveDialog />)
    const trigger = screen.getByRole('button', { name: /derive/i })
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows the stage while the job runs, in a live region', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(job({ stage: 'compile' }))
    await start()
    expect(await screen.findByText('Stage: compile')).toBeInTheDocument()
    expect(await screen.findByRole('status')).toHaveTextContent('Stage: compile')
  })

  it('says queued while the job has no stage yet', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(job({ status: 'pending', stage: '' }))
    await start()
    expect(await screen.findByText('Queued')).toBeInTheDocument()
  })

  it('polls until the job reaches a terminal status', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(derivedApi.getDeriveJob)
      .mockResolvedValueOnce(job({ status: 'running', stage: 'filter' }))
      .mockResolvedValue(job({ status: 'succeeded', stage: 'done', result: RESULT }))

    await start()
    expect(await screen.findByText('Stage: filter')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000)
    })
    expect(await screen.findByText('Derived knowledge base ready')).toBeInTheDocument()
  })

  it('reports counts and cost on success', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(
      job({ status: 'succeeded', stage: 'done', result: RESULT }),
    )
    await start()

    expect(await screen.findByText('Derived knowledge base ready')).toBeInTheDocument()
    expect(
      screen.getByText('6 documents compiled, 2 articles moved off-topic'),
    ).toBeInTheDocument()
    expect(screen.getByText('Cost: 1.2345 USD')).toBeInTheDocument()
    // A live region, so an operator who tabbed away still hears it finish.
    expect(screen.getByRole('status')).toHaveTextContent('Derived knowledge base ready')
  })

  it('forgets a finished run when the dialog is reopened', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(
      job({ status: 'succeeded', stage: 'done', result: RESULT }),
    )
    await start()
    expect(await screen.findByText('Derived knowledge base ready')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))

    expect(await screen.findByLabelText('Topic')).toBeInTheDocument()
    expect(screen.queryByText('Derived knowledge base ready')).not.toBeInTheDocument()
    expect(screen.queryByText('Cost: 1.2345 USD')).not.toBeInTheDocument()
  })

  it('announces the finished knowledge base to its parent', async () => {
    const onDerived = vi.fn()
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(
      job({ status: 'succeeded', stage: 'done', result: RESULT }),
    )
    render(<DeriveDialog onDerived={onDerived} />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(await screen.findByLabelText('Topic'), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /^start$/i }))

    await waitFor(() => expect(onDerived).toHaveBeenCalledWith('pricing'))
    expect(onDerived).toHaveBeenCalledTimes(1)
  })

  it('shows the error on failure and stops polling', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(
      job({ status: 'failed', stage: 'done', error: 'no documents resolved' }),
    )
    await start()
    expect(await screen.findByText('no documents resolved')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('no documents resolved')

    const polls = vi.mocked(derivedApi.getDeriveJob).mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(vi.mocked(derivedApi.getDeriveJob).mock.calls.length).toBe(polls)
  })

  it('does not announce a failed job', async () => {
    const onDerived = vi.fn()
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(
      job({ status: 'failed', stage: 'done', error: 'no documents resolved' }),
    )
    render(<DeriveDialog onDerived={onDerived} />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(await screen.findByLabelText('Topic'), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /^start$/i }))

    expect(await screen.findByText('no documents resolved')).toBeInTheDocument()
    expect(onDerived).not.toHaveBeenCalled()
  })

  it('surfaces a rejected start', async () => {
    vi.mocked(derivedApi.startDerive).mockRejectedValue(new Error('already exists'))
    await start()
    expect(await screen.findByText('already exists')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
    expect(derivedApi.getDeriveJob).not.toHaveBeenCalled()
  })

  it('surfaces a poll that fails and stays usable afterwards', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockRejectedValue(new Error('gateway down'))
    await start()
    expect(await screen.findByText('gateway down')).toBeInTheDocument()

    // A broken poll must not strand the form: the run it was following is gone
    // as far as this dialog is concerned, so both controls come back.
    const startButton = screen.getByRole('button', { name: /^start$/i })
    await waitFor(() => expect(startButton).not.toBeDisabled())
    expect(await screen.findByLabelText('Topic')).not.toBeDisabled()

    vi.mocked(derivedApi.startDerive).mockResolvedValue({ job_id: 'j2', slug: 'pricing' })
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(
      job({ id: 'j2', status: 'succeeded', stage: 'done', result: RESULT }),
    )
    await userEvent.click(startButton)

    expect(await screen.findByText('Derived knowledge base ready')).toBeInTheDocument()
    expect(screen.queryByText('gateway down')).not.toBeInTheDocument()
  })

  it('lets a second derive run after the first finished', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(
      job({ status: 'succeeded', stage: 'done', result: RESULT }),
    )
    await start()
    expect(await screen.findByText('Derived knowledge base ready')).toBeInTheDocument()

    const input = await screen.findByLabelText('Topic')
    expect(input).not.toBeDisabled()
    await userEvent.clear(input)
    await userEvent.type(input, 'compliance')
    await userEvent.click(screen.getByRole('button', { name: /^start$/i }))
    await waitFor(() =>
      expect(derivedApi.startDerive).toHaveBeenLastCalledWith({ topic: 'compliance' }),
    )
  })
})
