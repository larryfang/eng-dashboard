"""
LLM helper utilities.

Factory for getting the active LLM provider with singleton caching.
Prefers Anthropic (Haiku 4.5) when ANTHROPIC_API_KEY is set,
falls back to OpenAI (gpt-4o-mini), then to None (rule-based).

Keys are resolved via domain secrets first, then environment variables.
When both keys are present, wraps them in a FallbackProvider so that
rate-limit or API errors on Anthropic automatically retry with OpenAI.
"""
import logging
from typing import Optional

from backend.plugins.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_provider: Optional[LLMProvider] = None
_checked = False

# Canonical model identifiers
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_MODEL_DISPLAY = "Claude Haiku 4.5"
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_MODEL_DISPLAY = "GPT-4o Mini"


def _resolve_keys() -> tuple[str, str]:
    """Resolve LLM API keys from domain secrets, falling back to env vars."""
    from backend.services.domain_credentials import get_llm_settings
    settings = get_llm_settings()
    return settings["anthropic_api_key"], settings["openai_api_key"]


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
    anthropic_key, openai_key = _resolve_keys()

    if anthropic_key and openai_key:
        from backend.plugins.llm.anthropic_provider import AnthropicProvider
        from backend.plugins.llm.openai_provider import OpenAIProvider
        from backend.plugins.llm.fallback_provider import FallbackProvider
        _provider = FallbackProvider(
            primary=AnthropicProvider(),
            secondary=OpenAIProvider(),
        )
        logger.info("LLM provider: Anthropic (%s) → OpenAI (%s) fallback", ANTHROPIC_MODEL_DISPLAY, OPENAI_MODEL_DISPLAY)
    elif anthropic_key:
        from backend.plugins.llm.anthropic_provider import AnthropicProvider
        _provider = AnthropicProvider()
        logger.info("LLM provider: Anthropic (%s)", ANTHROPIC_MODEL_DISPLAY)
    elif openai_key:
        from backend.plugins.llm.openai_provider import OpenAIProvider
        _provider = OpenAIProvider()
        logger.info("LLM provider: OpenAI (%s)", OPENAI_MODEL_DISPLAY)
    else:
        logger.info("No LLM API key found — AI features will use rule-based fallbacks")

    return _provider


def reset_llm_plugin() -> None:
    """Reset the cached provider so next call to get_llm_plugin() re-resolves keys."""
    global _provider, _checked
    _provider = None
    _checked = False


def get_llm_status() -> dict:
    """Return current LLM configuration status (no secrets exposed)."""
    anthropic_key, openai_key = _resolve_keys()
    return {
        "anthropic": {
            "configured": bool(anthropic_key),
            "model": ANTHROPIC_MODEL,
            "model_display": ANTHROPIC_MODEL_DISPLAY,
            "description": "Fast, cost-efficient analysis and report generation",
        },
        "openai": {
            "configured": bool(openai_key),
            "model": OPENAI_MODEL,
            "model_display": OPENAI_MODEL_DISPLAY,
            "description": "General-purpose AI for summaries and insights",
        },
        "active_provider": (
            "anthropic+openai" if (anthropic_key and openai_key)
            else "anthropic" if anthropic_key
            else "openai" if openai_key
            else None
        ),
        "mode": (
            "fallback" if (anthropic_key and openai_key)
            else "single" if (anthropic_key or openai_key)
            else "rule-based"
        ),
    }
