"""Gemini multimodal AI provider.

Talks to the Gemini ``generateContent`` REST endpoint directly with ``httpx``
(no SDK dependency). The model is read from ``GEMINI_MODEL`` and the API key
from ``GEMINI_API_KEY`` — never hardcoded.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from django.conf import settings

from apps.ai.providers.base import AIProvider, AIProviderError
from apps.ai.prompts import build_analysis_schema, build_fix_schema, build_generation_config

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProvider):
    """Gemini provider driven entirely by Django settings."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_ms: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        raw_key = api_key if api_key is not None else getattr(settings, "GEMINI_API_KEY", "")
        self.api_key = raw_key.strip().strip('"\'') if raw_key else ""

        raw_model = model if model is not None else getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
        model_str = raw_model.strip().strip('"\'') if raw_model else "gemini-2.0-flash"
        self.model = model_str.removeprefix("models/").lstrip("/") if model_str else "gemini-2.0-flash"

        self.timeout_ms = (
            timeout_ms if timeout_ms is not None else getattr(settings, "GEMINI_TIMEOUT_MS", 30_000)
        )
        self.max_retries = (
            max_retries if max_retries is not None else getattr(settings, "GEMINI_MAX_RETRIES", 2)
        )

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _request(self, body: dict[str, Any]) -> str:
        try:
            import httpx
        except ImportError:  # pragma: no cover
            raise AIProviderError("httpx is not installed.")

        url = f"{API_BASE}/models/{self.model}:generateContent"
        # Determine authentication header variant order based on key format:
        # Standard Gemini API keys (AIza...) use x-goog-api-key.
        # OAuth access tokens (ya29... / AQ...) use Authorization: Bearer.
        auth_variants = (
            {"x-goog-api-key": self.api_key},
            {"Authorization": f"Bearer {self.api_key}"},
        )

        primary_error: Exception | None = None
        last_error: Exception | None = None

        for idx, headers in enumerate(auth_variants):
            should_try_next_auth = False
            for attempt in range(self.max_retries + 1):
                try:
                    response = httpx.post(
                        url,
                        headers=headers,
                        json=body,
                        timeout=httpx.Timeout(self.timeout_ms / 1000.0),
                    )
                except httpx.TimeoutException as exc:
                    detail = str(exc).strip() or "timed out"
                    last_error = AIProviderError(f"Gemini request timed out: {detail}")
                    logger.warning("Gemini request timed out (attempt %d): %s", attempt + 1, detail)
                    continue
                except httpx.HTTPError as exc:
                    detail = str(exc).strip() or "connection error"
                    last_error = AIProviderError(f"Gemini HTTP error: {detail}")
                    logger.warning("Gemini HTTP error (attempt %d): %s", attempt + 1, exc)
                    continue

                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usageMetadata") or {}
                    logger.info(
                        "Gemini usage: input_tokens=%s output_tokens=%s",
                        usage.get("promptTokenCount", "?"),
                        usage.get("candidatesTokenCount", "?"),
                    )
                    return self._extract_text(data)

                err_msg = (
                    f"Gemini returned HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
                last_error = AIProviderError(err_msg)
                logger.warning("Gemini error response (attempt %d): HTTP %d", attempt + 1, response.status_code)

                # For standard AIza... API keys, Bearer fallback will only return a misleading 401.
                # Stop fallback for AIza keys to preserve the true error response.
                if response.status_code in (401, 403):
                    if self.api_key.startswith("AIza"):
                        raise last_error
                    if response.status_code == 401:
                        should_try_next_auth = True
                    break

            if idx == 0:
                primary_error = last_error

            if not should_try_next_auth:
                break

        raise AIProviderError(f"Gemini request failed: {primary_error or last_error}")

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
            if text.strip():
                return text
        except (KeyError, IndexError, TypeError):
            pass
        raise AIProviderError("Gemini response contained no text.")

    def _generate(self, payload: dict[str, Any], response_schema: dict[str, Any] | None = None) -> str:
        if not self.is_available():
            raise AIProviderError("No GEMINI_API_KEY configured.")

        parts: list[dict[str, Any]] = [{"text": payload["prompt"]}]
        # Screenshots are the dominant input-token cost. They are only sent
        # when AI_SEND_IMAGES is enabled; text-only analysis keeps requests
        # in the low thousands of tokens.
        if settings.AI_SEND_IMAGES:
            for image in payload.get("images", []):
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": image["mime_type"],
                            "data": image["data"],
                        }
                    }
                )

        body = {
            "contents": [{"parts": parts}],
            "generationConfig": build_generation_config(response_schema),
        }
        logger.info(
            "Calling Gemini model %s with %d image(s) and %d text prompt chars",
            self.model,
            len(payload.get("images", [])) if settings.AI_SEND_IMAGES else 0,
            len(payload.get("prompt", "")),
        )
        return self._request(body)

    def analyze_ui(self, payload: dict[str, Any]) -> str:
        return self._generate(payload, build_analysis_schema())

    def generate_fix(self, payload: dict[str, Any]) -> str:
        return self._generate(payload, build_fix_schema())


def encode_image_bytes(data: bytes, mime_type: str = "image/jpeg") -> dict[str, str]:
    """Encode raw image bytes for the Gemini inline_data part."""
    return {"mime_type": mime_type, "data": base64.b64encode(data).decode("ascii")}
