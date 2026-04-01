from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import ComplexityEstimate
from services.complexity import CheckResult, ComplexityGuard


def _mock_adapter(estimated_rows: int) -> MagicMock:
    adapter = MagicMock()
    adapter.estimate_complexity = AsyncMock(
        return_value=ComplexityEstimate(
            estimated_rows=estimated_rows,
            estimated_cost=max(1, estimated_rows // 10_000),
            execution_ms=5,
        )
    )
    return adapter


class ComplexityGuardTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # 固定阈值，不依赖环境变量
        self.guard = ComplexityGuard(threshold=100_000_000)

    # ------------------------------------------------------------------
    # 场景 1：低代价查询通过
    # ------------------------------------------------------------------
    async def test_low_cost_passes(self) -> None:
        adapter = _mock_adapter(120_000)
        sql = (
            "SELECT channel, SUM(amount) AS gmv "
            "FROM fact_orders "
            "WHERE status = 'paid' AND order_date BETWEEN '2025-03-01' AND '2025-03-31' "
            "GROUP BY channel"
        )
        result = await self.guard.check(sql, adapter)

        self.assertIsInstance(result, CheckResult)
        self.assertTrue(result.allowed)
        self.assertEqual(result.level, "ok")
        self.assertIsNone(result.reason)
        self.assertEqual(result.estimated_rows, 120_000)

    # ------------------------------------------------------------------
    # 场景 2：超过阈值时拦截
    # ------------------------------------------------------------------
    async def test_exceeds_threshold_blocked(self) -> None:
        adapter = _mock_adapter(200_000_000)
        sql = (
            "SELECT channel, SUM(amount) AS gmv "
            "FROM fact_orders "
            "WHERE status = 'paid' "
            "GROUP BY channel"
        )
        result = await self.guard.check(sql, adapter)

        self.assertFalse(result.allowed)
        self.assertEqual(result.level, "blocked")
        self.assertIsNotNone(result.reason)
        self.assertIn("200,000,000", result.reason)
        self.assertEqual(result.estimated_rows, 200_000_000)

    # ------------------------------------------------------------------
    # 场景 3：大表无时间过滤 → 警告（allowed=True）
    # ------------------------------------------------------------------
    async def test_no_time_filter_warning(self) -> None:
        adapter = _mock_adapter(80_000)
        sql = (
            "SELECT channel, SUM(amount) AS gmv "
            "FROM fact_orders "
            "WHERE status = 'paid' "
            "GROUP BY channel"
        )
        result = await self.guard.check(sql, adapter)

        self.assertTrue(result.allowed)
        self.assertEqual(result.level, "warning")
        self.assertIsNotNone(result.suggestion)
        self.assertIn("order_date", result.suggestion)

    # ------------------------------------------------------------------
    # 场景 4：Mock 适配器不触发拦截
    # ------------------------------------------------------------------
    async def test_mock_adapter_never_blocks(self) -> None:
        from adapters.mock import MockAdapter

        adapter = MockAdapter()
        sqls = [
            "SELECT channel, SUM(amount) AS gmv FROM fact_orders GROUP BY channel",
            "SELECT stat_date, dau FROM fact_user_daily GROUP BY stat_date",
            "SELECT category_name, SUM(sales_amount) AS rev FROM fact_product_sales GROUP BY category_name",
            "SELECT channel, uv FROM fact_channel_traffic GROUP BY channel",
        ]
        for sql in sqls:
            result = await self.guard.check(sql, adapter)
            self.assertNotEqual(
                result.level,
                "blocked",
                msg=f"Mock adapter should never block, but got blocked for: {sql}",
            )

    # ------------------------------------------------------------------
    # 场景 5：拦截时给出高基数维度建议
    # ------------------------------------------------------------------
    async def test_high_cardinality_suggestion_in_block(self) -> None:
        adapter = _mock_adapter(150_000_000)
        sql = (
            "SELECT city, SUM(amount) AS gmv "
            "FROM fact_orders "
            "GROUP BY city"
        )
        result = await self.guard.check(sql, adapter)

        self.assertFalse(result.allowed)
        self.assertEqual(result.level, "blocked")
        self.assertIsNotNone(result.suggestion)
        # 建议中含有"省份"
        self.assertIn("省份", result.suggestion)

    # ------------------------------------------------------------------
    # 场景 6：有时间过滤的查询（小表）不触发警告
    # ------------------------------------------------------------------
    async def test_time_filter_present_no_warning(self) -> None:
        adapter = _mock_adapter(5_000)
        sql = (
            "SELECT stat_date, SUM(dau) AS total_dau "
            "FROM fact_user_daily "
            "WHERE stat_date BETWEEN '2025-03-01' AND '2025-03-31' "
            "GROUP BY stat_date"
        )
        result = await self.guard.check(sql, adapter)

        self.assertTrue(result.allowed)
        self.assertEqual(result.level, "ok")

    # ------------------------------------------------------------------
    # 场景 7：非大表查询不触发警告（即使无时间过滤）
    # ------------------------------------------------------------------
    async def test_non_large_table_no_warning(self) -> None:
        adapter = _mock_adapter(500)
        sql = "SELECT id, name FROM dim_users GROUP BY id, name"
        result = await self.guard.check(sql, adapter)

        # dim_users 不在大表列表中，不应触发警告
        self.assertTrue(result.allowed)
        self.assertEqual(result.level, "ok")


if __name__ == "__main__":
    unittest.main()
