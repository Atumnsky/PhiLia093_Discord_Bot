"""Aternos Minecraft server control for Discord commands.

`aternos_helper.py` runs as a small daemon in a Python 3.11 environment (the
`python-aternos` library needs js2py, which does not work on 3.12). It logs in
once, polls the servers, and prints a JSON line whenever a server changes state.

This module keeps that daemon alive, turns its events into Discord
announcements, and sends it status/start requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import discord

from config import settings

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
HELPER = HERE / "aternos_helper.py"
FALLBACK_PYTHONS = (
    "/home/ubuntu/aternos-env/bin/python",
    "/opt/aternos-env/bin/python",
)

_client: "AternosDaemon | None" = None


class MCError(RuntimeError):
    pass


def configured() -> bool:
    return bool(
        settings.aternos_session
        or (settings.aternos_username and settings.aternos_password)
    )


def python_path() -> str:
    if settings.aternos_python:
        return settings.aternos_python
    for candidate in FALLBACK_PYTHONS:
        if Path(candidate).exists():
            return candidate
    return sys.executable


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "ATERNOS_USERNAME": settings.aternos_username,
            "ATERNOS_PASSWORD": settings.aternos_password,
            "ATERNOS_SESSION": settings.aternos_session,
            "ATERNOS_SERVER": settings.aternos_server,
            "ATERNOS_POLL": str(settings.aternos_poll),
        }
    )
    return env


class AternosDaemon:
    """Owns the helper subprocess and multiplexes requests over stdin/stdout."""

    def __init__(self, on_change=None) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._stderr: asyncio.Task | None = None
        self._stderr_tail: list[str] = []
        self.on_change = on_change

    async def ensure(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        interpreter = python_path()
        log.info("Starting Aternos daemon with %s", interpreter)
        self._process = await asyncio.create_subprocess_exec(
            interpreter,
            str(HELPER),
            "serve",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(),
        )
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr = asyncio.create_task(self._read_stderr())

    async def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            try:
                payload = json.loads(line.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue

            if payload.get("event") == "change":
                await self._emit_change(payload)
                continue

            future = self._pending.pop(payload.get("id"), None)
            if future is not None and not future.done():
                future.set_result(payload)

        for future in self._pending.values():
            if not future.done():
                reason = "; ".join(self._stderr_tail[-3:]) or "helper exited"
                future.set_exception(MCError(f"Aternos helper stopped: {reason}"))
        self._pending.clear()

    async def _read_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            if text:
                self._stderr_tail = (self._stderr_tail + [text])[-5:]
            log.debug("aternos: %s", text)

    async def _emit_change(self, payload: dict) -> None:
        if self.on_change is None:
            return
        try:
            await self.on_change(payload)
        except Exception:
            log.exception("Aternos change handler failed")

    async def request(self, command: str, server: str | None = None, timeout: float = 120) -> dict:
        if not configured():
            raise MCError(
                "Aternos is not configured: set ATERNOS_USERNAME / ATERNOS_PASSWORD in .env"
            )

        async with self._lock:
            await self.ensure()
            assert self._process is not None and self._process.stdin is not None
            self._sequence += 1
            request_id = self._sequence
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future

            message: dict = {"id": request_id, "cmd": command}
            if server:
                message["server"] = server
            self._process.stdin.write((json.dumps(message) + "\n").encode())
            await self._process.stdin.drain()

        try:
            payload = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise MCError("Aternos request timed out") from exc
        finally:
            self._pending.pop(request_id, None)

        if not payload.get("ok"):
            raise MCError(payload.get("error") or "Aternos returned an error")
        return payload

    async def close(self) -> None:
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass


def daemon() -> AternosDaemon:
    global _client
    if _client is None:
        _client = AternosDaemon()
    return _client


def format_players(info: dict) -> str:
    names = info.get("names") or []
    players = info.get("players", 0)
    slots = info.get("slots", "?")
    if names:
        return f"{players}/{slots} — {', '.join(names)}"
    return f"{players}/{slots}"


def format_status(info: dict) -> str:
    icon = "🟢" if info.get("state") == "online" else "⚪"
    return (
        f"{icon} **{info['name']}** (`{info['address']}`)\n"
        f"　状态 `{info['state']}` · 在线 {format_players(info)} · {info.get('software', '?')}"
    )


async def list_status() -> list[dict]:
    payload = await daemon().request("list", timeout=120)
    return payload.get("servers", [])


async def start(server: str | None = None) -> dict:
    return await daemon().request("start", server=server, timeout=180)


async def start_announcer(bot) -> None:
    """Wire daemon state changes to Discord and bring the daemon up."""
    if not configured():
        log.info("Aternos is not configured, #mc will stay disabled")
        return

    async def on_change(payload: dict) -> None:
        channel = bot.get_channel(settings.minecraft_channel)
        if channel is None:
            return
        state = payload.get("state")
        previous = payload.get("previous")
        if state == "online" and previous != "online":
            await channel.send(
                f"🟢 **{payload['name']} 开好了！**\n"
                f"`{payload['address']}` · 在线 {format_players(payload)} ♪",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        elif previous == "online" and state != "online":
            await channel.send(
                f"💤 **{payload['name']}** 下线了 ♪",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    client = daemon()
    client.on_change = on_change
    try:
        servers = await list_status()
        log.info(
            "Aternos: watching %s",
            ", ".join(f"{s['name']}({s['state']})" for s in servers),
        )
    except Exception as exc:
        log.warning("Could not query Aternos at startup: %s", exc)
