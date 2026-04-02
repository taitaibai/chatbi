from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from models import ChatRequest, ParsedIntent, TimeRange
from services.pipeline import (
    AdapterError,
    ClarificationNeeded,
    ComplexityError,
    query_pipeline,
)
from services.security import SQLUnsafeError
from services.semantic import SemanticNotFoundError

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_chat(request: ChatRequest) -> AsyncGenerator[str, None]:
    try:
        result = await query_pipeline.run(
            query=request.query,
            session_id=request.session_id,
            user_id=request.user_id,
        )
    except ClarificationNeeded as exc:
        yield _sse_event("intent_summary", _serialize_intent(exc.intent))
        yield _sse_event(
            "error",
            {
                "code": "clarification_needed",
                "message": exc.question,
            },
        )
        yield _sse_event("done", {"request_id": None})
        return
    except SemanticNotFoundError as exc:
        yield _sse_event(
            "error",
            {
                "code": "semantic_not_found",
                "message": str(exc),
                "available_metrics": exc.available_metrics,
            },
        )
        yield _sse_event("done", {"request_id": None})
        return
    except SQLUnsafeError as exc:
        yield _sse_event(
            "error",
            {"code": "sql_unsafe", "message": str(exc)},
        )
        yield _sse_event("done", {"request_id": None})
        return
    except ComplexityError as exc:
        yield _sse_event(
            "error",
            {
                "code": "complexity_blocked",
                "message": exc.reason,
                "suggestion": exc.suggestion,
            },
        )
        yield _sse_event("done", {"request_id": None})
        return
    except AdapterError as exc:
        yield _sse_event(
            "error",
            {"code": "adapter_error", "message": str(exc)},
        )
        yield _sse_event("done", {"request_id": None})
        return
    except Exception:
        yield _sse_event(
            "error",
            {"code": "unexpected_error", "message": "Internal server error"},
        )
        yield _sse_event("done", {"request_id": None})
        return

    if request.options.show_intent:
        yield _sse_event("intent_summary", _serialize_intent(result.intent))

    if request.options.show_sql:
        yield _sse_event("sql", {"sql": result.sql})

    yield _sse_event("table_data", result.query_result.model_dump(mode="json"))
    yield _sse_event("chart_spec", result.chart.model_dump(mode="json"))

    async for token in result.interpretation:
        yield _sse_event(
            "interpretation",
            {"token": token, "done": False},
        )

    yield _sse_event("interpretation", {"token": "", "done": True})
    yield _sse_event(
        "done",
        {
            "request_id": result.request_id,
            "latency_ms": result.trace.total_ms,
            "token_usage": {
                "prompt": result.trace.llm_tokens.prompt_tokens,
                "completion": result.trace.llm_tokens.completion_tokens,
            },
        },
    )


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _serialize_intent(intent: ParsedIntent) -> dict[str, Any]:
    payload = intent.model_dump(mode="json")
    payload["time_range"] = _normalize_time_range(intent.time_range)
    payload["clarification_options"] = []
    return payload


def _normalize_time_range(time_range: TimeRange | None) -> dict[str, str] | None:
    if time_range is None:
        return None

    today = date.today()
    if time_range.type == "yesterday":
        start = end = today - timedelta(days=1)
    elif time_range.type == "last_7d":
        start = today - timedelta(days=7)
        end = today
    elif time_range.type == "last_30d":
        start = today - timedelta(days=30)
        end = today
    elif time_range.type == "last_week":
        days_since_monday = today.weekday()
        start = today - timedelta(days=days_since_monday + 7)
        end = start + timedelta(days=6)
    elif time_range.type == "last_month":
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timedelta(days=1)
        start = end.replace(day=1)
    else:
        start = date.fromisoformat(time_range.start) if time_range.start else today
        end = date.fromisoformat(time_range.end) if time_range.end else today

    return {
        "type": time_range.type,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
