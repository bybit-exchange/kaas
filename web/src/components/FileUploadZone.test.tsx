import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import type { UploadConfig } from '@/api/upload-config'
import type { SubmitFilesResult } from '@/api/submit'

// Deterministic upload limits — the hook itself is covered by its own test.
const CONFIG: UploadConfig = {
  maxFileSize: 1024,
  maxRichFileSize: 10 * 1024,
  maxZipFileSize: 2 * 1024 * 1024,
  maxFilesPerUpload: 3,
  allowedExtensions: ['.md', '.txt', '.zip'],
}

vi.mock('@/hooks/useUploadConfig', () => ({
  useUploadConfig: () => CONFIG,
}))

vi.mock('@/api/submit', () => ({
  submitFiles: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Import AFTER mocking
import { FileUploadZone } from './FileUploadZone'
import { submitFiles } from '@/api/submit'
import { toast } from 'sonner'

const mockSubmitFiles = vi.mocked(submitFiles)
const mockToast = vi.mocked(toast)

/**
 * Build a File with an arbitrary reported size without allocating the bytes.
 */
function makeFile(name: string, size: number): File {
  const file = new File(['x'], name)
  Object.defineProperty(file, 'size', { value: size })
  return file
}

function renderZone(onUploadComplete?: (r: SubmitFilesResult) => void) {
  return render(
    <LangProvider>
      <FileUploadZone onUploadComplete={onUploadComplete} />
    </LangProvider>,
  )
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector('input[type="file"]')
  if (!input) throw new Error('file input not found')
  return input as HTMLInputElement
}

/** Simulate the user picking files through the hidden <input type="file">. */
function selectFiles(files: File[]) {
  fireEvent.change(fileInput(), { target: { files } })
}

function dropzone(): HTMLElement {
  return screen.getByText('Drag and drop files here, or click to select').parentElement!
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  vi.clearAllMocks()
  mockSubmitFiles.mockResolvedValue({ uploaded: [], failed: [] })
})

describe('FileUploadZone', () => {
  describe('idle state', () => {
    it('shows the dropzone hint with human-readable size limits and allowed types', () => {
      renderZone()

      expect(
        screen.getByText('Drag and drop files here, or click to select'),
      ).toBeInTheDocument()
      // 1024 B -> "1.0 KB", 2 MiB -> "2.0 MB"
      expect(screen.getByText(/Max 1\.0 KB per file, 10\.0 KB for documents, 2\.0 MB for ZIP/)).toBeInTheDocument()
      expect(screen.getByText(/Supported: \.md \.txt \.zip/)).toBeInTheDocument()
    })

    it('restricts the native picker via the accept attribute', () => {
      renderZone()
      expect(fileInput()).toHaveAttribute('accept', '.md,.txt,.zip')
    })

    it('opens the native file picker when the dropzone is clicked', () => {
      renderZone()
      const input = fileInput()
      const clickSpy = vi.spyOn(input, 'click').mockImplementation(() => {})

      fireEvent.click(dropzone())

      expect(clickSpy).toHaveBeenCalledTimes(1)
    })
  })

  describe('file validation', () => {
    it('accepts a valid file and lists it with a formatted size', () => {
      renderZone()

      selectFiles([makeFile('notes.md', 512)])

      expect(screen.getByText('1 file(s) selected')).toBeInTheDocument()
      expect(screen.getByText('notes.md')).toBeInTheDocument()
      expect(screen.getByText('512 B')).toBeInTheDocument()
      expect(mockToast.error).not.toHaveBeenCalled()
    })

    it('rejects a file whose extension is not allowed', () => {
      renderZone()

      selectFiles([makeFile('report.pdf', 100)])

      expect(mockToast.error).toHaveBeenCalledWith('report.pdf has unsupported extension')
      expect(screen.queryByText('report.pdf')).not.toBeInTheDocument()
      // Still in idle state
      expect(
        screen.getByText('Drag and drop files here, or click to select'),
      ).toBeInTheDocument()
    })

    it('rejects a non-zip file above maxFileSize', () => {
      renderZone()

      selectFiles([makeFile('big.txt', 1025)])

      expect(mockToast.error).toHaveBeenCalledWith('big.txt exceeds size limit')
      expect(screen.queryByText('big.txt')).not.toBeInTheDocument()
    })

    it('accepts a zip above maxFileSize because zips get their own larger limit', () => {
      renderZone()

      selectFiles([makeFile('bundle.zip', 1536)])

      expect(mockToast.error).not.toHaveBeenCalled()
      expect(screen.getByText('bundle.zip')).toBeInTheDocument()
      expect(screen.getByText('1.5 KB')).toBeInTheDocument()
    })

    it('rejects a zip above maxZipFileSize', () => {
      renderZone()

      selectFiles([makeFile('huge.zip', 3 * 1024 * 1024)])

      expect(mockToast.error).toHaveBeenCalledWith('huge.zip exceeds ZIP size limit')
      expect(screen.queryByText('huge.zip')).not.toBeInTheDocument()
    })

    it('keeps the valid files and reports only the invalid one in a mixed selection', () => {
      renderZone()

      selectFiles([makeFile('ok.md', 100), makeFile('bad.exe', 100)])

      expect(mockToast.error).toHaveBeenCalledTimes(1)
      expect(screen.getByText('ok.md')).toBeInTheDocument()
      expect(screen.getByText('1 file(s) selected')).toBeInTheDocument()
    })

    it('rejects the whole batch when it would exceed maxFilesPerUpload', () => {
      renderZone()

      selectFiles([
        makeFile('a.md', 10),
        makeFile('b.md', 10),
        makeFile('c.md', 10),
        makeFile('d.md', 10),
      ])

      expect(mockToast.error).toHaveBeenCalledWith('Maximum 3 files per upload')
      expect(screen.queryByText('a.md')).not.toBeInTheDocument()
    })

    it('counts already-selected files against maxFilesPerUpload', () => {
      renderZone()

      selectFiles([makeFile('a.md', 10), makeFile('b.md', 10)])
      expect(screen.getByText('2 file(s) selected')).toBeInTheDocument()

      selectFiles([makeFile('c.md', 10), makeFile('d.md', 10)])

      expect(mockToast.error).toHaveBeenCalledWith('Maximum 3 files per upload')
      expect(screen.getByText('2 file(s) selected')).toBeInTheDocument()
    })

    it('appends files from a second selection to the existing list', () => {
      renderZone()

      selectFiles([makeFile('a.md', 10)])
      selectFiles([makeFile('b.md', 10)])

      expect(screen.getByText('2 file(s) selected')).toBeInTheDocument()
      expect(screen.getByText('a.md')).toBeInTheDocument()
      expect(screen.getByText('b.md')).toBeInTheDocument()
    })

    it('resets the input value so re-picking the same file still fires a change', () => {
      renderZone()

      selectFiles([makeFile('a.md', 10)])

      expect(fileInput().value).toBe('')
    })
  })

  describe('drag and drop', () => {
    it('highlights on dragover and clears the highlight on dragleave', () => {
      renderZone()
      const zone = dropzone()

      fireEvent.dragOver(zone)
      expect(zone.className).toContain('border-primary')

      fireEvent.dragLeave(zone)
      expect(zone.className).not.toContain('border-primary')
    })

    it('adds dropped files and validates them like picked files', () => {
      renderZone()

      fireEvent.drop(dropzone(), {
        dataTransfer: { files: [makeFile('dropped.md', 200), makeFile('nope.pdf', 200)] },
      })

      expect(screen.getByText('dropped.md')).toBeInTheDocument()
      expect(mockToast.error).toHaveBeenCalledWith('nope.pdf has unsupported extension')
    })

    it('ignores a drop that carries no files', () => {
      renderZone()

      fireEvent.drop(dropzone(), { dataTransfer: { files: [] } })

      expect(mockToast.error).not.toHaveBeenCalled()
      expect(
        screen.getByText('Drag and drop files here, or click to select'),
      ).toBeInTheDocument()
    })
  })

  describe('preview state', () => {
    it('removes a single file without touching the others', () => {
      renderZone()
      selectFiles([makeFile('a.md', 10), makeFile('b.md', 10)])

      const row = screen.getByText('a.md').parentElement!
      fireEvent.click(row.querySelector('button')!)

      expect(screen.queryByText('a.md')).not.toBeInTheDocument()
      expect(screen.getByText('b.md')).toBeInTheDocument()
      expect(screen.getByText('1 file(s) selected')).toBeInTheDocument()
    })

    it('returns to the idle dropzone after Clear', () => {
      renderZone()
      selectFiles([makeFile('a.md', 10)])

      fireEvent.click(screen.getByRole('button', { name: 'Clear' }))

      expect(
        screen.getByText('Drag and drop files here, or click to select'),
      ).toBeInTheDocument()
      expect(screen.queryByText('a.md')).not.toBeInTheDocument()
    })

    it('reopens the native picker from "Add more"', () => {
      renderZone()
      selectFiles([makeFile('a.md', 10)])

      const clickSpy = vi.spyOn(fileInput(), 'click').mockImplementation(() => {})
      fireEvent.click(screen.getByRole('button', { name: 'Add more' }))

      expect(clickSpy).toHaveBeenCalledTimes(1)
    })
  })

  describe('upload', () => {
    it('uploads the selected files, reports success and clears the list', async () => {
      const onComplete = vi.fn()
      const result: SubmitFilesResult = {
        uploaded: [{ id: 't1', name: 'a.md', status: 'pending' }],
        failed: [],
      }
      mockSubmitFiles.mockResolvedValue(result)

      renderZone(onComplete)
      const file = makeFile('a.md', 10)
      selectFiles([file])

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }))
      })

      expect(mockSubmitFiles).toHaveBeenCalledWith([file])
      expect(mockToast.success).toHaveBeenCalledWith('Uploaded 1/1 files')
      expect(onComplete).toHaveBeenCalledWith(result)
      expect(
        screen.getByText('Drag and drop files here, or click to select'),
      ).toBeInTheDocument()
    })

    it('shows the uploading placeholder while the request is in flight', async () => {
      let release: (r: SubmitFilesResult) => void = () => {}
      mockSubmitFiles.mockReturnValue(
        new Promise<SubmitFilesResult>((resolve) => {
          release = resolve
        }),
      )

      renderZone()
      selectFiles([makeFile('a.md', 10)])
      fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }))

      expect(screen.getByText('Uploading…')).toBeInTheDocument()
      expect(screen.queryByText('a.md')).not.toBeInTheDocument()

      await act(async () => {
        release({ uploaded: [], failed: [] })
      })

      expect(screen.queryByText('Uploading…')).not.toBeInTheDocument()
    })

    it('reports every rejected file alongside the partial success', async () => {
      mockSubmitFiles.mockResolvedValue({
        uploaded: [{ id: 't1', name: 'a.md', status: 'pending' }],
        failed: [
          { name: 'b.md', reason: 'duplicate' },
          { name: 'c.md', reason: 'corrupt' },
        ],
      })

      renderZone()
      selectFiles([makeFile('a.md', 10), makeFile('b.md', 10), makeFile('c.md', 10)])

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Upload 3 file(s)' }))
      })

      expect(mockToast.success).toHaveBeenCalledWith('Uploaded 1/3 files')
      expect(mockToast.error).toHaveBeenCalledWith('b.md: duplicate')
      expect(mockToast.error).toHaveBeenCalledWith('c.md: corrupt')
    })

    it('does not claim success when every file was rejected', async () => {
      mockSubmitFiles.mockResolvedValue({
        uploaded: [],
        failed: [{ name: 'a.md', reason: 'duplicate' }],
      })

      renderZone()
      selectFiles([makeFile('a.md', 10)])

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }))
      })

      expect(mockToast.success).not.toHaveBeenCalled()
      expect(mockToast.error).toHaveBeenCalledWith('a.md: duplicate')
    })

    it('surfaces the server error message and keeps the selection when the request throws', async () => {
      mockSubmitFiles.mockRejectedValue(new Error('network down'))

      renderZone()
      selectFiles([makeFile('a.md', 10)])

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }))
      })

      expect(mockToast.error).toHaveBeenCalledWith('network down')
      // Selection survives so the user can retry.
      expect(screen.getByText('a.md')).toBeInTheDocument()
    })

    it('falls back to a generic message when the failure carries no message', async () => {
      mockSubmitFiles.mockRejectedValue('boom')

      renderZone()
      selectFiles([makeFile('a.md', 10)])

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }))
      })

      expect(mockToast.error).toHaveBeenCalledWith('Upload failed, please retry')
    })
  })
})
