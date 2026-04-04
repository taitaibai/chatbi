from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from models.schemas import TokenUsage

# Strip chain-of-thought blocks emitted by reasoning models (e.g. MiniMax-M2.7, DeepSeek-R1)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        self._api_key = api_key or settings.llm_api_key
        # 空字符串视为未配置，交给 SDK 使用默认端点（OpenAI）
        self._base_url = base_url or settings.llm_base_url or None
        self._default_model = default_model or settings.llm_model
        self._client: AsyncOpenAI | None = None
        _limit = max_concurrent if max_concurrent is not None else settings.llm_max_concurrent
        self._semaphore = asyncio.Semaphore(_limit)

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncOpenAI:
        if not self._api_key:
            raise LLMClientError("LLM API key is not configured")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=settings.llm_timeout_seconds,
            )
        return self._client

    @retry(
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
        ),
        reraise=True,
    )
    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> str:
        async with self._semaphore:
            response = await self._get_client().chat.completions.create(
                model=model or self._default_model,
                messages=list(messages),
                temperature=temperature,
                **kwargs,
            )
        content = response.choices[0].message.content
        if not content:
            raise LLMClientError("Empty response returned from LLM")
        return _strip_think(content)

    @retry(
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
        ),
        reraise=True,
    )
    async def chat_with_usage(
        self,
        messages: Sequence[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> tuple[str, TokenUsage]:
        """Like chat(), but also returns token usage for billing/audit purposes."""
        async with self._semaphore:
            response = await self._get_client().chat.completions.create(
                model=model or self._default_model,
                messages=list(messages),
                temperature=temperature,
                **kwargs,
            )
        content = response.choices[0].message.content
        if not content:
            raise LLMClientError("Empty response returned from LLM")
        content = _strip_think(content)
        usage = TokenUsage(
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
        )
        return content, usage

    async def stream(
        self,
        messages: Sequence[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        # Only the connection-establishment step is retried; once the stream is
        # open and tokens are flowing, mid-stream retries are not safe.
        async with self._semaphore:
            stream = await self._create_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                **kwargs,
            )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    @retry(
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
        ),
        reraise=True,
    )
    async def _create_stream(
        self,
        messages: Sequence[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        **kwargs: Any,
    ):  # type: ignore[return]  # openai streaming type is internal
        return await self._get_client().chat.completions.create(
            model=model or self._default_model,
            messages=list(messages),
            temperature=temperature,
            stream=True,
            **kwargs,
        )


def _strip_think(content: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models before returning content."""
    return _THINK_RE.sub("", content).strip()
