from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock

from config.settings import settings
from models import ConversationTurn, ParsedIntent, SessionContext


class SessionManager:
    """In-process session store backed by a plain Python dict.

    ⚠️  SINGLE-WORKER LIMITATION
    This implementation stores all session state in the current process's heap.
    It works correctly when the application runs with a single worker (the default
    for ``uvicorn main:app``).

    Multi-worker deployments (``uvicorn --workers N`` or gunicorn) will cause each
    worker to maintain its own isolated dict; consecutive requests from the same
    user that land on different workers will lose context, breaking follow-up
    queries.

    Migration path (P1): replace with a RedisStore backend that implements the
    same get_context / update_context / clear interface so the rest of the code
    requires zero changes.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl_seconds = ttl_seconds or settings.session_ttl_seconds
        self._sessions: dict[str, SessionContext] = {}
        self._lock = RLock()

    def get_context(self, session_id: str) -> SessionContext:
        with self._lock:
            self._purge_expired()
            context = self._sessions.get(session_id)
            if context is None:
                context = SessionContext(session_id=session_id)
                self._sessions[session_id] = context
            context.updated_at = datetime.now(UTC)
            return context.model_copy(deep=True)

    def update_context(
        self,
        session_id: str,
        user_query: str,
        assistant_reply: str,
        intent: ParsedIntent | None = None,
        sql: str | None = None,
    ) -> SessionContext:
        with self._lock:
            self._purge_expired()
            context = self._sessions.get(session_id)
            if context is None:
                context = SessionContext(session_id=session_id)

            updated_context = context.model_copy(deep=True)
            updated_context.turns.extend(
                [
                    ConversationTurn(role="user", content=user_query),
                    ConversationTurn(role="assistant", content=assistant_reply),
                ]
            )
            updated_context.turns = updated_context.turns[-10:]
            updated_context.last_intent = intent or updated_context.last_intent
            updated_context.last_sql = sql or updated_context.last_sql
            updated_context.updated_at = datetime.now(UTC)
            self._sessions[session_id] = updated_context
            return updated_context.model_copy(deep=True)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _purge_expired(self) -> None:
        deadline = datetime.now(UTC) - timedelta(seconds=self._ttl_seconds)
        expired = [
            session_id
            for session_id, context in self._sessions.items()
            if context.updated_at < deadline
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)


session_manager = SessionManager()
