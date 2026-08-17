import { apiFetch } from './client'

export interface UploadConfig {
  maxFileSize: number
  maxRichFileSize: number
  maxZipFileSize: number
  maxFilesPerUpload: number
  allowedExtensions: string[]
}

export const DEFAULT_UPLOAD_CONFIG: UploadConfig = {
  maxFileSize: 1 * 1024 * 1024,
  maxRichFileSize: 10 * 1024 * 1024,
  maxZipFileSize: 5 * 1024 * 1024,
  maxFilesPerUpload: 20,
  allowedExtensions: ['.csv', '.docx', '.epub', '.htm', '.html', '.md', '.pdf', '.pptx', '.rtf', '.txt', '.xlsx', '.zip'],
}

export async function fetchUploadConfig(): Promise<UploadConfig> {
  const res = await apiFetch('/upload/config')
  const data = await res.json()
  return {
    maxFileSize: data.max_file_size,
    maxRichFileSize: data.max_rich_file_size,
    maxZipFileSize: data.max_zip_file_size,
    maxFilesPerUpload: data.max_files_per_upload,
    allowedExtensions: data.allowed_extensions,
  }
}
