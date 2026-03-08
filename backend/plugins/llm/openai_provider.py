"""
OpenAI LLM provider.

Wraps the OpenAI client with lazy init and the LLMProvider interface.
Default model: gpt-4o-mini (cost-efficient for analytical tasks).
"""
import logging
import os
from typing import List, Optional

from backend.plugins.llm.base import ChatMessage, ChatResponse, LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI-backed LLM provider."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self._model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        return self._client

    def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        client = self._get_client()
        kwargs = dict(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return ChatResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
        )

    def is_available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))
