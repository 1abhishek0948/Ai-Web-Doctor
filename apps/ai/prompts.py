"""Prompt templates for Gemini visual/UX analysis.

The prompt intentionally asks for subjective visual/UX reasoning only — never
objective measurements (those come from the deterministic scanner). The model
must return a strict JSON array matching :class:`apps.ai.schemas.AIAnalysis`.
"""

from __future__ import annotations

import json
from typing import Any

from apps.ai.schemas import (
    SUPPORTED_LANGUAGES,
    VALID_CATEGORIES,
    VALID_SEVERITIES,
)

SYSTEM_PROMPT = (
    "You are a senior front-end designer reviewing screenshots of a website. "
    "You provide visual and UX reasoning only. Do not guess measurements or "
    "numbers you cannot see; leave precise objective checks to automated "
    "tools. Analyze the provided screenshots for visual hierarchy, spacing "
    "consistency, alignment, typography, visual balance, navigation usability, "
    "CTA visibility, responsive behavior, visual inconsistencies, obvious UX "
    "problems, and confusing layouts. Return ONLY a JSON object matching this "
    "schema:\n"
    '{"issues": [{"title": str, "severity": "critical|high|medium|low|info", '
    '"category": "responsive|layout|spacing|typography|color|accessibility|'
    'navigation|interaction|performance|ux", "viewport_width": int, '
    '"viewport_height": int, "description": str, "likely_cause": str, '
    '"recommendation": str, "confidence": float between 0 and 1}]}\n'
    "Use viewport_width and viewport_height that match one of the provided "
    "screenshots. Report at most 20 issues, highest confidence first. Do not "
    "invent issues; if the site looks fine, return an empty issues array."
)


def build_payload_text(
    *,
    url: str,
    title: str,
    viewports: list[tuple[int, int]],
    deterministic_summary: str,
    dom_summary: str,
) -> str:
    """Build the textual part of the analysis payload."""
    viewport_text = ", ".join(f"{w}x{h}" for w, h in viewports)
    return (
        f"Website: {url}\n"
        f"Page title: {title}\n"
        f"Screenshots provided for viewports: {viewport_text}\n\n"
        f"Automated measurements (already known, do not re-measure):\n"
        f"{deterministic_summary}\n\n"
        f"Simplified DOM structure (for context):\n{dom_summary}\n\n"
        "Provide your visual and UX analysis of the screenshots. "
        "Return strict JSON only."
    )


def summarize_deterministic(findings: list[dict[str, Any]], limit: int = 40) -> str:
    """Turn deterministic/accessibility findings into a compact text summary."""
    if not findings:
        return "No deterministic problems detected."
    lines = []
    for finding in findings[:limit]:
        vp = finding.get("viewport_width")
        lines.append(
            f"- [{finding.get('severity')}/{finding.get('category')} "
            f"@{vp}px] {finding.get('title')}: {finding.get('description')}"
        )
    return "\n".join(lines)


def summarize_dom(
    dom_snapshots: list[list[dict[str, Any]]], limit_per_viewport: int = 40
) -> str:
    """Produce a compact structural summary of DOM snapshots per viewport."""
    if not dom_snapshots:
        return "No DOM snapshot available."
    blocks = []
    for snapshot in dom_snapshots[:4]:
        elements = []
        for el in snapshot[:limit_per_viewport]:
            tag = el.get("tag", "")
            text = (el.get("text") or "").strip()
            label = tag
            if text:
                label = f"{tag} \"{text[:40]}\""
            elements.append(label)
        blocks.append("\n".join(elements[:limit_per_viewport]))
    return "\n\n".join(blocks)


def _schema_field(name: str, enum: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "string", "enum": list(enum)}


def build_analysis_schema() -> dict[str, Any]:
    """OpenAPI-style responseSchema matching :class:`AIAnalysis`.

    Forces structured output so the model cannot drift from the schema.
    """
    return {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "severity": _schema_field("severity", VALID_SEVERITIES),
                        "category": _schema_field("category", VALID_CATEGORIES),
                        "viewport_width": {"type": "integer"},
                        "viewport_height": {"type": "integer"},
                        "description": {"type": "string"},
                        "likely_cause": {"type": "string"},
                        "recommendation": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "title",
                        "severity",
                        "category",
                        "viewport_width",
                        "viewport_height",
                        "description",
                        "likely_cause",
                        "recommendation",
                        "confidence",
                    ],
                },
            }
        },
        "required": ["issues"],
    }


def build_fix_schema() -> dict[str, Any]:
    """OpenAPI-style responseSchema matching :class:`AIFix`."""
    return {
        "type": "object",
        "properties": {
            "explanation": {"type": "string"},
            "recommended_change": {"type": "string"},
            "code": {"type": "string"},
            "language": _schema_field("language", SUPPORTED_LANGUAGES),
        },
        "required": ["explanation", "recommended_change", "code", "language"],
    }


def build_generation_config(response_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the generationConfig forcing structured JSON output."""
    config: dict[str, Any] = {
        "response_mime_type": "application/json",
        "temperature": 0.2,
        "max_output_tokens": 8192,
    }
    if response_schema is not None:
        config["responseSchema"] = response_schema
    return config


FIX_SYSTEM_PROMPT = (
    "You are a senior front-end engineer. Given ONE specific UI issue for a "
    "website, produce a practical, minimal, correct code fix. Analyze the "
    "screenshot and the provided context. Do not modify or deploy anything — "
    "you only suggest code that a developer will review and apply manually. "
    "Return ONLY a JSON object matching this schema:\n"
    '{"explanation": str (why the problem happens), "recommended_change": str '
    '(what to change and where), "code": str (the exact fix snippet), '
    '"language": "css"|"html"|"javascript"|"jsx"}.\n'
    "Only use jsx when the fix targets a React component. Use css when a media "
    "query or style change fixes it. Keep the code snippet focused and "
    "complete enough to apply."
)


def build_fix_prompt(issue_text: str, context_text: str) -> str:
    """Build the user prompt for a single-issue fix request."""
    return (
        f"Issue to fix:\n{issue_text}\n\n"
        f"Relevant context:\n{context_text}\n\n"
        "Return strict JSON only."
    )


def build_issue_summary(
    *,
    title: str,
    severity: str,
    category: str,
    description: str,
    viewport_label: str,
    selector: str,
    evidence_text: str,
    diagnosis_text: str,
) -> str:
    """Describe a single issue for the fix prompt."""
    parts = [
        f"Title: {title}",
        f"Severity: {severity}",
        f"Category: {category}",
        f"Viewport: {viewport_label}",
    ]
    if selector:
        parts.append(f"Element selector: {selector}")
    if description:
        parts.append(f"Description: {description}")
    if evidence_text:
        parts.append(f"Deterministic evidence: {evidence_text}")
    if diagnosis_text:
        parts.append(f"AI diagnosis: {diagnosis_text}")
    return "\n".join(parts)
