#!/usr/bin/env python3
"""Aternos bridge for the Discord bot.

Runs under a Python that can execute `python-aternos` (3.10/3.11 - js2py does not
support 3.12). The bot calls it as a subprocess and reads the JSON on stdout.

    python aternos_helper.py status
    python aternos_helper.py start
    python aternos_helper.py wait [timeout_seconds]

Environment: ATERNOS_USERNAME, ATERNOS_PASSWORD, ATERNOS_SESSION, ATERNOS_SERVER
"""

from __future__ import annotations

import json
import os
import sys
import time

POLL = 10
ONLINE_STATES = {"online"}
ONLINE_CODES = {2}


def emit(payload: dict, code: int = 0) -> None:
    print(json.dumps(payload), flush=True)
    sys.exit(code)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_client():
    from python_aternos import Client

    session = os.environ.get("ATERNOS_SESSION", "").strip()
    username = os.environ.get("ATERNOS_USERNAME", "").strip()
    password = os.environ.get("ATERNOS_PASSWORD", "").strip()

    client = Client()
    # 3.0.x exposes login()/login_with_session(); 3.1 adds from_credentials().
    if session:
        client.login_with_session(session)
        return client
    if username and password:
        client.login(username, password)
        return client
    raise RuntimeError(
        "Aternos credentials missing: set ATERNOS_USERNAME/ATERNOS_PASSWORD "
        "(or ATERNOS_SESSION) in .env"
    )


def list_servers(client):
    # 3.0.x keeps the list on the account object, 3.1 moves it to the client.
    account = getattr(client, "account", None)
    if account is not None and hasattr(account, "list_servers"):
        return account.list_servers()
    return client.list_servers()


def pick_server(client):
    servers = list_servers(client)
    if not servers:
        raise RuntimeError("This Aternos account cannot see any servers")

    wanted = os.environ.get("ATERNOS_SERVER", "").strip().lower()
    if wanted:
        for server in servers:
            info = getattr(server, "_info", {}) or {}
            haystack = " ".join(
                str(info.get(key, "")) for key in ("name", "ip", "displayAddress")
            ).lower()
            if wanted in haystack:
                return server
    return servers[0]


def state_of(info: dict) -> str:
    """Aternos exposes both a CSS class ('offline', 'loading', 'online') and a
    numeric status; prefer the readable one."""
    css = str(info.get("class", "")).strip().lower()
    if css:
        return css.split()[0]
    code = info.get("status")
    try:
        return {0: "offline", 2: "online", 6: "loading", 7: "error", 10: "preparing"}.get(
            int(code), str(code)
        )
    except (TypeError, ValueError):
        return "unknown"


def is_online(info: dict) -> bool:
    if state_of(info) in ONLINE_STATES:
        return True
    try:
        return int(info.get("status")) in ONLINE_CODES
    except (TypeError, ValueError):
        return False


def address_of(info: dict, server) -> str:
    host = info.get("ip") or info.get("displayAddress") or ""
    if not host:
        subdomain = getattr(server, "subdomain", "") or ""
        host = f"{subdomain}.aternos.me" if subdomain else "?"
    port = info.get("port")
    return f"{host}:{port}" if port else host


def snapshot(server) -> dict:
    server.fetch()
    info = getattr(server, "_info", {}) or {}
    return {
        "ok": True,
        "address": address_of(info, server),
        "state": state_of(info),
        "label": info.get("label") or state_of(info),
        "players": info.get("players", 0),
        "slots": info.get("slots", "?"),
        "names": list(info.get("playerlist") or []),
        "software": f"{info.get('software', '?')} {info.get('version', '')}".strip(),
        "name": info.get("name") or "",
    }


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 1200

    try:
        client = build_client()
        server = pick_server(client)
    except Exception as exc:
        emit({"ok": False, "error": str(exc)}, 1)

    try:
        if command == "status":
            emit(snapshot(server))

        if command == "start":
            info = snapshot(server)
            if is_online(info):
                info["already"] = True
                emit(info)
            server.start()
            try:
                server.confirm()
            except Exception:
                pass
            time.sleep(3)
            fresh = snapshot(server)
            fresh["already"] = False
            emit(fresh)

        if command == "wait":
            started = time.time()
            last = ""
            while time.time() - started < timeout:
                try:
                    info = snapshot(server)
                except Exception as exc:
                    log(f"poll failed: {exc}")
                    time.sleep(POLL)
                    continue
                if info["state"] != last:
                    log(f"state -> {info['state']}")
                    last = info["state"]
                if is_online(info):
                    info["elapsed"] = int(time.time() - started)
                    emit(info)
                time.sleep(POLL)
            emit(
                {
                    "ok": False,
                    "error": f"still not online after {timeout}s (last state: {last or 'unknown'})",
                    "state": last,
                },
                2,
            )

        emit({"ok": False, "error": f"unknown command: {command}"}, 3)
    except Exception as exc:
        emit({"ok": False, "error": str(exc)}, 1)


if __name__ == "__main__":
    main()
