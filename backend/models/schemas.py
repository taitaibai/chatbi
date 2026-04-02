from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FilterCondition(BaseModel):
    field: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "like"] = "eq"
    value: Any


class TimeRange(BaseModel):
    type: str
    start: str | None = None
    end: str | None = None


class ParsedIntent(BaseModel):
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_range: TimeRange | None = None
    filters: list[FilterCondition] = Field(default_factory=list)
    is_followup: bool = False
    clarification_needed: bool = False
    clarification_question: str | None = None


class TableRef(BaseModel):
    id: str
    name: str
    alias: str | None = None


class FieldRef(BaseModel):
    name: str
    expression: str
    alias: str | None = None
    format: str | None = None


class JoinClause(BaseModel):
    join_type: Literal["inner", "left", "right"] = "inner"
    table: str
    alias: str | None = None
    on: str


class QueryColumn(BaseModel):
    name: str
    type: Literal["string", "number", "date"] = "string"
    format: str | None = None


class ResolvedQuery(BaseModel):
    tables: list[TableRef] = Field(default_factory=list)
    select_fields: list[FieldRef] = Field(default_factory=list)
    join_clauses: list[JoinClause] = Field(default_factory=list)
    where_clauses: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    time_filter: str | None = None


class QueryResult(BaseModel):
    columns: list[QueryColumn]
    rows: list[list[Any]]
    total_rows: int
    execution_ms: int


class ComplexityEstimate(BaseModel):
    estimated_rows: int
    estimated_cost: int = 1
    execution_ms: int = 0


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "pie", "card", "table"]
    echarts_option: dict[str, Any]


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionContext(BaseModel):
    session_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)
    last_intent: ParsedIntent | None = None
    last_sql: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SemanticDimension(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    field: str


class SemanticMetric(BaseModel):
    id: str
    domain: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    expression: str
    base_table: str
    joins: list[JoinClause] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    format: str = "number"
    description: str = ""


class SemanticTable(BaseModel):
    id: str
    name: str
    description: str = ""
    time_field: str | None = None
    dimensions: list[SemanticDimension] = Field(default_factory=list)


class SemanticDomain(BaseModel):
    id: str
    name: str
    description: str = ""
    tables: list[SemanticTable] = Field(default_factory=list)
    metrics: list[SemanticMetric] = Field(default_factory=list)


class SemanticModel(BaseModel):
    version: str = "1.0"
    domains: list[SemanticDomain] = Field(default_factory=list)


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(slots=True)
class RequestTrace:
    request_id: str
    session_id: str
    user_id: str
    raw_query: str
    intent_json: str | None = None
    generated_sql: str | None = None
    response_type: str = "answer"
    error_code: str | None = None
    datasource_exec_ms: int | None = None
    total_ms: int | None = None
    llm_tokens: TokenUsage = field(default_factory=TokenUsage)
