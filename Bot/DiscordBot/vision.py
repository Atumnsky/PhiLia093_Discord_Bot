"""Image understanding through any OpenAI-compatible vision endpoint.

Default: Aliyun DashScope compatible mode with qwen3-vl-plus.
Any provider exposing /chat/completions works via VISION_BASE_URL/VISION_MODEL.
"""

from __future__ import annotations

import base64
import io
import logging

import aiohttp
from PIL import Image

from config import settings

log = logging.getLogger(__name__)

MAX_EDGE = 1024
TARGET_BYTES = 4 * 1024 * 1024


class VisionError(RuntimeError):
    pass


def compress(image_bytes: bytes) -> bytes:
    """Resize to <=1024px on the long edge and re-encode as JPEG."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)

        quality = 90
        buffer = io.BytesIO()
        while quality >= 40:
            buffer.seek(0)
            buffer.truncate()
            image.save(buffer, format="JPEG", quality=quality)
            if buffer.tell() <= TARGET_BYTES:
                return buffer.getvalue()
            quality -= 10
        return buffer.getvalue()
    except Exception as exc:
        log.warning("Could not compress image (%s), sending original", exc)
        return image_bytes


async def describe(image_bytes: bytes, prompt: str) -> str:
    """Return a text description / answer about the image."""
    if not settings.vision_key:
        raise VisionError(
            "Image recognition is not configured: set ALIYUN_API_KEY or VISION_API_KEY."
        )

    payload = await _payload(image_bytes, prompt)
    url = settings.vision_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.vision_key}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            body = await response.text()
            if response.status != 200:
                log.warning("Vision HTTP %s: %s", response.status, body[:300])
                raise VisionError(f"Vision API returned HTTP {response.status}")

    import json

    data = json.loads(body)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise VisionError("Unexpected vision response") from exc

    if isinstance(content, list):
        content = " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return (content or "").strip()


async def _payload(image_bytes: bytes, prompt: str) -> dict:
    compressed = await _compress_async(image_bytes)
    encoded = base64.b64encode(compressed).decode("ascii")
    return {
        "model": settings.vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }


async def _compress_async(image_bytes: bytes) -> bytes:
    import asyncio

    return await asyncio.to_thread(compress, image_bytes)


async def download(url: str, limit: int = 20 * 1024 * 1024) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=60)
        ) as response:
            if response.status != 200:
                raise VisionError(f"Download failed with HTTP {response.status}")
            return await response.read()
