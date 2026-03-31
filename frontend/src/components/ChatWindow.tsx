import { useState } from 'react'

import type { ChatMessage } from '../types'
import { MessageBubble } from './MessageBubble'

const initialMessages: ChatMessage[] = [
  {
    id: 'welcome',
    role: 'assistant',
    timestamp: Date.now() - 1000 * 60 * 5,
    content: [
      {
        type: 'text',
        payload: '请输入业务问题，例如：上周各渠道 GMV 对比。',
      },
    ],
  },
  {
    id: 'demo',
    role: 'assistant',
    timestamp: Date.now() - 1000 * 60 * 4,
    content: [
      {
        type: 'intent_summary',
        payload: {
          metrics: ['GMV'],
          dimensions: ['渠道'],
          time_range: {
            type: 'last_week',
            start: '2025-03-24',
            end: '2025-03-30',
          },
          filters: [],
          clarification_needed: false,
          clarification_question: null,
          clarification_options: [],
        },
      },
      {
        type: 'sql',
        payload: "SELECT channel, SUM(amount) AS gmv FROM dw.fact_orders WHERE status = 'paid' GROUP BY channel",
      },
    ],
  },
]

export function ChatWindow() {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages)
  const [query, setQuery] = useState('')

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) {
      return
    }
    setMessages((current) => [
      ...current,
      {
        id: `user-${Date.now()}`,
        role: 'user',
        timestamp: Date.now(),
        content: [{ type: 'text', payload: trimmed }],
      },
      {
        id: `placeholder-${Date.now() + 1}`,
        role: 'assistant',
        timestamp: Date.now(),
        content: [{ type: 'loading', payload: null }],
      },
    ])
    setQuery('')
  }

  return (
    <main className="chat-shell">
      <section className="chat-panel">
        <header className="chat-hero">
          <div>
            <p className="chat-kicker">Wave 1 / Foundation</p>
            <h1>ChatBI Workspace</h1>
          </div>
          <p className="chat-description">
            当前只交付基础模块层。界面保持静态演示，不接入 SSE 和真实查询。
          </p>
        </header>

        <div className="chat-layout">
          <div className="chat-messages">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </div>

          <aside className="chat-sidebar">
            <div className="sidebar-card">
              <div className="sidebar-title">Wave 1 Modules</div>
              <ul>
                <li>LLM Client</li>
                <li>Semantic YAML + Loader</li>
                <li>Mock Adapter</li>
                <li>Audit Logger</li>
                <li>Security Checker</li>
                <li>Visualization Rules</li>
                <li>Session Manager</li>
              </ul>
            </div>
            <div className="sidebar-card sidebar-card-accent">
              <div className="sidebar-title">Next Wave</div>
              <p>NLU、语义映射、复杂度守卫和解读服务会在 Wave 2 进入可调用状态。</p>
            </div>
          </aside>
        </div>

        <form className="chat-input" onSubmit={handleSubmit}>
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="输入你的分析问题"
            rows={3}
          />
          <button type="submit">发送</button>
        </form>
      </section>
    </main>
  )
}
