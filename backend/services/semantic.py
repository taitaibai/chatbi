from __future__ import annotations

import re
from datetime import date, timedelta

from config.loader import get_semantic_model
from models.schemas import (
    FieldRef,
    FilterCondition,
    JoinClause,
    ParsedIntent,
    ResolvedQuery,
    SemanticMetric,
    SemanticModel,
    SemanticTable,
    TableRef,
    TimeRange,
)


class SemanticNotFoundError(ValueError):
    """Raised when a requested metric or dimension cannot be resolved."""

    def __init__(self, message: str, available_metrics: list[str] | None = None) -> None:
        super().__init__(message)
        self.available_metrics: list[str] = available_metrics or []


class SemanticService:
    """Maps ParsedIntent (business terms) → ResolvedQuery (physical tables/fields/SQL)."""

    def __init__(self) -> None:
        # Index cache: rebuilt only when the semantic model object changes (hot-reload safe)
        self._cached_model_id: int | None = None
        self._metric_index: dict[str, SemanticMetric] = {}
        self._dimension_index: dict[str, tuple[str, str]] = {}

    def _get_indexes(
        self, model: SemanticModel
    ) -> tuple[dict[str, SemanticMetric], dict[str, tuple[str, str]]]:
        """Return (metric_index, dimension_index), rebuilding only on model identity change."""
        if id(model) != self._cached_model_id:
            self._metric_index = _build_metric_index(model)
            self._dimension_index = _build_dimension_index(model)
            self._cached_model_id = id(model)
        return self._metric_index, self._dimension_index

    def resolve(self, intent: ParsedIntent) -> ResolvedQuery:
        model = get_semantic_model()
        metric_index, dimension_index = self._get_indexes(model)

        # --- Resolve metrics ---
        resolved_metrics: list[SemanticMetric] = []
        for raw in intent.metrics:
            key = raw.strip().lower()
            if key not in metric_index:
                available = _list_metric_names(model)
                raise SemanticNotFoundError(
                    f"指标 '{raw}' 未找到，可查询: {', '.join(available[:8])}",
                    available_metrics=available,
                )
            resolved_metrics.append(metric_index[key])

        # --- Collect tables, JOINs, WHERE, SELECT ---
        tables_needed: dict[str, str] = {}  # table_id → physical_name
        join_clauses: list[JoinClause] = []
        where_clauses: list[str] = []
        select_fields: list[FieldRef] = []

        primary_table_id: str = ""

        for idx, metric in enumerate(resolved_metrics):
            base_id = metric.base_table
            base_table = _find_table(model, base_id)
            if base_table and base_id not in tables_needed:
                tables_needed[base_id] = base_table.name

            if idx == 0:
                primary_table_id = base_id

            # Metric-defined JOINs (e.g. refund_rate needs LEFT JOIN fact_refunds)
            for jc in metric.joins:
                join_table = _find_table(model, jc.table)
                join_physical = join_table.name if join_table else jc.table
                # Avoid duplicate join on same table
                already = any(j.table == join_physical for j in join_clauses)
                if not already:
                    join_clauses.append(
                        JoinClause(
                            join_type=jc.join_type,
                            table=join_physical,
                            alias=jc.alias,
                            on=jc.on,
                        )
                    )
                if jc.table not in tables_needed:
                    tables_needed[jc.table] = join_physical

            # Metric-defined WHERE filters
            for f in metric.filters:
                if f not in where_clauses:
                    where_clauses.append(f)

            select_fields.append(
                FieldRef(
                    name=metric.id,
                    expression=metric.expression,
                    alias=metric.name,
                    format=metric.format,
                )
            )

        # --- Resolve dimensions → GROUP BY + prepend to SELECT ---
        group_by: list[str] = []
        for raw_dim in intent.dimensions:
            key = raw_dim.strip().lower()
            if key in dimension_index:
                field = dimension_index[key][1]
                if field not in group_by:
                    group_by.append(field)
                    select_fields.insert(
                        len(group_by) - 1,
                        FieldRef(name=field, expression=field, alias=raw_dim),
                    )

        # --- Resolve intent filters → WHERE ---
        for fc in intent.filters:
            clause = _build_filter_clause(fc)
            if clause and clause not in where_clauses:
                where_clauses.append(clause)

        # --- Build TableRef list (primary table first) ---
        table_refs: list[TableRef] = []
        if primary_table_id and primary_table_id in tables_needed:
            table_refs.append(
                TableRef(id=primary_table_id, name=tables_needed[primary_table_id])
            )
        for tid, tname in tables_needed.items():
            if tid == primary_table_id:
                continue
            # Skip tables already covered by a JOIN clause
            if any(jc.table == tname for jc in join_clauses):
                continue
            table_refs.append(TableRef(id=tid, name=tname))

        # --- Time filter ---
        time_filter: str | None = None
        if intent.time_range:
            primary_table = _find_table(model, primary_table_id) if primary_table_id else None
            time_filter = _resolve_time_filter(intent.time_range, primary_table)

        return ResolvedQuery(
            tables=table_refs,
            select_fields=select_fields,
            join_clauses=join_clauses,
            where_clauses=where_clauses,
            group_by=group_by,
            time_filter=time_filter,
        )

    def get_available_metrics(self) -> dict[str, list[dict[str, str]]]:
        """Return queryable metrics grouped by domain name."""
        model = get_semantic_model()
        return {
            domain.name: [
                {"id": m.id, "name": m.name, "description": m.description}
                for m in domain.metrics
            ]
            for domain in model.domains
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_metric_index(model: SemanticModel) -> dict[str, SemanticMetric]:
    index: dict[str, SemanticMetric] = {}
    for domain in model.domains:
        for metric in domain.metrics:
            index[metric.id.lower()] = metric
            index[metric.name.lower()] = metric
            for alias in metric.aliases:
                index[alias.lower()] = metric
    return index


def _build_dimension_index(model: SemanticModel) -> dict[str, tuple[str, str]]:
    """alias_lower → (table_id, field_name)"""
    index: dict[str, tuple[str, str]] = {}
    for domain in model.domains:
        for table in domain.tables:
            for dim in table.dimensions:
                index[dim.id.lower()] = (table.id, dim.field)
                index[dim.name.lower()] = (table.id, dim.field)
                for alias in dim.aliases:
                    index[alias.lower()] = (table.id, dim.field)
    return index


def _find_table(model: SemanticModel, table_id: str) -> SemanticTable | None:
    for domain in model.domains:
        for table in domain.tables:
            if table.id == table_id:
                return table
    return None


def _list_metric_names(model: SemanticModel) -> list[str]:
    return [m.name for domain in model.domains for m in domain.metrics]


# Regex that only permits safe SQL identifiers (table.column or plain column).
# Prevents injection via field name (e.g. "x OR 1=1 --").
_SAFE_FIELD_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}(\.[a-zA-Z][a-zA-Z0-9_]{0,63})?$")


def _escape_str(value: str) -> str:
    """ANSI SQL-compliant single-quote escape: ' → ''."""
    return value.replace("'", "''")


def _build_filter_clause(fc: FilterCondition) -> str | None:
    # 1. Validate field name against safe-identifier pattern (prevents field-name injection)
    if not _SAFE_FIELD_RE.match(fc.field):
        return None

    op_map = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}

    # 2. Handle NULL value comparisons
    if fc.value is None:
        if fc.op == "eq":
            return f"{fc.field} IS NULL"
        if fc.op == "ne":
            return f"{fc.field} IS NOT NULL"
        return None

    if fc.op in op_map:
        if isinstance(fc.value, str):
            value_sql = f"'{_escape_str(fc.value)}'"
        else:
            value_sql = str(fc.value)
        return f"{fc.field} {op_map[fc.op]} {value_sql}"

    if fc.op == "in":
        items: list[str]
        if isinstance(fc.value, list):
            items = [
                f"'{_escape_str(v)}'" if isinstance(v, str) else str(v)
                for v in fc.value
                if v is not None
            ]
        else:
            items = [f"'{_escape_str(fc.value)}'"]
        if not items:
            return None
        return f"{fc.field} IN ({', '.join(items)})"

    if fc.op == "like":
        if isinstance(fc.value, str):
            return f"{fc.field} LIKE '{_escape_str(fc.value)}'"
        return None

    return None


def _resolve_time_filter(
    time_range: TimeRange,
    primary_table: SemanticTable | None,
) -> str:
    today = date.today()

    if time_range.type == "yesterday":
        d = today - timedelta(days=1)
        start = end = d.isoformat()

    elif time_range.type == "last_7d":
        start = (today - timedelta(days=7)).isoformat()
        end = today.isoformat()

    elif time_range.type == "last_30d":
        start = (today - timedelta(days=30)).isoformat()
        end = today.isoformat()

    elif time_range.type == "last_week":
        # Last complete calendar week Mon–Sun
        days_since_monday = today.weekday()  # Monday=0, Sunday=6
        last_monday = today - timedelta(days=days_since_monday + 7)
        last_sunday = last_monday + timedelta(days=6)
        start = last_monday.isoformat()
        end = last_sunday.isoformat()

    elif time_range.type == "last_month":
        first_of_this_month = today.replace(day=1)
        last_day_of_prev = first_of_this_month - timedelta(days=1)
        start = last_day_of_prev.replace(day=1).isoformat()
        end = last_day_of_prev.isoformat()

    elif time_range.type == "custom":
        start = time_range.start or today.isoformat()
        end = time_range.end or today.isoformat()

    else:
        start = time_range.start or today.isoformat()
        end = time_range.end or today.isoformat()

    time_field = (primary_table.time_field or "stat_date") if primary_table else "stat_date"
    return f"{time_field} BETWEEN '{start}' AND '{end}'"


# Module-level singleton
semantic_service = SemanticService()
