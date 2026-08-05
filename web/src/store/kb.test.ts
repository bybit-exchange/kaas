/**
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useKB } from './kb'

const PERSIST_KEY = 'kaas-kb'

describe('useKB store', () => {
  beforeEach(() => {
    localStorage.clear()
    useKB.setState({ kb: null })
  })

  it('defaults to the root knowledge base', () => {
    expect(useKB.getState().kb).toBeNull()
  })

  it('selects a derived knowledge base', () => {
    useKB.getState().setKB('pricing')
    expect(useKB.getState().kb).toBe('pricing')
  })

  it('goes back to the root', () => {
    useKB.getState().setKB('pricing')
    useKB.getState().setKB(null)
    expect(useKB.getState().kb).toBeNull()
  })

  it('persists the selection so a reload keeps the corpus', () => {
    useKB.getState().setKB('pricing')
    const stored = localStorage.getItem(PERSIST_KEY)
    expect(stored).not.toBeNull()
    expect(JSON.parse(stored!).state.kb).toBe('pricing')
  })
})
