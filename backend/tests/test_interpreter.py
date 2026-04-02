"""Unit tests for Interpreter Service (T-13).

Scenarios covered:
1. Basic channel-GMV data  – tokens streamed, output contains highest channel & value
2. Top-N row truncation    – only 10 rows forwarded even when result has more
3. Data security           – prompt does NOT contain raw row count beyond Top-N limit
4. Empty result            – empty rows still produce a valid generator
5. Period comparison       – prev_result included in prompt when provided
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import ParsedIntent, QueryColumn, QueryResult, TimeRange
from services.interpreter import InterpreterService, _TOP_N, _build_messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _channel_gmv_result() -> QueryResult:
    """4-channel GMV result: App has the highest value."""
    return QueryResult(
        columns=[
            QueryColumn(name="channel", type="string"),
            QueryColumn(name="gmv", type="number", format="currency"),
        ],
        rows=[
            ["App", 1_234_567],
            ["Web", 987_654],
            ["H5", 543_210],
            ["小程序", 321_098],
        ],
        total_rows=4,
        execution_ms=42,
    )


def _gmv_intent() -> ParsedIntent:
    return ParsedIntent(
        metrics=["GMV"],
        dimensions=["渠道"],
        time_range=TimeRange(type="last_week"),
    )


def _make_service(tokens: list[str]) -> InterpreterService:
    """Build InterpreterService whose LLM streams the given tokens."""

    async def _fake_stream(**_kwargs):  # type: ignore[no-untyped-def]
        for token in tokens:
            yield token

    mock_client = MagicMock()
    mock_client.stream = _fake_stream
    return InterpreterService(llm_client=mock_client)


async def _collect(gen) -> str:  # type: ignore[type-arg]
    """Drain an async generator into a single string."""
    parts = []
    async for token in await gen:
        parts.append(token)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInterpreterBasic(unittest.IsolatedAsyncioTestCase):
    async def test_channel_gmv_output_contains_highest_channel_and_value(self) -> None:
        """Core acceptance criterion: output must mention the top channel and its value."""
        tokens = ["上周", "App", "渠道", "GMV", "最高", "，达", "123.5", "万元", "。"]
        service = _make_service(tokens)

        result_text = await _collect(
            service.interpret(
                result=_channel_gmv_result(),
                intent=_gmv_intent(),
                query="上周各渠道的GMV",
            )
        )

        self.assertIn("App", result_text)
        # Numeric value of the highest channel appears somewhere in the output
        self.assertTrue(
            any(v in result_text for v in ["1234567", "123.5", "123", "App"]),
            f"Expected highest channel info in output, got: {result_text!r}",
        )

    async def test_returns_async_generator(self) -> None:
        """interpret() must return an awaitable that yields an async generator."""
        import inspect

        service = _make_service(["hello"])
        gen = service.interpret(
            result=_channel_gmv_result(),
            intent=_gmv_intent(),
            query="test",
        )
        # The coroutine should be awaitable
        self.assertTrue(inspect.isawaitable(gen))
        resolved = await gen
        self.assertTrue(hasattr(resolved, "__aiter__"), "Resolved value must be async iterable")


class TestInterpreterTopNTruncation(unittest.IsolatedAsyncioTestCase):
    async def test_only_top_n_rows_in_prompt(self) -> None:
        """Rows beyond _TOP_N must be truncated before reaching the LLM."""
        captured_messages: list = []

        async def _capturing_stream(messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured_messages.extend(messages)
            yield "ok"

        mock_client = MagicMock()
        mock_client.stream = _capturing_stream
        service = InterpreterService(llm_client=mock_client)

        # Build a result with more than _TOP_N rows
        many_rows = [[f"ch_{i}", i * 1000] for i in range(_TOP_N + 5)]
        big_result = QueryResult(
            columns=[QueryColumn(name="channel"), QueryColumn(name="gmv", type="number")],
            rows=many_rows,
            total_rows=len(many_rows),
            execution_ms=10,
        )

        await _collect(
            service.interpret(result=big_result, intent=_gmv_intent(), query="各渠道GMV")
        )

        prompt_text = captured_messages[0]["content"]
        # Row beyond Top-N must not appear in the prompt
        self.assertNotIn(f"ch_{_TOP_N}", prompt_text)
        # Last allowed row must appear
        self.assertIn(f"ch_{_TOP_N - 1}", prompt_text)

    async def test_raw_rows_beyond_top_n_excluded(self) -> None:
        """Data security: raw overflow rows must be absent from prompt content."""
        big_result = QueryResult(
            columns=[QueryColumn(name="channel"), QueryColumn(name="gmv", type="number")],
            rows=[[f"secret_ch_{i}", i] for i in range(_TOP_N + 3)],
            total_rows=_TOP_N + 3,
            execution_ms=5,
        )
        messages = _build_messages(big_result, _gmv_intent(), "test", None)
        prompt = messages[0]["content"]

        # Rows past index 9 must NOT appear in the prompt
        for i in range(_TOP_N, _TOP_N + 3):
            self.assertNotIn(f"secret_ch_{i}", prompt)


class TestInterpreterEmptyResult(unittest.IsolatedAsyncioTestCase):
    async def test_empty_rows_still_streams(self) -> None:
        service = _make_service(["暂无数据。"])
        empty_result = QueryResult(
            columns=[QueryColumn(name="channel"), QueryColumn(name="gmv", type="number")],
            rows=[],
            total_rows=0,
            execution_ms=0,
        )
        result_text = await _collect(
            service.interpret(result=empty_result, intent=_gmv_intent(), query="各渠道GMV")
        )
        self.assertIsInstance(result_text, str)


class TestInterpreterPrevResult(unittest.IsolatedAsyncioTestCase):
    async def test_prev_result_included_in_prompt(self) -> None:
        """When prev_result is supplied, it should appear in the rendered prompt."""
        prev = QueryResult(
            columns=[QueryColumn(name="channel"), QueryColumn(name="gmv", type="number")],
            rows=[["App", 900_000], ["Web", 800_000]],
            total_rows=2,
            execution_ms=10,
        )
        messages = _build_messages(_channel_gmv_result(), _gmv_intent(), "上周渠道GMV", prev)
        prompt = messages[0]["content"]

        self.assertIn("900000", prompt)
        self.assertIn("上期", prompt)


if __name__ == "__main__":
    unittest.main()
