r"""Offline smoke test: drives the real handlers with fake Discord objects.

Usage:
    venv\Scripts\python.exe tests\smoke_test.py
    (from the DiscordBot folder)

It hits the real APIs (DeepSeek, Tavily, Qwen, Pollinations), so it costs a
fraction of a cent and needs network access. No Discord connection is made.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.chdir(BASE)

import commands  # noqa: E402  (needs the path setup above)
import memory  # noqa: E402
import vision  # noqa: E402

_original_download = vision.download


async def _download(url: str, limit: int = 20 * 1024 * 1024) -> bytes:
    """Allow file:// URLs so the test can reuse a local sticker."""
    if url.startswith("file://"):
        from urllib.parse import unquote, urlparse

        return Path(unquote(urlparse(url).path.lstrip("/"))).read_bytes()
    return await _original_download(url, limit)


vision.download = _download  # type: ignore[assignment]


class FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeAttachment:
    def __init__(self, path: Path):
        self.url = path.as_uri()
        self.filename = path.name
        self.content_type = "image/png"
        self.path = path


class FakeChannel:
    def __init__(self, channel_id: int = 1):
        self.id = channel_id
        self.sent: list[str] = []
        self.files: list[str] = []

    def typing(self) -> FakeTyping:
        return FakeTyping()

    async def send(self, content: str | None = None, **kwargs):
        if content:
            self.sent.append(str(content))
        file = kwargs.get("file")
        if file is not None:
            self.files.append(getattr(file, "filename", "file"))
            file.close()


class FakeAuthor:
    def __init__(self, user_id: int = 42, name: str = "tester"):
        self.id = user_id
        self.name = name
        self.bot = False


class FakeMessage:
    def __init__(self, content: str, channel: FakeChannel, attachments=None):
        self.content = content
        self.channel = channel
        self.author = FakeAuthor()
        self.attachments = attachments or []
        self.created_at = dt.datetime.now(dt.timezone.utc)
        self.id = 1


def show(label: str, channel: FakeChannel) -> None:
    print(f"\n=== {label} ===")
    if not channel.sent and not channel.files:
        print("  (nothing sent)")
    for text in channel.sent:
        first = text.splitlines()[0] if text.strip() else ""
        print(f"  [{len(text)} chars] {first[:150]}")
    for name in channel.files:
        print(f"  [file] {name}")


async def main() -> int:
    channel = FakeChannel(channel_id=999)
    failures: list[str] = []

    async def run(label: str, content: str, expect_file: bool = False) -> None:
        message = FakeMessage(content, channel)
        before = len(channel.sent)
        before_files = len(channel.files)
        try:
            handled = await commands.handle_command(message)
            if not handled:
                await commands.chat(message, content)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: raised {type(exc).__name__}: {exc}")
            print(f"FAIL {label}: {exc}")
            return
        show(label, channel)
        if expect_file and len(channel.files) == before_files:
            failures.append(f"{label}: expected an image attachment")
        if not expect_file and len(channel.sent) == before:
            failures.append(f"{label}: produced no message")
        channel.sent.clear()
        channel.files.clear()

    await run("help", "#help")
    await run("ping", "#ping")
    await run("thinking", "#thinking")
    await run("model", "#model pro")
    await run("model back", "#model flash")
    await run("chat", "#hello PhiLia093, what is your name?")
    await run("search", "#search what is the latest Python version")
    await run("learn", "#learn PhiLia093's favourite tea is jasmine green tea")
    await run("knowledge", "#knowledge")
    await run("imagine", "#imagine a small robot drinking tea", expect_file=True)
    await run("news", "#news")
    await run("minecraft", "#mc status")
    await run("song", "#lets sing jasmine")

    # describe with a real sticker as attachment
    sticker_dir = BASE / "stickers" / "happy"
    image = next(sticker_dir.glob("*.png"), None) or next(sticker_dir.glob("*.*"))
    message = FakeMessage("#describe", channel, attachments=[FakeAttachment(image)])
    try:
        await commands.handle_command(message)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"describe: {exc}")
    show("describe", channel)
    channel.sent.clear()

    # undo what the test wrote (knowledge entry + preferences)
    entries = await memory.listing(limit=200)
    doomed = [entry_id for entry_id, doc in entries if "jasmine green tea" in doc]
    if doomed:
        await memory.delete(doomed)
    memory.prefs.set("thinking", 42, True)
    memory.prefs.set("model", 42, "flash")
    print(f"\ncleaned {len(doomed)} test knowledge entry(ies)")

    print("\n--- summary ---")
    if failures:
        for failure in failures:
            print("FAILED:", failure)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
