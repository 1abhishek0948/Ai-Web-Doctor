"""Abstract AI provider interface.

Providers implement ``analyze_ui`` (visual analysis, Part 6) and
``generate_fix`` (developer fixes, Part 7). Concrete providers live in
:mod:`apps.ai.providers`. The app never hardcodes a specific model name — each
provider reads its configuration from environment variables via Django
settings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProviderError(Exception):
    """Raised when an AI provider call fails (timeout, HTTP error, ...)."""


class AIProvider(ABC):
    """Interface every UI-analysis provider must implement."""

    name: str = "abstract"

    @abstractmethod
    def analyze_ui(self, payload: dict[str, Any]) -> str:
        """Analyze UI screenshots + context and return raw model text.

        ``payload`` contains at least:
          * ``prompt`` — textual context for the model
          * ``images`` — list of ``{"mime_type": str, "data": <base64 str>}``
        The returned text must be valid JSON matching
        :class:`apps.ai.schemas.AIAnalysis`.

        Raises :class:`AIProviderError` on failure.
        """

    @abstractmethod
    def generate_fix(self, payload: dict[str, Any]) -> str:
        """Generate a code fix for a single issue.

        ``payload`` contains at least ``prompt`` and optional ``images``.
        The returned text must be valid JSON matching
        :class:`apps.ai.schemas.AIFix`.

        Raises :class:`AIProviderError` on failure.
        """

    def is_available(self) -> bool:
        """Whether this provider can be called right now."""
        return True
