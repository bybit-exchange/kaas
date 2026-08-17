import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useUploadConfig } from './useUploadConfig'
import { DEFAULT_UPLOAD_CONFIG, type UploadConfig } from '@/api/upload-config'

const fetchUploadConfig = vi.hoisted(() => vi.fn())

vi.mock('@/api/upload-config', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/upload-config')>()
  return { ...actual, fetchUploadConfig }
})

const serverConfig: UploadConfig = {
  maxFileSize: 4096,
  maxRichFileSize: 16384,
  maxZipFileSize: 8192,
  maxFilesPerUpload: 7,
  allowedExtensions: ['.md'],
}

beforeEach(() => {
  fetchUploadConfig.mockReset()
})

describe('useUploadConfig', () => {
  it('starts from the defaults so the UI can render before the fetch resolves', () => {
    fetchUploadConfig.mockReturnValue(new Promise(() => {}))

    const { result } = renderHook(() => useUploadConfig())

    expect(result.current).toEqual(DEFAULT_UPLOAD_CONFIG)
  })

  it('swaps in the server config once loaded', async () => {
    fetchUploadConfig.mockResolvedValue(serverConfig)

    const { result } = renderHook(() => useUploadConfig())

    await waitFor(() => expect(result.current).toEqual(serverConfig))
  })

  it('keeps the defaults when the request fails', async () => {
    fetchUploadConfig.mockRejectedValue(new Error('network down'))

    const { result } = renderHook(() => useUploadConfig())

    await waitFor(() => expect(fetchUploadConfig).toHaveBeenCalled())
    expect(result.current).toEqual(DEFAULT_UPLOAD_CONFIG)
  })

  it('fetches once per mount', async () => {
    fetchUploadConfig.mockResolvedValue(serverConfig)

    const { rerender, result } = renderHook(() => useUploadConfig())
    await waitFor(() => expect(result.current).toEqual(serverConfig))
    rerender()

    expect(fetchUploadConfig).toHaveBeenCalledTimes(1)
  })

  it('ignores a response that lands after unmount', async () => {
    let resolveFetch: (c: UploadConfig) => void = () => {}
    fetchUploadConfig.mockReturnValue(
      new Promise<UploadConfig>((resolve) => {
        resolveFetch = resolve
      }),
    )

    const { unmount } = renderHook(() => useUploadConfig())
    unmount()

    // Resolving after unmount must not attempt a state update on a dead component.
    const errors: unknown[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...args) => {
      errors.push(args)
    })
    resolveFetch(serverConfig)
    await Promise.resolve()
    spy.mockRestore()

    expect(errors).toEqual([])
  })
})
