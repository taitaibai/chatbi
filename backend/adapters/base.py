from __future__ import annotations

from abc import ABC, abstractmethod

from models import ComplexityEstimate, QueryResult


class DataSourceAdapter(ABC):
    @abstractmethod
    async def execute(self, sql: str, params: dict | None = None) -> QueryResult:
        """执行 SQL，返回结构化结果。"""

    @abstractmethod
    async def estimate_complexity(self, sql: str) -> ComplexityEstimate:
        """预估查询复杂度。"""

    @abstractmethod
    async def health_check(self) -> bool:
        """检查数据源可用性。"""
