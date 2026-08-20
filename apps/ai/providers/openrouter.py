"""OpenRouter AI provider.

Talks to the OpenRouter ``chat/completions`` endpoint (OpenAI-compatible).
The model is read from ``OPENROUTER_MODEL`` and the API key
from ``OPENROUTER_API_KEY`` — never hardcoded.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings

from apps.ai.providers.base import AIProvider, AIProviderError
from apps.ai.prompts import build_analysis_schema, build_fix_schema, build_generation_config

logger = logging.getLogger(__name__)

API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterProvider(AIProvider):
    """OpenRouter provider driven entirely by Django settings."""

    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_ms: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        raw_key = api_key if api_key is not None else getattr(settings, "OPENROUTER_API_KEY", "")
        self.api_key = raw_key.strip().strip('"\'') if raw_key else ""

        raw_model = model if model is not None else getattr(settings, "OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        model_str = raw_model.strip().strip('"\'') if raw_model else "nvidia/nemotron-3-ultra-550b-a55b:free"
        self.model = model_str

        self.timeout_ms = (
            timeout_ms if timeout_ms is not None else getattr(settings, "OPENROUTER_TIMEOUT_MS", 120_000)
        )
        self.max_retries = (
            max_retries if max_retries is not None else getattr(settings, "OPENROUTER_MAX_RETRIES", 2)
        )

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _request(self, body: dict[str, Any]) -> str:
        try:
            import httpx
        except ImportError:  # pragma: no cover
            raise AIProviderError("httpx is not installed.")

        read_timeout_s = max(10.0, float(self.timeout_ms) / 1000.0)
        httpx_timeout = httpx.Timeout(read=read_timeout_s, connect=10.0, write=30.0, pool=10.0)

        primary_error: Exception | None = None
        last_error: Exception | None = None

        url = f"{API_BASE}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                time.sleep(1.0 * attempt)
            try:
                response = httpx.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=httpx_timeout,
                )
            except httpx.TimeoutException as exc:
                detail = str(exc).strip() or "timed out"
                last_error = AIProviderError(f"OpenRouter request timed out: {detail}")
                logger.warning("OpenRouter timed out (attempt %d): %s", attempt + 1, detail)
                continue
            except httpx.HTTPError as exc:
                detail = str(exc).strip() or "connection error"
                last_error = AIProviderError(f"OpenRouter HTTP error: {detail}")
                logger.warning("OpenRouter HTTP error (attempt %d): %s", attempt + 1, exc)
                continue

            if response.status_code == 200:
                data = response.json()
                usage = data.get("usage") or {}
                logger.info(
                    "OpenRouter usage (%s): prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    self.model,
                    usage.get("prompt_tokens", "?"),
                    usage.get("completion_tokens", "?"),
                    usage.get("total_tokens", "?"),
                )
                return self._extract_text(data)

            err_msg = (
                f"OpenRouter model {self.model} returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
            last_error = AIProviderError(err_msg)
            logger.warning(
                "OpenRouter error response (attempt %d): HTTP %d",
                attempt + 1, response.status_code
            )

            if response.status_code in (401, 403):
                raise last_error

            if response.status_code == 404:
                break

        if primary_error is None:
            primary_error = last_error

        raise AIProviderError(f"OpenRouter request failed: {primary_error or last_error}")

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
            if content and content.strip():
                return content
        except (KeyError, IndexError, TypeError):
            pass
        raise AIProviderError("OpenRouter response contained no text.")

    def _generate(self, payload: dict[str, Any], response_schema: dict[str, Any] | None = None) -> str:
        if not self.is_available():
            raise AIProviderError("No OPENROUTER_API_KEY configured.")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are an expert web UI/UX analyzer. Return only valid JSON."},
            {"role": "user", "content": payload["prompt"]},
        ]

        # Add images if enabled
        if settings.AI_SEND_IMAGES:
            for image in payload.get("images", []):
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {
                            "url": f"data:{image['mime_type']};base64,{image['data']}"
                        }}
                    ]
                })

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 8192,
        }

        if response_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "analysis",
                    "schema": response_schema,
                    "strict": True,
                }
            }

        logger.info(
            "Calling OpenRouter model %s with %d message(s)",
            self.model,
            len(messages),
        )
        return self._request(body)

    def analyze_ui(self, payload: dict[str, Any]) -> str:
        return self._generate(payload, build_analysis_schema())

    def generate_fix(self, payload: dict[str, Any]) -> str:
        return self._generate(payload, build_fix_schema())