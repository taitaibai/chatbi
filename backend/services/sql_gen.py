from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from llm.client import LLMClient
from models import FieldRef, ResolvedQuery, TokenUsage

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "llm" / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPT_DIR)), autoescape=False)

_SQL_GEN_MODEL = "gpt-4o"
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AGGREGATE_RE = re.compile(r"\b(sum|count|avg|min|max)\s*\(", re.IGNORECASE)


class SQLGenService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._client = llm_client or LLMClient()

    async def generate(self, resolved: ResolvedQuery, query: str = "") -> str:
        sql, _ = await self.generate_with_usage(resolved, query)
        return sql

    async def generate_with_usage(
        self, resolved: ResolvedQuery, query: str = ""
    ) -> tuple[str, TokenUsage]:
        """Like generate(), but also returns LLM token usage for pipeline accounting."""
        if not resolved.tables:
            raise ValueError("ResolvedQuery must contain at least one table")
        if not resolved.select_fields:
            raise ValueError("ResolvedQuery must contain at least one select field")

        if not self._client.is_configured:
            return _compile_sql(resolved), TokenUsage()

        messages = _build_messages(resolved, query)
        raw, usage = await self._client.chat_with_usage(
            messages=messages,
            model=_SQL_GEN_MODEL,
            temperature=0.0,
        )
        cleaned = _clean_sql(raw)
        return cleaned or _compile_sql(resolved), usage


def _build_messages(resolved: ResolvedQuery, query: str) -> list[dict[str, Any]]:
    template = _jinja_env.get_template("sql_gen.jinja2")
    system_content = template.render(
        query=query,
        tables=resolved.tables,
        select_fields=resolved.select_fields,
        join_clauses=resolved.join_clauses,
        where_clauses=resolved.where_clauses,
        time_filter=resolved.time_filter,
        group_by=resolved.group_by,
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": query or "请基于上述 resolved_query 生成 SQL。"},
    ]


def _clean_sql(raw: str) -> str:
    text = raw.strip()
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    select_match = re.search(r"(?is)\bselect\b.*", text)
    if select_match:
        text = select_match.group(0).strip()

    return text.rstrip("; \n\t")


def _compile_sql(resolved: ResolvedQuery) -> str:
    select_sql = ", ".join(_render_select_field(field) for field in resolved.select_fields)
    from_sql = resolved.tables[0].name

    sql_parts = [f"SELECT {select_sql}", f"FROM {from_sql}"]

    for join_clause in resolved.join_clauses:
        join_type = join_clause.join_type.upper()
        sql_parts.append(f"{join_type} JOIN {join_clause.table} ON {join_clause.on}")

    where_clauses = [*resolved.where_clauses]
    if resolved.time_filter:
        where_clauses.append(resolved.time_filter)
    if where_clauses:
        sql_parts.append("WHERE " + " AND ".join(where_clauses))

    if resolved.group_by:
        sql_parts.append("GROUP BY " + ", ".join(resolved.group_by))
    elif not _has_aggregate(resolved.select_fields):
        sql_parts.append("LIMIT 200")

    return "\n".join(sql_parts)


def _render_select_field(field: FieldRef) -> str:
    alias = field.name if _SAFE_IDENTIFIER_RE.match(field.name) else None
    expression = field.expression.strip()
    if alias and alias.lower() != expression.lower():
        return f"{expression} AS {alias}"
    return expression


def _has_aggregate(fields: list[FieldRef]) -> bool:
    return any(_AGGREGATE_RE.search(field.expression) for field in fields)


sql_gen_service = SQLGenService()
