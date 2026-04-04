from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

import aiosqlite
import structlog

from config.paths import resolve_app_path
from config.settings import settings
from models import RequestTrace

logger = structlog.get_logger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS request_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    raw_query TEXT NOT NULL,
    intent_json TEXT,
    generated_sql TEXT,
    response_type TEXT,
    error_code TEXT,
    datasource_exec_ms INTEGER,
    total_ms INTEGER,
    llm_prompt_tokens INTEGER,
    llm_completion_tokens INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

_INSERT_SQL = """
INSERT INTO request_audit (
    request_id, session_id, user_id, raw_query, intent_json,
    generated_sql, response_type, error_code, datasource_exec_ms,
    total_ms, llm_prompt_tokens, llm_completion_tokens
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(request_id) DO UPDATE SET
    session_id = excluded.session_id,
    user_id = excluded.user_id,
    raw_query = excluded.raw_query,
    intent_json = excluded.intent_json,
    generated_sql = excluded.generated_sql,
    response_type = excluded.response_type,
    error_code = excluded.error_code,
    datasource_exec_ms = excluded.datasource_exec_ms,
    total_ms = excluded.total_ms,
    llm_prompt_tokens = excluded.llm_prompt_tokens,
    llm_completion_tokens = excluded.llm_completion_tokens
"""


class AuditLogger:
    """Audit logger backed by a persistent aiosqlite connection and an asyncio write queue.

    Design:
    - A single long-lived connection is created in initialize() and reused for all writes.
      This avoids the overhead of open/close on every request.
    - A background writer task drains an asyncio.Queue, serialising all INSERT operations
      through a single coroutine. This prevents SQLite's single-writer contention under
      concurrent request handling.
    - log_request() enqueues a sentinel-free RequestTrace and returns immediately
      (fire-and-forget), so it never blocks the SSE streaming path.
    """

    _EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
    _LONG_NUMBER_RE = re.compile(r"\b\d{11,}\b")

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = resolve_app_path(db_path or settings.audit_db_path)

        self._db: aiosqlite.Connection | None = None
        self._queue: asyncio.Queue[RequestTrace | None] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE_SQL)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_request_audit_session ON request_audit(session_id)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_request_audit_user ON request_audit(user_id)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_request_audit_created_at ON request_audit(created_at)"
        )
        await self._db.commit()
        self._writer_task = asyncio.ensure_future(self._writer_loop())

    async def close(self) -> None:
        """Flush the queue and close the database connection gracefully."""
        if self._writer_task is not None:
            await self._queue.put(None)  # Sentinel: stop the writer
            await self._writer_task
            self._writer_task = None
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def log_request(self, trace: RequestTrace) -> None:
        """Enqueue a trace record for async writing (non-blocking)."""
        await self._queue.put(trace)

    # ------------------------------------------------------------------
    # Background writer
    # ------------------------------------------------------------------

    async def _writer_loop(self) -> None:
        """Single-consumer coroutine that serialises all DB writes."""
        while True:
            item = await self._queue.get()
            if item is None:
                break  # Shutdown sentinel received
            try:
                await self._write(item)
            except Exception:
                logger.error("audit_write_failed", request_id=item.request_id, exc_info=True)
            finally:
                self._queue.task_done()

    async def _write(self, trace: RequestTrace) -> None:
        if self._db is None:
            raise RuntimeError("AuditLogger.initialize() must be called before writing")
        await self._db.execute(
            _INSERT_SQL,
            (
                trace.request_id,
                trace.session_id,
                self._hash_user_id(trace.user_id),
                self._sanitize_text(trace.raw_query),
                self._sanitize_text(trace.intent_json),
                self._sanitize_text(trace.generated_sql),
                trace.response_type,
                trace.error_code,
                trace.datasource_exec_ms,
                trace.total_ms,
                trace.llm_tokens.prompt_tokens,
                trace.llm_tokens.completion_tokens,
            ),
        )
        await self._db.commit()
        logger.info("audit_log_persisted", request_id=trace.request_id)

    # ------------------------------------------------------------------
    # Privacy helpers
    # ------------------------------------------------------------------

    def _hash_user_id(self, user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    def _sanitize_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        sanitized = self._EMAIL_RE.sub("[redacted-email]", value)
        sanitized = self._LONG_NUMBER_RE.sub("[redacted-number]", sanitized)
        return sanitized


audit_logger = AuditLogger()
