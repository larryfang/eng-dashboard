"""
LLM helper utilities.

Factory for getting the active LLM provider with singleton caching.
Prefers Anthropic (Haiku 4.5) when ANTHROPIC_API_KEY is set,
falls back to OpenAI (gpt-4o-mini), then to None (rule-based).

When both keys are present, wraps them in a FallbackProvider so that
rate-limit or API errors on Anthropic automatically retry with OpenAI.
"""
import logging
import os
from typing import Optional

from backend.plugins.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_provider: Optional[LLMProvider] = None
_checked = False


def get_llm_plugin() -> Optional[LLMProvider]:
    """Get the configured LLM provider, or None if unavailable.

    Priority: Anthropic > OpenAI > None.
    When both keys are set, uses FallbackProvider (Anthropic → OpenAI).
    Caches the singleton after first check.
    """
    global _provider, _checked

    if _checked:
        return _provider

    _checked = True

    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if has_anthropic and has_openai:
        from backend.plugins.llm.anthropic_provider import AnthropicProvider
        from backend.plugins.llm.openai_provider import OpenAIProvider
        from backend.plugins.llm.fallback_provider import FallbackProvider
        _provider = FallbackProvider(
            primary=AnthropicProvider(),
            secondary=OpenAIProvider(),
        )
        logger.info("LLM provider: Anthropic (claude-haiku-4-5) → OpenAI (gpt-4o-mini) fallback")
    elif has_anthropic:
        from backend.plugins.llm.anthropic_provider import AnthropicProvider
        _provider = AnthropicProvider()
        logger.info("LLM provider: Anthropic (claude-haiku-4-5)")
    elif has_openai:
        from backend.plugins.llm.openai_provider import OpenAIProvider
        _provider = OpenAIProvider()
        logger.info("LLM provider: OpenAI (gpt-4o-mini)")
    else:
        logger.info("No LLM API key found — AI features will use rule-based fallbacks")

    return _provider
