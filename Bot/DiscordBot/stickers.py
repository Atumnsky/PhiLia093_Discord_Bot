"""Local sticker collection, grouped by emotion folder."""

from __future__ import annotations

import io
import logging
import os
import random
from typing import Tuple

import discord
from PIL import Image, ImageSequence

from config import settings

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MAX_EDGE = 150  # keep stickers small so they do not fill the chat window

_stickers: dict[str, list[str]] = {}


def load() -> None:
    """Scan STICKERS_DIR; each subfolder is an emotion."""
    _stickers.clear()
    root = settings.stickers_dir
    if not root.exists():
        log.warning("Sticker folder %s does not exist, skipping", root)
        return

    for emotion in sorted(os.listdir(root)):
        folder = root / emotion
        if not folder.is_dir():
            continue
        files = [
            str(folder / name)
            for name in sorted(os.listdir(folder))
            if name.lower().endswith(IMAGE_SUFFIXES)
        ]
        if files:
            _stickers[emotion.lower()] = files

    log.info("Loaded stickers: %s", ", ".join(sorted(_stickers)) or "none")


def emotions() -> list[str]:
    return sorted(_stickers)


def _shrink(path: str) -> Tuple[io.BytesIO, str]:
    """Resize a sticker to MAX_EDGE, keeping animation for GIFs."""
    try:
        image = Image.open(path)

        if getattr(image, "is_animated", False):
            frames = []
            duration = image.info.get("duration", 80)
            for frame in ImageSequence.Iterator(image):
                converted = frame.convert("RGBA")
                converted.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                frames.append(converted)
            buffer = io.BytesIO()
            frames[0].save(
                buffer,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,
                disposal=2,
            )
            buffer.seek(0)
            return buffer, "sticker.gif"

        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if image.mode in ("RGBA", "LA", "P"):
            image.convert("RGBA").save(buffer, format="PNG")
            return buffer, "sticker.png"
        image.convert("RGB").save(buffer, format="JPEG", quality=88)
        return buffer, "sticker.jpg"
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not resize sticker %s: %s", path, exc)
        with open(path, "rb") as handle:
            return io.BytesIO(handle.read()), os.path.basename(path)


async def send(channel, emotion: str) -> bool:
    emotion = emotion.lower().strip()
    files = _stickers.get(emotion)
    if not files:
        return False

    path = random.choice(files)
    buffer, filename = _shrink(path)
    try:
        await channel.send(
            file=discord.File(buffer, filename=filename),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not send sticker %s: %s", path, exc)
        return False
