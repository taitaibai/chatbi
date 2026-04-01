"""Unit tests for T-11: SemanticService.

Covers:
  1. Single metric resolution
  2. Multi-metric cross-table resolution (auto JOIN via YAML)
  3. Metric not found → SemanticNotFoundError with available_metrics
  4. Time range parsing (yesterday / last_7d / last_30d / last_week / last_month / custom)
  5. Dimension resolution + GROUP BY
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.schemas import FilterCondition, ParsedIntent, TimeRange
from services.semantic import SemanticNotFoundError, SemanticService

service = SemanticService()


# ---------------------------------------------------------------------------
# 1. Single metric resolution
# ---------------------------------------------------------------------------


def test_single_metric_gmv():
    intent = ParsedIntent(metrics=["GMV"])
    result = service.resolve(intent)

    assert len(result.tables) == 1
    assert result.tables[0].id == "fact_orders"

    assert len(result.select_fields) == 1
    sf = result.select_fields[0]
    assert sf.name == "gmv"
    assert "SUM(amount)" in sf.expression
    assert sf.format == "currency"

    # Metric filter carried over
    assert "status = 'paid'" in result.where_clauses


def test_single_metric_by_alias():
    intent = ParsedIntent(metrics=["订单量"])
    result = service.resolve(intent)

    assert result.select_fields[0].name == "order_count"


def test_single_metric_dau():
    intent = ParsedIntent(metrics=["DAU"])
    result = service.resolve(intent)

    assert result.tables[0].id == "fact_user_daily"
    assert result.select_fields[0].name == "dau"


# ---------------------------------------------------------------------------
# 2. Multi-metric cross-table resolution via YAML-defined JOIN
# ---------------------------------------------------------------------------


def test_refund_rate_join_inferred():
    """refund_rate has an explicit LEFT JOIN in YAML → JoinClause must be present."""
    intent = ParsedIntent(metrics=["退款率"])
    result = service.resolve(intent)

    assert len(result.join_clauses) == 1
    jc = result.join_clauses[0]
    assert jc.join_type == "left"
    assert "fact_refunds" in jc.table
    assert "order_id" in jc.on


def test_multi_metric_same_table():
    """GMV + 订单量 both from fact_orders → only one table, no JOINs."""
    intent = ParsedIntent(metrics=["GMV", "订单量"])
    result = service.resolve(intent)

    assert len(result.tables) == 1
    assert result.tables[0].id == "fact_orders"
    assert len(result.join_clauses) == 0
    assert len(result.select_fields) == 2
    names = {sf.name for sf in result.select_fields}
    assert names == {"gmv", "order_count"}


def test_multi_metric_with_join():
    """GMV + 退款率 → fact_orders primary, LEFT JOIN fact_refunds."""
    intent = ParsedIntent(metrics=["GMV", "退款率"])
    result = service.resolve(intent)

    table_ids = [t.id for t in result.tables]
    assert "fact_orders" in table_ids
    assert len(result.join_clauses) == 1
    assert result.join_clauses[0].join_type == "left"


# ---------------------------------------------------------------------------
# 3. Metric not found → SemanticNotFoundError
# ---------------------------------------------------------------------------


def test_metric_not_found_raises():
    intent = ParsedIntent(metrics=["不存在的指标XYZ"])
    with pytest.raises(SemanticNotFoundError) as exc_info:
        service.resolve(intent)

    err = exc_info.value
    assert len(err.available_metrics) > 0
    # available_metrics should contain known metric names
    assert any(m in err.available_metrics for m in ["GMV", "DAU", "PV"])


def test_metric_not_found_message():
    intent = ParsedIntent(metrics=["活跃度"])
    with pytest.raises(SemanticNotFoundError) as exc_info:
        service.resolve(intent)

    assert "活跃度" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Time range parsing
# ---------------------------------------------------------------------------


def _parse_dates_from_filter(time_filter: str) -> tuple[date, date]:
    """Extract start and end date from "field BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'"."""
    m = re.search(r"'(\d{4}-\d{2}-\d{2})' AND '(\d{4}-\d{2}-\d{2})'", time_filter)
    assert m is not None, f"Unexpected time_filter format: {time_filter}"
    return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))


def _intent_with_time(type_: str, start: str | None = None, end: str | None = None) -> ParsedIntent:
    return ParsedIntent(
        metrics=["GMV"],
        time_range=TimeRange(type=type_, start=start, end=end),
    )


def test_time_yesterday():
    result = service.resolve(_intent_with_time("yesterday"))
    assert result.time_filter is not None
    start, end = _parse_dates_from_filter(result.time_filter)
    expected = date.today() - timedelta(days=1)
    assert start == expected
    assert end == expected


def test_time_last_7d():
    result = service.resolve(_intent_with_time("last_7d"))
    assert result.time_filter is not None
    start, end = _parse_dates_from_filter(result.time_filter)
    today = date.today()
    assert start == today - timedelta(days=7)
    assert end == today


def test_time_last_30d():
    result = service.resolve(_intent_with_time("last_30d"))
    assert result.time_filter is not None
    start, end = _parse_dates_from_filter(result.time_filter)
    today = date.today()
    assert start == today - timedelta(days=30)
    assert end == today


def test_time_last_week():
    result = service.resolve(_intent_with_time("last_week"))
    assert result.time_filter is not None
    start, end = _parse_dates_from_filter(result.time_filter)
    today = date.today()
    # start must be a Monday
    assert start.weekday() == 0
    # end must be a Sunday (start + 6)
    assert end == start + timedelta(days=6)
    # the week must be fully in the past
    assert end < today


def test_time_last_month():
    result = service.resolve(_intent_with_time("last_month"))
    assert result.time_filter is not None
    start, end = _parse_dates_from_filter(result.time_filter)
    # start is the 1st of a month
    assert start.day == 1
    # end is the last day of the same month
    assert end.month == start.month
    assert end.year == start.year
    # the month is before current month
    today = date.today()
    assert end < today.replace(day=1)


def test_time_custom():
    result = service.resolve(_intent_with_time("custom", start="2024-01-01", end="2024-01-31"))
    assert result.time_filter is not None
    start, end = _parse_dates_from_filter(result.time_filter)
    assert start == date(2024, 1, 1)
    assert end == date(2024, 1, 31)


def test_time_filter_uses_table_time_field():
    """The time filter should use order_date for fact_orders metrics."""
    result = service.resolve(_intent_with_time("last_7d"))
    assert result.time_filter is not None
    assert result.time_filter.startswith("order_date")


def test_no_time_range():
    intent = ParsedIntent(metrics=["GMV"])
    result = service.resolve(intent)
    assert result.time_filter is None


# ---------------------------------------------------------------------------
# 5. Dimension resolution + GROUP BY
# ---------------------------------------------------------------------------


def test_dimension_channel():
    intent = ParsedIntent(metrics=["GMV"], dimensions=["渠道"])
    result = service.resolve(intent)

    assert "channel" in result.group_by
    dim_fields = [sf.expression for sf in result.select_fields]
    assert "channel" in dim_fields


def test_dimension_city():
    intent = ParsedIntent(metrics=["订单量"], dimensions=["城市"])
    result = service.resolve(intent)

    assert "city" in result.group_by


def test_multiple_dimensions():
    intent = ParsedIntent(metrics=["GMV"], dimensions=["渠道", "城市"])
    result = service.resolve(intent)

    assert "channel" in result.group_by
    assert "city" in result.group_by
    assert len(result.group_by) == 2


# ---------------------------------------------------------------------------
# 6. Intent filter resolution
# ---------------------------------------------------------------------------


def test_intent_filter_eq():
    fc = FilterCondition(field="status", op="eq", value="paid")
    intent = ParsedIntent(metrics=["GMV"], filters=[fc])
    result = service.resolve(intent)

    assert "status = 'paid'" in result.where_clauses


def test_intent_filter_in():
    fc = FilterCondition(field="channel", op="in", value=["ios", "android"])
    intent = ParsedIntent(metrics=["GMV"], filters=[fc])
    result = service.resolve(intent)

    combined = " ".join(result.where_clauses)
    assert "channel IN" in combined
    assert "'ios'" in combined


# ---------------------------------------------------------------------------
# 7. get_available_metrics
# ---------------------------------------------------------------------------


def test_get_available_metrics_grouped():
    metrics = service.get_available_metrics()
    assert "销售域" in metrics
    assert "用户域" in metrics
    assert "商品域" in metrics
    assert "流量域" in metrics

    gmv_entry = next((m for m in metrics["销售域"] if m["id"] == "gmv"), None)
    assert gmv_entry is not None
    assert gmv_entry["name"] == "GMV"
