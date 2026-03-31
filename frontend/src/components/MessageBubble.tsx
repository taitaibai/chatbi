import type { ChartSpec, ChatMessage, IntentSummary, MessageContent, QueryData } from '../types'

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
    const summary = content.payload
    return (
      <div key={index} className="message-card">
        <div className="message-card-title">Intent Summary</div>
        <div>指标：{summary.metrics.join('、') || '待解析'}</div>
        <div>维度：{summary.dimensions.join('、') || '待解析'}</div>
        <div>时间：{summary.time_range ? `${summary.time_range.start} ~ ${summary.time_range.end}` : '未指定'}</div>
      </div>
    )
  }

  if (content.type === 'sql' && typeof content.payload === 'string') {
    return (
      <pre key={index} className="message-code">
        {content.payload}
      </pre>
    )
  }

  if (content.type === 'table_data' && isQueryData(content.payload)) {
    const table = content.payload
    return (
      <div key={index} className="message-table-wrap">
        <table className="message-table">
          <thead>
            <tr>
              {table.columns.map((column: QueryData['columns'][number]) => (
                <th key={column.name}>{column.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row: QueryData['rows'][number], rowIndex: number) => (
              <tr key={rowIndex}>
                {row.map((cell: QueryData['rows'][number][number], cellIndex: number) => (
                  <td key={cellIndex}>{cell ?? '-'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (content.type === 'chart_spec' && isChartSpec(content.payload)) {
    const chart = content.payload
    return (
      <div key={index} className="message-card">
        <div className="message-card-title">Chart Spec</div>
        <div>类型：{chart.type}</div>
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
