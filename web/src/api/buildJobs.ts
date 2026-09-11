import { apiFetch } from './client'
import type { TaskDTO } from './tasks'

export interface BuildJobDTO {
  id: string
  source: string
  title: string
  file_count: number
  status: string // "pending" | "running" | "succeeded" | "failed" | "partial"
  error?: string
  created_at: number
  updated_at: number
}

export interface BuildJobDetailDTO extends BuildJobDTO {
  tasks: TaskDTO[]
}

export interface ListBuildJobsParams {
  status?: string
  q?: string
  sort?: string
  order?: string
  limit?: number
  offset?: number
}

export interface ListBuildJobsResponse {
  jobs: BuildJobDTO[]
  total: number
}

export async function listBuildJobs(p?: ListBuildJobsParams): Promise<ListBuildJobsResponse> {
  const qs = new URLSearchParams()
  if (p?.status !== undefined) qs.set('status', p.status)
  if (p?.q !== undefined) qs.set('q', p.q)
  if (p?.sort) qs.set('sort', p.sort)
  if (p?.order) qs.set('order', p.order)
  qs.set('limit', String(p?.limit ?? 20))
  if (p?.offset !== undefined) qs.set('offset', String(p.offset))
  const str = qs.toString()
  const path = str ? `/build-jobs?${str}` : '/build-jobs'
  const res = await apiFetch(path)
  return res.json() as Promise<ListBuildJobsResponse>
}

export async function getBuildJob(id: string, signal?: AbortSignal): Promise<BuildJobDetailDTO> {
  const res = await apiFetch(`/build-jobs/${encodeURIComponent(id)}`, { signal })
  return res.json() as Promise<BuildJobDetailDTO>
}

export async function deleteBuildJob(id: string): Promise<void> {
  await apiFetch(`/build-jobs/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
