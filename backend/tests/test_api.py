from __future__ import annotations

import sys
import unittest
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app
from models import ChartSpec, ParsedIntent, QueryColumn, QueryResult, RequestTrace, TimeRange, TokenUsage
from services.pipeline import PipelineResult
from api.middleware import RateLimitMiddleware


async def _fake_interpretation() -> AsyncGenerator[str, None]:
    for token in ["上周", "App", "渠道", "领先"]:
        yield token


class _FakePipeline:
    async def run(self, query: str, session_id: str, user_id: str) -> PipelineResult:
        return PipelineResult(
            request_id="req-test-001",
            intent=ParsedIntent(
                metrics=["GMV"],
                dimensions=["渠道"],
                time_range=TimeRange(type="last_week"),
                filters=[],
                clarification_needed=False,
            ),
            sql="SELECT channel, SUM(amount) AS gmv FROM fact_orders GROUP BY channel",
            query_result=QueryResult(
                columns=[
                    QueryColumn(name="channel", type="string"),
                    QueryColumn(name="gmv", type="number"),
                ],
                rows=[["App", 123456], ["Web", 65432]],
                total_rows=2,
                execution_ms=36,
            ),
            chart=ChartSpec(
                type="bar",
                echarts_option={"xAxis": {"type": "category"}, "series": [{"type": "bar"}]},
            ),
            interpretation=_fake_interpretation(),
            trace=RequestTrace(
                request_id="req-test-001",
                session_id=session_id,
                user_id=user_id,
                raw_query=query,
                response_type="answer",
                total_ms=120,
                llm_tokens=TokenUsage(prompt_tokens=10, completion_tokens=5),
            ),
        )


class TestChatAPI(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_chat_sse_stream_emits_expected_events(self) -> None:
        request = {
            "session_id": "sess-test-1",
            "query": "查询上周各渠道GMV",
            "user_id": "user-test-1",
            "options": {"show_sql": True, "show_intent": True},
        }

        with patch("api.v1.chat.query_pipeline", _FakePipeline()):
            with self.client.stream("POST", "/api/v1/chat", json=request) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")

                events = []
                current_event = None
                current_data = None
                for line in response.iter_lines():
                    if not line:
                        if current_event and current_data:
                            events.append((current_event, current_data))
                        current_event = None
                        current_data = None
                        continue
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        current_data = line.split(":", 1)[1].strip()

        event_names = [event for event, _ in events]
        self.assertEqual(
            event_names,
            [
                "intent_summary",
                "sql",
                "table_data",
                "chart_spec",
                "interpretation",
                "interpretation",
                "interpretation",
                "interpretation",
                "interpretation",
                "done",
            ],
        )
        self.assertIn('"start"', events[0][1])
        self.assertIn('"sql"', events[1][1])
        self.assertIn('"rows"', events[2][1])
        self.assertIn('"echarts_option"', events[3][1])
        self.assertIn('"done": true', events[-2][1])

    def test_semantic_metrics_endpoint_returns_domains(self) -> None:
        response = self.client.get("/api/v1/semantic/metrics")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("domains", payload)
        self.assertIsInstance(payload["domains"], dict)
        self.assertGreater(len(payload["domains"]), 0)

    def test_semantic_reload_requires_admin_token(self) -> None:
        response = self.client.post("/api/v1/semantic/reload")
        self.assertEqual(response.status_code, 401)

    def test_semantic_reload_succeeds_with_admin_token(self) -> None:
        response = self.client.post(
            "/api/v1/semantic/reload",
            headers={"X-Admin-Token": "change-me-in-production"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "reloaded")
        self.assertGreaterEqual(payload["domain_count"], 1)

    def test_rate_limit_blocks_request_after_20_calls_per_minute(self) -> None:
        request = {
            "session_id": "sess-rate-limit",
            "query": "查询上周各渠道GMV",
            "user_id": "user-rate-limit",
            "options": {"show_sql": False, "show_intent": False},
        }

        with patch("api.v1.chat.query_pipeline", _FakePipeline()):
            for _ in range(20):
                response = self.client.post("/api/v1/chat", json=request)
                self.assertEqual(response.status_code, 200)

            blocked = self.client.post("/api/v1/chat", json=request)

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["code"], "rate_limit_exceeded")

    def test_rate_limit_accepts_user_id_from_header(self) -> None:
        request = {
            "session_id": "sess-header-user",
            "query": "查询上周各渠道GMV",
            "user_id": "user-in-body",
            "options": {"show_sql": False, "show_intent": False},
        }

        with patch("api.v1.chat.query_pipeline", _FakePipeline()):
            response = self.client.post(
                "/api/v1/chat",
                json=request,
                headers={"X-User-Id": "user-from-header"},
            )

        self.assertEqual(response.status_code, 200)

    def test_rate_limit_removes_empty_buckets_after_window_expires(self) -> None:
        middleware = RateLimitMiddleware(app=lambda *_: None, max_requests_per_minute=2)
        middleware._requests["user-a"].append(10.0)

        with patch("api.middleware.time.time", return_value=100.0):
            bucket = middleware._prune_bucket("user-a", 100.0)

        self.assertNotIn("user-a", middleware._requests)
        self.assertIsNone(bucket)
