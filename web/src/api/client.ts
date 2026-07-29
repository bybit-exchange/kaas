/**
 * No-auth API client for KaaS web UI.
 * All web API requests should go through apiFetch — it is the single seam
 * for prefixing paths and surfacing backend errors as ApiError.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = path.startsWith('/api') ? path : `/api${path}`

  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  }

  if (!(init.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  const res = await fetch(url, { ...init, headers })

  if (!res.ok) {
    let message = res.statusText
    try {
      const cloned = res.clone()
      const text = await cloned.text()
      try {
        const parsed = JSON.parse(text) as { error?: string; message?: string }
        message = parsed.error ?? parsed.message ?? message
      } catch {
        message = text || message
      }
    } catch {
      // could not read body, use statusText
    }
    throw new ApiError(res.status, message)
  }

  return res
}
