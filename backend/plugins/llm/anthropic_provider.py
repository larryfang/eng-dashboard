"""
Anthropic LLM provider.

Wraps the Anthropic client with lazy init and the LLMProvider interface.
Default model: claude-haiku-4-5-20251001 (fast, cost-efficient).
"""
import logging
import os
from typing import List, Optional

from backend.plugins.llm.base import ChatMessage, ChatResponse, LLMProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic-backed LLM provider."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self._model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        return self._client

    def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        client = self._get_client()

        # Anthropic uses a separate system param instead of a system message
        system_text = ""
        user_messages = []
        for m in messages:
            if m.role == "system":
                system_text = m.content
            else:
                user_messages.append({"role": m.role, "content": m.content})

        kwargs = dict(
            model=self._model,
            system=system_text,
            messages=user_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if timeout is not None:
            kwargs["timeout"] = timeout

        response = client.messages.create(**kwargs)

        # Extract text from the first TextBlock in the response
        content = ""
        for block in response.content:
            if hasattr(block, "text"):
                content = block.text
                break
        if not content:
            logger.warning(
                "Anthropic response contained no TextBlock (model=%s, stop_reason=%s)",
                response.model,
                response.stop_reason,
            )
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }
        return ChatResponse(
            content=content,
            model=response.model,
            usage=usage,
            finish_reason=response.stop_reason or "stop",
        )

    def is_available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
