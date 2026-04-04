import { useState } from 'react'

interface Props { sql: string }

export function SQLPanel({ sql }: Props) {
  const [open, setOpen] = useState(false)
  const preview = sql.split('\n')[0].slice(0, 60) + (sql.length > 60 ? ' …' : '')

  return (
    <div className="card">
      <div
        className="card-header card-header--clickable"
        onClick={() => setOpen((v) => !v)}
        role="button"
        aria-expanded={open}
      >
        <div className="card-header-left">
          <span className="card-eyebrow">SQL</span>
          <span className="card-summary" style={{ fontFamily: 'monospace', fontSize: '12px' }}>
            {open ? '收起' : preview}
          </span>
        </div>
        <span className={`card-chevron${open ? ' card-chevron--open' : ''}`}>▾</span>
      </div>

      {open && (
        <div className="card-body">
          <pre className="sql-pre">{sql}</pre>
        </div>
      )}
    </div>
  )
}
