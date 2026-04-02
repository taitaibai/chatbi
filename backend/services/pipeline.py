"""T-17: Query Pipeline Orchestrator.

run(query, session_id, user_id) chains:
  NLU → Semantic → SQL Gen → Security → Complexity → Execute → Viz → Interpret

Error hierarchy:
  ClarificationNeeded   – NLU flagged clarification_needed=True; short-circuits immediately
  SemanticNotFoundError – metric/dimension not resolved (re-raised from semantic.py)
  SQLUnsafeError        – SQL failed security validation (re-raised from security.py)
  ComplexityError       – query blocked by complexity guard
  AdapterError          – datasource execution failed

Token tracking:
  NLU and SQL Gen calls use chat_with_usage(); tokens are accumulated into
  RequestTrace.llm_tokens across both steps. The Interpreter uses streaming
  which does not expose per-request usage, so it is not counted here.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import structlog

from adapters.base import DataSourceAdapter
from adapters.registry import get_adapter
from models.schemas import (
    ChartSpec,
    ParsedIntent,
    QueryResult,
    RequestTrace,
    TokenUsage,
)
from observability.audit import audit_logger
from services.complexity import ComplexityGuard, complexity_guard
from services.interpreter import InterpreterService, interpreter_service
from services.nlu import NLUService, nlu_service
from services.security import SQLUnsafeError, SecurityChecker, security_checker
from services.semantic import SemanticNotFoundError, SemanticService, semantic_service
from services.sql_gen import SQLGenService, sql_gen_service
from services.visualization import VisualizationService, visualization_service
from session.manager import SessionManager, session_manager

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class ClarificationNeeded(Exception):
    """NLU determined the query needs clarification before processing.

    Short-circuits the pipeline; no SQL is generated or executed.
    """

    def __init__(self, question: str, intent: ParsedIntent) -> None:
        super().__init__(question)
        self.question = question
        self.intent = intent


class ComplexityError(Exception):
    """Query was blocked by the complexity guard (estimated cost too high)."""

    def __init__(self, reason: str, suggestion: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.suggestion = suggestion


class AdapterError(Exception):
    """Datasource adapter failed to execute the query."""


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    request_id: str
    intent: ParsedIntent
    sql: str
    query_result: QueryResult
    chart: ChartSpec
    interpretation: AsyncGenerator[str, None]
    trace: RequestTrace
    complexity_warning: str | None = None


# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------


class QueryPipeline:
    """Orchestrates the full NLU→SQL→Execute→Viz→Interpret query pipeline.

    All service dependencies are injected; pass ``None`` to use the
    module-level singletons (normal production path).  Tests supply mocks
    via the constructor.
    """

    def __init__(
        self,
        nlu: NLUService | None = None,
        semantic: SemanticService | None = None,
        sql_gen: SQLGenService | None = None,
        security: SecurityChecker | None = None,
        complexity: ComplexityGuard | None = None,
        visualization: VisualizationService | None = None,
        interpreter: InterpreterService | None = None,
        session_mgr: SessionManager | None = None,
        adapter: DataSourceAdapter | None = None,
    ) -> None:
        self._nlu = nlu or nlu_service
        self._semantic = semantic or semantic_service
        self._sql_gen = sql_gen or sql_gen_service
        self._security = security or security_checker
        self._complexity = complexity or complexity_guard
        self._visualization = visualization or visualization_service
        self._interpreter = interpreter or interpreter_service
        self._session_mgr = session_mgr or session_manager
        self._adapter = adapter  # None → resolved lazily per request

    def _get_adapter(self) -> DataSourceAdapter:
        return self._adapter or get_adapter()

    async def run(
        self,
        query: str,
        session_id: str,
        user_id: str,
    ) -> PipelineResult:
        """Execute the full query pipeline and return a PipelineResult.

        Parameters
        ----------
        query:      The raw natural language query from the user.
        session_id: Identifies the conversation session (multi-turn context).
        user_id:    Identifies the user for audit logging.

        Raises
        ------
        ClarificationNeeded   – user intent is ambiguous; ask a follow-up question.
        SemanticNotFoundError – a requested metric/dimension is not in the semantic model.
        SQLUnsafeError        – generated SQL failed security validation.
        ComplexityError       – query is too expensive and has been blocked.
        AdapterError          – datasource execution failed.
        """
        request_id = str(uuid.uuid4())
        t_start = time.perf_counter()
        tokens = TokenUsage()

        trace = RequestTrace(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            raw_query=query,
        )

        log = logger.bind(request_id=request_id, session_id=session_id)

        try:
            return await self._run_pipeline(
                query=query,
                session_id=session_id,
                t_start=t_start,
                tokens=tokens,
                trace=trace,
                log=log,
            )

        except (
            ClarificationNeeded,
            SemanticNotFoundError,
            SQLUnsafeError,
            ComplexityError,
            AdapterError,
        ):
            # Audit already written inside _run_pipeline before raising
            raise

        except Exception:
            log.error("pipeline_unexpected_error", exc_info=True)
            if not trace.error_code:
                trace.error_code = "unexpected_error"
            if not trace.total_ms:
                trace.total_ms = int((time.perf_counter() - t_start) * 1000)
            await audit_logger.log_request(trace)
            raise

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        query: str,
        session_id: str,
        t_start: float,
        tokens: TokenUsage,
        trace: RequestTrace,
        log: structlog.BoundLogger,
    ) -> PipelineResult:
        # ── Step 1: Session context ──────────────────────────────────────
        ctx = self._session_mgr.get_context(session_id)

        # ── Step 2: NLU ─────────────────────────────────────────────────
        t0 = time.perf_counter()
        intent, nlu_usage = await self._nlu.parse_with_usage(query, ctx)
        tokens.prompt_tokens += nlu_usage.prompt_tokens
        tokens.completion_tokens += nlu_usage.completion_tokens
        log.info(
            "nlu_done",
            clarification_needed=intent.clarification_needed,
            ms=int((time.perf_counter() - t0) * 1000),
        )

        trace.intent_json = intent.model_dump_json()

        if intent.clarification_needed:
            trace.response_type = "clarification"
            trace.llm_tokens = tokens
            trace.total_ms = int((time.perf_counter() - t_start) * 1000)
            await audit_logger.log_request(trace)
            raise ClarificationNeeded(
                question=intent.clarification_question or "请告诉我您想查看什么？",
                intent=intent,
            )

        # ── Step 3: Semantic mapping ─────────────────────────────────────
        t0 = time.perf_counter()
        try:
            resolved = self._semantic.resolve(intent)
        except SemanticNotFoundError:
            trace.error_code = "semantic_not_found"
            trace.llm_tokens = tokens
            trace.total_ms = int((time.perf_counter() - t_start) * 1000)
            await audit_logger.log_request(trace)
            raise
        log.info(
            "semantic_done",
            tables=len(resolved.tables),
            ms=int((time.perf_counter() - t0) * 1000),
        )

        # ── Step 4: SQL generation ───────────────────────────────────────
        t0 = time.perf_counter()
        sql, sql_usage = await self._sql_gen.generate_with_usage(resolved, query)
        tokens.prompt_tokens += sql_usage.prompt_tokens
        tokens.completion_tokens += sql_usage.completion_tokens
        trace.generated_sql = sql
        log.info("sql_gen_done", ms=int((time.perf_counter() - t0) * 1000))

        # ── Step 5: Security validation ──────────────────────────────────
        t0 = time.perf_counter()
        try:
            self._security.validate(sql)
        except SQLUnsafeError:
            trace.error_code = "sql_unsafe"
            trace.llm_tokens = tokens
            trace.total_ms = int((time.perf_counter() - t_start) * 1000)
            await audit_logger.log_request(trace)
            raise
        log.info("security_ok", ms=int((time.perf_counter() - t0) * 1000))

        # ── Step 6: Complexity guard ─────────────────────────────────────
        adapter = self._get_adapter()
        t0 = time.perf_counter()
        check = await self._complexity.check(sql, adapter)
        log.info(
            "complexity_check",
            level=check.level,
            estimated_rows=check.estimated_rows,
            ms=int((time.perf_counter() - t0) * 1000),
        )

        if not check.allowed:
            trace.error_code = "complexity_blocked"
            trace.response_type = "blocked"
            trace.llm_tokens = tokens
            trace.total_ms = int((time.perf_counter() - t_start) * 1000)
            await audit_logger.log_request(trace)
            raise ComplexityError(
                reason=check.reason or "查询复杂度超出限制",
                suggestion=check.suggestion,
            )

        complexity_warning = check.suggestion if check.level == "warning" else None

        # ── Step 7: Execute query ────────────────────────────────────────
        t0 = time.perf_counter()
        try:
            query_result = await adapter.execute(sql)
        except AdapterError:
            raise
        except Exception as exc:
            trace.error_code = "adapter_error"
            trace.llm_tokens = tokens
            trace.total_ms = int((time.perf_counter() - t_start) * 1000)
            await audit_logger.log_request(trace)
            raise AdapterError(str(exc)) from exc

        exec_ms = int((time.perf_counter() - t0) * 1000)
        trace.datasource_exec_ms = query_result.execution_ms or exec_ms
        log.info("execute_done", rows=query_result.total_rows, ms=exec_ms)

        # ── Step 8: Visualization recommendation ────────────────────────
        chart = self._visualization.recommend(query_result)
        log.info("viz_done", chart_type=chart.type)

        # ── Step 9: Interpretation (streaming) ──────────────────────────
        interpretation = await self._interpreter.interpret(
            result=query_result,
            intent=intent,
            query=query,
        )

        # ── Finalize trace ───────────────────────────────────────────────
        trace.response_type = "answer"
        trace.llm_tokens = tokens
        trace.total_ms = int((time.perf_counter() - t_start) * 1000)
        await audit_logger.log_request(trace)

        # Update session context for follow-up queries
        self._session_mgr.update_context(
            session_id=session_id,
            user_query=query,
            assistant_reply=f"[chart:{chart.type}]",
            intent=intent,
            sql=sql,
        )

        log.info("pipeline_done", total_ms=trace.total_ms)

        return PipelineResult(
            request_id=trace.request_id,
            intent=intent,
            sql=sql,
            query_result=query_result,
            chart=chart,
            interpretation=interpretation,
            trace=trace,
            complexity_warning=complexity_warning,
        )


# Module-level singleton — used by the API layer (T-18)
query_pipeline = QueryPipeline()
