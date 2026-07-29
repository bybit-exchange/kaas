import { apiFetch } from './client'

export interface TaskDTO {
  id: string
  source: string
  title: string
  file_title?: string
  status: string
  stage: string
  attempts: number
  max_attempts: number
  error?: string
  result?: unknown
  created_at: number
  updated_at: number
}

export interface ListTasksParams {
  status?: string
  q?: string
  sort?: string
  order?: string
  limit?: number
  offset?: number
}

export async function listTasks(p?: ListTasksParams): Promise<{ tasks: TaskDTO[]; total: number }> {
  const qs = new URLSearchParams()
  if (p?.status !== undefined) qs.set('status', p.status)
  if (p?.q !== undefined) qs.set('q', p.q)
  if (p?.sort) qs.set('sort', p.sort)
  if (p?.order) qs.set('order', p.order)
  qs.set('limit', String(p?.limit ?? 20))
  if (p?.offset !== undefined) qs.set('offset', String(p.offset))
  const str = qs.toString()
  const path = str ? `/tasks?${str}` : '/tasks'
  const res = await apiFetch(path)
  return res.json() as Promise<{ tasks: TaskDTO[]; total: number }>
}

export async function getTask(id: string): Promise<TaskDTO> {
  const res = await apiFetch(`/tasks/${id}`)
  return res.json() as Promise<TaskDTO>
}

export async function deleteTask(id: string): Promise<void> {
  await apiFetch(`/tasks/${id}`, { method: 'DELETE' })
}

export interface TaskContentResponse {
  content: string
  size: number
  truncated: boolean
}

export async function getTaskContent(id: string, signal?: AbortSignal): Promise<TaskContentResponse> {
  const res = await apiFetch(`/tasks/${id}/content`, { signal })
  return res.json() as Promise<TaskContentResponse>
}
