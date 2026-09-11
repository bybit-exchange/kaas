import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { usePrefs } from '@/store/prefs'
import { StatusStageBadge, statusColor, statusBadgeStyles } from '../StatusStageBadge'

describe('statusBadgeStyles', () => {
  it('returns correct colors for succeeded', () => {
    expect(statusBadgeStyles('succeeded')).toEqual({
      color: '#1a7a3a',
      backgroundColor: '#e8f5e9',
      borderColor: '#a5d6a7',
    })
  })

  it('returns correct colors for failed', () => {
    expect(statusBadgeStyles('failed')).toEqual({
      color: '#b5302b',
      backgroundColor: '#ffe8e7',
      borderColor: '#ef9a9a',
    })
  })

  it('returns correct colors for cancelled', () => {
    expect(statusBadgeStyles('cancelled')).toEqual({
      color: '#a04a1b',
      backgroundColor: '#fff3e0',
      borderColor: '#ffcc80',
    })
  })

  it('returns correct colors for partial', () => {
    expect(statusBadgeStyles('partial')).toEqual({
      color: '#7a6010',
      backgroundColor: '#fff8e1',
      borderColor: '#ffe082',
    })
  })

  it('returns correct colors for running', () => {
    expect(statusBadgeStyles('running')).toEqual({
      color: '#0f5f6d',
      backgroundColor: '#e0f5f5',
      borderColor: '#80cbc4',
    })
  })

  it('returns correct colors for pending', () => {
    expect(statusBadgeStyles('pending')).toEqual({
      color: '#6a5f10',
      backgroundColor: '#fdf8e8',
      borderColor: '#fff59d',
    })
  })

  it('returns default colors for unknown status', () => {
    expect(statusBadgeStyles('something_else')).toEqual({
      color: '#4b5563',
      backgroundColor: '#f3f4f6',
      borderColor: '#d1d5db',
    })
  })
})

describe('StatusStageBadge', () => {
  beforeEach(() => {
    usePrefs.setState({ theme: 'light', lang: 'en' })
  })

  // --- Inline style color assertions ---

  it('applies correct inline styles for succeeded status', () => {
    render(<StatusStageBadge status="succeeded" stage="done" />)
    const badge = screen.getByText('Succeeded')
    expect(badge.style.color).toBe('rgb(26, 122, 58)')
    expect(badge.style.backgroundColor).toBe('rgb(232, 245, 233)')
    expect(badge.style.borderColor).toBe('rgb(165, 214, 167)')
  })

  it('applies correct inline styles for failed status', () => {
    render(<StatusStageBadge status="failed" stage="extract" />)
    const badge = screen.getByText('Failed')
    expect(badge.style.color).toBe('rgb(181, 48, 43)')
    expect(badge.style.backgroundColor).toBe('rgb(255, 232, 231)')
  })

  it('applies correct inline styles for cancelled status', () => {
    render(<StatusStageBadge status="cancelled" stage="queued" />)
    const badge = screen.getByText('Cancelled')
    expect(badge.style.color).toBe('rgb(160, 74, 27)')
    expect(badge.style.backgroundColor).toBe('rgb(255, 243, 224)')
  })

  it('applies correct inline styles for running status', () => {
    render(<StatusStageBadge status="running" stage="extract" />)
    const badge = screen.getByText(/Running/)
    expect(badge.style.color).toBe('rgb(15, 95, 109)')
    expect(badge.style.backgroundColor).toBe('rgb(224, 245, 245)')
  })

  it('applies correct inline styles for pending status', () => {
    render(<StatusStageBadge status="pending" stage="queued" />)
    const badge = screen.getByText(/Pending/)
    expect(badge.style.color).toBe('rgb(106, 95, 16)')
    expect(badge.style.backgroundColor).toBe('rgb(253, 248, 232)')
  })

  it('applies correct inline styles for partial status', () => {
    render(<StatusStageBadge status="partial" stage="done" />)
    const badge = screen.getByText('Partial')
    expect(badge.style.color).toBe('rgb(122, 96, 16)')
    expect(badge.style.backgroundColor).toBe('rgb(255, 248, 225)')
  })

  it('applies default inline styles for unknown status', () => {
    render(<StatusStageBadge status="unknown_status" stage="done" />)
    const badge = screen.getByText('unknown_status · Done')
    expect(badge.style.color).toBe('rgb(75, 85, 99)')
    expect(badge.style.backgroundColor).toBe('rgb(243, 244, 246)')
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

  // --- Partial status ---

  it('shows only status text for partial (terminal)', () => {
    render(<StatusStageBadge status="partial" stage="done" />)
    expect(screen.getByText('Partial')).toBeInTheDocument()
  })

  // --- Optional stage (omitted) ---

  it('shows status only when stage is omitted', () => {
    render(<StatusStageBadge status="running" />)
    // Without a stage, the separator dot should not appear
    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('shows status only when stage is undefined for pending', () => {
    render(<StatusStageBadge status="pending" />)
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })

  // --- statusColor (deprecated) still works ---

  it('returns empty string for unknown status', () => {
    expect(statusColor('something_else')).toBe('')
  })

  it('returns amber classes for partial status', () => {
    expect(statusColor('partial')).toContain('text-amber-700')
  })
})
