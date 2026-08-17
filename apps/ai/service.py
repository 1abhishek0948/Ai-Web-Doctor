"""AI analysis orchestration (Part 6) and fix generation (Part 7).

The deterministic scanner runs first and always. This module optionally augments
its findings with Gemini visual/UX reasoning, merges overlapping findings into
combined issues, and — on demand — generates developer code fixes for a single
issue. If Gemini is unavailable, the deterministic report is preserved and a
clear message is surfaced instead.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.files.storage import default_storage
from pydantic import ValidationError

from apps.ai.image_utils import optimize_screenshot
from apps.ai.providers import AIProvider, AIProviderError, GeminiProvider
from apps.ai.prompts import (
    build_fix_prompt,
    build_issue_summary,
    build_payload_text,
    summarize_deterministic,
    summarize_dom,
)
from apps.ai.schemas import AIAnalysis, AIFix, normalize_language
from apps.issues.models import Issue, IssueSource, SEVERITY_ORDER
from config.logging_config import log_event

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}")

AI_UNAVAILABLE_MESSAGE = (
    "AI visual analysis unavailable. Deterministic responsive and "
    "accessibility results are still available."
)

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "at", "of",
    "to", "on", "in", "for", "and", "or", "with", "this", "that", "it", "its",
    "as", "by", "from", "than", "but", "not", "no", "so", "if", "do", "does",
    "you", "your", "has", "have", "had", "will", "would", "can", "could",
    "should", "may", "might", "too", "very", "px", "the",
}


@dataclass
class AIAnalysisResult:
    """Outcome of running AI analysis for a scan.

    ``status`` is the machine-readable value stored on ``Scan.ai_status``
    (pending/running/completed/unavailable/failed/rate_limited/skipped);
    ``reason`` is a short internal key describing why analysis was skipped or
    failed. ``message`` stays the human-readable text shown to developers.
    """

    available: bool = False
    created: int = 0
    combined: int = 0
    message: str = ""
    model: str = ""
    status: str = "pending"
    reason: str = ""

    @property
    def unavailable_message(self) -> str:
        return AI_UNAVAILABLE_MESSAGE


@dataclass
class FixResult:
    """Outcome of a fix generation request for a single issue."""

    ok: bool
    explanation: str = ""
    recommended_change: str = ""
    code: str = ""
    language: str = ""
    error: str = ""


def get_provider() -> AIProvider:
    """Return the configured AI provider (currently Gemini)."""
    return GeminiProvider()


def _provider_available() -> bool:
    if not settings.AI_ENABLED:
        return False
    return get_provider().is_available()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _significant_tokens(text: str) -> set[str]:
    return {t for t in _tokens(text) if t not in STOPWORDS and len(t) >= 4}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_json(raw: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if match:
            return json.loads(match.group(0))
        raise ValueError("The AI response was not valid JSON.")


def _issue_to_finding(issue: Issue) -> dict[str, Any]:
    return {
        "check": (issue.evidence or {}).get("check", ""),
        "category": issue.category,
        "title": issue.title,
        "severity": issue.severity,
        "description": issue.description,
        "viewport_width": issue.viewport_width,
        "viewport_height": issue.viewport_height,
        "selector": issue.selector,
        "evidence": issue.evidence or {},
        "confidence": issue.confidence,
        "source": issue.source,
    }


def _load_scan_context(scan) -> dict[str, Any]:
    """Load the archived result JSON (DOM snapshots, warnings) for a scan."""
    try:
        with default_storage.open(f"scans/{scan.pk}/result.json", "r") as f:
            return json.loads(f.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Part 6: visual analysis
# ---------------------------------------------------------------------------

def _select_screenshots(scan) -> list[dict[str, Any]]:
    """Pick representative screenshots + viewports with important findings.

    Keeps the Gemini payload small: representative viewports are always sent,
    plus viewports where deterministic analysis found critical/high issues.
    """
    by_viewport = {
        (s.viewport_width, s.viewport_height): s for s in scan.screenshots.all()
    }
    wanted: list[tuple[int, int]] = []
    for vp in settings.AI_REPRESENTATIVE_VIEWPORTS:
        if vp in by_viewport and vp not in wanted:
            wanted.append(vp)

    issue_viewports: list[tuple[int, int]] = []
    for issue in scan.issues.filter(severity__in=["critical", "high"]):
        if issue.viewport_width:
            vp = (issue.viewport_width, issue.viewport_height or 0)
            if vp not in issue_viewports:
                issue_viewports.append(vp)
    for vp in issue_viewports:
        if vp not in wanted and vp in by_viewport:
            wanted.append(vp)

    images: list[dict[str, Any]] = []
    for vp in wanted:
        screenshot = by_viewport[vp]
        try:
            with default_storage.open(screenshot.path, "rb") as f:
                data = f.read()
            optimized = optimize_screenshot(
                data,
                max_width=settings.AI_IMAGE_MAX_WIDTH,
                quality=settings.AI_IMAGE_QUALITY,
            )
            images.append(
                {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(optimized).decode("ascii"),
                    "viewport": vp,
                }
            )
        except Exception:  # noqa: BLE001
            logger.warning("Could not read screenshot %s for AI payload.", screenshot.path)
    return images


def _fit_payload_size(prompt: str, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the largest images until the AI payload fits MAX_AI_REQUEST_SIZE.

    Keeps prompt text intact (it is small and informative); drops the biggest
    screenshots first so the most representative viewports survive.
    """
    limit = int(settings.MAX_AI_REQUEST_SIZE)
    prompt_bytes = len((prompt or "").encode("utf-8"))
    if prompt_bytes > limit:
        log_event("ai.error", level=logging.WARNING, reason="prompt_exceeds_size_limit")
        return []
    ordered = sorted(
        images, key=lambda img: len(img.get("data", "")), reverse=True
    )
    kept: list[dict[str, Any]] = []
    total = prompt_bytes
    for image in ordered:
        candidate = total + len(image.get("data", "")) + 512
        if candidate <= limit:
            kept.append(image)
            total = candidate
    return kept


def build_payload(scan) -> dict[str, Any]:
    """Assemble the compact prompt + images payload for Gemini."""
    findings = [_issue_to_finding(i) for i in scan.issues.all()]
    images = _select_screenshots(scan)
    context = _load_scan_context(scan)
    dom_snapshots = context.get("dom_snapshots", [])

    prompt = build_payload_text(
        url=scan.normalized_url or scan.url,
        title=context.get("title", ""),
        viewports=[img["viewport"] for img in images],
        deterministic_summary=summarize_deterministic(findings),
        dom_summary=summarize_dom(dom_snapshots),
    )
    images = _fit_payload_size(prompt, images)
    return {"prompt": prompt, "images": images}


_TYPE_TO_CATEGORY = {
    "visual": "layout",
    "visual_design": "color",
    "accessibility": "accessibility",
    "ux": "ux",
    "responsive": "responsive",
    "layout": "layout",
    "spacing": "spacing",
    "typography": "typography",
    "color": "color",
    "navigation": "navigation",
    "interaction": "interaction",
    "performance": "performance",
}


def _parse_viewport(value: Any) -> tuple[int, int] | None:
    """Parse a viewport value (834, '834px', '375x812', 'all') to (w, h)."""
    if isinstance(value, (int, float)) and value > 0:
        return int(value), 812
    s = str(value or "").strip().lower()
    if s in ("all", ""):
        return 1440, 900
    m = re.match(r"(\d+)\s*[x×]\s*(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"(\d+)\s*(?:px)?", s)
    if m:
        return int(m.group(1)), 812
    return None


def _normalize_issue(item: Any) -> Any:
    """Map alternate model field names onto the canonical AIIssue shape."""
    if not isinstance(item, dict):
        return item
    out = dict(item)
    if not out.get("category") and out.get("type"):
        out["category"] = _TYPE_TO_CATEGORY.get(
            str(out["type"]).strip().lower(), str(out["type"]).strip().lower()
        )
    if not out.get("viewport_width") or not out.get("viewport_height"):
        parsed = _parse_viewport(out.get("viewport"))
        if parsed is not None:
            out["viewport_width"], out["viewport_height"] = parsed
    for key in ("type", "viewport"):
        out.pop(key, None)
    return out


def _validate_analysis(raw: str) -> AIAnalysis:
    parsed = _parse_json(raw)
    if isinstance(parsed, list):
        parsed = {"issues": parsed}
    if isinstance(parsed, dict) and isinstance(parsed.get("issues"), list):
        parsed = {"issues": [_normalize_issue(i) for i in parsed["issues"]]}
    return AIAnalysis.model_validate(parsed)


def _match_score(ai_issue, existing: Issue) -> float:
    a_text = f"{ai_issue.title} {ai_issue.description}"
    b_text = f"{existing.title} {existing.description}"
    a_tokens = _significant_tokens(a_text)
    b_tokens = _significant_tokens(b_text)
    return _jaccard(a_tokens, b_tokens)


def _shares_significant_token(ai_issue, existing: Issue) -> bool:
    a_tokens = _significant_tokens(f"{ai_issue.title} {ai_issue.description}")
    b_tokens = _significant_tokens(f"{existing.title} {existing.description}")
    return bool(a_tokens & b_tokens)


def _find_match(ai_issue, existing_issues: list[Issue]) -> Issue | None:
    """Find an existing deterministic/accessibility issue the AI finding maps to.

    Same category + same viewport (when both specify one) + a significant token
    overlap. Never merges onto another AI-only issue.
    """
    best: Issue | None = None
    best_score = 0.0
    for existing in existing_issues:
        if existing.category != ai_issue.category:
            continue
        if existing.viewport_width and ai_issue.viewport_width:
            if existing.viewport_width != ai_issue.viewport_width:
                continue
        if existing.status == "dismissed":
            continue
        if existing.source == IssueSource.AI:
            continue
        score = _match_score(ai_issue, existing)
        if score > best_score:
            best = existing
            best_score = score

    if best is not None and (
        best_score >= 0.25 or _shares_significant_token(ai_issue, best)
    ):
        return best
    return None


def _combine(match: Issue, ai_issue) -> None:
    """Merge an AI finding into an existing issue, preserving both evidences."""
    evidence = dict(match.evidence or {})
    ai_evidence = {
        "title": ai_issue.title,
        "description": ai_issue.description,
        "likely_cause": ai_issue.likely_cause,
        "recommendation": ai_issue.recommendation,
        "confidence": ai_issue.confidence,
    }
    evidence["ai"] = ai_evidence
    match.source = IssueSource.COMBINED
    match.ai_explanation = (
        f"{ai_issue.likely_cause}\n\nRecommended: {ai_issue.recommendation}"
    )
    if SEVERITY_ORDER.get(ai_issue.severity, 5) > SEVERITY_ORDER.get(match.severity, 5):
        match.severity = ai_issue.severity
    match.evidence = evidence
    match.save(update_fields=["source", "ai_explanation", "severity", "evidence"])


def merge_ai_issues(scan, analysis: AIAnalysis) -> tuple[int, int]:
    """Persist AI findings, combining them with matching existing findings.

    Returns ``(created, combined)`` counts.
    """
    existing = list(scan.issues.all())
    created = 0
    combined = 0
    used_keys: set[tuple] = set()

    for ai_issue in analysis.issues:
        dedup_key = (ai_issue.category, ai_issue.viewport_width, ai_issue.title.strip().lower())
        if dedup_key in used_keys:
            continue
        used_keys.add(dedup_key)

        match = _find_match(ai_issue, existing)
        if match is not None:
            _combine(match, ai_issue)
            combined += 1
            continue

        Issue.objects.create(
            scan=scan,
            title=ai_issue.title,
            severity=ai_issue.severity,
            category=ai_issue.category,
            source=IssueSource.AI,
            description=ai_issue.description,
            viewport_width=ai_issue.viewport_width,
            viewport_height=ai_issue.viewport_height,
            confidence=ai_issue.confidence,
            ai_explanation=(
                f"{ai_issue.likely_cause}\n\nRecommended: {ai_issue.recommendation}"
            ),
            evidence={
                "ai": {
                    "likely_cause": ai_issue.likely_cause,
                    "recommendation": ai_issue.recommendation,
                }
            },
        )
        created += 1

    return created, combined


def _is_rate_limited(error: Exception | None) -> bool:
    """True when a provider error means the API quota/billing is exhausted."""
    lowered = (str(error) or "").lower()
    return (
        "429" in lowered
        or "quota" in lowered
        or "resource_exhausted" in lowered
        or "rate limit" in lowered
    )


def analyze_scan(scan) -> AIAnalysisResult:
    """Run AI visual analysis for a scan and merge its findings.

    Never raises; AI failures only affect AI findings, never the scan.
    """
    if not _provider_available():
        logger.info("AI analysis unavailable (disabled or no API key); skipping.")
        return AIAnalysisResult(
            available=False,
            status="unavailable",
            reason="disabled_or_no_key",
            message=AI_UNAVAILABLE_MESSAGE,
        )

    payload = build_payload(scan)
    if not payload["images"]:
        return AIAnalysisResult(
            available=False,
            status="unavailable",
            reason="no_screenshots",
            message="No screenshots available for AI analysis.",
        )

    provider = get_provider()
    analysis: AIAnalysis | None = None
    last_error: Exception | None = None
    attempts = settings.GEMINI_MAX_RETRIES + 1

    for attempt in range(attempts):
        try:
            raw = provider.analyze_ui(payload)
            analysis = _validate_analysis(raw)
            break
        except AIProviderError as exc:
            last_error = exc
            logger.warning("AI provider error on attempt %d: %s", attempt + 1, exc)
        except (ValueError, ValidationError) as exc:
            last_error = exc
            logger.warning("Invalid AI response on attempt %d: %s", attempt + 1, exc)

    if analysis is None:
        logger.warning(
            "AI analysis failed for scan %s: %s", scan.pk, last_error or "unknown"
        )
        log_event(
            "ai.error",
            scan_id=scan.pk,
            reason=str(last_error or "unknown"),
            attempts=attempts,
        )
        if _is_rate_limited(last_error):
            return AIAnalysisResult(
                available=False,
                status="rate_limited",
                reason="provider_rate_limited",
                message=_friendly_provider_error(str(last_error or "")),
            )
        return AIAnalysisResult(
            available=False,
            status="failed",
            reason="provider_or_validation_error",
            message=AI_UNAVAILABLE_MESSAGE,
        )

    created, combined = merge_ai_issues(scan, analysis)
    logger.info(
        "AI analysis for scan %s: %d created, %d combined (model %s)",
        scan.pk, created, combined, provider.model,
    )
    return AIAnalysisResult(
        available=True,
        created=created,
        combined=combined,
        model=provider.model,
        status="completed",
        reason="ok",
    )


# ---------------------------------------------------------------------------
# Part 7: fix generation
# ---------------------------------------------------------------------------

def _build_fix_payload(issue: Issue) -> dict[str, Any]:
    evidence = issue.evidence or {}
    deterministic = evidence.get("check") or evidence.get("rule_id")
    diagnosis = issue.ai_explanation or ""

    issue_text = build_issue_summary(
        title=issue.title,
        severity=issue.severity,
        category=issue.category,
        description=issue.description,
        viewport_label=issue.viewport_label,
        selector=issue.selector,
        evidence_text=f"{deterministic} — {json.dumps(evidence, default=str)[:300]}",
        diagnosis_text=diagnosis,
    )

    context_parts: list[str] = []
    snippet = evidence.get("snippet")
    if snippet:
        context_parts.append(f"Relevant element HTML:\n{snippet}")
    context_parts.append(
        "Security note: this is a suggestion only. Never apply it automatically; "
        "a developer must review and apply the fix manually."
    )
    prompt = f"{build_fix_prompt(issue_text, '\n\n'.join(context_parts))}"

    payload: dict[str, Any] = {
        "prompt": prompt,
        "images": [],
        "issue": issue,
    }

    screenshot = None
    if issue.viewport_width:
        screenshot = (
            issue.scan.screenshots.filter(
                viewport_width=issue.viewport_width,
                viewport_height=issue.viewport_height or 812,
            ).first()
            or issue.scan.screenshots.first()
        )
    if screenshot is None:
        screenshot = issue.scan.screenshots.first()
    if screenshot is not None:
        try:
            with default_storage.open(screenshot.path, "rb") as f:
                data = f.read()
            optimized = optimize_screenshot(
                data,
                max_width=settings.AI_IMAGE_MAX_WIDTH,
                quality=settings.AI_IMAGE_QUALITY,
            )
            payload["images"].append(
                {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(optimized).decode("ascii"),
                }
            )
        except Exception:  # noqa: BLE001
            logger.warning("Could not attach screenshot for fix on issue %s.", issue.pk)
    return payload


def _validate_fix(raw: str) -> AIFix:
    parsed = _parse_json(raw)
    language_raw = parsed.get("language", "")
    language = normalize_language(str(language_raw))
    if language is None:
        raise ValueError(
            f"The AI suggested an unsupported language ({language_raw!r}). "
            "Supported: CSS, HTML, JavaScript, React/JSX."
        )
    parsed["language"] = language
    return AIFix.model_validate(parsed)


def _friendly_provider_error(message: str) -> str:
    """Turn a raw provider error into a developer-facing hint."""
    lowered = (message or "").lower()
    if "429" in lowered or "quota" in lowered:
        return (
            "The AI provider is rate-limited (quota exceeded). "
            "Check your Gemini API plan/billing and try again later."
        )
    if "timeout" in lowered or "timed out" in lowered:
        return "The AI provider timed out. Please try again."
    if "unauthorized" in lowered or "401" in lowered or "invalid api key" in lowered:
        return "The AI provider rejected the API key. Check GEMINI_API_KEY."
    return "The AI could not be reached. Please try again."


def generate_fix(issue: Issue) -> FixResult:
    """Generate a code fix suggestion for a single issue.

    The generated code is only returned to the developer for manual review. It
    is never executed, injected into the scanned website, or deployed.
    """
    if not _provider_available():
        return FixResult(
            ok=False,
            error="AI visual analysis unavailable. Deterministic responsive and "
            "accessibility results are still available.",
        )

    payload = _build_fix_payload(issue)
    provider = get_provider()
    attempts = settings.GEMINI_MAX_RETRIES + 1
    last_provider_error = ""

    for attempt in range(attempts):
        try:
            raw = provider.generate_fix(payload)
        except AIProviderError as exc:
            last_provider_error = str(exc)
            logger.warning(
                "Fix provider error on attempt %d: %s", attempt + 1, exc
            )
            if attempt < attempts - 1:
                continue
            log_event(
                "ai.fix_error",
                level=logging.WARNING,
                issue_id=issue.pk,
                reason="provider_unreachable",
            )
            return FixResult(ok=False, error=_friendly_provider_error(last_provider_error))

        try:
            fix = _validate_fix(raw)
            if not fix.code.strip():
                return FixResult(
                    ok=False, error="The AI returned an empty fix. Please try again."
                )
            return FixResult(
                ok=True,
                explanation=fix.explanation,
                recommended_change=fix.recommended_change,
                code=fix.code,
                language=fix.language,
            )
        except (ValueError, ValidationError) as exc:
            logger.warning("Invalid fix response on attempt %d: %s", attempt + 1, exc)
            if attempt < attempts - 1:
                continue
            log_event(
                "ai.fix_error", level=logging.WARNING, issue_id=issue.pk, reason="invalid_response"
            )
            return FixResult(ok=False, error=str(exc))

    return FixResult(
        ok=False, error="The AI returned an empty fix. Please try again."
    )
