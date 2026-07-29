import '@testing-library/jest-dom'

// jsdom does not implement IntersectionObserver — provide a no-op stub so
// components that use it (e.g. TableOfContents) don't throw.
if (typeof window !== 'undefined' && !window.IntersectionObserver) {
  const noop = () => {}
  class IntersectionObserverStub {
    observe = noop
    unobserve = noop
    disconnect = noop
  }
  Object.defineProperty(window, 'IntersectionObserver', {
    value: IntersectionObserverStub,
    writable: true,
    configurable: true,
  })
}

// Node.js 22+ ships an experimental localStorage that conflicts with jsdom.
// When --localstorage-file is not passed, Node sets globalThis.localStorage to
// undefined, overwriting jsdom's own implementation. We restore it here so
// tests can use localStorage / window.localStorage normally.
if (typeof window !== 'undefined' && typeof window.localStorage === 'undefined') {
  const store: Record<string, string> = {}
  const mockLocalStorage: Storage = {
    get length() { return Object.keys(store).length },
    key(index: number) { return Object.keys(store)[index] ?? null },
    getItem(key: string) { return key in store ? store[key] : null },
    setItem(key: string, value: string) { store[key] = String(value) },
    removeItem(key: string) { delete store[key] },
    clear() { Object.keys(store).forEach((k) => delete store[k]) },
  }
  // Define directly on window (jsdom's global); also makes bare `localStorage` work
  // because in jsdom, `window === globalThis`, so we just set the value directly.
  Object.defineProperty(window, 'localStorage', {
    value: mockLocalStorage,
    writable: true,
    configurable: true,
  })
}
