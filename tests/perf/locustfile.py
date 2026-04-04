"""T-20 性能压测: ChatBI 并发负载测试

验收指标：50 并发下，普通查询 P95 ≤ 8s

运行方式（需先安装 locust）：
    pip install locust
    cd /path/to/chatbi
    locust -f tests/perf/locustfile.py --host http://localhost:8000 \
           --users 50 --spawn-rate 5 --run-time 120s --headless \
           --html tests/perf/report.html

或交互式 Web UI：
    locust -f tests/perf/locustfile.py --host http://localhost:8000
    # 访问 http://localhost:8089

注意：
- 后端服务需在运行中（docker compose up 或 uvicorn）
- OPENAI_API_KEY 需正确配置
- 压测结果关注 /api/v1/chat 的 P95 响应时间（应 ≤ 8000ms）
"""
from __future__ import annotations

import json
import uuid

from locust import HttpUser, between, events, task
from locust.runners import MasterRunner


# ── 测试数据 ─────────────────────────────────────────────────────────────────

_QUERIES = [
    "查询上周各渠道的 GMV",
    "上周各渠道订单量是多少",
    "最近 7 天的 DAU 趋势",
    "本月各商品类目的销售额",
    "上月各渠道的 ROI",
    "上周退款率最高的渠道",
    "最近 30 天新增用户趋势",
]

_FOLLOWUP_QUERIES = [
    "那各渠道的订单量呢？",
    "按城市细分呢？",
    "和上个月比如何？",
]


# ── 普通查询用户 ──────────────────────────────────────────────────────────────

class ChatBIUser(HttpUser):
    """模拟普通用户: 发起标准查询，每次请求间隔 1~3 秒。"""

    wait_time = between(1, 3)
    host = "http://localhost:8000"

    def on_start(self) -> None:
        self.session_id = str(uuid.uuid4())
        self.query_index = 0

    @task(8)
    def standard_query(self) -> None:
        """AC-01 场景: 标准分析查询，P95 ≤ 8s。"""
        query = _QUERIES[self.query_index % len(_QUERIES)]
        self.query_index += 1

        payload = {
            "session_id": self.session_id,
            "query": query,
            "user_id": f"perf-user-{self.session_id[:8]}",
            "options": {"show_sql": True, "show_intent": True},
        }

        with self.client.post(
            "/api/v1/chat",
            json=payload,
            headers={"Accept": "text/event-stream"},
            stream=True,
            catch_response=True,
            name="/api/v1/chat [standard]",
        ) as response:
            if response.status_code != 200:
                response.failure(f"非预期状态码: {response.status_code}")
                return

            # 消费完整 SSE 流并验证关键事件
            got_done = False
            got_error = False
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                    if event_type == "done":
                        got_done = True
                    elif event_type == "error":
                        got_error = True

            if not got_done:
                response.failure("SSE 流未收到 done 事件")
            elif got_error:
                # error 事件不一定代表失败（如 clarification），仅记录
                response.success()
            else:
                response.success()

    @task(2)
    def multi_turn_query(self) -> None:
        """AC-03 场景: 多轮对话，追问。"""
        if self.query_index == 0:
            return  # 首次必须先有第一轮
        followup = _FOLLOWUP_QUERIES[self.query_index % len(_FOLLOWUP_QUERIES)]
        payload = {
            "session_id": self.session_id,
            "query": followup,
            "user_id": f"perf-user-{self.session_id[:8]}",
            "options": {"show_sql": False, "show_intent": False},
        }
        with self.client.post(
            "/api/v1/chat",
            json=payload,
            headers={"Accept": "text/event-stream"},
            stream=True,
            catch_response=True,
            name="/api/v1/chat [followup]",
        ) as response:
            if response.status_code != 200:
                response.failure(f"非预期状态码: {response.status_code}")
                return
            # 消费流
            for _ in response.iter_lines():
                pass
            response.success()

    @task(1)
    def health_check(self) -> None:
        """健康检查：验证服务可用性。"""
        self.client.get("/health", name="/health")

    @task(1)
    def get_semantic_metrics(self) -> None:
        """获取可查询指标列表（AC-06 相关）。"""
        self.client.get("/api/v1/semantic/metrics", name="/api/v1/semantic/metrics")


# ── 高并发压测用户（轻量版，不解析 SSE）────────────────────────────────────────

class HighConcurrencyUser(HttpUser):
    """纯并发压力用户: 快速发送请求，仅验证连接成功。

    用于测试 LLM Semaphore 并发限流是否生效。
    """

    wait_time = between(0.5, 1.5)
    weight = 3  # 相对权重（比 ChatBIUser 少一些）

    def on_start(self) -> None:
        self.session_id = str(uuid.uuid4())

    @task
    def fire_and_forget(self) -> None:
        payload = {
            "session_id": self.session_id,
            "query": "查询上周各渠道的 GMV",
            "user_id": f"hc-user-{self.session_id[:8]}",
            "options": {"show_sql": False, "show_intent": False},
        }
        with self.client.post(
            "/api/v1/chat",
            json=payload,
            headers={"Accept": "text/event-stream"},
            stream=True,
            catch_response=True,
            name="/api/v1/chat [high-concurrency]",
        ) as response:
            if response.status_code == 429:
                # 限流是预期行为，不算失败
                response.success()
            elif response.status_code == 200:
                # 消费流
                for _ in response.iter_lines():
                    pass
                response.success()
            else:
                response.failure(f"非预期状态码: {response.status_code}")


# ── 事件钩子：输出关键性能指标 ────────────────────────────────────────────────

@events.quitting.add_listener
def on_quitting(environment, **kwargs) -> None:  # type: ignore[type-arg]
    """压测结束时打印 P95 响应时间汇总。"""
    stats = environment.stats
    chat_stats = stats.get("/api/v1/chat [standard]", "POST")
    if chat_stats and hasattr(chat_stats, "get_response_time_percentile"):
        p95 = chat_stats.get_response_time_percentile(0.95)
        threshold = 8000  # ms
        status = "PASS" if p95 <= threshold else "FAIL"
        print(f"\n{'='*60}")
        print(f"AC-01 性能验收: P95 响应时间 = {p95:.0f}ms (阈值 {threshold}ms) [{status}]")
        print(f"{'='*60}\n")
