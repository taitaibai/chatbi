import type { FilterCondition, IntentSummary } from '../types'

interface IntentSummaryCardProps {
  summary: IntentSummary
}

function formatTimeRange(summary: IntentSummary): string {
  if (!summary.time_range) {
    return '未指定'
  }

  return `${summary.time_range.start} ~ ${summary.time_range.end}`
}

function formatFilterValue(value: FilterCondition['value']): string {
  if (Array.isArray(value)) {
    return value.join('、')
  }
  if (value === null) {
    return '空值'
  }
  return String(value)
}

function formatFilter(filter: FilterCondition): string {
  const opMap: Record<FilterCondition['op'], string> = {
    eq: '=',
    ne: '!=',
    gt: '>',
    gte: '>=',
    lt: '<',
    lte: '<=',
    in: 'IN',
    like: 'LIKE',
  }

  return `${filter.field} ${opMap[filter.op]} ${formatFilterValue(filter.value)}`
}

export function IntentSummaryCard({ summary }: IntentSummaryCardProps) {
  return (
    <section className="biz-card intent-card">
      <header className="biz-card-header">
        <div>
          <p className="biz-card-eyebrow">Intent Summary</p>
          <h3>意图摘要</h3>
        </div>
        {summary.clarification_needed ? (
          <span className="intent-status intent-status-warning">需要澄清</span>
        ) : (
          <span className="intent-status intent-status-ready">已解析</span>
        )}
      </header>

      <div className="intent-grid">
        <div className="intent-metric">
          <span className="intent-label">指标</span>
          <strong>{summary.metrics.join('、') || '待解析'}</strong>
        </div>
        <div className="intent-metric">
          <span className="intent-label">维度</span>
          <strong>{summary.dimensions.join('、') || '未指定'}</strong>
        </div>
        <div className="intent-metric">
          <span className="intent-label">时间范围</span>
          <strong>{formatTimeRange(summary)}</strong>
        </div>
      </div>

      <div className="intent-section">
        <div className="intent-label">过滤条件</div>
        {summary.filters.length > 0 ? (
          <div className="intent-chip-list">
            {summary.filters.map((filter, index) => (
              <span key={`${filter.field}-${index}`} className="intent-chip">
                {formatFilter(filter)}
              </span>
            ))}
          </div>
        ) : (
          <div className="intent-empty">当前没有额外过滤条件</div>
        )}
      </div>

      {summary.clarification_needed && (
        <div className="intent-clarification">
          <div className="intent-label">澄清问题</div>
          <p>{summary.clarification_question ?? '请补充更明确的分析目标。'}</p>
          {summary.clarification_options.length > 0 && (
            <div className="intent-chip-list">
              {summary.clarification_options.map((option) => (
                <span key={option} className="intent-chip intent-chip-accent">
                  {option}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
