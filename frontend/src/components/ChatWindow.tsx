import { useRef, useEffect, useState } from 'react'

import { useSSEChat } from '../hooks/useSSEChat'
import { getClientIdentity } from '../api/chatbi'
import { MessageBubble } from './MessageBubble'

export function ChatWindow() {
  const [identity] = useState(() => getClientIdentity())
  const { messages, sendMessage, isLoading, clearSession } = useSSEChat()
  const [query, setQuery] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // 新消息到达时自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    sendMessage(query)
    setQuery('')
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl/Cmd + Enter 发送
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      sendMessage(query)
      setQuery('')
    }
  }

  return (
    <main className="chat-shell">
      <section className="chat-panel">
        <header className="chat-hero">
          <div>
            <p className="chat-kicker">Wave 2 / Core Services</p>
            <h1>ChatBI Workspace</h1>
          </div>
          <p className="chat-description">
            SSE 流式对话已就绪。输入业务问题，系统将依次推送意图摘要 → SQL → 数据 → 解读。
          </p>
        </header>

        <div className="chat-layout">
          <div className="chat-messages">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </div>

          <aside className="chat-sidebar">
            <div className="sidebar-card">
              <div className="sidebar-title">Wave 2 Modules</div>
              <div className="sidebar-meta">Session: {identity.sessionId.slice(0, 18)}...</div>
              <div className="sidebar-meta">User: {identity.userId.slice(0, 18)}...</div>
              <ul>
                <li>NLU Service</li>
                <li>Semantic Service</li>
                <li>Complexity Guard</li>
                <li>Interpreter Service</li>
                <li>SSE Hook (T-14)</li>
              </ul>
            </div>
            <div className="sidebar-card sidebar-card-accent">
              <div className="sidebar-title">操作</div>
              <button
                className="btn-clear"
                onClick={clearSession}
                disabled={isLoading}
                type="button"
              >
                清除会话
              </button>
            </div>
          </aside>
        </div>

        <form className="chat-input" onSubmit={handleSubmit}>
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isLoading ? '正在处理中…' : '输入你的分析问题（Ctrl+Enter 发送）'}
            rows={3}
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading || !query.trim()}>
            {isLoading ? '处理中' : '发送'}
          </button>
        </form>
      </section>
    </main>
  )
}
