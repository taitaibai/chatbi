import type { QueryData, QueryColumn } from '../types'

interface ResultTableProps {
  data: QueryData
}

function formatCell(value: string | number | null, column: QueryColumn): string {
  if (value === null) {
    return '-'
  }

  if (typeof value === 'number') {
    if (column.format === 'percent') {
      return `${(value * 100).toFixed(2)}%`
    }
    if (column.format === 'currency') {
      return new Intl.NumberFormat('zh-CN', {
        style: 'currency',
        currency: 'CNY',
        maximumFractionDigits: 2,
      }).format(value)
    }
    return new Intl.NumberFormat('zh-CN', {
      maximumFractionDigits: 2,
    }).format(value)
  }

  return value
}

export function ResultTable({ data }: ResultTableProps) {
  return (
    <section className="biz-card result-panel">
      <header className="biz-card-header">
        <div>
          <p className="biz-card-eyebrow">Query Result</p>
          <h3>数据结果</h3>
        </div>
        <div className="result-meta">
          <span>{data.total_rows} 行</span>
          {typeof data.execution_ms === 'number' && <span>{data.execution_ms} ms</span>}
        </div>
      </header>

      <div className="message-table-wrap">
        <table className="message-table">
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column.name}>{column.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={`${rowIndex}-${cellIndex}`}>
                    {formatCell(cell, data.columns[cellIndex])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
