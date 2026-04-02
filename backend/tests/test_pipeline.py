"""T-17 Integration Tests: Query Pipeline.

Uses Mock LLM + MockAdapter to walk through the full
"查询上周各渠道GMV" pipeline and verify each step's inputs/outputs.
"""
from __future__ import annotations

import json
import sys
import unittest
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from adapters.mock import MockAdapter
from models.schemas import (
    ParsedIntent,
    QueryColumn,
    QueryResult,
    TimeRange,
    TokenUsage,
)
from services.complexity import ComplexityGuard
from services.interpreter import InterpreterService
from services.nlu import NLUService
from services.pipeline import (
    AdapterError,
    ClarificationNeeded,
    ComplexityError,
    QueryPipeline,
)
from services.security import SQLUnsafeError, SecurityChecker
from services.semantic import SemanticNotFoundError, SemanticService
from services.sql_gen import SQLGenService
from services.visualization import VisualizationService
from session.manager import SessionManager


# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------

_GMV_INTENT_JSON = json.dumps(
    {
        "metrics": ["GMV"],
        "dimensions": ["渠道"],
        "time_range": {"type": "last_week"},
        "filters": [],
        "clarification_needed": False,
        "clarification_question": None,
    }
)

_CHANNEL_GMV_SQL = (
    "SELECT channel, SUM(amount) AS gmv "
    "FROM fact_orders "
    "WHERE stat_date BETWEEN '2026-03-23' AND '2026-03-29' "
    "GROUP BY channel"
)

_CLARIFICATION_INTENT_JSON = json.dumps(
    {
        "metrics": [],
        "dimensions": [],
        "time_range": None,
        "filters": [],
        "clarification_needed": True,
        "clarification_question": "您想查看哪个时间段的数据？",
    }
)


def _make_mock_nlu(intent_json: str) -> NLUService:
    """Return a NLUService whose LLM always returns *intent_json*."""
    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.chat_with_usage = AsyncMock(
        return_value=(intent_json, TokenUsage(prompt_tokens=100, completion_tokens=50))
    )
    return NLUService(llm_client=mock_client)


def _make_mock_sql_gen(sql: str) -> SQLGenService:
    """Return a SQLGenService whose LLM always returns *sql*."""
    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.chat_with_usage = AsyncMock(
        return_value=(sql, TokenUsage(prompt_tokens=200, completion_tokens=80))
    )
    return SQLGenService(llm_client=mock_client)


async def _mock_interpreter_stream() -> AsyncGenerator[str, None]:
    for token in ["上周", "各渠道", "GMV", "中，App", "渠道", "表现最佳。"]:
        yield token


def _make_mock_interpreter() -> InterpreterService:
    """Return an InterpreterService that yields a fixed token stream."""
    mock_client = MagicMock()
    mock_client.is_configured = True
    svc = InterpreterService(llm_client=mock_client)

    async def _interpret(*args: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        return _mock_interpreter_stream()

    svc.interpret = _interpret  # type: ignore[method-assign]
    return svc


def _make_pipeline(
    *,
    intent_json: str = _GMV_INTENT_JSON,
    sql: str = _CHANNEL_GMV_SQL,
    adapter: MockAdapter | None = None,
) -> QueryPipeline:
    return QueryPipeline(
        nlu=_make_mock_nlu(intent_json),
        sql_gen=_make_mock_sql_gen(sql),
        interpreter=_make_mock_interpreter(),
        adapter=adapter or MockAdapter(),
        session_mgr=SessionManager(ttl_seconds=300),
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestPipelineHappyPath(unittest.IsolatedAsyncioTestCase):
    """Full happy-path: 查询上周各渠道GMV."""

    async def asyncSetUp(self) -> None:
        self.pipeline = _make_pipeline()
        self.result = await self.pipeline.run(
            query="查询上周各渠道GMV",
            session_id="test-session-1",
            user_id="test-user",
        )

    async def test_returns_pipeline_result(self) -> None:
        self.assertIsNotNone(self.result)

    async def test_intent_has_correct_metrics_and_dimensions(self) -> None:
        intent = self.result.intent
        self.assertIn("GMV", intent.metrics)
        self.assertIn("渠道", intent.dimensions)
        self.assertFalse(intent.clarification_needed)
        self.assertIsNotNone(intent.time_range)
        self.assertEqual(intent.time_range.type, "last_week")  # type: ignore[union-attr]

    async def test_sql_is_non_empty_string(self) -> None:
        self.assertIsInstance(self.result.sql, str)
        self.assertGreater(len(self.result.sql), 0)

    async def test_query_result_has_rows(self) -> None:
        qr = self.result.query_result
        self.assertIsInstance(qr, QueryResult)
        self.assertGreater(qr.total_rows, 0)
        self.assertGreater(len(qr.columns), 0)

    async def test_chart_spec_assigned(self) -> None:
        self.assertIsNotNone(self.result.chart)
        self.assertIn(self.result.chart.type, ("bar", "line", "pie", "card", "table"))

    async def test_interpretation_is_async_generator(self) -> None:
        tokens = []
        async for token in self.result.interpretation:
            tokens.append(token)
        self.assertGreater(len(tokens), 0)

    async def test_trace_fields_populated(self) -> None:
        trace = self.result.trace
        self.assertEqual(trace.session_id, "test-session-1")
        self.assertEqual(trace.raw_query, "查询上周各渠道GMV")
        self.assertIsNotNone(trace.intent_json)
        self.assertIsNotNone(trace.generated_sql)
        self.assertEqual(trace.response_type, "answer")
        self.assertIsNone(trace.error_code)
        self.assertIsNotNone(trace.total_ms)
        self.assertGreaterEqual(trace.total_ms, 0)  # type: ignore[operator]

    async def test_token_usage_accumulated(self) -> None:
        # NLU: 100+50, SQL Gen: 200+80 → total prompt=300, completion=130
        self.assertEqual(self.result.trace.llm_tokens.prompt_tokens, 300)
        self.assertEqual(self.result.trace.llm_tokens.completion_tokens, 130)

    async def test_datasource_exec_ms_recorded(self) -> None:
        self.assertIsNotNone(self.result.trace.datasource_exec_ms)
        self.assertGreaterEqual(self.result.trace.datasource_exec_ms, 0)  # type: ignore[operator]

    async def test_request_id_is_uuid_string(self) -> None:
        import uuid
        uuid.UUID(self.result.request_id)  # raises ValueError if invalid


class TestPipelineClarificationShortCircuit(unittest.IsolatedAsyncioTestCase):
    """When NLU returns clarification_needed=True, pipeline short-circuits."""

    async def test_raises_clarification_needed(self) -> None:
        pipeline = _make_pipeline(intent_json=_CLARIFICATION_INTENT_JSON)

        with self.assertRaises(ClarificationNeeded) as ctx:
            await pipeline.run(
                query="随便问问",
                session_id="test-session-2",
                user_id="test-user",
            )

        exc = ctx.exception
        self.assertIsInstance(exc.question, str)
        self.assertGreater(len(exc.question), 0)
        self.assertTrue(exc.intent.clarification_needed)

    async def test_no_sql_generated_on_clarification(self) -> None:
        """SQL Gen should not be called when clarification is needed."""
        mock_sql_gen = MagicMock()
        mock_sql_gen.generate_with_usage = AsyncMock()

        pipeline = QueryPipeline(
            nlu=_make_mock_nlu(_CLARIFICATION_INTENT_JSON),
            sql_gen=mock_sql_gen,
            adapter=MockAdapter(),
            session_mgr=SessionManager(ttl_seconds=300),
        )

        with self.assertRaises(ClarificationNeeded):
            await pipeline.run(
                query="随便问问",
                session_id="test-session-3",
                user_id="test-user",
            )

        mock_sql_gen.generate_with_usage.assert_not_called()


class TestPipelineSemanticError(unittest.IsolatedAsyncioTestCase):
    """SemanticNotFoundError propagates correctly."""

    async def test_raises_semantic_not_found(self) -> None:
        bad_intent_json = json.dumps(
            {
                "metrics": ["不存在的指标xyz"],
                "dimensions": [],
                "time_range": None,
                "filters": [],
                "clarification_needed": False,
                "clarification_question": None,
            }
        )
        pipeline = _make_pipeline(intent_json=bad_intent_json)

        with self.assertRaises(SemanticNotFoundError):
            await pipeline.run(
                query="查询不存在的指标",
                session_id="test-session-4",
                user_id="test-user",
            )


class TestPipelineSecurityError(unittest.IsolatedAsyncioTestCase):
    """SQLUnsafeError propagates correctly."""

    async def test_raises_sql_unsafe_error(self) -> None:
        # LLM returns a DROP TABLE — security should reject it
        unsafe_sql = "DROP TABLE fact_orders"
        pipeline = _make_pipeline(sql=unsafe_sql)

        with self.assertRaises(SQLUnsafeError):
            await pipeline.run(
                query="查询上周各渠道GMV",
                session_id="test-session-5",
                user_id="test-user",
            )


class TestPipelineComplexityBlocked(unittest.IsolatedAsyncioTestCase):
    """ComplexityError is raised when the guard blocks the query."""

    async def test_raises_complexity_error(self) -> None:
        from services.complexity import CheckResult

        mock_guard = MagicMock(spec=ComplexityGuard)
        mock_guard.check = AsyncMock(
            return_value=CheckResult(
                allowed=False,
                level="blocked",
                reason="预估扫描行数 10,000,000 超过阈值",
                suggestion="建议增加时间范围过滤",
                estimated_rows=10_000_000,
            )
        )

        pipeline = QueryPipeline(
            nlu=_make_mock_nlu(_GMV_INTENT_JSON),
            sql_gen=_make_mock_sql_gen(_CHANNEL_GMV_SQL),
            complexity=mock_guard,
            adapter=MockAdapter(),
            session_mgr=SessionManager(ttl_seconds=300),
        )

        with self.assertRaises(ComplexityError) as ctx:
            await pipeline.run(
                query="查询上周各渠道GMV",
                session_id="test-session-6",
                user_id="test-user",
            )

        exc = ctx.exception
        self.assertIn("超过阈值", exc.reason)
        self.assertIsNotNone(exc.suggestion)


class TestPipelineAdapterError(unittest.IsolatedAsyncioTestCase):
    """AdapterError is raised when the datasource fails."""

    async def test_raises_adapter_error(self) -> None:
        failing_adapter = MagicMock(spec=MockAdapter)
        failing_adapter.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        failing_adapter.estimate_complexity = AsyncMock(
            return_value=MagicMock(estimated_rows=1000, estimated_cost=1, execution_ms=5)
        )

        pipeline = QueryPipeline(
            nlu=_make_mock_nlu(_GMV_INTENT_JSON),
            sql_gen=_make_mock_sql_gen(_CHANNEL_GMV_SQL),
            adapter=failing_adapter,
            session_mgr=SessionManager(ttl_seconds=300),
        )

        with self.assertRaises(AdapterError):
            await pipeline.run(
                query="查询上周各渠道GMV",
                session_id="test-session-7",
                user_id="test-user",
            )


class TestPipelineComplexityWarning(unittest.IsolatedAsyncioTestCase):
    """Warning-level complexity check allows the query but sets complexity_warning."""

    async def test_warning_sets_complexity_warning_field(self) -> None:
        from services.complexity import CheckResult

        mock_guard = MagicMock(spec=ComplexityGuard)
        mock_guard.check = AsyncMock(
            return_value=CheckResult(
                allowed=True,
                level="warning",
                reason="涉及大表但未包含时间范围过滤",
                suggestion="建议增加时间范围过滤",
                estimated_rows=500_000,
            )
        )

        pipeline = QueryPipeline(
            nlu=_make_mock_nlu(_GMV_INTENT_JSON),
            sql_gen=_make_mock_sql_gen(_CHANNEL_GMV_SQL),
            complexity=mock_guard,
            interpreter=_make_mock_interpreter(),
            adapter=MockAdapter(),
            session_mgr=SessionManager(ttl_seconds=300),
        )

        result = await pipeline.run(
            query="查询上周各渠道GMV",
            session_id="test-session-8",
            user_id="test-user",
        )

        self.assertIsNotNone(result.complexity_warning)
        self.assertIn("建议", result.complexity_warning)  # type: ignore[operator]


class TestPipelineSessionContextUpdated(unittest.IsolatedAsyncioTestCase):
    """Session context is updated after a successful run for follow-up support."""

    async def test_session_updated_after_run(self) -> None:
        session_mgr = SessionManager(ttl_seconds=300)
        pipeline = QueryPipeline(
            nlu=_make_mock_nlu(_GMV_INTENT_JSON),
            sql_gen=_make_mock_sql_gen(_CHANNEL_GMV_SQL),
            interpreter=_make_mock_interpreter(),
            adapter=MockAdapter(),
            session_mgr=session_mgr,
        )

        await pipeline.run(
            query="查询上周各渠道GMV",
            session_id="test-session-9",
            user_id="test-user",
        )

        ctx = session_mgr.get_context("test-session-9")
        self.assertIsNotNone(ctx.last_intent)
        self.assertIsNotNone(ctx.last_sql)
        self.assertGreater(len(ctx.turns), 0)


if __name__ == "__main__":
    unittest.main()
