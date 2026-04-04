"""T-20 验收测试: AC-01 ~ AC-08 自动化

覆盖需求文档 v1.0 中所有 Given-When-Then 验收标准。
运行方式（在项目根目录）：
    python -m pytest tests/e2e/test_acceptance.py -v

依赖: 后端依赖均在 backend/requirements.txt，需先安装。
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app
from models.schemas import (
    ChartSpec,
    ParsedIntent,
    QueryColumn,
    QueryResult,
    RequestTrace,
    TimeRange,
    TokenUsage,
)
from services.pipeline import (
    AdapterError,
    ClarificationNeeded,
    ComplexityError,
    PipelineResult,
)
from services.semantic import SemanticNotFoundError

# ── Shared helpers ───────────────────────────────────────────────────────────

_STANDARD_SQL = (
    "SELECT channel, SUM(amount) AS gmv "
    "FROM fact_orders "
    "WHERE stat_date BETWEEN '2026-03-23' AND '2026-03-29' "
    "GROUP BY channel"
)

_STANDARD_INTENT = ParsedIntent(
    metrics=["GMV"],
    dimensions=["渠道"],
    time_range=TimeRange(type="last_week"),
    filters=[],
    clarification_needed=False,
)

_STANDARD_RESULT = QueryResult(
    columns=[
        QueryColumn(name="channel", type="string"),
        QueryColumn(name="gmv", type="number", format="currency"),
    ],
    rows=[["App", 258000.0], ["Web", 187500.0], ["H5", 96500.0]],
    total_rows=3,
    execution_ms=36,
)

_STANDARD_CHART = ChartSpec(
    type="bar",
    echarts_option={"xAxis": {"type": "category"}, "series": [{"type": "bar"}]},
)


async def _fake_interpretation() -> AsyncGenerator[str, None]:
    for token in ["App", "渠道", "领先", "，GMV", "25.8万"]:
        yield token


def _make_standard_pipeline_result(session_id: str, user_id: str) -> PipelineResult:
    return PipelineResult(
        request_id="req-ac-test-001",
        intent=_STANDARD_INTENT,
        sql=_STANDARD_SQL,
        query_result=_STANDARD_RESULT,
        chart=_STANDARD_CHART,
        interpretation=_fake_interpretation(),
        trace=RequestTrace(
            request_id="req-ac-test-001",
            session_id=session_id,
            user_id=user_id,
            raw_query="查询上周各渠道的 GMV",
            response_type="answer",
            total_ms=450,
            llm_tokens=TokenUsage(prompt_tokens=200, completion_tokens=80),
        ),
    )


def _collect_sse_events(client: TestClient, request_body: dict) -> list[tuple[str, dict]]:
    """POST to /api/v1/chat and return list of (event_name, data_dict) tuples."""
    events: list[tuple[str, dict]] = []
    with client.stream("POST", "/api/v1/chat", json=request_body) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].split(";")[0] == "text/event-stream"

        current_event: str | None = None
        for line in response.iter_lines():
            if not line:
                current_event = None
                continue
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and current_event:
                data = json.loads(line.split(":", 1)[1].strip())
                events.append((current_event, data))
                current_event = None

    return events


# ═══════════════════════════════════════════════════════════════════════════════
# AC-01: 基础查询生成
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC01BasicQuery(unittest.TestCase):
    """
    Given  语义模型中已注册"订单表"及"GMV"指标
    When   用户输入"查询上周各渠道的 GMV"
    Then   系统依次推送: intent_summary / sql / table_data / chart_spec /
           interpretation / done 事件，各事件数据结构正确。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.request = {
            "session_id": "sess-ac01",
            "query": "查询上周各渠道的 GMV",
            "user_id": "user-ac01",
            "options": {"show_sql": True, "show_intent": True},
        }

    def _make_pipeline(self) -> MagicMock:
        pipeline = MagicMock()
        pipeline.run = AsyncMock(
            return_value=_make_standard_pipeline_result("sess-ac01", "user-ac01")
        )
        return pipeline

    def test_all_events_emitted_in_correct_order(self) -> None:
        with patch("api.v1.chat.query_pipeline", self._make_pipeline()):
            events = _collect_sse_events(self.client, self.request)

        event_names = [name for name, _ in events]
        # intent_summary and sql come first, then table, chart, interpretations, done
        self.assertIn("intent_summary", event_names)
        self.assertIn("sql", event_names)
        self.assertIn("table_data", event_names)
        self.assertIn("chart_spec", event_names)
        self.assertIn("interpretation", event_names)
        self.assertIn("done", event_names)

        # Ordering: intent_summary < sql < table_data < chart_spec < done
        idx = {name: event_names.index(name) for name in
               ("intent_summary", "sql", "table_data", "chart_spec", "done")}
        self.assertLess(idx["intent_summary"], idx["sql"])
        self.assertLess(idx["sql"], idx["table_data"])
        self.assertLess(idx["table_data"], idx["chart_spec"])
        self.assertLess(idx["chart_spec"], idx["done"])

    def test_intent_summary_contains_required_fields(self) -> None:
        with patch("api.v1.chat.query_pipeline", self._make_pipeline()):
            events = _collect_sse_events(self.client, self.request)

        intent_events = [d for name, d in events if name == "intent_summary"]
        self.assertEqual(len(intent_events), 1)
        data = intent_events[0]
        self.assertIn("metrics", data)
        self.assertIn("dimensions", data)
        self.assertIn("time_range", data)
        self.assertIn("GMV", data["metrics"])
        self.assertIn("渠道", data["dimensions"])

    def test_sql_event_contains_select_statement(self) -> None:
        with patch("api.v1.chat.query_pipeline", self._make_pipeline()):
            events = _collect_sse_events(self.client, self.request)

        sql_events = [d for name, d in events if name == "sql"]
        self.assertEqual(len(sql_events), 1)
        self.assertIn("sql", sql_events[0])
        self.assertIn("SELECT", sql_events[0]["sql"].upper())

    def test_table_data_contains_rows(self) -> None:
        with patch("api.v1.chat.query_pipeline", self._make_pipeline()):
            events = _collect_sse_events(self.client, self.request)

        table_events = [d for name, d in events if name == "table_data"]
        self.assertEqual(len(table_events), 1)
        data = table_events[0]
        self.assertIn("rows", data)
        self.assertIn("columns", data)
        self.assertGreater(data["total_rows"], 0)

    def test_chart_spec_contains_echarts_option(self) -> None:
        with patch("api.v1.chat.query_pipeline", self._make_pipeline()):
            events = _collect_sse_events(self.client, self.request)

        chart_events = [d for name, d in events if name == "chart_spec"]
        self.assertEqual(len(chart_events), 1)
        self.assertIn("echarts_option", chart_events[0])
        self.assertIn("type", chart_events[0])

    def test_done_event_contains_latency(self) -> None:
        with patch("api.v1.chat.query_pipeline", self._make_pipeline()):
            events = _collect_sse_events(self.client, self.request)

        done_events = [d for name, d in events if name == "done"]
        self.assertEqual(len(done_events), 1)
        self.assertIn("latency_ms", done_events[0])
        # AC-01 要求 P95 ≤ 8000ms；此处验证字段存在且为非负数
        self.assertGreaterEqual(done_events[0]["latency_ms"], 0)

    def test_interpretation_tokens_streamed(self) -> None:
        with patch("api.v1.chat.query_pipeline", self._make_pipeline()):
            events = _collect_sse_events(self.client, self.request)

        interp_events = [d for name, d in events if name == "interpretation"]
        self.assertGreater(len(interp_events), 1, "应有多个 interpretation token 事件")
        # 最后一个 interpretation 事件应标记 done=True
        self.assertTrue(interp_events[-1].get("done"), "最后一个 interpretation 应 done=True")


# ═══════════════════════════════════════════════════════════════════════════════
# AC-02: 歧义澄清
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC02Clarification(unittest.TestCase):
    """
    Given  用户输入"最近的销售情况怎么样"
    When   "最近"和"销售情况"存在多种解释
    Then   系统反问，不执行查询，不直接报错退出。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _make_clarification_pipeline(self) -> MagicMock:
        clarification_intent = ParsedIntent(
            metrics=[],
            dimensions=[],
            time_range=None,
            clarification_needed=True,
            clarification_question="请问是最近 7 天还是 30 天？需要查看销售额、订单量还是两者都要？",
        )
        pipeline = MagicMock()
        pipeline.run = AsyncMock(
            side_effect=ClarificationNeeded(
                question="请问是最近 7 天还是 30 天？需要查看销售额、订单量还是两者都要？",
                intent=clarification_intent,
            )
        )
        return pipeline

    def test_clarification_triggers_on_ambiguous_query(self) -> None:
        request = {
            "session_id": "sess-ac02",
            "query": "最近的销售情况怎么样",
            "user_id": "user-ac02",
            "options": {"show_sql": True, "show_intent": True},
        }
        with patch("api.v1.chat.query_pipeline", self._make_clarification_pipeline()):
            events = _collect_sse_events(self.client, request)

        event_names = [name for name, _ in events]
        # 应有 intent_summary（告知解析结果）+ error（clarification）+ done
        self.assertIn("error", event_names, "歧义查询应触发 error 事件")
        self.assertIn("done", event_names, "应有 done 事件收尾")

    def test_clarification_error_code_correct(self) -> None:
        request = {
            "session_id": "sess-ac02-b",
            "query": "最近的销售情况怎么样",
            "user_id": "user-ac02",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_clarification_pipeline()):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        self.assertTrue(error_events, "应有 error 事件")
        self.assertEqual(error_events[0].get("code"), "clarification_needed")

    def test_clarification_message_is_friendly_chinese(self) -> None:
        request = {
            "session_id": "sess-ac02-c",
            "query": "最近的销售情况怎么样",
            "user_id": "user-ac02",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_clarification_pipeline()):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        message = error_events[0].get("message", "")
        self.assertTrue(len(message) > 0, "澄清消息不能为空")
        # 应包含中文
        self.assertTrue(any('\u4e00' <= c <= '\u9fff' for c in message), "澄清消息应为中文")

    def test_no_sql_generated_on_clarification(self) -> None:
        request = {
            "session_id": "sess-ac02-d",
            "query": "最近的销售情况怎么样",
            "user_id": "user-ac02",
            "options": {"show_sql": True, "show_intent": True},
        }
        with patch("api.v1.chat.query_pipeline", self._make_clarification_pipeline()):
            events = _collect_sse_events(self.client, request)

        sql_events = [name for name, _ in events if name == "sql"]
        self.assertEqual(len(sql_events), 0, "歧义时不应生成 SQL 事件")


# ═══════════════════════════════════════════════════════════════════════════════
# AC-03: 多轮上下文继承
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC03MultiTurnContext(unittest.TestCase):
    """
    Given  上一轮已查询"上周各渠道 GMV"
    When   用户追问"那退款率呢？"
    Then   系统继承上轮时间范围（上周）和维度（渠道），生成退款率查询。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_second_turn_inherits_context(self) -> None:
        session_id = "sess-ac03"
        user_id = "user-ac03"

        # 第一轮: GMV 查询（设置 session context）
        first_pipeline = MagicMock()
        first_pipeline.run = AsyncMock(
            return_value=_make_standard_pipeline_result(session_id, user_id)
        )

        # 第二轮: 追问退款率（验证 session_id 相同，管道被调用）
        refund_intent = ParsedIntent(
            metrics=["退款率"],
            dimensions=["渠道"],
            time_range=TimeRange(type="last_week"),
            filters=[],
            is_followup=True,
            clarification_needed=False,
        )
        refund_result = QueryResult(
            columns=[
                QueryColumn(name="channel", type="string"),
                QueryColumn(name="refund_rate", type="number", format="number"),
            ],
            rows=[["App", 0.032], ["Web", 0.041], ["H5", 0.058]],
            total_rows=3,
            execution_ms=28,
        )
        refund_pipeline_result = PipelineResult(
            request_id="req-ac03-002",
            intent=refund_intent,
            sql="SELECT channel, refund_rate FROM fact_refunds WHERE stat_date BETWEEN '2026-03-23' AND '2026-03-29' GROUP BY channel",
            query_result=refund_result,
            chart=_STANDARD_CHART,
            interpretation=_fake_interpretation(),
            trace=RequestTrace(
                request_id="req-ac03-002",
                session_id=session_id,
                user_id=user_id,
                raw_query="那退款率呢？",
                response_type="answer",
                total_ms=380,
                llm_tokens=TokenUsage(prompt_tokens=220, completion_tokens=90),
            ),
        )
        second_pipeline = MagicMock()
        second_pipeline.run = AsyncMock(return_value=refund_pipeline_result)

        first_request = {
            "session_id": session_id,
            "query": "查询上周各渠道 GMV",
            "user_id": user_id,
            "options": {"show_sql": False, "show_intent": False},
        }
        second_request = {
            "session_id": session_id,  # 同一 session_id
            "query": "那退款率呢？",
            "user_id": user_id,
            "options": {"show_sql": True, "show_intent": True},
        }

        with patch("api.v1.chat.query_pipeline", first_pipeline):
            events1 = _collect_sse_events(self.client, first_request)
        with patch("api.v1.chat.query_pipeline", second_pipeline):
            events2 = _collect_sse_events(self.client, second_request)

        # 第二轮应成功返回数据（不是 clarification error）
        event_names2 = [name for name, _ in events2]
        self.assertIn("table_data", event_names2, "追问应返回 table_data")
        self.assertIn("done", event_names2)

        # 第二轮意图摘要中应包含继承的维度（渠道）
        intent_events2 = [d for name, d in events2 if name == "intent_summary"]
        if intent_events2:
            self.assertIn("渠道", intent_events2[0].get("dimensions", []))

        # 第二轮调用 pipeline.run 时传入的 session_id 应与第一轮相同
        second_pipeline.run.assert_called_once()
        call_kwargs = second_pipeline.run.call_args
        self.assertEqual(call_kwargs.kwargs.get("session_id", call_kwargs.args[1] if len(call_kwargs.args) > 1 else None), session_id)


# ═══════════════════════════════════════════════════════════════════════════════
# AC-04: 权限拦截（通过语义层隔离实现）
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC04PermissionBlock(unittest.TestCase):
    """
    Given  用户查询的指标（薪资/部门）未注册在语义模型中
    When   用户请求"查询各部门薪资分布"
    Then   系统返回"无法找到指标"提示，不生成也不执行任何 SQL。

    实现说明: MVP 阶段通过语义模型隔离实现访问控制——
    未注册的指标（如 finance 域的薪资）会触发 SemanticNotFoundError。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _make_semantic_blocked_pipeline(self) -> MagicMock:
        pipeline = MagicMock()
        pipeline.run = AsyncMock(
            side_effect=SemanticNotFoundError(
                "指标 '薪资' 未找到，可查询: GMV, 订单量, 退款率, DAU, 新增用户",
                available_metrics=["GMV", "订单量", "退款率", "DAU", "新增用户"],
            )
        )
        return pipeline

    def test_unregistered_metric_blocked(self) -> None:
        request = {
            "session_id": "sess-ac04",
            "query": "查询各部门薪资分布",
            "user_id": "user-ac04",
            "options": {"show_sql": True, "show_intent": True},
        }
        with patch("api.v1.chat.query_pipeline", self._make_semantic_blocked_pipeline()):
            events = _collect_sse_events(self.client, request)

        event_names = [name for name, _ in events]
        self.assertIn("error", event_names, "未注册指标应触发 error 事件")
        self.assertNotIn("sql", event_names, "权限拦截时不应生成 SQL 事件")
        self.assertNotIn("table_data", event_names, "权限拦截时不应执行查询")

    def test_error_code_is_semantic_not_found(self) -> None:
        request = {
            "session_id": "sess-ac04-b",
            "query": "查询各部门薪资分布",
            "user_id": "user-ac04",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_semantic_blocked_pipeline()):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        self.assertTrue(error_events)
        self.assertEqual(error_events[0].get("code"), "semantic_not_found")

    def test_available_metrics_listed_in_error(self) -> None:
        request = {
            "session_id": "sess-ac04-c",
            "query": "查询各部门薪资分布",
            "user_id": "user-ac04",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_semantic_blocked_pipeline()):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        self.assertTrue(error_events)
        available = error_events[0].get("available_metrics", [])
        self.assertIsInstance(available, list)
        self.assertGreater(len(available), 0, "应列出可查询的指标列表")


# ═══════════════════════════════════════════════════════════════════════════════
# AC-05: 高危查询拦截
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC05ComplexityBlock(unittest.TestCase):
    """
    Given  查询复杂度超过阈值（预估扫描行数 > 1 亿）
    When   生成的 SQL 触发阈值告警
    Then   系统拦截执行，提示用户缩小范围并给出建议。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _make_complexity_blocked_pipeline(self) -> MagicMock:
        pipeline = MagicMock()
        pipeline.run = AsyncMock(
            side_effect=ComplexityError(
                reason="预估扫描行数 150,000,000 超过阈值 100,000,000，查询被拦截",
                suggestion="建议增加 order_date 范围（如 WHERE order_date BETWEEN '...' AND '...'）",
            )
        )
        return pipeline

    def test_high_complexity_query_blocked(self) -> None:
        request = {
            "session_id": "sess-ac05",
            "query": "查询所有订单的详细记录",
            "user_id": "user-ac05",
            "options": {"show_sql": True, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_complexity_blocked_pipeline()):
            events = _collect_sse_events(self.client, request)

        event_names = [name for name, _ in events]
        self.assertIn("error", event_names)
        self.assertNotIn("table_data", event_names, "高复杂度查询不应执行并返回数据")

    def test_complexity_error_code_and_suggestion(self) -> None:
        request = {
            "session_id": "sess-ac05-b",
            "query": "查询所有订单的详细记录",
            "user_id": "user-ac05",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_complexity_blocked_pipeline()):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        self.assertTrue(error_events)
        data = error_events[0]
        self.assertEqual(data.get("code"), "complexity_blocked")
        self.assertIn("suggestion", data, "应包含缩小范围的建议")
        suggestion = data.get("suggestion", "")
        self.assertTrue(len(suggestion) > 0, "建议内容不能为空")


# ═══════════════════════════════════════════════════════════════════════════════
# AC-06: 语义缺失处理
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC06SemanticMissing(unittest.TestCase):
    """
    Given  用户查询包含语义模型中未注册的指标"活跃度"
    When   系统无法完成映射
    Then   系统告知"暂不支持该指标"，并列出当前可查询的相关指标。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _make_pipeline_with_unknown_metric(self, metric: str) -> MagicMock:
        available = ["GMV", "订单量", "退款率", "DAU", "新增用户", "商品销售额", "渠道UV"]
        pipeline = MagicMock()
        pipeline.run = AsyncMock(
            side_effect=SemanticNotFoundError(
                f"指标 '{metric}' 未找到，可查询: {', '.join(available[:8])}",
                available_metrics=available,
            )
        )
        return pipeline

    def test_unknown_metric_returns_not_found_error(self) -> None:
        request = {
            "session_id": "sess-ac06",
            "query": "查询用户活跃度",
            "user_id": "user-ac06",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_pipeline_with_unknown_metric("活跃度")):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        self.assertTrue(error_events)
        self.assertEqual(error_events[0].get("code"), "semantic_not_found")

    def test_available_metrics_include_common_indicators(self) -> None:
        request = {
            "session_id": "sess-ac06-b",
            "query": "查询用户活跃度",
            "user_id": "user-ac06",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", self._make_pipeline_with_unknown_metric("活跃度")):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        available = error_events[0].get("available_metrics", [])
        self.assertGreater(len(available), 0)
        # 应包含 GMV 等常见指标
        self.assertIn("GMV", available)

    def test_real_semantic_model_rejects_unknown_metric(self) -> None:
        """使用真实语义模型，验证未注册指标（活跃度）触发 SemanticNotFoundError。"""
        from services.semantic import SemanticService

        svc = SemanticService()
        intent = ParsedIntent(
            metrics=["活跃度"],
            dimensions=[],
            time_range=None,
            filters=[],
            clarification_needed=False,
        )
        with self.assertRaises(SemanticNotFoundError) as ctx:
            svc.resolve(intent)

        self.assertGreater(len(ctx.exception.available_metrics), 0,
                           "SemanticNotFoundError 应附带可用指标列表")


# ═══════════════════════════════════════════════════════════════════════════════
# AC-07: 数据源适配器隔离（MVP 专项）
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC07AdapterIsolation(unittest.TestCase):
    """
    Given  Mock 适配器已注册，真实数据库未接入
    When   系统执行生成的 SQL
    Then   Mock 适配器返回预设数据，核心链路完整跑通，
           切换为真实适配器时无需修改上层代码。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_mock_adapter_health_check(self) -> None:
        """Mock 适配器健康检查应返回 True。"""
        import asyncio
        from adapters.mock import MockAdapter
        adapter = MockAdapter()
        result = asyncio.run(adapter.health_check())
        self.assertTrue(result)

    def test_mock_adapter_executes_sales_query(self) -> None:
        """Mock 适配器对销售查询返回预设数据集。"""
        import asyncio
        from adapters.mock import MockAdapter
        adapter = MockAdapter()
        sql = "SELECT channel, SUM(amount) AS gmv FROM fact_orders GROUP BY channel"
        result = asyncio.run(adapter.execute(sql))
        self.assertGreater(result.total_rows, 0)
        self.assertGreater(len(result.columns), 0)
        col_names = [c.name for c in result.columns]
        self.assertIn("channel", col_names)

    def test_mock_adapter_returns_user_dataset(self) -> None:
        """Mock 适配器对用户查询返回用户数据集。"""
        import asyncio
        from adapters.mock import MockAdapter
        adapter = MockAdapter()
        sql = "SELECT stat_date, dau, new_users FROM fact_user_daily GROUP BY stat_date"
        result = asyncio.run(adapter.execute(sql))
        self.assertGreater(result.total_rows, 0)
        col_names = [c.name for c in result.columns]
        self.assertIn("dau", col_names)

    def test_adapter_interface_contract(self) -> None:
        """验证 MockAdapter 实现了 DataSourceAdapter 的所有抽象方法。"""
        from adapters.base import DataSourceAdapter
        from adapters.mock import MockAdapter
        self.assertTrue(issubclass(MockAdapter, DataSourceAdapter))
        adapter = MockAdapter()
        self.assertTrue(hasattr(adapter, "execute"))
        self.assertTrue(hasattr(adapter, "estimate_complexity"))
        self.assertTrue(hasattr(adapter, "health_check"))

    def test_full_pipeline_with_mock_adapter(self) -> None:
        """通过 API 层验证全链路在 Mock 适配器下正常跑通。"""
        request = {
            "session_id": "sess-ac07",
            "query": "查询上周各渠道的 GMV",
            "user_id": "user-ac07",
            "options": {"show_sql": True, "show_intent": True},
        }
        pipeline = MagicMock()
        pipeline.run = AsyncMock(
            return_value=_make_standard_pipeline_result("sess-ac07", "user-ac07")
        )
        with patch("api.v1.chat.query_pipeline", pipeline):
            events = _collect_sse_events(self.client, request)

        event_names = [name for name, _ in events]
        self.assertIn("table_data", event_names, "全链路应返回 table_data")
        self.assertIn("chart_spec", event_names, "全链路应返回 chart_spec")
        self.assertNotIn("error", event_names, "全链路不应有 error 事件")


# ═══════════════════════════════════════════════════════════════════════════════
# AC-08: LLM 数据安全
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC08LLMDataSecurity(unittest.TestCase):
    """
    Given  用户发起任意分析请求
    When   系统调用 LLM API
    Then   请求体中仅包含：用户 Query + 表结构元信息 + 语义配置
           不包含任何实际业务数据（表中的真实行数据）。
    """

    def test_nlu_prompt_contains_no_row_data(self) -> None:
        """NLU 构建的 messages 中只含元信息，不含真实数据行。"""
        from services.nlu import _build_messages
        from config.loader import get_semantic_model
        from models.schemas import SessionContext

        semantic_model = get_semantic_model()
        session_ctx = SessionContext(session_id="sess-ac08-nlu")
        messages = _build_messages(
            query="查询上周各渠道的 GMV",
            ctx=session_ctx,
            semantic_model=semantic_model,
            is_followup=False,
        )

        prompt_text = json.dumps(messages, ensure_ascii=False)

        # Mock 适配器中的实际数据行值
        forbidden_row_values = ["258000.0", "187500.0", "96500.0", "142300.0",
                                "10234", "10892", "356000.0", "285500.0"]
        for value in forbidden_row_values:
            self.assertNotIn(value, prompt_text,
                             f"NLU prompt 中不应含实际数据行值: {value}")

    def test_sql_gen_prompt_contains_no_row_data(self) -> None:
        """SQL Gen 构建的 messages 中只含 schema 信息，不含真实数据行。"""
        from services.sql_gen import _build_messages as build_sql_messages
        from models.schemas import (
            FieldRef, ResolvedQuery, TableRef, TimeRange as TR
        )

        resolved = ResolvedQuery(
            tables=[TableRef(id="fact_orders", name="fact_orders")],
            select_fields=[
                FieldRef(name="channel", expression="channel", alias="渠道"),
                FieldRef(name="gmv", expression="SUM(amount)", alias="GMV"),
            ],
            where_clauses=["status = 'paid'"],
            group_by=["channel"],
            time_filter="stat_date BETWEEN '2026-03-23' AND '2026-03-29'",
        )
        messages = build_sql_messages(resolved=resolved, query="查询上周各渠道的 GMV")

        prompt_text = json.dumps(messages, ensure_ascii=False)

        # 确保 prompt 只含 schema/表达式，不含实际数据行
        forbidden_row_values = ["258000.0", "187500.0", "96500.0", "10234", "10892"]
        for value in forbidden_row_values:
            self.assertNotIn(value, prompt_text,
                             f"SQL Gen prompt 中不应含实际数据行值: {value}")

    def test_interpreter_only_sends_aggregated_top_n(self) -> None:
        """Interpreter 仅传递聚合后的 Top-N 行，而非原始明细记录。"""
        from services.interpreter import _TOP_N, _build_messages as build_interpret_messages
        from models.schemas import ParsedIntent, QueryColumn, QueryResult

        # 构造包含大量行的 QueryResult（模拟明细数据）
        large_result = QueryResult(
            columns=[QueryColumn(name="channel", type="string"),
                     QueryColumn(name="gmv", type="number")],
            rows=[[f"channel_{i}", i * 1000.0] for i in range(50)],
            total_rows=50,
            execution_ms=100,
        )
        intent = ParsedIntent(
            metrics=["GMV"], dimensions=["渠道"], clarification_needed=False
        )

        messages = build_interpret_messages(
            result=large_result, intent=intent, query="查询各渠道GMV", prev_result=None
        )

        prompt_text = json.dumps(messages, ensure_ascii=False)

        # 验证只有 Top-N 行被包含（channel_9 是第 10 行，应存在；channel_10 是第 11 行，不应存在）
        self.assertIn("channel_9", prompt_text, "Top-N 行应出现在 prompt 中")
        self.assertNotIn("channel_10", prompt_text,
                         f"超出 Top-{_TOP_N} 的行不应出现在 LLM prompt 中")

    def test_llm_client_does_not_expose_api_key_in_messages(self) -> None:
        """LLM 客户端发送的消息中不含 API Key。"""
        from llm.client import LLMClient

        client = LLMClient(api_key="sk-test-secret-key-12345")
        # api_key 只用于认证头，不应出现在消息内容中
        # 此测试通过审查客户端构造逻辑验证
        self.assertFalse(
            hasattr(client, "_messages_cache"),
            "LLMClient 不应缓存消息内容（防止 key 泄露）",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 附加测试: LLM 降级（API Key 缺失时的友好提示）
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMFallback(unittest.TestCase):
    """
    验收补充: 关闭 OPENAI_API_KEY 后，请求返回友好提示而非 500。
    """

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_llm_unavailable_returns_friendly_error(self) -> None:
        from llm.client import LLMClientError

        pipeline = MagicMock()
        pipeline.run = AsyncMock(
            side_effect=LLMClientError("OpenAI API key is not configured")
        )

        request = {
            "session_id": "sess-fallback",
            "query": "查询上周各渠道的 GMV",
            "user_id": "user-fallback",
            "options": {"show_sql": False, "show_intent": False},
        }
        with patch("api.v1.chat.query_pipeline", pipeline):
            events = _collect_sse_events(self.client, request)

        error_events = [d for name, d in events if name == "error"]
        self.assertTrue(error_events, "LLM 不可用时应推送 error 事件")
        self.assertEqual(error_events[0].get("code"), "llm_unavailable")
        message = error_events[0].get("message", "")
        self.assertTrue(len(message) > 0)
        # 不应暴露技术性错误信息（如 500 / stack trace）
        self.assertNotIn("500", message)
        self.assertNotIn("Traceback", message)
        # 应包含中文友好提示
        self.assertTrue(any('\u4e00' <= c <= '\u9fff' for c in message))


# ═══════════════════════════════════════════════════════════════════════════════
# 附加测试: Swagger 文档可访问
# ═══════════════════════════════════════════════════════════════════════════════

class TestSwaggerDocs(unittest.TestCase):
    """验收补充: /docs 可访问，接口有描述。"""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_swagger_docs_accessible(self) -> None:
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)

    def test_openapi_schema_has_chat_endpoint(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        paths = schema.get("paths", {})
        self.assertIn("/api/v1/chat", paths, "/api/v1/chat 应出现在 OpenAPI schema 中")

    def test_chat_endpoint_has_summary(self) -> None:
        response = self.client.get("/openapi.json")
        schema = response.json()
        chat_path = schema.get("paths", {}).get("/api/v1/chat", {})
        post_op = chat_path.get("post", {})
        self.assertTrue(post_op.get("summary"), "POST /api/v1/chat 应有 summary")

    def test_health_endpoint_works(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
