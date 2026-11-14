"""Daily news digest.

Once a day (at NEWS_TIME + a random jitter) the bot searches the web, picks the
single most interesting global story and posts a short summary plus its own two
cents. `#news` triggers the same thing on demand.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime, timedelta

import discord

import ai
import search
from config import settings
from constants import SYSTEM_PROMPT, language_rule

log = logging.getLogger(__name__)

STATE_FILE = settings.data_dir / "state.json"
STICKER_TAG = re.compile(r"\[STICKER:\s*[a-zA-Z_]+\s*\]", re.IGNORECASE)

_prompt = (
    "Pick the single hottest story from the news results above. "
    "Write 2-3 sentences on what happened, one short personal reaction, "
    "then one question that invites me to chat. "
    "Then add a new line exactly like: '📈 Trending today: ' followed by 5 short "
    "keywords or topics (1-3 words each) separated by ' · ', drawn from the "
    "trends results below (if they are useless, infer from the headlines). "
    "Keep everything under 700 characters, warm tone, end with ♪. "
    "You may append one [STICKER: emotion] tag."
)


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
    except Exception:
        log.exception("Could not save state")


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour, minute = value.strip().split(":")
        return int(hour) % 24, int(minute) % 60
    except Exception:
        return 9, 30


def next_run_from(now: datetime) -> datetime:
    hour, minute = _parse_time(settings.news_time)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target += timedelta(minutes=random.randint(0, settings.news_jitter))
    if target <= now:
        target += timedelta(days=1)
    return target


async def _post(channel, text: str) -> None:
    """Send without pings and without link previews."""
    message = await channel.send(
        text, allowed_mentions=discord.AllowedMentions.none()
    )
    if "http" in text:
        try:
            await message.edit(suppress=True)
        except Exception:
            log.debug("Could not suppress embeds", exc_info=True)


async def compose(channel) -> str:
    """Search, write and post the daily story. Returns the text (may be empty)."""
    outcome, trends = await asyncio.gather(
        search.web_search("top world news today", 6),
        search.web_search("what people are searching for today google trends", 4),
    )

    now = datetime.now(settings.tz)
    system = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": language_rule(settings.reply_language)},
        {
            "role": "system",
            "content": (
                f"IMPORTANT: right now it is {now.strftime('%Y-%m-%d %H:%M %Z')} "
                f"({now.strftime('%A')}). Use this as the truth for any date question."
            ),
        },
        {
            "role": "system",
            "content": (
                f"Web search results for today's world news:\n\n{outcome.text}\n\n{_prompt}"
                if outcome.found
                else f"The web search returned nothing usable.\n\n{_prompt}"
            ),
        },
    ]

    if trends.found:
        system.append(
            {
                "role": "system",
                "content": "Search trends results (for the trending list):\n\n"
                + trends.text,
            }
        )

    try:
        reply = await ai.complete(system, thinking=False, max_tokens=800)
    except ai.ChatError as exc:
        log.warning("News generation failed: %s", exc)
        return ""

    if not reply:
        return ""

    text = STICKER_TAG.sub("", reply).strip()
    sticker = STICKER_TAG.search(reply)

    await _post(channel, text)
    if sticker:
        import stickers

        emotion = sticker.group(0).split(":")[1].strip(" ]").lower()
        await stickers.send(channel, emotion)

    if outcome.links:
        sources = "\n".join(f"[{i + 1}] {url}" for i, url in enumerate(outcome.links[:3]))
        await _post(channel, f"**Sources:**\n{sources}")

    return reply


async def scheduler(bot, fallback_channel_id: int = 0) -> None:
    """Background loop; posts once per day (jittered) when enabled."""
    if not settings.news_enabled:
        log.info("Daily news is disabled")
        return

    channel_id = settings.news_channel or fallback_channel_id
    await asyncio.sleep(20)  # let the gateway settle first

    while True:
        now = datetime.now(settings.tz)
        target = next_run_from(now)
        log.info(
            "Next daily news at %s", target.strftime("%Y-%m-%d %H:%M %Z")
        )

        while datetime.now(settings.tz) < target:
            remaining = (target - datetime.now(settings.tz)).total_seconds()
            await asyncio.sleep(max(30, min(600, remaining)))

        today = datetime.now(settings.tz).date().isoformat()
        state = _load_state()
        if state.get("last_news") == today:
            log.info("News already posted today, skipping")
            await asyncio.sleep(60)
            continue

        channel = bot.get_channel(channel_id)
        if channel is None:
            log.warning("News channel %s not found", channel_id)
            await asyncio.sleep(600)
            continue

        try:
            await compose(channel)
            state["last_news"] = today
            _save_state(state)
            log.info("Daily news posted")
        except Exception:
            log.exception("Daily news failed")
        await asyncio.sleep(60)
