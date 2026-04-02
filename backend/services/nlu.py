from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader

from config.loader import get_semantic_model
from llm.client import LLMClient, LLMClientError
from models import FilterCondition, ParsedIntent, SemanticModel, SessionContext, TimeRange

logger = structlog.get_logger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "llm" / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPT_DIR)), autoescape=False)

# Model for intent parsing (cost-efficient)
_NLU_MODEL = "gpt-4o-mini"

# Keywords that indicate a follow-up question inheriting previous context
_FOLLOWUP_RE = re.compile(
    r"那[个些]?|也[要看]?|呢|按.{0,4}细分|换[成个]|改[成为]|再[看查]|还有|对比|另外|继续|上[面次]|刚才"
)


class NLUService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._client = llm_client or LLMClient()

    async def parse(self, query: str, ctx: SessionContext) -> ParsedIntent:
        """Parse natural language query into structured ParsedIntent.

        Calls LLM (gpt-4o-mini) with a Jinja2-rendered prompt. Retries up to
        2 times on JSON parse failure; returns clarification_needed=True if all
        attempts are exhausted.
        """
        is_followup = _detect_followup(query)
        semantic_model = get_semantic_model()
        messages = _build_messages(query, ctx, semantic_model, is_followup)

        raw = await self._call_with_retry(messages)
        if raw is None:
            return ParsedIntent(
                is_followup=is_followup,
                clarification_needed=True,
                clarification_question="抱歉，我暂时无法理解您的问题，能否换个方式描述？",
            )

        data: dict[str, Any] = json.loads(raw)
        return _build_intent(data, is_followup, ctx)

    async def _call_with_retry(self, messages: list[dict[str, Any]]) -> str | None:
        """Attempt LLM call up to 3 times (initial + 2 retries) on JSON parse failure."""
        for attempt in range(3):
            try:
                raw = await self._client.chat(
                    messages=messages,
                    model=_NLU_MODEL,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                json.loads(raw)  # Validate JSON before returning
                return raw
            except json.JSONDecodeError:
                if attempt >= 2:
                    return None
                # Retry: add a correction hint to encourage valid JSON output
                messages = messages + [
                    {
                        "role": "assistant",
                        "content": raw,
                    },
                    {
                        "role": "user",
                        "content": "你的响应不是合法 JSON，请重新输出，只输出 JSON 对象，不要包含任何其他内容。",
                    },
                ]
            except LLMClientError:
                # Infrastructure-level failure (bad API key, network, rate limit after
                # tenacity retries exhausted): propagate so the API layer can return 503.
                raise
            except Exception:
                # Unexpected error: log with full traceback for observability, then
                # degrade gracefully so the user sees a clarification prompt.
                logger.warning("nlu_unexpected_error", exc_info=True)
                return None
        return None


def _detect_followup(query: str) -> bool:
    return bool(_FOLLOWUP_RE.search(query))


def _build_messages(
    query: str,
    ctx: SessionContext,
    semantic_model: SemanticModel,
    is_followup: bool,
) -> list[dict[str, Any]]:
    """Build the LLM messages list from template + context."""
    metrics: list[dict[str, Any]] = []
    dimensions: list[dict[str, Any]] = []

    for domain in semantic_model.domains:
        for metric in domain.metrics:
            metrics.append(
                {
                    "name": metric.name,
                    "aliases": metric.aliases,
                    "description": metric.description,
                    "domain": domain.name,
                }
            )
        for table in domain.tables:
            for dim in table.dimensions:
                # Deduplicate by name
                if not any(d["name"] == dim.name for d in dimensions):
                    dimensions.append(
                        {
                            "name": dim.name,
                            "aliases": dim.aliases,
                        }
                    )

    context_str = _build_context_str(ctx, is_followup)

    template = _jinja_env.get_template("nlu.jinja2")
    system_content = template.render(
        metrics=metrics,
        dimensions=dimensions,
        context_str=context_str,
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": query},
    ]


def _build_context_str(ctx: SessionContext, is_followup: bool) -> str:
    if not ctx.turns and ctx.last_intent is None:
        return ""

    parts: list[str] = []
    if ctx.last_intent and is_followup:
        intent = ctx.last_intent
        parts.append(
            f"上轮意图: metrics={intent.metrics}, "
            f"dimensions={intent.dimensions}, "
            f"time_range={intent.time_range.model_dump() if intent.time_range else None}"
        )
    if ctx.turns:
        recent = ctx.turns[-4:]  # Last 2 dialogue rounds (user + assistant each)
        for turn in recent:
            parts.append(f"{turn.role}: {turn.content}")

    return "\n".join(parts)


def _build_intent(
    data: dict[str, Any],
    is_followup: bool,
    ctx: SessionContext,
) -> ParsedIntent:
    """Convert raw LLM JSON dict into a ParsedIntent, inheriting context for follow-ups."""
    metrics: list[str] = data.get("metrics") or []
    dimensions: list[str] = data.get("dimensions") or []

    # Parse time_range
    time_range: TimeRange | None = None
    tr_raw = data.get("time_range")
    if isinstance(tr_raw, dict) and tr_raw.get("type") not in (None, "null", ""):
        time_range = TimeRange(
            type=tr_raw["type"],
            start=tr_raw.get("start") or None,
            end=tr_raw.get("end") or None,
        )

    # Inherit from previous intent when this is a follow-up
    if is_followup and ctx.last_intent:
        prev = ctx.last_intent
        if not metrics:
            metrics = list(prev.metrics)
        if not dimensions:
            dimensions = list(prev.dimensions)
        if time_range is None:
            time_range = prev.time_range

    # Parse filters
    filters: list[FilterCondition] = []
    for f in data.get("filters") or []:
        try:
            filters.append(
                FilterCondition(
                    field=str(f.get("field", "")),
                    op=f.get("op", "eq"),
                    value=f.get("value"),
                )
            )
        except Exception:
            pass

    clarification_needed: bool = bool(data.get("clarification_needed", False))
    clarification_question: str | None = data.get("clarification_question") or None

    # Force clarification when metrics are still empty after context inheritance
    if not metrics and not clarification_needed:
        clarification_needed = True
        clarification_question = "请告诉我您想查看哪些指标？例如：GMV、订单量、用户数等。"

    return ParsedIntent(
        metrics=metrics,
        dimensions=dimensions,
        time_range=time_range,
        filters=filters,
        is_followup=is_followup,
        clarification_needed=clarification_needed,
        clarification_question=clarification_question,
    )


# Module-level singleton for convenience
nlu_service = NLUService()
