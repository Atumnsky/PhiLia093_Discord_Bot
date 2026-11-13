"""PhiLia093 / Cyrene — Discord entry point.

Run with:  python main.py
Windows:   start_bot.bat
Linux:     pm2 start ecosystem.config.js
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler

import discord

import commands
import news
import stickers
from config import settings

log = logging.getLogger("philia")

_chat_channels: list[int] = []
_news_started = False


def resolve_chat_channels(bot: discord.Client) -> list[int]:
    """Configured IDs that still exist, else a channel found by name."""
    found: list[int] = []
    for channel_id in settings.chat_channels:
        if bot.get_channel(channel_id) is not None:
            found.append(channel_id)
        else:
            log.warning(
                "Chat channel %s does not exist any more - ignoring it", channel_id
            )
    if found:
        return found

    for guild in bot.guilds:
        for name in settings.chat_channel_names:
            channel = discord.utils.get(guild.text_channels, name=name)
            if channel is not None:
                found.append(channel.id)
                log.info("Auto-detected chat channel #%s (id=%s)", channel.name, channel.id)
                break
        if found:
            break

    if not found:
        log.warning(
            "No chat channel found - plain messages will be ignored. Set "
            "PHILIA093_CHAT_CHANNEL, or create a channel named #%s.",
            settings.chat_channel_names[0] if settings.chat_channel_names else "cyrene-chat",
        )
    return found


def setup_logging() -> None:
    try:  # Windows consoles default to cp1252, which cannot print Chinese
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(
        RotatingFileHandler(
            settings.data_dir / "bot.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)


def pick_online_channel(bot: discord.Client) -> discord.abc.Messageable | None:
    """ONLINE_CHANNEL_ID, else the first chat channel, else any writable channel."""
    candidates = [settings.online_channel, *_chat_channels, *settings.chat_channels]
    for channel_id in candidates:
        if not channel_id:
            continue
        channel = bot.get_channel(channel_id)
        if channel is not None:
            return channel

    for guild in bot.guilds:
        me = guild.me
        for channel in guild.text_channels:
            if me is not None and channel.permissions_for(me).send_messages:
                return channel
    return None


async def announce(bot: discord.Client, text: str) -> None:
    """Optional status notice; disabled unless STATUS_MESSAGES=true."""
    if not settings.status_messages:
        return
    channel = pick_online_channel(bot)
    if channel is None:
        return
    try:
        await channel.send(text)
        guild = getattr(channel, "guild", None)
        log.info(
            "Status message sent to %s#%s",
            getattr(guild, "name", "DM"),
            getattr(channel, "name", "?"),
        )
    except Exception as exc:
        log.warning("Could not send status message: %s", exc)


async def run() -> None:
    setup_logging()
    stickers.load()

    if not settings.chat_channels:
        log.warning(
            "PHILIA093_CHAT_CHANNEL is empty or invalid - the bot will only answer "
            "messages that start with '#'."
        )

    intents = discord.Intents.default()
    intents.message_content = True
    bot = discord.Client(intents=intents)

    stopping = asyncio.Event()

    @bot.event
    async def on_ready() -> None:
        global _chat_channels, _news_started
        _chat_channels = resolve_chat_channels(bot)
        log.info("Logged in as %s (id=%s)", bot.user, getattr(bot.user, "id", "?"))
        log.info(
            "Chat channels: %s",
            ", ".join(str(c) for c in _chat_channels) or "none",
        )
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, name="#help ♪"
            )
        )

        if not _news_started:
            _news_started = True
            fallback = _chat_channels[0] if _chat_channels else 0
            asyncio.create_task(news.scheduler(bot, fallback))
        channel = pick_online_channel(bot)
        if settings.status_messages:
            await announce(bot, "PhiLia093 is Online! ✨")
        elif channel is None:
            log.warning("No writable channel found")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot or message.author.id == getattr(bot.user, "id", None):
            return

        try:
            if await commands.game_tick(message):
                return

            content = message.content.strip()
            in_chat_channel = message.channel.id in _chat_channels

            if in_chat_channel and not content.startswith("#"):
                if content:
                    await commands.chat(message, content)
                return

            if content.startswith("#"):
                await commands.handle_command(message)
        except Exception:
            log.exception("Unhandled error while processing a message")
            try:
                await message.channel.send("⚠️ Something broke on my side, sorry.")
            except Exception:
                pass

    async def shutdown(*_: object) -> None:
        if stopping.is_set():
            return
        stopping.set()
        log.info("Shutting down...")
        await announce(bot, "PhiLia093 is Offline! 👋")
        await bot.close()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except (NotImplementedError, RuntimeError, AttributeError):
            pass  # Windows

    try:
        await bot.start(settings.discord_token)
    except asyncio.CancelledError:
        await shutdown()
    except discord.LoginFailure:
        log.error("Discord rejected the token - check DISCORD_TOKEN in .env")
        raise SystemExit(1)
    except KeyboardInterrupt:
        await shutdown()
    finally:
        await announce(bot, "PhiLia093 is Offline! 👋")
        if not bot.is_closed():
            await bot.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
