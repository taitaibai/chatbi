import type { StreamErrorPayload } from '../types'

interface Props { payload: StreamErrorPayload }

export function ClarificationCard({ payload }: Props) {
  return (
    <div className="clari-card">
      <div className="clari-label">需要补充信息</div>
      <p className="clari-text">{payload.message}</p>

      {payload.suggestion && (
        <p className="clari-text" style={{ marginTop: 6, opacity: 0.8 }}>
          {payload.suggestion}
        </p>
      )}

      {payload.available_metrics && payload.available_metrics.length > 0 && (
        <div className="clari-chip-row">
          {payload.available_metrics.map((m) => (
            <span key={m} className="clari-chip">{m}</span>
          ))}
        </div>
      )}
    </div>
  )
}
