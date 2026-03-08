"""
LLM plugin base classes.

Provides ChatMessage/ChatResponse dataclasses and the LLMProvider ABC
used by all AI services (briefing, Q&A, etc.).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChatMessage:
    """A single message in a chat conversation."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class ChatResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    usage: dict = field(default_factory=dict)
    finish_reason: str = "stop"


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        """Send messages and get a completion response.

        Args:
            timeout: Request timeout in seconds. None uses provider default.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and ready."""
        ...
