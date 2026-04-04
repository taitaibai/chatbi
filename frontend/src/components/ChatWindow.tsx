import { useRef, useEffect, useState } from 'react'
import { useSSEChat } from '../hooks/useSSEChat'
import { getClientIdentity } from '../api/chatbi'
import { MessageBubble } from './MessageBubble'

export function ChatWindow() {
  const [identity] = useState(() => getClientIdentity())
  const { messages, sendMessage, isLoading, clearSession } = useSSEChat()
  const [query, setQuery] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 新消息到达时自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || isLoading) return
    sendMessage(trimmed)
    setQuery('')
    // 重置 textarea 高度
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault()
      handleSubmit(e as unknown as React.FormEvent)
    }
  }

  // 自动撑高 textarea
  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setQuery(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
  }

  // identity 只为保证会话绑定，不展示给用户
  void identity

  return (
    <>
      {/* 顶部导航栏 */}
      <header className="topbar">
        <div className="topbar-brand">
          <div className="brand-logo">BI</div>
          <span className="brand-name">ChatBI</span>
          <span className="brand-badge">Beta</span>
        </div>

        <div className="topbar-right">
          {isLoading && (
            <div className="status-indicator">
              <span className="status-dot status-dot--on" />
              <span>分析中…</span>
            </div>
          )}
          <button
            className="btn-new"
            onClick={clearSession}
            disabled={isLoading}
            type="button"
            title="开始新对话"
          >
            ＋ 新对话
          </button>
        </div>
      </header>

      {/* 对话区 */}
      <main className="chat-body">
        <div className="chat-feed">
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* 输入框 */}
      <footer className="chat-composer">
        <form className="composer-form" onSubmit={handleSubmit}>
          <textarea
            ref={textareaRef}
            className="composer-textarea"
            value={query}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={isLoading ? '正在分析，请稍候…' : '输入业务问题，例如：上周各渠道 GMV 对比（Enter 发送）'}
            rows={1}
            disabled={isLoading}
          />
          <button
            className="composer-send"
            type="submit"
            disabled={isLoading || !query.trim()}
            title="发送"
          >
            ↑
          </button>
        </form>
        <p className="composer-hint">Shift+Enter 换行</p>
      </footer>
    </>
  )
}
