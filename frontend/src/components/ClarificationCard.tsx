import type { StreamErrorPayload } from '../types'

interface ClarificationCardProps {
  payload: StreamErrorPayload
}

export function ClarificationCard({ payload }: ClarificationCardProps) {
  return (
    <section className="biz-card clarification-card">
      <header className="biz-card-header">
        <div>
          <p className="biz-card-eyebrow">Clarification</p>
          <h3>需要补充信息</h3>
        </div>
      </header>

      <p className="clarification-message">{payload.message}</p>

      {payload.suggestion ? (
        <p className="clarification-suggestion">建议：{payload.suggestion}</p>
      ) : null}

      {payload.available_metrics && payload.available_metrics.length > 0 ? (
        <div className="intent-chip-list">
          {payload.available_metrics.map((metric) => (
            <span key={metric} className="intent-chip intent-chip-accent">
              {metric}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  )
}
