import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchUploadConfig, DEFAULT_UPLOAD_CONFIG } from './upload-config'
import { ApiError } from './client'

const mockFetch = vi.fn()
global.fetch = mockFetch

function makeResponse(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'HTTP ' + status,
    clone() {
      return this
    },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(text),
  } as unknown as Response
}

beforeEach(() => {
  mockFetch.mockReset()
})

describe('DEFAULT_UPLOAD_CONFIG', () => {
  it('keeps the plain-file limit below the zip limit', () => {
    expect(DEFAULT_UPLOAD_CONFIG.maxFileSize).toBeLessThan(DEFAULT_UPLOAD_CONFIG.maxZipFileSize)
  })

  it('accepts zip alongside the text formats', () => {
    expect(DEFAULT_UPLOAD_CONFIG.allowedExtensions).toContain('.zip')
    expect(DEFAULT_UPLOAD_CONFIG.allowedExtensions).toContain('.md')
  })

  it('lists extensions with a leading dot so name.endsWith checks work', () => {
    for (const ext of DEFAULT_UPLOAD_CONFIG.allowedExtensions) {
      expect(ext.startsWith('.')).toBe(true)
    }
  })
})

describe('fetchUploadConfig', () => {
  it('maps the snake_case payload to camelCase', async () => {
    mockFetch.mockResolvedValue(
      makeResponse(200, {
        max_file_size: 2097152,
        max_rich_file_size: 5242880,
        max_zip_file_size: 10485760,
        max_files_per_upload: 50,
        allowed_extensions: ['.md', '.txt'],
      }),
    )

    const config = await fetchUploadConfig()

    expect(config).toEqual({
      maxFileSize: 2097152,
      maxRichFileSize: 5242880,
      maxZipFileSize: 10485760,
      maxFilesPerUpload: 50,
      allowedExtensions: ['.md', '.txt'],
    })
    expect(mockFetch.mock.calls[0][0]).toBe('/api/upload/config')
  })

  it('does not leak the snake_case keys through', async () => {
    mockFetch.mockResolvedValue(
      makeResponse(200, {
        max_file_size: 1,
        max_rich_file_size: 5,
        max_zip_file_size: 2,
        max_files_per_upload: 3,
        allowed_extensions: [],
      }),
    )

    const config = await fetchUploadConfig()

    expect(Object.keys(config).sort()).toEqual([
      'allowedExtensions',
      'maxFileSize',
      'maxFilesPerUpload',
      'maxRichFileSize',
      'maxZipFileSize',
    ])
  })

  it('surfaces a backend error as ApiError', async () => {
    mockFetch.mockResolvedValue(makeResponse(503, { error: 'config unavailable' }))

    await expect(fetchUploadConfig()).rejects.toThrow(ApiError)
    await expect(fetchUploadConfig()).rejects.toThrow('config unavailable')
  })
})
