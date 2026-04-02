/**
 * T-14: useSSEChat — 前端 SSE 聊天 Hook
 *
 * 设计要点：
 *  - useReducer + 状态机，避免多个 useState 并发竞态
 *  - 使用 AbortController 取消上一次未完成的请求
 *  - sendMessage 通过 ref 访问最新 isLoading，保持回调引用稳定
 */

import { useReducer, useRef, useCallback, useEffect } from 'react'
import type {
  ChatMessage,
  ChartSpec,
  IntentSummary,
  QueryData,
  StreamDonePayload,
  StreamErrorPayload,
} from '../types'
import {
  buildChatRequest,
  getClientIdentity,
  normalizeQueryResult,
  streamChat,
} from '../api/chatbi'

// ─────────────────────────────────────────────
// State & Actions
// ─────────────────────────────────────────────

interface State {
  messages: ChatMessage[]
  isLoading: boolean
  error: string | null
}

type Action =
  | { type: 'SEND'; userMsg: ChatMessage; botMsg: ChatMessage }
  | { type: 'INTENT_SUMMARY'; id: string; payload: IntentSummary }
  | { type: 'SQL'; id: string; sql: string }
  | { type: 'TABLE_DATA'; id: string; payload: QueryData }
  | { type: 'CHART_SPEC'; id: string; payload: ChartSpec }
  | { type: 'INTERPRETATION_TOKEN'; id: string; token: string }
  | { type: 'BOT_ERROR'; id: string; payload: StreamErrorPayload }
  | { type: 'DONE'; id: string; payload: StreamDonePayload | null }
  | { type: 'CLEAR' }

// ─────────────────────────────────────────────
// 初始欢迎消息
// ─────────────────────────────────────────────

function makeWelcome(): ChatMessage {
  return {
    id: 'welcome',
    role: 'assistant',
    timestamp: Date.now(),
    content: [{ type: 'text', payload: '请输入业务问题，例如：上周各渠道 GMV 对比。' }],
  }
}

const initialState: State = {
  messages: [makeWelcome()],
  isLoading: false,
  error: null,
}

// ─────────────────────────────────────────────
// Reducer
// ─────────────────────────────────────────────

function patchMessage(
  messages: ChatMessage[],
  id: string,
  updater: (m: ChatMessage) => ChatMessage,
): ChatMessage[] {
  return messages.map((m) => (m.id === id ? updater(m) : m))
}

function appendAssistantContent(
  msg: ChatMessage,
  content: ChatMessage['content'][number],
): ChatMessage {
  return {
    ...msg,
    status: 'streaming',
    content: [...msg.content.filter((entry) => entry.type !== 'loading'), content],
  }
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SEND':
      return {
        ...state,
        messages: [...state.messages, action.userMsg, action.botMsg],
        isLoading: true,
        error: null,
      }

    case 'INTENT_SUMMARY':
      return {
        ...state,
        messages: patchMessage(state.messages, action.id, (msg) =>
          appendAssistantContent(msg, { type: 'intent_summary', payload: action.payload }),
        ),
      }

    case 'SQL':
      return {
        ...state,
        messages: patchMessage(state.messages, action.id, (msg) =>
          appendAssistantContent(msg, { type: 'sql', payload: action.sql }),
        ),
      }

    case 'TABLE_DATA':
      return {
        ...state,
        messages: patchMessage(state.messages, action.id, (msg) =>
          appendAssistantContent(msg, { type: 'table_data', payload: action.payload }),
        ),
      }

    case 'CHART_SPEC':
      return {
        ...state,
        messages: patchMessage(state.messages, action.id, (msg) =>
          appendAssistantContent(msg, { type: 'chart_spec', payload: action.payload }),
        ),
      }

    case 'INTERPRETATION_TOKEN': {
      return {
        ...state,
        messages: patchMessage(state.messages, action.id, (msg) => {
          const hasInterp = msg.content.some((c) => c.type === 'interpretation')
          if (hasInterp) {
            // 追加 token 到已有的 interpretation 内容项
            return {
              ...msg,
              status: 'streaming',
              content: msg.content.map((c) =>
                c.type === 'interpretation'
                  ? { ...c, payload: (c.payload as string) + action.token }
                  : c,
              ),
            }
          }
          // 首个 token：新建 interpretation 内容项
          return {
            ...msg,
            status: 'streaming',
            content: [
              ...msg.content.filter((entry) => entry.type !== 'loading'),
              { type: 'interpretation', payload: action.token },
            ],
          }
        }),
      }
    }

    case 'BOT_ERROR':
      return {
        ...state,
        messages: patchMessage(state.messages, action.id, (msg) => ({
          ...msg,
          status: 'error',
          content: [
            ...msg.content.filter((c) => c.type !== 'loading'),
            { type: 'error', payload: action.payload },
          ],
        })),
        isLoading: false,
        error: action.payload.message,
      }

    case 'DONE':
      return {
        ...state,
        messages: patchMessage(state.messages, action.id, (msg) => ({
          ...msg,
          status: 'done',
          meta: {
            requestId: action.payload?.request_id ?? null,
            latencyMs: action.payload?.latency_ms ?? null,
            tokenUsage: action.payload?.token_usage ?? null,
          },
        })),
        isLoading: false,
      }

    case 'CLEAR':
      return {
        messages: [makeWelcome()],
        isLoading: false,
        error: null,
      }

    default:
      return state
  }
}

// ─────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────

export interface UseSSEChatReturn {
  messages: ChatMessage[]
  sendMessage: (query: string) => void
  isLoading: boolean
  error: string | null
  clearSession: () => void
}

export function useSSEChat(): UseSSEChatReturn {
  const [state, dispatch] = useReducer(reducer, initialState)

  // Refs 用于在稳定回调中访问最新值，避免不必要的重新渲染
  const abortRef = useRef<AbortController | null>(null)
  const isLoadingRef = useRef(false)

  // 同步 isLoading 到 ref，使 sendMessage 无需重建即可感知最新状态
  isLoadingRef.current = state.isLoading

  // 组件卸载时取消进行中的请求
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const sendMessage = useCallback((query: string) => {
    const trimmed = query.trim()
    if (!trimmed || isLoadingRef.current) return

    // 取消上一次未完成的请求
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const identity = getClientIdentity()
    const request = buildChatRequest(trimmed, identity)

    const now = Date.now()
    const userMsg: ChatMessage = {
      id: `user-${now}`,
      role: 'user',
      timestamp: now,
      content: [{ type: 'text', payload: trimmed }],
    }
    const botId = `bot-${now}`
    const botMsg: ChatMessage = {
      id: botId,
      role: 'assistant',
      timestamp: now,
      content: [{ type: 'loading', payload: null }],
      status: 'streaming',
    }

    dispatch({ type: 'SEND', userMsg, botMsg })

    // 异步消费 SSE 流
    void (async () => {
      try {
        for await (const { event, data } of streamChat(request, controller.signal)) {
          if (controller.signal.aborted) break

          switch (event) {
            case 'intent_summary': {
              const payload = JSON.parse(data) as IntentSummary
              dispatch({ type: 'INTENT_SUMMARY', id: botId, payload })
              break
            }
            case 'sql': {
              const parsed = JSON.parse(data) as { sql: string }
              dispatch({ type: 'SQL', id: botId, sql: parsed.sql })
              break
            }
            case 'table_data': {
              const raw = JSON.parse(data) as Parameters<typeof normalizeQueryResult>[0]
              dispatch({ type: 'TABLE_DATA', id: botId, payload: normalizeQueryResult(raw) })
              break
            }
            case 'chart_spec': {
              const payload = JSON.parse(data) as ChartSpec
              dispatch({ type: 'CHART_SPEC', id: botId, payload })
              break
            }
            case 'interpretation': {
              const parsed = JSON.parse(data) as { token: string; done: boolean }
              if (parsed.token) {
                dispatch({ type: 'INTERPRETATION_TOKEN', id: botId, token: parsed.token })
              }
              break
            }
            case 'error': {
              const parsed = JSON.parse(data) as Partial<StreamErrorPayload>
              dispatch({
                type: 'BOT_ERROR',
                id: botId,
                payload: {
                  code: parsed.code,
                  message: parsed.message ?? '查询失败，请重试',
                  available_metrics: parsed.available_metrics,
                  suggestion: parsed.suggestion,
                },
              })
              return
            }
            case 'done': {
              const parsed = JSON.parse(data) as StreamDonePayload
              dispatch({ type: 'DONE', id: botId, payload: parsed })
              return
            }
          }
        }
        // 流正常结束但未收到 done 事件时兜底
        dispatch({ type: 'DONE', id: botId, payload: null })
      } catch (err) {
        if (!controller.signal.aborted) {
          const msg = err instanceof Error ? err.message : '请求失败，请重试'
          dispatch({ type: 'BOT_ERROR', id: botId, payload: { message: msg } })
        }
      }
    })()
  }, []) // sendMessage 引用稳定，通过 ref 感知 isLoading 变化

  const clearSession = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    dispatch({ type: 'CLEAR' })
    // 清除 sessionStorage 中的会话 ID，下次请求将生成新会话
    window.sessionStorage.removeItem('chatbi_session_id')
  }, [])

  return {
    messages: state.messages,
    sendMessage,
    isLoading: state.isLoading,
    error: state.error,
    clearSession,
  }
}
