/**
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useKB } from './kb'

const PERSIST_KEY = 'kaas-kb'

describe('useKB store', () => {
  beforeEach(() => {
    localStorage.clear()
    useKB.setState({ kb: null, chatKB: null })
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

  it('chatKB defaults to null', () => {
    expect(useKB.getState().chatKB).toBeNull()
  })

  it('setChatKB selects a derived knowledge base for chat', () => {
    useKB.getState().setChatKB('pricing')
    expect(useKB.getState().chatKB).toBe('pricing')
  })

  it('setChatKB(null) goes back to the root', () => {
    useKB.getState().setChatKB('pricing')
    useKB.getState().setChatKB(null)
    expect(useKB.getState().chatKB).toBeNull()
  })

  it('chatKB and kb are independent', () => {
    useKB.getState().setKB('compliance')
    useKB.getState().setChatKB('pricing')
    expect(useKB.getState().kb).toBe('compliance')
    expect(useKB.getState().chatKB).toBe('pricing')
  })

  it('persists chatKB alongside kb', () => {
    useKB.getState().setChatKB('pricing')
    const stored = localStorage.getItem(PERSIST_KEY)
    expect(stored).not.toBeNull()
    expect(JSON.parse(stored!).state.chatKB).toBe('pricing')
  })
})
