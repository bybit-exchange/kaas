import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { usePrefs } from '@/store/prefs'
import { StatusStageBadge, statusColor } from '../StatusStageBadge'

describe('StatusStageBadge', () => {
  beforeEach(() => {
    usePrefs.setState({ theme: 'light', lang: 'en' })
  })

  // --- Status color mapping ---

  it('applies green color for succeeded status', () => {
    render(<StatusStageBadge status="succeeded" stage="done" />)
    const badge = screen.getByText('Succeeded')
    expect(badge.className).toContain('text-green-700')
  })

  it('applies red color for failed status', () => {
    render(<StatusStageBadge status="failed" stage="extract" />)
    const badge = screen.getByText('Failed')
    expect(badge.className).toContain('text-red-700')
  })

  it('applies orange color for cancelled status', () => {
    render(<StatusStageBadge status="cancelled" stage="queued" />)
    const badge = screen.getByText('Cancelled')
    expect(badge.className).toContain('text-orange-700')
  })

  it('applies blue color for running status', () => {
    render(<StatusStageBadge status="running" stage="extract" />)
    const badge = screen.getByText(/Running/)
    expect(badge.className).toContain('text-blue-700')
  })

  it('applies yellow color for pending status', () => {
    render(<StatusStageBadge status="pending" stage="queued" />)
    const badge = screen.getByText(/Pending/)
    expect(badge.className).toContain('text-yellow-700')
  })

  // --- Terminal status shows only status ---

  it('shows only status text for succeeded', () => {
    render(<StatusStageBadge status="succeeded" stage="done" />)
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
  })

  it('shows only status text for failed', () => {
    render(<StatusStageBadge status="failed" stage="extract" />)
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('shows only status text for cancelled', () => {
    render(<StatusStageBadge status="cancelled" stage="queued" />)
    expect(screen.getByText('Cancelled')).toBeInTheDocument()
  })

  // --- Running/pending shows status + stage ---

  it('shows "Running · Extracting" for running+extract', () => {
    render(<StatusStageBadge status="running" stage="extract" />)
    expect(screen.getByText('Running · Extracting')).toBeInTheDocument()
  })

  it('shows "Pending · Queued" for pending+queued', () => {
    render(<StatusStageBadge status="pending" stage="queued" />)
    expect(screen.getByText('Pending · Queued')).toBeInTheDocument()
  })

  it('shows "Running · Pipeline" for running+pipeline', () => {
    render(<StatusStageBadge status="running" stage="pipeline" />)
    expect(screen.getByText('Running · Pipeline')).toBeInTheDocument()
  })

  // --- Derive stage labels ---

  it('resolves deriveStage keys for derive stages', () => {
    render(<StatusStageBadge status="running" stage="filter" />)
    expect(screen.getByText('Running · Filtering')).toBeInTheDocument()
  })

  it('resolves deriveStage.compile for compile stage', () => {
    render(<StatusStageBadge status="running" stage="compile" />)
    expect(screen.getByText('Running · Compiling')).toBeInTheDocument()
  })

  // --- Unknown status/stage fallback ---

  it('falls back to raw status string for unknown status', () => {
    render(<StatusStageBadge status="unknown_status" stage="done" />)
    // Unknown status is not terminal, so it shows status · stage
    expect(screen.getByText('unknown_status · Done')).toBeInTheDocument()
  })

  it('falls back to raw stage string for unknown stage', () => {
    render(<StatusStageBadge status="running" stage="unknown_stage" />)
    expect(screen.getByText('Running · unknown_stage')).toBeInTheDocument()
  })

  // --- statusColor export ---

  it('returns empty string for unknown status', () => {
    expect(statusColor('something_else')).toBe('')
  })
})
