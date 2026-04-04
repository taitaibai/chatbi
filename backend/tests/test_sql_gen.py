from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import FieldRef, JoinClause, ResolvedQuery, TableRef
from config.settings import settings
from services.sql_gen import SQLGenService


def _resolved_query() -> ResolvedQuery:
    return ResolvedQuery(
        tables=[TableRef(id="fact_orders", name="fact_orders")],
        select_fields=[
            FieldRef(name="channel", expression="channel"),
            FieldRef(name="gmv", expression="SUM(amount)"),
        ],
        join_clauses=[
            JoinClause(
                join_type="left",
                table="fact_refunds",
                on="fact_orders.order_id = fact_refunds.order_id",
            )
        ],
        where_clauses=["status = 'paid'"],
        group_by=["channel"],
        time_filter="order_date BETWEEN '2025-03-01' AND '2025-03-31'",
    )


class SQLGenServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_generate_cleans_fenced_sql(self) -> None:
        from models.schemas import TokenUsage

        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.chat_with_usage = AsyncMock(
            return_value=(
                "```sql\n"
                "SELECT channel, SUM(amount) AS gmv\n"
                "FROM fact_orders\n"
                "GROUP BY channel;\n"
                "```",
                TokenUsage(),
            )
        )
        service = SQLGenService(llm_client=mock_client)

        sql = await service.generate(_resolved_query(), query="上月各渠道GMV")

        self.assertEqual(
            sql,
            "SELECT channel, SUM(amount) AS gmv\nFROM fact_orders\nGROUP BY channel",
        )
        mock_client.chat_with_usage.assert_awaited_once()
        _, kwargs = mock_client.chat_with_usage.await_args
        self.assertEqual(kwargs["model"], settings.llm_model)
        self.assertEqual(kwargs["temperature"], 0.0)

    async def test_generate_falls_back_to_compiled_sql_when_llm_not_configured(self) -> None:
        mock_client = MagicMock()
        mock_client.is_configured = False
        mock_client.chat = AsyncMock()
        service = SQLGenService(llm_client=mock_client)

        sql = await service.generate(_resolved_query(), query="上月各渠道GMV")

        self.assertIn("SELECT channel, SUM(amount) AS gmv", sql)
        self.assertIn("FROM fact_orders", sql)
        self.assertIn("LEFT JOIN fact_refunds", sql)
        self.assertIn("status = 'paid'", sql)
        self.assertIn("order_date BETWEEN '2025-03-01' AND '2025-03-31'", sql)
        self.assertIn("GROUP BY channel", sql)
        mock_client.chat.assert_not_called()

    async def test_non_aggregate_query_adds_limit_in_fallback(self) -> None:
        mock_client = MagicMock()
        mock_client.is_configured = False
        service = SQLGenService(llm_client=mock_client)

        resolved = ResolvedQuery(
            tables=[TableRef(id="dim_users", name="dim_users")],
            select_fields=[
                FieldRef(name="user_id", expression="user_id"),
                FieldRef(name="city", expression="city"),
            ],
        )

        sql = await service.generate(resolved, query="查看用户明细")

        self.assertIn("SELECT user_id, city", sql)
        self.assertIn("FROM dim_users", sql)
        self.assertTrue(sql.endswith("LIMIT 200"))

    async def test_missing_tables_raises(self) -> None:
        mock_client = MagicMock()
        mock_client.is_configured = False
        service = SQLGenService(llm_client=mock_client)

        with self.assertRaises(ValueError):
            await service.generate(ResolvedQuery(select_fields=[FieldRef(name="gmv", expression="SUM(amount)")]))


if __name__ == "__main__":
    unittest.main()
