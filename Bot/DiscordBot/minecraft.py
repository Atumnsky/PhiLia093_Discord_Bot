"""Aternos Minecraft server control for Discord commands.

The heavy lifting (login, Cloudflare bypass, start, polling) happens in
`aternos_helper.py`, which needs a Python able to run `python-aternos` (3.10/3.11
- js2py has no 3.12 support). This module only shells out to it and formats the
answer for Discord.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
HELPER = HERE / "aternos_helper.py"
START_TIMEOUT = 20 * 60
FALLBACK_PYTHONS = (
    "/home/ubuntu/aternos-env/bin/python",
    "/opt/aternos-env/bin/python",
)

_watcher: asyncio.Task | None = None


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
        }
    )
    return env


async def _run(*args: str, timeout: float) -> dict:
    interpreter = python_path()
    log.info("Aternos helper: %s %s", interpreter, " ".join(args))
    try:
        process = await asyncio.create_subprocess_exec(
            interpreter,
            str(HELPER),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(),
        )
    except FileNotFoundError as exc:
        raise MCError(f"Aternos helper interpreter not found: {interpreter}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        raise MCError("Aternos request timed out") from exc

    out = stdout.decode("utf-8", "replace").strip()
    err = stderr.decode("utf-8", "replace").strip()
    if err:
        log.debug("Aternos helper stderr: %s", err[-800:])

    if not out:
        raise MCError("Aternos helper returned nothing" + (f": {err[-200:]}" if err else ""))

    line = out.splitlines()[-1]
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MCError(f"Aternos helper returned junk: {line[:200]}") from exc

    if not payload.get("ok"):
        raise MCError(payload.get("error") or "Aternos returned an error")
    return payload


async def status() -> dict:
    if not configured():
        raise MCError("Aternos is not configured: set ATERNOS_USERNAME / ATERNOS_PASSWORD in .env")
    return await _run("status", timeout=90)


async def start() -> dict:
    if not configured():
        raise MCError("Aternos is not configured: set ATERNOS_USERNAME / ATERNOS_PASSWORD in .env")
    return await _run("start", timeout=120)


def _format_players(info: dict) -> str:
    names = info.get("names") or []
    players = info.get("players", 0)
    slots = info.get("slots", "?")
    if names:
        return f"{players}/{slots} — {', '.join(names)}"
    return f"{players}/{slots}"


async def watch_until_online(channel) -> None:
    """Wait for the server to come up (the helper polls Aternos) and report."""
    try:
        info = await _run("wait", str(START_TIMEOUT), timeout=START_TIMEOUT + 120)
    except MCError as exc:
        await channel.send(f"⌛ The server did not come up: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Aternos wait failed")
        await channel.send(f"⌛ Error while waiting for the server: {exc}")
        return

    await channel.send(
        f"✅ **The server is up!**\n"
        f"Address: `{info['address']}`\n"
        f"Players: {_format_players(info)}\n"
        f"Version: {info.get('software', '?')} · took {info.get('elapsed', '?')}s ♪\n"
        f"Come join~"
    )


def spawn_watcher(channel) -> bool:
    global _watcher
    if _watcher is not None and not _watcher.done():
        return False
    _watcher = asyncio.create_task(watch_until_online(channel))
    return True
