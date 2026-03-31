from __future__ import annotations

from pathlib import Path

import aiosqlite
import structlog

from config.settings import settings
from models import RequestTrace

logger = structlog.get_logger(__name__)


class AuditLogger:
    def __init__(self, db_path: str | None = None) -> None:
        configured_path = Path(db_path or settings.audit_db_path)
        if configured_path.is_absolute():
            self._db_path = configured_path
        else:
            project_root = Path(__file__).resolve().parents[2]
            self._db_path = project_root / configured_path

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
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
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_audit_session ON request_audit(session_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_audit_user ON request_audit(user_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_audit_created_at ON request_audit(created_at)"
            )
            await db.commit()

    async def log_request(self, trace: RequestTrace) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO request_audit (
                    request_id, session_id, user_id, raw_query, intent_json,
                    generated_sql, response_type, error_code, datasource_exec_ms,
                    total_ms, llm_prompt_tokens, llm_completion_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.request_id,
                    trace.session_id,
                    trace.user_id,
                    trace.raw_query,
                    trace.intent_json,
                    trace.generated_sql,
                    trace.response_type,
                    trace.error_code,
                    trace.datasource_exec_ms,
                    trace.total_ms,
                    trace.llm_tokens.prompt_tokens,
                    trace.llm_tokens.completion_tokens,
                ),
            )
            await db.commit()
        logger.info("audit_log_persisted", request_id=trace.request_id)


audit_logger = AuditLogger()
