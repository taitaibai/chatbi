from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config.settings import settings


class RateLimitMiddleware:
    """Simple in-memory rate limiter for POST /api/v1/chat by user_id."""

    def __init__(
        self,
        app: ASGIApp,
        max_requests_per_minute: int | None = None,
    ) -> None:
        self.app = app
        self._max_requests = max_requests_per_minute or settings.rate_limit_per_minute
        self._window_seconds = 60
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["method"] != "POST" or scope["path"] != "/api/v1/chat":
            await self.app(scope, receive, send)
            return

        user_id, receive = await self._extract_user_id(scope, receive)
        if not user_id:
            await self._send_json(
                scope,
                send,
                status_code=400,
                content={"detail": "user_id is required for rate limiting"},
            )
            return

        now = time.time()
        bucket = self._prune_bucket(user_id, now)
        if bucket is None:
            bucket = self._requests[user_id]

        if len(bucket) >= self._max_requests:
            retry_after = max(1, int(bucket[0] + self._window_seconds - now))
            await self._send_json(
                scope,
                send,
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "detail": f"Rate limit exceeded: max {self._max_requests} requests per minute",
                    "code": "rate_limit_exceeded",
                },
            )
            return

        bucket.append(now)
        await self.app(scope, receive, send)

    def _prune_bucket(self, user_id: str, now: float) -> deque[float] | None:
        bucket = self._requests[user_id]
        cutoff = now - self._window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket and user_id in self._requests:
            del self._requests[user_id]
            return None
        return bucket

    async def _extract_user_id(
        self, scope: Scope, receive: Receive
    ) -> tuple[str | None, Receive]:
        headers = Headers(scope=scope)
        header_user_id = headers.get("x-user-id")
        if header_user_id and header_user_id.strip():
            return header_user_id.strip(), receive

        body = bytearray()
        messages: list[Message] = []
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        except Exception:
            payload = None

        if not isinstance(payload, dict):
            return None, self._replay_receive(messages, receive)

        user_id = payload.get("user_id")
        normalized = user_id.strip() if isinstance(user_id, str) and user_id.strip() else None
        return normalized, self._replay_receive(messages, receive)

    def _replay_receive(
        self, messages: list[Message], original_receive: Receive
    ) -> Callable[[], Awaitable[Message]]:
        queue = deque(messages)

        async def replay() -> Message:
            if queue:
                return queue.popleft()
            return await original_receive()

        return replay

    async def _send_json(
        self,
        scope: Scope,
        send: Send,
        *,
        status_code: int,
        content: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        response = JSONResponse(status_code=status_code, content=content, headers=headers)
        await response(scope, self._empty_receive, send)

    async def _empty_receive(self) -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}
