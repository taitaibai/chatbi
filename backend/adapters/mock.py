from __future__ import annotations

import time

from adapters.base import DataSourceAdapter
from models import ComplexityEstimate, QueryColumn, QueryResult


class MockAdapter(DataSourceAdapter):
    def __init__(self) -> None:
        self._datasets = {
            "sales": {
                "columns": [
                    QueryColumn(name="channel", type="string"),
                    QueryColumn(name="gmv", type="number", format="currency"),
                    QueryColumn(name="order_count", type="number", format="number"),
                ],
                "rows": [
                    ["App", 258000.0, 320],
                    ["Web", 187500.0, 245],
                    ["H5", 96500.0, 158],
                    ["小程序", 142300.0, 211],
                ],
            },
            "user": {
                "columns": [
                    QueryColumn(name="stat_date", type="date"),
                    QueryColumn(name="dau", type="number", format="number"),
                    QueryColumn(name="new_users", type="number", format="number"),
                ],
                "rows": [
                    ["2025-03-24", 10234, 580],
                    ["2025-03-25", 10892, 604],
                    ["2025-03-26", 11015, 598],
                    ["2025-03-27", 11201, 621],
                ],
            },
            "product": {
                "columns": [
                    QueryColumn(name="category_name", type="string"),
                    QueryColumn(name="sales_amount", type="number", format="currency"),
                    QueryColumn(name="sales_volume", type="number", format="number"),
                ],
                "rows": [
                    ["3C", 356000.0, 1780],
                    ["服装", 285500.0, 2420],
                    ["食品", 165200.0, 3910],
                ],
            },
            "traffic": {
                "columns": [
                    QueryColumn(name="channel", type="string"),
                    QueryColumn(name="uv", type="number", format="number"),
                    QueryColumn(name="pay_uv", type="number", format="number"),
                    QueryColumn(name="roi", type="number", format="number"),
                ],
                "rows": [
                    ["App", 45200, 5220, 4.3],
                    ["Web", 28300, 2710, 3.1],
                    ["小程序", 31800, 3920, 4.8],
                ],
            },
            "default": {
                "columns": [
                    QueryColumn(name="label", type="string"),
                    QueryColumn(name="value", type="number", format="number"),
                ],
                "rows": [["mock_result", 1]],
            },
        }

    async def execute(self, sql: str, params: dict | None = None) -> QueryResult:
        started = time.perf_counter()
        dataset = self._select_dataset(sql)
        execution_ms = max(int((time.perf_counter() - started) * 1000), 5)
        return QueryResult(
            columns=dataset["columns"],
            rows=dataset["rows"],
            total_rows=len(dataset["rows"]),
            execution_ms=execution_ms,
        )

    async def estimate_complexity(self, sql: str) -> ComplexityEstimate:
        domain = self._infer_domain(sql)
        estimated_rows = {
            "sales": 120_000,
            "user": 80_000,
            "product": 60_000,
            "traffic": 90_000,
            "default": 10_000,
        }[domain]
        return ComplexityEstimate(
            estimated_rows=estimated_rows,
            estimated_cost=max(1, estimated_rows // 10_000),
            execution_ms=20,
        )

    async def health_check(self) -> bool:
        return True

    def _select_dataset(self, sql: str) -> dict[str, list[QueryColumn] | list[list]]:
        return self._datasets[self._infer_domain(sql)]

    def _infer_domain(self, sql: str) -> str:
        lowered = sql.lower()
        if "refund" in lowered or "fact_orders" in lowered or "gmv" in lowered:
            return "sales"
        if "user" in lowered or "dau" in lowered:
            return "user"
        if "product" in lowered or "stock" in lowered or "sales_volume" in lowered:
            return "product"
        if "traffic" in lowered or "uv" in lowered or "pv" in lowered:
            return "traffic"
        return "default"
