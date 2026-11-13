"""Aternos Minecraft server control.

Uses the unofficial `python-aternos` library (pip install python-aternos).
It logs in with the account credentials from .env and talks to Aternos' private
web API, so it can start a server and report when it is actually online.

Note: Aternos' ToS forbids automated access. Use at your own risk.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from config import settings

log = logging.getLogger(__name__)

START_TIMEOUT = 20 * 60  # Aternos queues can be long
POLL_INTERVAL = 15

_client = None
_client_lock = threading.Lock()
_watcher: asyncio.Task | None = None


class MCError(RuntimeError):
    pass


def configured() -> bool:
    return bool(
        settings.aternos_session
        or (settings.aternos_username and settings.aternos_password)
    )


def _get_client():
    global _client
    try:
        from python_aternos import Client
    except ImportError as exc:
        raise MCError(
            "python-aternos is not installed: pip install python-aternos"
        ) from exc

    with _client_lock:
        if _client is None:
            if settings.aternos_session:
                _client = Client.from_session(settings.aternos_session)
            elif settings.aternos_username and settings.aternos_password:
                _client = Client.from_credentials(
                    settings.aternos_username, settings.aternos_password
                )
            else:
                raise MCError(
                    "Aternos is not configured: set ATERNOS_USERNAME / ATERNOS_PASSWORD in .env"
                )
        return _client


def _pick_server(client):
    servers = client.list_servers()
    if not servers:
        raise MCError("This Aternos account has no servers")

    wanted = (settings.aternos_server or "").lower().strip()
    if wanted:
        for server in servers:
            haystack = f"{server.address} {server.subdomain or ''}".lower()
            if wanted in haystack:
                return server
    return servers[0]


def _status_sync() -> dict:
    server = _pick_server(_get_client())
    server.fetch()
    return {
        "address": f"{server.domain}:{server.port}",
        "status": server.status,
        "players": server.players_count,
        "slots": server.slots,
        "names": list(server.players_list or []),
        "software": f"{server.software} {server.version}",
    }


def _start_sync() -> dict:
    server = _pick_server(_get_client())
    server.fetch()
    if server.status == "online":
        return {
            "address": f"{server.domain}:{server.port}",
            "status": "online",
            "already": True,
            "players": server.players_count,
            "slots": server.slots,
            "names": list(server.players_list or []),
            "software": f"{server.software} {server.version}",
        }

    try:
        server.start()
    except Exception as exc:
        raise MCError(str(exc)) from exc

    try:  # 确认启动（部分账号需要）
        server.confirm()
    except Exception:
        pass

    server.fetch()
    return {
        "address": f"{server.domain}:{server.port}",
        "status": server.status,
        "already": False,
        "software": f"{server.software} {server.version}",
    }


async def status() -> dict:
    if not configured():
        raise MCError("Aternos is not configured yet - add your account to .env")
    return await asyncio.to_thread(_status_sync)


async def start() -> dict:
    if not configured():
        raise MCError("Aternos is not configured yet - add your account to .env")
    return await asyncio.to_thread(_start_sync)


def _format_players(info: dict) -> str:
    names = info.get("names") or []
    players = info.get("players", 0)
    slots = info.get("slots", "?")
    if names:
        return f"{players}/{slots} — {', '.join(names)}"
    return f"{players}/{slots}"


async def watch_until_online(channel) -> None:
    """Poll Aternos until the server is up (or we give up) and say so."""
    deadline = time.time() + START_TIMEOUT
    last_status = None
    announce_every = 120
    last_announce = 0.0

    while time.time() < deadline:
        try:
            info = await status()
        except Exception as exc:
            log.warning("Status poll failed: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)
            continue

        state = info.get("status", "unknown")
        if state != last_status:
            log.info("Aternos status: %s", state)
            last_status = state

        if state == "online":
            await channel.send(
                f"✅ **The server is up!**\n"
                f"Address: `{info['address']}`\n"
                f"Players: {_format_players(info)} ♪\n"
                f"Come join whenever you like~"
            )
            return

        now = time.time()
        if now - last_announce > announce_every and now - (deadline - START_TIMEOUT) > 60:
            last_announce = now
            if state in {"queue", "loading", "preparing", "starting"}:
                await channel.send(f"⏳ Still queued/starting (status: {state}), I keep watching ♪")
        await asyncio.sleep(POLL_INTERVAL)

    await channel.send(
        "⌛ Still not up after 20 minutes - the queue may be long or the launch "
        "failed. You can check the Aternos website ♪"
    )


def spawn_watcher(channel) -> bool:
    """Start the polling task once. Returns False if one is already running."""
    global _watcher
    if _watcher is not None and not _watcher.done():
        return False
    _watcher = asyncio.create_task(watch_until_online(channel))
    return True
