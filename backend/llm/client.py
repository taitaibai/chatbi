from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from typing import Any

from openai import AsyncOpenAI
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
    ) -> None:
        self._api_key = api_key or settings.openai_api_key
        self._base_url = base_url or settings.llm_base_url
        self._default_model = default_model or settings.llm_model
        self._client: AsyncOpenAI | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncOpenAI:
        if not self._api_key:
            raise LLMClientError("OpenAI API key is not configured")
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    @retry(
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> str:
        response = await self._get_client().chat.completions.create(
            model=model or self._default_model,
            messages=list(messages),
            temperature=temperature,
            **kwargs,
        )
        content = response.choices[0].message.content
        if not content:
            raise LLMClientError("Empty response returned from LLM")
        return content

    async def stream(
        self,
        messages: Sequence[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        stream = await self._get_client().chat.completions.create(
            model=model or self._default_model,
            messages=list(messages),
            temperature=temperature,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
