import { beforeEach, describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import React from 'react'
import { LangProvider, useT } from './index'
import { usePrefs } from '@/store/prefs'
import { STRINGS } from './strings'

describe('i18n', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    // Reset prefs store to defaults
    usePrefs.setState({ theme: 'light', lang: 'en' })
  })

  describe('STRINGS', () => {
    it('has all layout keys in en', () => {
      const keys = ['layout.chat', 'layout.submit', 'layout.wiki', 'layout.status', 'layout.toggleTheme', 'layout.toggleLang']
      for (const k of keys) {
        expect(typeof STRINGS.en[k]).toBe('string')
        expect(STRINGS.en[k].length).toBeGreaterThan(0)
      }
    })

    it('has all layout keys in zh', () => {
      const keys = ['layout.chat', 'layout.submit', 'layout.wiki', 'layout.status', 'layout.toggleTheme', 'layout.toggleLang']
      for (const k of keys) {
        expect(typeof STRINGS.zh[k]).toBe('string')
        expect(STRINGS.zh[k].length).toBeGreaterThan(0)
      }
    })
  })

  describe('useT', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <LangProvider>{children}</LangProvider>
    )

    it('returns English string for layout.chat by default (lang=en)', () => {
      const { result } = renderHook(() => useT(), { wrapper })
      expect(result.current('layout.chat')).toBe(STRINGS.en['layout.chat'])
    })

    it('returns Chinese string after lang switched to zh', () => {
      const { result } = renderHook(() => useT(), { wrapper })
      act(() => {
        usePrefs.setState({ lang: 'zh' })
      })
      expect(result.current('layout.chat')).toBe(STRINGS.zh['layout.chat'])
    })

    it('interpolates {{var}} tokens', () => {
      // Temporarily add a test key to STRINGS for this test
      const origEn = STRINGS.en['greet']
      STRINGS.en['greet'] = 'Hi {{name}}'
      try {
        const { result } = renderHook(() => useT(), { wrapper })
        expect(result.current('greet', { name: 'X' })).toBe('Hi X')
      } finally {
        // Cleanup: ensure temporary key is removed even if assertion fails
        if (origEn === undefined) {
          delete STRINGS.en['greet']
        } else {
          STRINGS.en['greet'] = origEn
        }
      }
    })

    it('returns key itself for unknown key', () => {
      const { result } = renderHook(() => useT(), { wrapper })
      expect(result.current('some.unknown.key')).toBe('some.unknown.key')
    })

    it('handles multiple interpolation variables', () => {
      STRINGS.en['msg'] = '{{a}} and {{b}}'
      try {
        const { result } = renderHook(() => useT(), { wrapper })
        expect(result.current('msg', { a: 'foo', b: 'bar' })).toBe('foo and bar')
      } finally {
        delete STRINGS.en['msg']
      }
    })
  })
})
