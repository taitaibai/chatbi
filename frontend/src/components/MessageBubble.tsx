import type {
  ChartSpec,
  ChatMessage,
  IntentSummary,
  MessageContent,
  QueryData,
  StreamErrorPayload,
} from '../types'
import { ChartRenderer } from './ChartRenderer'
import { ClarificationCard } from './ClarificationCard'
import { IntentSummaryCard } from './IntentSummaryCard'
import { ResultTable } from './ResultTable'
import { SQLPanel } from './SQLPanel'

function isIntentSummary(p: MessageContent['payload']): p is IntentSummary {
  return typeof p === 'object' && p !== null && 'metrics' in p
}
function isQueryData(p: MessageContent['payload']): p is QueryData {
  return typeof p === 'object' && p !== null && 'columns' in p && 'rows' in p
}
function isChartSpec(p: MessageContent['payload']): p is ChartSpec {
  return typeof p === 'object' && p !== null && 'type' in p && 'echarts_option' in p
}
function isStreamError(p: MessageContent['payload']): p is StreamErrorPayload {
  return typeof p === 'object' && p !== null && 'message' in p
}

function renderContent(content: MessageContent, index: number) {
  if (content.type === 'loading') {
    return (
      <div key={index} className="loading-dots">
        <span className="loading-dot" />
        <span className="loading-dot" />
        <span className="loading-dot" />
      </div>
    )
  }

  if (content.type === 'text' && typeof content.payload === 'string') {
    return <p key={index} className="welcome-text">{content.payload}</p>
  }

  if (content.type === 'intent_summary' && isIntentSummary(content.payload)) {
    return <IntentSummaryCard key={index} summary={content.payload} />
  }

  if (content.type === 'sql' && typeof content.payload === 'string') {
    return <SQLPanel key={index} sql={content.payload} />
  }

  if (content.type === 'table_data' && isQueryData(content.payload)) {
    return <ResultTable key={index} data={content.payload} />
  }

  if (content.type === 'chart_spec' && isChartSpec(content.payload)) {
    return <ChartRenderer key={index} spec={content.payload} />
  }

  if (content.type === 'interpretation' && typeof content.payload === 'string') {
    return <p key={index} className="interp-text">{content.payload}</p>
  }

  if (content.type === 'error') {
    if (isStreamError(content.payload)) {
      const payload = content.payload
      if (payload.code === 'clarification_needed' || payload.code === 'semantic_not_found') {
        return <ClarificationCard key={index} payload={payload} />
      }
      return (
        <div key={index} className="error-card">
          <div className="error-label">分析失败</div>
          <div className="error-body">{payload.message}</div>
        </div>
      )
    }
    if (typeof content.payload === 'string') {
      return (
        <div key={index} className="error-card">
          <div className="error-body">{content.payload}</div>
        </div>
      )
    }
  }

  return null
}

interface Props { message: ChatMessage }

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user'
  const time = new Date(message.timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })

  if (isUser) {
    const text = message.content.find((c) => c.type === 'text')?.payload as string | undefined
    return (
      <div className="msg msg--user">
        <div className="msg-user-bubble">{text}</div>
        <span className="msg-label">{time}</span>
      </div>
    )
  }

  return (
    <div className="msg msg--assistant">
      <span className="msg-label">ChatBI</span>
      <div className="msg-assistant-body">
        {message.content.map((c, i) => renderContent(c, i))}
      </div>
      {message.status === 'done' && message.meta?.latencyMs ? (
        <div className="msg-footer">
          <span>{message.meta.latencyMs} ms</span>
        </div>
      ) : null}
    </div>
  )
}
