from __future__ import annotations

from datetime import datetime, timedelta

from config.settings import settings
from models import ConversationTurn, ParsedIntent, SessionContext


class SessionManager:
    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl_seconds = ttl_seconds or settings.session_ttl_seconds
        self._sessions: dict[str, SessionContext] = {}

    def get_context(self, session_id: str) -> SessionContext:
        self._purge_expired()
        context = self._sessions.get(session_id)
        if context is None:
            context = SessionContext(session_id=session_id)
            self._sessions[session_id] = context
        context.updated_at = datetime.utcnow()
        return context

    def update_context(
        self,
        session_id: str,
        user_query: str,
        assistant_reply: str,
        intent: ParsedIntent | None = None,
        sql: str | None = None,
    ) -> SessionContext:
        context = self.get_context(session_id)
        context.turns.extend(
            [
                ConversationTurn(role="user", content=user_query),
                ConversationTurn(role="assistant", content=assistant_reply),
            ]
        )
        context.turns = context.turns[-10:]
        context.last_intent = intent or context.last_intent
        context.last_sql = sql or context.last_sql
        context.updated_at = datetime.utcnow()
        return context

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _purge_expired(self) -> None:
        deadline = datetime.utcnow() - timedelta(seconds=self._ttl_seconds)
        expired = [
            session_id
            for session_id, context in self._sessions.items()
            if context.updated_at < deadline
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)


session_manager = SessionManager()
