interface SQLPanelProps {
  sql: string
}

export function SQLPanel({ sql }: SQLPanelProps) {
  return (
    <section className="biz-card sql-panel">
      <header className="biz-card-header">
        <div>
          <p className="biz-card-eyebrow">Generated SQL</p>
          <h3>SQL 面板</h3>
        </div>
      </header>
      <pre className="message-code">{sql}</pre>
    </section>
  )
}
