"""Screenshot capture.

Capture lives here; persistence goes through Django's media storage
abstraction (passed in as a ``storage`` object) so S3-compatible backends can
be swapped in later without touching the scanner.

Screenshots are captured as JPEG (quality 60): roughly 10x smaller than PNG,
much faster to encode, and perfectly adequate for AI vision analysis. The
trade-off is slightly lower sharpness for text, which is irrelevant for the
AI's visual/UX reasoning.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

IMAGE_FORMAT = "jpeg"
IMAGE_QUALITY = 60
FULL_PAGE = False


def capture_screenshot(page: Page) -> bytes:
    """Capture a screenshot of the current page as JPEG bytes."""
    return page.screenshot(
        full_page=FULL_PAGE,
        type=IMAGE_FORMAT,
        quality=IMAGE_QUALITY,
    )


def _compress_image(data: bytes, max_bytes: int) -> bytes | None:
    """Downscale an image until it fits within ``max_bytes``.

    Returns the compressed bytes, or None if it cannot be brought under the
    limit. Pillow is required; if it is unavailable or compression fails, None
    is returned and the caller decides what to do.
    """
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.load()
        image = image.convert("RGB")
        scale = 1.0
        while scale >= 0.25:
            candidate = image
            if scale < 1.0:
                width = max(1, int(image.width * scale))
                height = max(1, int(image.height * scale))
                candidate = image.resize((width, height), Image.LANCZOS)
            buffer = io.BytesIO()
            candidate.save(buffer, format="JPEG", quality=IMAGE_QUALITY, optimize=True)
            compressed = buffer.getvalue()
            if len(compressed) <= max_bytes:
                return compressed
            scale *= 0.5
    except Exception:  # noqa: BLE001 - compression must never crash a scan
        logger.warning("Could not compress screenshot; dropping it.", exc_info=True)
    return None


def save_screenshot(
    storage: Any,
    data: bytes,
    *,
    scan_id: int | str,
    viewport_width: int,
    viewport_height: int,
    max_bytes: int | None = None,
) -> str:
    """Persist screenshot bytes through a Django storage backend.

    Returns the storage name (relative path), or ``""`` when the screenshot was
    dropped for exceeding ``MAX_SCREENSHOT_SIZE``. The name never leaks the
    absolute filesystem path to callers.
    """
    from django.conf import settings
    from django.core.files.base import ContentFile

    name = f"scans/{scan_id}/viewport-{viewport_width}x{viewport_height}.jpg"
    limit = settings.MAX_SCREENSHOT_SIZE if max_bytes is None else int(max_bytes)

    if len(data) > limit:
        compressed = _compress_image(data, limit)
        if compressed is not None:
            logger.info(
                "Compressed screenshot %s (%d -> %d bytes)", name, len(data), len(compressed)
            )
            data = compressed
        else:
            logger.warning("Screenshot %s exceeds size limit; not stored.", name)
            return ""

    storage.save(name, ContentFile(data))
    logger.info("Saved screenshot %s (%d bytes)", name, len(data))
    return name