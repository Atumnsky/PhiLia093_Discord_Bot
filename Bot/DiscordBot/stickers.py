"""Local sticker collection, grouped by emotion folder."""

from __future__ import annotations

import logging
import os
import random

import discord

from config import settings

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
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


async def send(channel, emotion: str) -> bool:
    emotion = emotion.lower().strip()
    files = _stickers.get(emotion)
    if not files:
        return False
    path = random.choice(files)
    try:
        await channel.send(file=discord.File(path))
        return True
    except Exception as exc:
        log.warning("Could not send sticker %s: %s", path, exc)
        return False
