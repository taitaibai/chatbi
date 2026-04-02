// ─────────────────────────────────────────────
// 请求 / 响应基础类型
// ─────────────────────────────────────────────

export interface ChatRequest {
  query: string
  session_id: string
  user_id: string
  options?: {
    show_sql?: boolean
    show_intent?: boolean
  }
}

// ─────────────────────────────────────────────
// 意图解析结果
// ─────────────────────────────────────────────

export interface TimeRange {
  type: 'last_7d' | 'last_30d' | 'last_week' | 'last_month' | 'yesterday' | 'custom'
  start: string  // ISO date string
  end: string    // ISO date string
}

export interface FilterCondition {
  field: string
  op: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'like'
  value: string | number | string[] | null
}

export interface IntentSummary {
  metrics: string[]
  dimensions: string[]
  time_range: TimeRange | null
  filters: FilterCondition[]
  clarification_needed: boolean
  clarification_question: string | null
  clarification_options: string[]
}

// ─────────────────────────────────────────────
// 查询数据结果
// ─────────────────────────────────────────────

export interface QueryColumn {
  name: string
  type: 'string' | 'number' | 'date'
  format?: string  // e.g. "currency" | "percent" | "number"
}

export interface QueryData {
  columns: QueryColumn[]
  rows: (string | number | null)[][]
  total_rows: number
  execution_ms?: number
}

// ─────────────────────────────────────────────
// 图表规格
// ─────────────────────────────────────────────

export type ChartType = 'bar' | 'line' | 'pie' | 'card' | 'table'

export interface ChartSpec {
  type: ChartType
  echarts_option: Record<string, unknown>  // ECharts option JSON
}

export interface TokenUsage {
  prompt: number
  completion: number
}

export interface StreamDonePayload {
  request_id: string | null
  latency_ms?: number | null
  token_usage?: TokenUsage | null
}

export interface StreamErrorPayload {
  code?: string
  message: string
  available_metrics?: string[]
  suggestion?: string
}

// ─────────────────────────────────────────────
// SSE 事件类型
// ─────────────────────────────────────────────

export type SSEEventType =
  | 'intent_summary'
  | 'sql'
  | 'table_data'
  | 'chart_spec'
  | 'interpretation'
  | 'error'
  | 'done'

export interface SSEEvent<T = unknown> {
  event: SSEEventType
  data: T
}

// ─────────────────────────────────────────────
// 聊天消息类型
// ─────────────────────────────────────────────

export type MessageRole = 'user' | 'assistant'

export type MessageContentType = 'text' | 'loading' | 'error' | 'intent_summary' | 'sql' | 'table_data' | 'chart_spec' | 'interpretation'

export interface MessageContent {
  type: MessageContentType
  payload?: IntentSummary | string | QueryData | ChartSpec | StreamErrorPayload | null
}

export interface MessageMeta {
  requestId?: string | null
  latencyMs?: number | null
  tokenUsage?: TokenUsage | null
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: MessageContent[]
  timestamp: number
  status?: 'streaming' | 'done' | 'error'
  meta?: MessageMeta
}

// ─────────────────────────────────────────────
// ChatResponse（非流式，供类型对齐参考）
// ─────────────────────────────────────────────

export interface ChatResponse {
  request_id: string
  intent: IntentSummary
  sql: string
  data: QueryData
  chart: ChartSpec
  interpretation: string
}
