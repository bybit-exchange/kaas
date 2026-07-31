import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CitationMarker } from './CitationMarker'

describe('CitationMarker', () => {
  it('renders the citation index as the label', () => {
    render(<CitationMarker index={3} onClick={() => {}} />)

    expect(screen.getByRole('button', { name: 'Jump to source 3' })).toHaveTextContent('3')
  })

  it('is a non-submitting button so it cannot post an enclosing form', () => {
    render(<CitationMarker index={1} onClick={() => {}} />)

    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })

  it('reports its own index on click', async () => {
    const onClick = vi.fn()
    render(<CitationMarker index={7} onClick={onClick} />)

    await userEvent.click(screen.getByRole('button'))

    expect(onClick).toHaveBeenCalledTimes(1)
    expect(onClick).toHaveBeenCalledWith(7)
  })

  it('reports the right index when several markers are rendered', async () => {
    const onClick = vi.fn()
    render(
      <>
        <CitationMarker index={1} onClick={onClick} />
        <CitationMarker index={2} onClick={onClick} />
      </>,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Jump to source 2' }))

    expect(onClick).toHaveBeenCalledTimes(1)
    expect(onClick).toHaveBeenCalledWith(2)
  })

  it('fires once per click', async () => {
    const onClick = vi.fn()
    render(<CitationMarker index={1} onClick={onClick} />)

    const button = screen.getByRole('button')
    await userEvent.click(button)
    await userEvent.click(button)

    expect(onClick).toHaveBeenCalledTimes(2)
  })
})
