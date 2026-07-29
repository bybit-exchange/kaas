import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { ApiError } from '@/api/client'

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

// Mock useNavigate
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

// Mock submit API
vi.mock('@/api/submit', () => ({
  submit: vi.fn(),
}))

// Mock upload config API to avoid network calls in tests
vi.mock('@/api/upload-config', () => ({
  fetchUploadConfig: vi.fn().mockRejectedValue(new Error('no network')),
  DEFAULT_UPLOAD_CONFIG: {
    maxFileSize: 1 * 1024 * 1024,
    maxZipFileSize: 5 * 1024 * 1024,
    maxFilesPerUpload: 20,
    allowedExtensions: ['.csv', '.md', '.txt', '.zip'],
  },
}))

// Import AFTER mocking
import { Submit } from './Submit'
import { submit } from '@/api/submit'
import { toast } from 'sonner'

const mockSubmit = vi.mocked(submit)
const mockToastSuccess = vi.mocked(toast.success)
const mockToastError = vi.mocked(toast.error)

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter>
      <LangProvider>{children}</LangProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  vi.clearAllMocks()
  mockSubmit.mockResolvedValue({ id: 'abc', status: 'pending', stage: 'queued' })
})

describe('Submit page', () => {
  it('paste: types content + title, clicks submit → submit called with source=paste and success toast', async () => {
    const user = userEvent.setup()

    render(
      <Wrapper>
        <Submit />
      </Wrapper>,
    )

    // Switch to paste tab (default is file tab)
    await user.click(screen.getByRole('button', { name: /paste/i }))

    const contentTextarea = screen.getByRole('textbox', { name: /content/i })
    await user.type(contentTextarea, 'Hello world content')

    const titleInput = screen.getByRole('textbox', { name: /title/i })
    await user.type(titleInput, 'My Title')

    const submitBtn = screen.getByRole('button', { name: /submit/i })
    await user.click(submitBtn)

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledWith({
        source: 'paste',
        content: 'Hello world content',
        title: 'My Title',
      })
    })

    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith('Content submitted successfully')
    })

    // Status navigation should be offered
    await waitFor(() => {
      const viewStatusBtn = screen.getByRole('button', { name: /view in status/i })
      expect(viewStatusBtn).toBeInTheDocument()
      return viewStatusBtn
    })

    // Clicking "View in Status" navigates to /tasks
    await user.click(screen.getByRole('button', { name: /view in status/i }))
    expect(mockNavigate).toHaveBeenCalledWith('/tasks')
  })

  it('url: switches to url tab, enters url, clicks submit → submit called with source=url', async () => {
    const user = userEvent.setup()

    render(
      <Wrapper>
        <Submit />
      </Wrapper>,
    )

    // Switch to URL tab
    await user.click(screen.getByRole('button', { name: /url/i }))

    const urlInput = screen.getByRole('textbox', { name: /url/i })
    await user.type(urlInput, 'https://example.com/article')

    const submitBtn = screen.getByRole('button', { name: /submit/i })
    await user.click(submitBtn)

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledWith({
        source: 'url',
        url: 'https://example.com/article',
      })
    })
  })

  it('409: mock submit rejects ApiError(409) → distinct "already submitted" message, not generic error', async () => {
    mockSubmit.mockRejectedValueOnce(new ApiError(409, 'duplicate'))

    const user = userEvent.setup()

    render(
      <Wrapper>
        <Submit />
      </Wrapper>,
    )

    // Switch to paste tab (default is file tab)
    await user.click(screen.getByRole('button', { name: /paste/i }))

    const contentTextarea = screen.getByRole('textbox', { name: /content/i })
    await user.type(contentTextarea, 'Some content')

    const submitBtn = screen.getByRole('button', { name: /submit/i })
    await user.click(submitBtn)

    await waitFor(() => {
      // 409 must fire the distinct duplicate message, not the generic error
      expect(mockToastError).toHaveBeenCalledWith('This content was already submitted')
    })

    // Generic error must NOT have been shown
    expect(mockToastError).not.toHaveBeenCalledWith('Submission failed. Please try again.')
  })

  it('file: rejects a disallowed file type with toast error', async () => {
    const user = userEvent.setup()

    render(
      <Wrapper>
        <Submit />
      </Wrapper>,
    )

    // Switch to file tab
    await user.click(screen.getByRole('button', { name: /file/i }))

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(fileInput).toBeTruthy()

    // Upload a disallowed file type using fireEvent to bypass accept attribute filtering
    const badFile = new File(['binary content'], 'document.pdf', { type: 'application/pdf' })
    Object.defineProperty(fileInput, 'files', {
      value: [badFile],
      configurable: true,
    })
    fireEvent.change(fileInput)

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith('document.pdf has unsupported extension')
    })

    // submit should NOT have been called
    expect(mockSubmit).not.toHaveBeenCalled()
  })
})
