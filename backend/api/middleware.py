from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from config.settings import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter for POST /api/v1/chat by user_id."""

    def __init__(
        self,
        app: Any,
        max_requests_per_minute: int | None = None,
    ) -> None:
        super().__init__(app)
        self._max_requests = max_requests_per_minute or settings.rate_limit_per_minute
        self._window_seconds = 60
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        if request.method != "POST" or request.url.path != "/api/v1/chat":
            return await call_next(request)

        user_id = await self._extract_user_id(request)
        if not user_id:
            return JSONResponse(
                status_code=400,
                content={"detail": "user_id is required for rate limiting"},
            )

        now = time.time()
        bucket = self._requests[user_id]
        cutoff = now - self._window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self._max_requests:
            retry_after = max(1, int(bucket[0] + self._window_seconds - now))
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "detail": f"Rate limit exceeded: max {self._max_requests} requests per minute",
                    "code": "rate_limit_exceeded",
                },
            )

        bucket.append(now)
        return await call_next(request)

    async def _extract_user_id(self, request: Request) -> str | None:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return None
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        user_id = payload.get("user_id")
        return user_id if isinstance(user_id, str) and user_id.strip() else None
