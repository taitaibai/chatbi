from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import sqlglot
from sqlglot import exp

from config.settings import settings

if TYPE_CHECKING:
    from adapters.base import DataSourceAdapter

# 需要时间过滤的大表（全量扫描代价高）
_LARGE_TABLES = frozenset(
    {
        "fact_orders",
        "fact_refunds",
        "fact_user_daily",
        "fact_product_sales",
        "fact_page_views",
        "fact_channel_traffic",
    }
)

# 时间维度字段
_TIME_FIELDS = frozenset(
    {
        "order_date",
        "refund_date",
        "stat_date",
        "sale_date",
        "visit_date",
        "event_date",
        "date",
        "created_at",
        "updated_at",
    }
)

# 高基数维度 → 建议替换的低基数维度
_HIGH_CARDINALITY_SUGGESTIONS: dict[str, str] = {
    "city": "建议将城市改为省份（province）以降低维度基数",
    "user_id": "建议按渠道（channel）或城市（city）聚合，而非按用户粒度查询",
    "order_id": "建议增加聚合维度，而非按订单明细查询",
}


@dataclass
class CheckResult:
    allowed: bool
    level: Literal["ok", "warning", "blocked"]
    reason: str | None = None
    suggestion: str | None = None
    estimated_rows: int = 0


class ComplexityGuard:
    """查询复杂度守卫：根据预估代价决定是否拦截或给出警告。"""

    def __init__(self, threshold: int | None = None) -> None:
        self._threshold = threshold if threshold is not None else settings.complexity_threshold

    async def check(self, sql: str, adapter: "DataSourceAdapter") -> CheckResult:
        """
        调用 adapter.estimate_complexity(sql) 评估查询代价。

        Returns
        -------
        CheckResult
            level="blocked"  → allowed=False，调用方应拒绝执行
            level="warning"  → allowed=True，可继续但建议用户优化
            level="ok"       → allowed=True，无问题
        """
        estimate = await adapter.estimate_complexity(sql)
        estimated_rows = estimate.estimated_rows

        # 解析一次，传递给所有辅助方法复用
        try:
            tree: exp.Expression | None = sqlglot.parse_one(sql)
        except sqlglot.errors.ParseError:
            tree = None

        # 规则 1：预估扫描行数超过阈值 → 拦截
        if estimated_rows > self._threshold:
            suggestion = self._build_block_suggestion(tree)
            return CheckResult(
                allowed=False,
                level="blocked",
                reason=f"预估扫描行数 {estimated_rows:,} 超过阈值 {self._threshold:,}，查询被拦截",
                suggestion=suggestion,
                estimated_rows=estimated_rows,
            )

        # 规则 2：涉及大表但无时间过滤 → 警告
        warning = self._check_missing_time_filter(tree)
        if warning:
            return CheckResult(
                allowed=True,
                level="warning",
                reason=warning["reason"],
                suggestion=warning["suggestion"],
                estimated_rows=estimated_rows,
            )

        return CheckResult(
            allowed=True,
            level="ok",
            estimated_rows=estimated_rows,
        )

    # ------------------------------------------------------------------
    # 内部辅助方法（均接受已解析的 tree，避免重复 parse）
    # ------------------------------------------------------------------

    def _build_block_suggestion(self, tree: exp.Expression | None) -> str:
        suggestions: list[str] = []

        if not self._has_time_filter(tree):
            suggestions.append("建议增加 order_date 范围（如 WHERE order_date BETWEEN '...' AND '...'）")

        high_card = self._detect_high_cardinality(tree)
        if high_card:
            suggestions.append(high_card)

        if not suggestions:
            suggestions.append("建议缩小查询时间范围或增加过滤条件以降低扫描量")

        return "；".join(suggestions)

    def _check_missing_time_filter(self, tree: exp.Expression | None) -> dict[str, str] | None:
        """若查询涉及大表且没有时间过滤，返回警告信息字典，否则返回 None。"""
        if tree is None:
            return None

        tables_in_query = {
            node.name.lower()
            for node in tree.walk()
            if isinstance(node, exp.Table) and node.name
        }
        if not (tables_in_query & _LARGE_TABLES):
            return None

        if self._has_time_filter(tree):
            return None

        return {
            "reason": "查询涉及大表但未包含时间范围过滤，全表扫描可能影响性能",
            "suggestion": "建议增加 order_date 范围（如 WHERE order_date BETWEEN '...' AND '...'）",
        }

    def _has_time_filter(self, tree: exp.Expression | None) -> bool:
        """判断 WHERE 子句是否引用了时间维度字段。"""
        if tree is None:
            return False

        where = tree.args.get("where")
        if where is None:
            return False

        for node in where.walk():
            if isinstance(node, exp.Column) and node.name.lower() in _TIME_FIELDS:
                return True
        return False

    def _detect_high_cardinality(self, tree: exp.Expression | None) -> str | None:
        """检测 GROUP BY 中是否包含高基数维度，返回优化建议（若有）。"""
        if tree is None:
            return None

        group_by = tree.args.get("group")
        if group_by is None:
            return None

        for node in group_by.walk():
            if isinstance(node, exp.Column):
                suggestion = _HIGH_CARDINALITY_SUGGESTIONS.get(node.name.lower())
                if suggestion:
                    return suggestion
        return None


complexity_guard = ComplexityGuard()
