"""Unit tests for NLU Service (T-10).

Scenarios covered:
1. Normal query  – successfully parsed intent with metrics / dimensions / time_range
2. Follow-up     – is_followup=True, inherits previous intent fields
3. Ambiguity     – clarification_needed=True returned from LLM
4. Empty metrics – clarification forced when no metrics can be identified
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import ConversationTurn, ParsedIntent, SessionContext, TimeRange
from services.nlu import NLUService, _detect_followup


def _make_ctx(
    last_intent: ParsedIntent | None = None,
    turns: list[ConversationTurn] | None = None,
) -> SessionContext:
    return SessionContext(
        session_id="test-session",
        turns=turns or [],
        last_intent=last_intent,
    )


def _make_service(llm_response: str | None = None, raises: Exception | None = None) -> NLUService:
    """Build NLUService with a mocked LLM client."""
    from models.schemas import TokenUsage

    mock_client = MagicMock()
    if raises is not None:
        mock_client.chat_with_usage = AsyncMock(side_effect=raises)
    else:
        mock_client.chat_with_usage = AsyncMock(return_value=(llm_response, TokenUsage()))
    return NLUService(llm_client=mock_client)


class TestDetectFollowup(unittest.TestCase):
    def test_followup_keywords_detected(self) -> None:
        self.assertTrue(_detect_followup("那按渠道细分一下"))
        self.assertTrue(_detect_followup("换成折线图呢"))
        self.assertTrue(_detect_followup("再看看上周的"))
        self.assertTrue(_detect_followup("那城市维度也看看"))

    def test_normal_query_not_followup(self) -> None:
        self.assertFalse(_detect_followup("上周各渠道的GMV"))
        self.assertFalse(_detect_followup("最近30天新增用户数"))


class TestNLUServiceNormalQuery(unittest.IsolatedAsyncioTestCase):
    async def test_normal_query_returns_parsed_intent(self) -> None:
        llm_json = json.dumps(
            {
                "metrics": ["GMV"],
                "dimensions": ["渠道"],
                "time_range": {"type": "last_week", "start": None, "end": None},
                "filters": [],
                "clarification_needed": False,
                "clarification_question": None,
            }
        )
        service = _make_service(llm_response=llm_json)
        ctx = _make_ctx()

        result = await service.parse("上周各渠道的GMV", ctx)

        self.assertIsInstance(result, ParsedIntent)
        self.assertEqual(result.metrics, ["GMV"])
        self.assertEqual(result.dimensions, ["渠道"])
        self.assertIsNotNone(result.time_range)
        self.assertEqual(result.time_range.type, "last_week")  # type: ignore[union-attr]
        self.assertFalse(result.clarification_needed)
        self.assertFalse(result.is_followup)


class TestNLUServiceFollowup(unittest.IsolatedAsyncioTestCase):
    async def test_followup_inherits_previous_intent(self) -> None:
        # LLM returns only dimensions (user asked "那按城市呢?")
        llm_json = json.dumps(
            {
                "metrics": [],
                "dimensions": ["城市"],
                "time_range": None,
                "filters": [],
                "clarification_needed": False,
                "clarification_question": None,
            }
        )
        service = _make_service(llm_response=llm_json)

        prev_intent = ParsedIntent(
            metrics=["GMV"],
            dimensions=["渠道"],
            time_range=TimeRange(type="last_week"),
            is_followup=False,
        )
        ctx = _make_ctx(last_intent=prev_intent)

        result = await service.parse("那按城市呢", ctx)

        self.assertTrue(result.is_followup)
        # Metrics inherited from previous intent
        self.assertEqual(result.metrics, ["GMV"])
        # Dimensions from current query
        self.assertEqual(result.dimensions, ["城市"])
        # Time range inherited from previous intent
        self.assertIsNotNone(result.time_range)
        self.assertEqual(result.time_range.type, "last_week")  # type: ignore[union-attr]
        self.assertFalse(result.clarification_needed)


class TestNLUServiceAmbiguity(unittest.IsolatedAsyncioTestCase):
    async def test_llm_returns_clarification_needed(self) -> None:
        llm_json = json.dumps(
            {
                "metrics": [],
                "dimensions": [],
                "time_range": None,
                "filters": [],
                "clarification_needed": True,
                "clarification_question": "您是想查看销售额还是利润？",
            }
        )
        service = _make_service(llm_response=llm_json)
        ctx = _make_ctx()

        result = await service.parse("帮我看看那个钱的数据", ctx)

        self.assertTrue(result.clarification_needed)
        self.assertIsNotNone(result.clarification_question)
        self.assertIn("销售额", result.clarification_question or "")


class TestNLUServiceEmptyMetrics(unittest.IsolatedAsyncioTestCase):
    async def test_empty_metrics_triggers_clarification(self) -> None:
        # LLM returns metrics=[] without marking clarification_needed
        llm_json = json.dumps(
            {
                "metrics": [],
                "dimensions": ["渠道"],
                "time_range": {"type": "last_month", "start": None, "end": None},
                "filters": [],
                "clarification_needed": False,
                "clarification_question": None,
            }
        )
        service = _make_service(llm_response=llm_json)
        ctx = _make_ctx()  # No previous intent to inherit from

        result = await service.parse("按渠道看看上个月", ctx)

        # Service should force clarification when metrics are empty
        self.assertTrue(result.clarification_needed)
        self.assertIsNotNone(result.clarification_question)

    async def test_json_parse_failure_returns_clarification(self) -> None:
        # LLM returns invalid JSON on all attempts
        service = _make_service(llm_response="not valid json at all {{}")
        ctx = _make_ctx()

        result = await service.parse("随便问一下", ctx)

        self.assertTrue(result.clarification_needed)
        self.assertIsNotNone(result.clarification_question)

    async def test_llm_exception_returns_clarification(self) -> None:
        service = _make_service(raises=RuntimeError("connection error"))
        ctx = _make_ctx()

        result = await service.parse("GMV是多少", ctx)

        self.assertTrue(result.clarification_needed)


if __name__ == "__main__":
    unittest.main()
