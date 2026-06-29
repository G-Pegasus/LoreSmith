import { ApiError } from './client'

const pythonBaseUrl = import.meta.env.VITE_PYTHON_INTERNAL_API_BASE_URL ?? 'http://127.0.0.1:8000'
const pythonToken = import.meta.env.VITE_PYTHON_INTERNAL_API_TOKEN ?? ''

function buildPythonHeaders(extra?: HeadersInit): HeadersInit {
  const headers: Record<string, string> = {
    ...(extra instanceof Headers ? Object.fromEntries(extra.entries()) : Array.isArray(extra) ? Object.fromEntries(extra) : extra ?? {}),
  }
  if (pythonToken) {
    headers.Authorization = `Bearer ${pythonToken}`
  }
  return headers
}

export async function pythonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${pythonBaseUrl}${path}`, {
    ...init,
    headers: buildPythonHeaders({
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    }),
  })

  const text = await response.text()
  const json = text ? (JSON.parse(text) as { code?: string; message?: string; data?: T }) : null

  if (!response.ok) {
    throw new ApiError(json?.message ?? '请求失败', json?.code ?? 'HTTP_ERROR', response.status)
  }

  if (!json || json.code !== 'OK' || json.data === undefined) {
    throw new ApiError(json?.message ?? '接口返回异常', json?.code ?? 'INVALID_ENVELOPE', response.status)
  }

  return json.data
}

export async function pythonStream(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${pythonBaseUrl}${path}`, {
    ...init,
    headers: buildPythonHeaders({
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    }),
  })
  if (!response.ok) {
    const text = await response.text()
    let json: { code?: string; message?: string } | null = null
    try {
      json = text ? (JSON.parse(text) as { code?: string; message?: string }) : null
    } catch {
      json = null
    }
    throw new ApiError(json?.message ?? '请求失败', json?.code ?? 'HTTP_ERROR', response.status)
  }
  return response
}

export type PythonCreateRunRequest = {
  run_id: string
  story: {
    story_id: string
    title: string
    premise: string
    genre?: string
    language?: string
    characters?: Array<{ name: string; role?: string | null; description?: string | null }>
    word_count?: { min_words: number; target_words: number }
  }
  execution: {
    provider?: string
    model?: string
    context_window?: number
  }
  input: {
    mode: 'start'
    prompt: string
  }
  storage: {
    kind?: 'local'
    base_path: string
  }
  metadata?: {
    workspace_id?: string
    tenant_id?: string
    user_id?: string
    extra?: Record<string, unknown>
  }
  config_path?: string
}

export async function pythonCreateRun(payload: PythonCreateRunRequest) {
  return pythonFetch<{ run_id: string; status: string; kernel_status: string }>(`/internal/v1/runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
