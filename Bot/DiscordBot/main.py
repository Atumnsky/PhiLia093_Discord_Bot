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
import stickers
from config import settings

log = logging.getLogger("philia")

_offline_sent = False


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
    logging.getLogger("chromadb").setLevel(logging.WARNING)


def pick_online_channel(bot: discord.Client) -> discord.abc.Messageable | None:
    """ONLINE_CHANNEL_ID, else the first chat channel, else any writable channel."""
    candidates = [settings.online_channel, *settings.chat_channels]
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


async def notify_offline(bot: discord.Client) -> None:
    global _offline_sent
    if _offline_sent:
        return
    _offline_sent = True
    channel = pick_online_channel(bot)
    if channel is not None:
        try:
            await channel.send("PhiLia093 is Offline! 👋")
        except Exception as exc:
            log.warning("Could not send offline message: %s", exc)


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
        log.info("Logged in as %s (id=%s)", bot.user, getattr(bot.user, "id", "?"))
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, name="#help ♪"
            )
        )
        channel = pick_online_channel(bot)
        if channel is not None:
            try:
                await channel.send("PhiLia093 is Online! ✨")
                guild = getattr(channel, "guild", None)
                log.info(
                    "Online message sent to %s#%s",
                    getattr(guild, "name", "DM"),
                    getattr(channel, "name", "?"),
                )
            except Exception as exc:
                log.warning("Could not send online message: %s", exc)
        else:
            log.warning("No writable channel found for the online message")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot or message.author.id == getattr(bot.user, "id", None):
            return

        try:
            if await commands.game_tick(message):
                return

            content = message.content.strip()
            in_chat_channel = message.channel.id in settings.chat_channels

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
        await notify_offline(bot)
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
        await notify_offline(bot)
        if not bot.is_closed():
            await bot.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
