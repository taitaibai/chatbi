import type { ChartSpec, ChatMessage, IntentSummary, MessageContent, QueryData } from '../types'
import { ChartRenderer } from './ChartRenderer'
import { IntentSummaryCard } from './IntentSummaryCard'
import { ResultTable } from './ResultTable'
import { SQLPanel } from './SQLPanel'

function isIntentSummary(payload: MessageContent['payload']): payload is IntentSummary {
  return typeof payload === 'object' && payload !== null && 'metrics' in payload
}

function isQueryData(payload: MessageContent['payload']): payload is QueryData {
  return typeof payload === 'object' && payload !== null && 'columns' in payload && 'rows' in payload
}

function isChartSpec(payload: MessageContent['payload']): payload is ChartSpec {
  return typeof payload === 'object' && payload !== null && 'type' in payload && 'echarts_option' in payload
}

function renderContent(content: MessageContent, index: number) {
  if (content.type === 'loading') {
    return <div key={index} className="message-loading">正在准备分析链路...</div>
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
    return (
      <section key={index} className="biz-card message-chart">
        <header className="biz-card-header">
          <div>
            <p className="biz-card-eyebrow">Visualization</p>
            <h3>图表展示</h3>
          </div>
        </header>
        <ChartRenderer spec={content.payload} />
      </section>
    )
  }

  if (content.type === 'error' && typeof content.payload === 'string') {
    return (
      <div key={index} className="message-error">
        {content.payload}
      </div>
    )
  }

  if (content.type === 'interpretation' && typeof content.payload === 'string') {
    return (
      <div key={index} className="message-interpretation">
        {content.payload}
      </div>
    )
  }

  if (typeof content.payload === 'string') {
    return <div key={index}>{content.payload}</div>
  }

  return null
}

interface MessageBubbleProps {
  message: ChatMessage
}

export function MessageBubble({ message }: MessageBubbleProps) {
  return (
    <article className={`message-bubble message-bubble-${message.role}`}>
      <header className="message-meta">
        <span>{message.role === 'user' ? '业务方' : 'ChatBI'}</span>
        <time>{new Date(message.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time>
      </header>
      <div className="message-body">
        {message.content.map((content, index) => renderContent(content, index))}
      </div>
    </article>
  )
}
