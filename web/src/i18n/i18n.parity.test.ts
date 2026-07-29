/**
 * i18n key parity test — asserts that every key present in `en` is also
 * present in `zh` and vice-versa.  Add keys to STRINGS in `strings.ts`
 * for BOTH locales to keep this green.
 */
import { describe, it, expect } from 'vitest'
import { STRINGS } from './strings'

describe('i18n key parity', () => {
  it('en and zh have exactly the same keys', () => {
    const enKeys = Object.keys(STRINGS.en).sort()
    const zhKeys = Object.keys(STRINGS.zh).sort()
    expect(enKeys).toEqual(zhKeys)
  })
})
