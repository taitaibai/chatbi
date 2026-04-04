import type { QueryData, QueryColumn } from '../types'

interface Props { data: QueryData }

function formatCell(value: string | number | null, col: QueryColumn): string {
  if (value === null) return '—'
  if (typeof value === 'number') {
    if (col.format === 'percent') return `${(value * 100).toFixed(2)}%`
    if (col.format === 'currency') {
      return new Intl.NumberFormat('zh-CN', {
        style: 'currency', currency: 'CNY', maximumFractionDigits: 2,
      }).format(value)
    }
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
  }
  return value
}

export function ResultTable({ data }: Props) {
  const isNumeric = (col: QueryColumn) =>
    col.type === 'number' || col.format === 'currency' || col.format === 'percent'

  return (
    <div className="card">
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {data.columns.map((col) => (
                <th key={col.name} style={isNumeric(col) ? { textAlign: 'right' } : undefined}>
                  {col.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => {
                  const col = data.columns[ci]
                  return (
                    <td key={ci} className={isNumeric(col) ? 'td-number' : undefined}>
                      {formatCell(cell, col)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        <span>{data.total_rows} 行</span>
        {typeof data.execution_ms === 'number' && <span>{data.execution_ms} ms</span>}
      </div>
    </div>
  )
}
