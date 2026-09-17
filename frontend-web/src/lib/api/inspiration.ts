import { ApiError, apiFetch } from './client'
import type { InspirationMessage, InspirationSession } from '../types/api'

export async function fetchInspirationSession(sessionId: string) {
  return apiFetch<InspirationSession>(`/api/v1/inspiration-sessions/${encodeURIComponent(sessionId)}`)
}

type InspirationStreamHandlers = {
  onUser?: (message: InspirationMessage) => void
  onDelta?: (delta: string) => void
  /** 正文流完、后端开始抽取设定草稿时触发（当前只有 'extracting'） */
  onPhase?: (phase: string) => void
}

export async function streamInspirationMessage(sessionId: string, content: string, handlers: InspirationStreamHandlers = {}) {
  const response = await fetch(`/api/v1/inspiration-sessions/${encodeURIComponent(sessionId)}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ content }),
  })

  if (!response.ok) {
    throw new ApiError('灵感对话请求失败', 'HTTP_ERROR', response.status)
  }
  if (!response.body) {
    throw new ApiError('浏览器不支持流式响应', 'STREAM_UNAVAILABLE', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalSession: InspirationSession | null = null

  const processEvent = (rawEvent: string) => {
    const lines = rawEvent.split(/\r?\n/)
    let eventName = 'message'
    const dataLines: string[] = []

    lines.forEach((line) => {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
        return
      }
      if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    })

    const data = dataLines.join('\n')
    if (!data) return

    if (eventName === 'delta') {
      const payload = JSON.parse(data) as { delta?: string }
      if (payload.delta) {
        handlers.onDelta?.(payload.delta)
      }
      return
    }

    if (eventName === 'user') {
      handlers.onUser?.(JSON.parse(data) as InspirationMessage)
      return
    }

    if (eventName === 'phase') {
      const payload = JSON.parse(data) as { phase?: string }
      if (payload.phase) {
        handlers.onPhase?.(payload.phase)
      }
      return
    }

    if (eventName === 'done') {
      finalSession = JSON.parse(data) as InspirationSession
      return
    }

    if (eventName === 'error') {
      const payload = JSON.parse(data) as { message?: string }
      throw new ApiError(payload.message ?? '灵感对话暂时不可用', 'STREAM_ERROR', response.status)
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    const events = buffer.split(/\r?\n\r?\n/)
    buffer = events.pop() ?? ''
    events.forEach(processEvent)
    if (done) {
      break
    }
  }

  if (buffer.trim()) {
    processEvent(buffer)
  }
  if (!finalSession) {
    throw new ApiError('灵感对话流式响应未完成', 'STREAM_INCOMPLETE', response.status)
  }
  return finalSession
}

/**
 * 确认整张设定草稿。服务端会校验 expectedDraftRevision，不匹配时抛
 * ApiError(code = 'STALE_DRAFT', status = 409)。确认只写 session 上的快照，
 * 不写 store —— 落库仍走「保存并开始创作」。
 */
export async function confirmInspirationSettings(sessionId: string, expectedDraftRevision: number) {
  return apiFetch<InspirationSession>(
    `/api/v1/inspiration-sessions/${encodeURIComponent(sessionId)}/settings/confirm`,
    {
      method: 'POST',
      body: JSON.stringify({ expectedDraftRevision }),
    },
  )
}

/**
 * 删除整个会话（含消息与设定快照）。「重置对话」用它把旧会话从库里抹掉。
 *
 * 注意：界面的清空不依赖这个请求 —— 那是上层轮换 sessionId 让面板重挂载完成的。
 * 所以调用方应当 fire-and-forget，失败也不要阻断重置。
 */
export async function deleteInspirationSession(sessionId: string) {
  return apiFetch<{ deleted: boolean }>(`/api/v1/inspiration-sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}
