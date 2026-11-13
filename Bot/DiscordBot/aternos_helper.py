#!/usr/bin/env python3
"""Aternos bridge for the Discord bot.

This script must run under a Python that can execute `python-aternos`
(3.10/3.11 - js2py does not work on 3.12). The bot calls it as a subprocess and
reads the JSON it prints on stdout.

    python aternos_helper.py status
    python aternos_helper.py start
    python aternos_helper.py wait [timeout_seconds]

Credentials come from the environment:
ATERNOS_USERNAME, ATERNOS_PASSWORD, ATERNOS_SESSION, ATERNOS_SERVER
"""

from __future__ import annotations

import json
import os
import sys
import time

POLL = 10


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
    # python-aternos 3.0.x exposes login()/login_with_session() instead of the
    # from_credentials()/from_session() helpers shown in the 3.1 docs.
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


def pick_server(client):
    servers = client.list_servers()
    if not servers:
        raise RuntimeError("This Aternos account has no servers")

    wanted = os.environ.get("ATERNOS_SERVER", "").strip().lower()
    if wanted:
        for server in servers:
            haystack = f"{server.address} {server.subdomain or ''}".lower()
            if wanted in haystack:
                return server
    return servers[0]


def snapshot(server) -> dict:
    server.fetch()
    return {
        "ok": True,
        "address": f"{server.domain}:{server.port}",
        "status": server.status,
        "players": server.players_count,
        "slots": server.slots,
        "names": list(server.players_list or []),
        "software": f"{server.software} {server.version}",
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
            if info["status"] == "online":
                info["already"] = True
                emit(info)
            server.start()
            try:
                server.confirm()
            except Exception:
                pass
            server.fetch()
            emit(
                {
                    "ok": True,
                    "already": False,
                    "status": server.status,
                    "address": f"{server.domain}:{server.port}",
                    "software": f"{server.software} {server.version}",
                }
            )

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
                if info["status"] != last:
                    log(f"status -> {info['status']}")
                    last = info["status"]
                if info["status"] == "online":
                    info["elapsed"] = int(time.time() - started)
                    emit(info)
                time.sleep(POLL)
            emit(
                {
                    "ok": False,
                    "error": f"still not online after {timeout}s (last status: {last or 'unknown'})",
                    "status": last,
                },
                2,
            )

        emit({"ok": False, "error": f"unknown command: {command}"}, 3)
    except Exception as exc:
        emit({"ok": False, "error": str(exc)}, 1)


if __name__ == "__main__":
    main()
