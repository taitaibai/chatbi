"""T-13: Interpreter Service — LLM-driven text interpretation (LLM Step 3).

Streams a concise Chinese business insight for a QueryResult via SSE.

Design constraints (data security):
  - Only aggregated Top-N rows are sent to the LLM; raw detail rows are never
    transmitted, making this the last data-security gate in the pipeline.
  - Prompt contains only: metric names, dimension names, Top-10 aggregated
    rows, and the user's original question.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from config.settings import settings
from llm.client import LLMClient
from models import ParsedIntent, QueryResult

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "llm" / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPT_DIR)), autoescape=False)

# Use the configured LLM so OpenAI-compatible providers such as MiniMax work
_INTERPRET_MODEL = settings.llm_model
_TOP_N = 10  # Maximum rows forwarded to LLM


class InterpreterService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._client = llm_client or LLMClient()

    async def interpret(
        self,
        result: QueryResult,
        intent: ParsedIntent,
        query: str = "",
        prev_result: QueryResult | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text interpretation tokens for *result*.

        Parameters
        ----------
        result:
            The query result to interpret (only Top-N rows are forwarded).
        intent:
            Parsed user intent supplying metric and dimension names for context.
        query:
            The user's original natural language question.
        prev_result:
            Previous turn's result for period-over-period comparison (optional).

        Returns
        -------
        AsyncGenerator[str, None]
            An async generator that yields string tokens suitable for SSE push.
        """
        messages = _build_messages(result, intent, query, prev_result)
        return self._client.stream(
            messages=messages,
            model=_INTERPRET_MODEL,
            temperature=0.3,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_messages(
    result: QueryResult,
    intent: ParsedIntent,
    query: str,
    prev_result: QueryResult | None,
) -> list[dict[str, Any]]:
    col_names = [c.name for c in result.columns]
    rows = _top_n_rows(result)
    prev_rows = _top_n_rows(prev_result) if prev_result else None

    template = _jinja_env.get_template("interpret.jinja2")
    system_content = template.render(
        query=query,
        metrics=intent.metrics,
        dimensions=intent.dimensions,
        columns=col_names,
        rows=rows,
        prev_rows=prev_rows,
    )

    return [{"role": "user", "content": system_content}]


def _top_n_rows(result: QueryResult | None) -> list[list[Any]]:
    """Return at most _TOP_N rows, formatted as plain Python values."""
    if result is None:
        return []
    return [list(row) for row in result.rows[:_TOP_N]]


# Module-level singleton for convenience
interpreter_service = InterpreterService()
