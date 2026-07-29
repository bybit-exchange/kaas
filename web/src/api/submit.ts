import { apiFetch } from './client'

export interface SubmitRequest {
  source: 'paste' | 'file' | 'url'
  title?: string
  content?: string
  url?: string
}

export interface SubmitResponse {
  id: string
  status: string
  stage: string
}

export async function submit(req: SubmitRequest): Promise<SubmitResponse> {
  const res = await apiFetch('/submit', {
    method: 'POST',
    body: JSON.stringify(req),
  })
  return res.json() as Promise<SubmitResponse>
}

export interface SubmitFilesResult {
  uploaded: Array<{ id: string; name: string; status: string }>
  failed: Array<{ name: string; reason: string }>
}

export async function submitFiles(files: File[]): Promise<SubmitFilesResult> {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  const res = await apiFetch('/submit/files', { method: 'POST', body: formData })
  return res.json() as Promise<SubmitFilesResult>
}
