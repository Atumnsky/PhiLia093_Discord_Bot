"""Image generation.

Default backend is Pollinations.ai: free, keyless, no account.
Aliyun Qwen-Image is optional and only used for `hq` requests and edits.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp

from config import settings

log = logging.getLogger(__name__)

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
ALIYUN_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)


class ImageError(RuntimeError):
    pass


class RateLimited(ImageError):
    """The free backend allows one image per ~45s per IP."""

    def __init__(self, seconds: int) -> None:
        self.seconds = max(1, seconds)
        super().__init__(f"rate limited for {self.seconds}s")


@dataclass
class Picture:
    data: bytes
    source: str
    filename: str = "image.jpg"


async def _download(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as response:
        if response.status == 402:
            try:
                retry_after = int(response.headers.get("Retry-After", 45))
            except (TypeError, ValueError):
                retry_after = 45
            raise RateLimited(retry_after)
        if response.status != 200:
            raise ImageError(f"Download failed with HTTP {response.status}")
        return await response.read()


async def generate(prompt: str, *, hq: bool = False, count: int = 1) -> list[Picture]:
    """Generate `count` pictures. Raises ImageError with a readable reason."""
    prompt = prompt.strip()[:1500]
    if not prompt:
        raise ImageError("Empty prompt")

    use_aliyun = hq and bool(settings.aliyun_key)
    if not use_aliyun and settings.image_provider == "aliyun" and settings.aliyun_key:
        use_aliyun = True

    try:
        if use_aliyun:
            return await _aliyun_generate(prompt, count)
        return await _pollinations_generate(prompt)
    except ImageError:
        # Already has a user-facing message; never fall back to the paid
        # backend silently.
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("Image generation failed: %s", exc)
        raise ImageError("image generation failed, try again in a moment") from exc


async def _pollinations_generate(prompt: str) -> list[Picture]:
    size = settings.image_size
    last_error: Exception | None = None

    for attempt in range(3):
        seed = random.randint(1, 2_000_000_000)
        url = (
            POLLINATIONS_URL.format(prompt=quote(prompt, safe=""))
            + f"?width={size}&height={size}"
            + f"&model={quote(settings.pollinations_model)}"
            + f"&seed={seed}&nologo=true&private=true"
        )
        try:
            async with aiohttp.ClientSession() as session:
                data = await _download(session, url)
            if len(data) < 2000:
                raise ImageError("the free service returned an empty image")
            return [
                Picture(data=data, source="pollinations", filename=f"philia_{seed}.jpg")
            ]
        except RateLimited as exc:
            # Waiting 45s inside a chat turn is too long; tell the user how long.
            if exc.seconds <= 12:
                log.info("Rate limited, waiting %ss", exc.seconds)
                await asyncio.sleep(exc.seconds + 2)
                continue
            raise ImageError(
                f"the free image service allows one image every ~45s - "
                f"try again in {exc.seconds}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.info("Pollinations attempt %s failed: %r", attempt + 1, exc)
            await asyncio.sleep(1.5 * (attempt + 1))

    raise ImageError(
        "the free image service is busy right now, try again in a moment"
    ) from last_error


async def _aliyun_generate(prompt: str, count: int) -> list[Picture]:
    payload = {
        "model": settings.aliyun_image_model,
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": {
            "negative_prompt": (
                "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，"
                "人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。"
            ),
            "size": settings.aliyun_image_size,
            "n": max(1, min(4, count)),
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.aliyun_key}",
        "Content-Type": "application/json",
    }
    urls = await _aliyun_call(payload, headers)
    if not urls:
        raise ImageError("Aliyun returned no image")

    pictures: list[Picture] = []
    async with aiohttp.ClientSession() as session:
        for index, url in enumerate(urls):
            try:
                data = await _download(session, url)
            except Exception as exc:
                log.warning("Could not download generated image: %s", exc)
                continue
            pictures.append(
                Picture(data=data, source="aliyun", filename=f"philia_hq_{index}.png")
            )
    if not pictures:
        raise ImageError("Could not download generated image")
    return pictures


async def edit(image_bytes: bytes, instruction: str) -> list[Picture]:
    """Edit an uploaded image (Aliyun only, there is no free equivalent)."""
    if not settings.aliyun_key:
        raise ImageError(
            "Image editing needs ALIYUN_API_KEY (Qwen-Image). "
            "Add it to .env or use #imagine instead."
        )

    import base64

    from vision import compress

    compressed = compress(image_bytes)
    encoded = base64.b64encode(compressed).decode("ascii")

    payload = {
        "model": settings.aliyun_edit_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": f"data:image/jpeg;base64,{encoded}"},
                        {"text": instruction.strip()[:1000]},
                    ],
                }
            ]
        },
        "parameters": {},
    }
    headers = {
        "Authorization": f"Bearer {settings.aliyun_key}",
        "Content-Type": "application/json",
    }
    urls = await _aliyun_call(payload, headers)
    if not urls:
        raise ImageError("Aliyun returned no edited image")

    pictures: list[Picture] = []
    async with aiohttp.ClientSession() as session:
        for index, url in enumerate(urls):
            data = await _download(session, url)
            pictures.append(
                Picture(data=data, source="aliyun-edit", filename=f"philia_edit_{index}.png")
            )
    return pictures


async def _aliyun_call(payload: dict, headers: dict) -> list[str]:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            ALIYUN_URL,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            body = await response.text()
            if response.status != 200:
                log.warning("Aliyun image HTTP %s: %s", response.status, body[:300])
                raise ImageError(f"Aliyun returned HTTP {response.status}")

    import json

    data = json.loads(body)
    try:
        content = data["output"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return []
    return [item["image"] for item in content if isinstance(item, dict) and "image" in item]
