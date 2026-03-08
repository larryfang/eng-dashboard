"""
Fallback LLM provider.

Wraps a primary and secondary provider — if the primary fails (rate limit,
API error, timeout), transparently retries with the secondary.

Includes a simple circuit breaker: after `_FAILURE_THRESHOLD` consecutive
primary failures, the primary is skipped for `_COOLDOWN_SECONDS`.
"""
import logging
import time
from typing import List, Optional

from backend.plugins.llm.base import ChatMessage, ChatResponse, LLMProvider

logger = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = 300  # 5 minutes


class FallbackProvider(LLMProvider):
    """LLM provider that falls back from primary to secondary on errors."""

    def __init__(self, primary: LLMProvider, secondary: LLMProvider):
        self._primary = primary
        self._secondary = secondary
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0  # monotonic timestamp

    def _is_circuit_open(self) -> bool:
        if self._consecutive_failures < _FAILURE_THRESHOLD:
            return False
        if time.monotonic() >= self._circuit_open_until:
            # Cooldown elapsed — allow one probe attempt
            self._consecutive_failures = 0
            return False
        return True

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= _FAILURE_THRESHOLD:
            self._circuit_open_until = time.monotonic() + _COOLDOWN_SECONDS
            logger.warning(
                "Circuit breaker OPEN: primary LLM failed %d times, "
                "skipping for %ds",
                self._consecutive_failures,
                _COOLDOWN_SECONDS,
            )

    def _record_success(self) -> None:
        self._consecutive_failures = 0

    def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        if self._is_circuit_open():
            logger.info("Circuit breaker open — routing directly to secondary LLM")
            return self._secondary.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )

        try:
            result = self._primary.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure()
            logger.warning(
                "Primary LLM failed (%s), falling back to secondary: %s",
                type(exc).__name__,
                str(exc)[:120],
            )
            return self._secondary.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )

    def is_available(self) -> bool:
        return self._primary.is_available() or self._secondary.is_available()
