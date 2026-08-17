"""Screenshot optimization for AI requests.

Gemini requests are billed by payload size, so screenshots are downscaled and
re-encoded to JPEG before being sent. The originals stored for the dashboard
are never touched.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:  # pragma: no cover - Pillow is in requirements
    _HAS_PIL = False
    Image = None


def optimize_screenshot(
    data: bytes,
    *,
    max_width: int = 1024,
    quality: int = 70,
) -> bytes:
    """Resize and compress a PNG screenshot into a compact JPEG.

    Returns the optimized bytes. If Pillow is unavailable the input is
    returned unchanged so the pipeline never breaks.
    """
    if not _HAS_PIL or not data:
        return data
    try:
        image = Image.open(io.BytesIO(data))
        image = image.convert("RGB")
        if image.width > max_width:
            new_height = round(image.height * max_width / image.width)
            image = image.resize((max_width, new_height), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 - never break the scan for an image
        logger.warning("Could not optimize screenshot; sending original.")
        return data
