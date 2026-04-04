import { useState } from 'react'
import type { FilterCondition, IntentSummary } from '../types'

interface Props { summary: IntentSummary }

function fmtTimeRange(s: IntentSummary): string {
  if (!s.time_range) return '未指定时间'
  return `${s.time_range.start} ~ ${s.time_range.end}`
}

function fmtFilter(f: FilterCondition): string {
  const op: Record<string, string> = {
    eq: '=', ne: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤', in: 'IN', like: '~',
  }
  const val = Array.isArray(f.value) ? f.value.join('、') : f.value === null ? '空' : String(f.value)
  return `${f.field} ${op[f.op] ?? f.op} ${val}`
}

function buildSummaryLine(s: IntentSummary): string {
  const parts: string[] = []
  if (s.metrics.length) parts.push(s.metrics.join('、'))
  if (s.dimensions.length) parts.push(`按${s.dimensions.join('、')}`)
  if (s.time_range) parts.push(fmtTimeRange(s))
  return parts.join(' · ') || '意图已解析'
}

export function IntentSummaryCard({ summary }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div className="card">
      <div
        className="card-header card-header--clickable"
        onClick={() => setOpen((v) => !v)}
        role="button"
        aria-expanded={open}
      >
        <div className="card-header-left">
          <span className="card-eyebrow">意图</span>
          <span className="card-summary">{buildSummaryLine(summary)}</span>
        </div>
        <span className={`card-chevron${open ? ' card-chevron--open' : ''}`}>▾</span>
      </div>

      {open && (
        <div className="card-body">
          <div className="intent-body">
            <div className="intent-grid">
              <div className="intent-cell">
                <span className="intent-cell-label">指标</span>
                <span className="intent-cell-value">
                  {summary.metrics.length ? summary.metrics.join('、') : <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>未指定</span>}
                </span>
              </div>
              <div className="intent-cell">
                <span className="intent-cell-label">维度</span>
                <span className="intent-cell-value">
                  {summary.dimensions.length ? summary.dimensions.join('、') : <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>未指定</span>}
                </span>
              </div>
              <div className="intent-cell">
                <span className="intent-cell-label">时间范围</span>
                <span className="intent-cell-value">{fmtTimeRange(summary)}</span>
              </div>
            </div>

            {summary.filters.length > 0 && (
              <div>
                <div className="intent-filters-label">过滤条件</div>
                <div className="intent-chip-row">
                  {summary.filters.map((f, i) => (
                    <span key={i} className="chip">{fmtFilter(f)}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
