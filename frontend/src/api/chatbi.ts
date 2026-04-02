import type { ChatRequest, QueryData, SSEEventType } from '../types'

const SESSION_KEY = 'chatbi_session_id'
const USER_KEY = 'chatbi_user_id'

export interface ClientIdentity {
  sessionId: string
  userId: string
}

function ensureBrowserId(storageKey: string, prefix: string): string {
  const storage = storageKey === SESSION_KEY ? window.sessionStorage : window.localStorage
  const current = storage.getItem(storageKey)
  if (current) {
    return current
  }

  const next = `${prefix}-${crypto.randomUUID()}`
  storage.setItem(storageKey, next)
  return next
}

export function getClientIdentity(): ClientIdentity {
  return {
    sessionId: ensureBrowserId(SESSION_KEY, 'session'),
    userId: import.meta.env.VITE_CHATBI_USER_ID || ensureBrowserId(USER_KEY, 'anon'),
  }
}

export function buildChatRequest(query: string, identity: ClientIdentity = getClientIdentity()): ChatRequest {
  return {
    query,
    session_id: identity.sessionId,
    user_id: identity.userId,
    options: {
      show_sql: true,
      show_intent: true,
    },
  }
}

interface BackendQueryResult {
  columns: Array<{
    name: string
    type?: 'string' | 'number' | 'date'
    format?: string
  }>
  rows: Array<Array<string | number | null>>
  total_rows: number
  execution_ms: number
}

export function normalizeQueryResult(result: BackendQueryResult): QueryData {
  return {
    columns: result.columns.map((column) => ({
      name: column.name,
      type: column.type ?? 'string',
      format: column.format,
    })),
    rows: result.rows,
    total_rows: result.total_rows,
    execution_ms: result.execution_ms,
  }
}

// ─────────────────────────────────────────────
// SSE 流式请求（POST + ReadableStream）
// ─────────────────────────────────────────────

export interface SSEChunk {
  event: SSEEventType
  data: string
}

/**
 * 向 /api/v1/chat 发起 POST 请求并以 AsyncGenerator 逐条产出 SSE 事件。
 * EventSource 仅支持 GET，因此使用 fetch + ReadableStream 手动解析 SSE 协议。
 */
export async function* streamChat(
  request: ChatRequest,
  signal: AbortSignal,
): AsyncGenerator<SSEChunk> {
  const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''
  const response = await fetch(`${apiBase}/api/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(request),
    signal,
  })

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status}: ${text}`)
  }

  if (!response.body) {
    throw new Error('Response body is null')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''
  let currentData = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // 按行分割，保留不完整的最后一行
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          currentData = line.slice(5).trim()
        } else if (line === '' && currentData) {
          // 空行表示一个 SSE 事件结束
          yield { event: (currentEvent || 'message') as SSEEventType, data: currentData }
          currentEvent = ''
          currentData = ''
        }
      }
    }

    // 处理流结束时 buffer 中残留的最后一个事件
    if (currentData) {
      yield { event: (currentEvent || 'message') as SSEEventType, data: currentData }
    }
  } finally {
    reader.releaseLock()
  }
}
