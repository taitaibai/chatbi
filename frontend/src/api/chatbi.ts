import type { ChatRequest } from '../types'

export function buildChatRequest(query: string): ChatRequest {
  return {
    query,
    session_id: 'wave1-static-session',
    user_id: 'demo-user',
    options: {
      show_sql: true,
      show_intent: true,
    },
  }
}
