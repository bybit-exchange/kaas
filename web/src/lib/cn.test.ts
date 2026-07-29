import { describe, it, expect } from 'vitest'
import { cn } from './cn'

describe('cn', () => {
  it('merges and dedupes tailwind classes', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4')
    expect(cn('a', false && 'b', 'c')).toBe('a c')
  })
})
