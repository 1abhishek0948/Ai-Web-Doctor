"""Strict Pydantic schemas for AI visual analysis output.

The provider is expected to return structured JSON; these models validate and
normalize it. Invalid output is rejected so the deterministic report is always
preserved even when the AI misbehaves.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["critical", "high", "medium", "low", "info"]

Category = Literal[
    "responsive",
    "layout",
    "spacing",
    "typography",
    "color",
    "accessibility",
    "navigation",
    "interaction",
    "performance",
    "ux",
]

VALID_SEVERITIES = ("critical", "high", "medium", "low", "info")
VALID_CATEGORIES = (
    "responsive",
    "layout",
    "spacing",
    "typography",
    "color",
    "accessibility",
    "navigation",
    "interaction",
    "performance",
    "ux",
)

SupportedLanguage = Literal["css", "html", "javascript", "jsx"]

SUPPORTED_LANGUAGES = ("css", "html", "javascript", "jsx")

# Alias mapping used to normalize whatever the model calls a language.
LANGUAGE_ALIASES = {
    "css": "css",
    "css3": "css",
    "stylesheet": "css",
    "html": "html",
    "html5": "html",
    "markup": "html",
    "html/css": "html",
    "html+css": "html",
    "css/html": "html",
    "javascript": "javascript",
    "js": "javascript",
    "es6": "javascript",
    "es2015": "javascript",
    "react": "jsx",
    "react/jsx": "jsx",
    "jsx": "jsx",
}


def normalize_language(raw: str) -> str | None:
    """Map a raw language label to one of the supported values.

    Returns ``None`` for anything unrecognized so callers can reject it.
    """
    key = (raw or "").strip().lower()
    if key in SUPPORTED_LANGUAGES:
        return key
    return LANGUAGE_ALIASES.get(key)


class AIIssue(BaseModel):
    """One visual/UX finding returned by the model."""

    model_config = ConfigDict(extra="forbid", strict=False)

    title: str = Field(min_length=3, max_length=200)
    severity: Severity
    category: Category
    viewport_width: int = Field(ge=100, le=8000)
    viewport_height: int = Field(ge=100, le=8000)
    description: str = Field(min_length=5, max_length=1000)
    likely_cause: str = Field(min_length=3, max_length=600)
    recommendation: str = Field(min_length=3, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("title", "description", "likely_cause", "recommendation")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        return value.strip()


class AIAnalysis(BaseModel):
    """The full structured response from the model."""

    model_config = ConfigDict(extra="forbid")

    issues: list[AIIssue] = Field(default_factory=list)


class AIFix(BaseModel):
    """A generated developer fix for a single issue."""

    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=5, max_length=1500)
    recommended_change: str = Field(min_length=5, max_length=1500)
    code: str = Field(min_length=1)
    language: SupportedLanguage

    @field_validator("explanation", "recommended_change", "code")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        return value.strip()
