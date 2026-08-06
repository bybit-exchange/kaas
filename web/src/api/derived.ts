import { apiFetch } from './client'

export interface DerivedKB {
  slug: string
  topic: string
  created_at: string
  article_count: number
}

/**
 * Which catalog a derive filters over.
 *
 * - `articles`: the compiled catalog, then each matching article's sources.
 * - `documents`: the raw-document catalog, skipping the compiled wiki entirely.
 */
export type SelectFrom = 'articles' | 'documents'

/** Counts and cost the engine reported for a finished derive. */
export interface DeriveResult {
  /** The catalog the run actually filtered, as resolved by the engine. */
  select_from?: SelectFrom
  /** Articles or documents, depending on `select_from`. */
  selected: number
  documents: number
  bytes: number
  offtopic: number
  filter_batches: number
  compiled: boolean
  cost?: { total_cost_usd: number }
  warnings?: string[]
}

export type DeriveStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface DeriveJob {
  id: string
  slug: string
  topic: string
  status: DeriveStatus
  stage: string
  error?: string
  result?: DeriveResult
  created_at: number
  updated_at: number
}

export interface StartDeriveRequest {
  topic: string
  slug?: string
  model?: string
  /** Omit for the engine default. Sending a value the backend does not know is a 400. */
  select_from?: SelectFrom
}

export async function listDerived(): Promise<{ kbs: DerivedKB[] }> {
  const res = await apiFetch('/derived')
  return res.json() as Promise<{ kbs: DerivedKB[] }>
}

export async function startDerive(
  req: StartDeriveRequest,
): Promise<{ job_id: string; slug: string }> {
  const res = await apiFetch('/derive', { method: 'POST', body: JSON.stringify(req) })
  return res.json() as Promise<{ job_id: string; slug: string }>
}

export async function getDeriveJob(id: string): Promise<DeriveJob> {
  const res = await apiFetch(`/derive/${encodeURIComponent(id)}`)
  return res.json() as Promise<DeriveJob>
}
