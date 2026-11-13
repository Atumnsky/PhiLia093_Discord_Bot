#!/usr/bin/env python3
"""Aternos bridge for the Discord bot.

Runs under a Python that can execute `python-aternos` (3.10/3.11 — js2py has no
3.12 support). Two modes:

    python aternos_helper.py status [server]
    python aternos_helper.py start  [server]
    python aternos_helper.py serve            # long running JSON-lines daemon

The daemon logs in once, keeps two servers' state in memory, answers requests on
stdin and prints state changes as events, so the bot can announce "server is
online" without logging in over and over.

Environment: ATERNOS_USERNAME, ATERNOS_PASSWORD, ATERNOS_SESSION, ATERNOS_SERVER,
            ATERNOS_POLL (seconds, default 60)
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time

POLL = max(20, int(os.environ.get("ATERNOS_POLL", "60") or 60))
STATUS_RE = re.compile(r"var lastStatus\s*?=\s*?(\{.+?\});?\s*</script>")
ONLINE_STATES = {"online"}
SESSION_FILE = os.path.expanduser("~/.philia_aternos_session")

_print_lock = threading.Lock()


def emit(payload: dict, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    if code:
        sys.exit(code)


def send_line(payload: dict) -> None:
    with _print_lock:
        print(json.dumps(payload, ensure_ascii=False), flush=True)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_client():
    from python_aternos import Client
    from python_aternos.atconnect import AternosConnect

    # The library defaults to a 4 second timeout, which is too short for
    # start/stop requests; widen it once for the whole process.
    if not getattr(AternosConnect.request_cloudflare, "_philia_patched", False):
        original = AternosConnect.request_cloudflare

        def patched(self, url, method, **kwargs):
            kwargs.setdefault("timeout", 30)
            kwargs.setdefault("retries", 3)
            return original(self, url, method, **kwargs)

        patched._philia_patched = True  # type: ignore[attr-defined]
        AternosConnect.request_cloudflare = patched  # type: ignore[assignment]

    session = os.environ.get("ATERNOS_SESSION", "").strip()
    if not session and os.path.exists(SESSION_FILE):
        try:
            session = open(SESSION_FILE, encoding="utf-8").read().strip()
            log("using stored Aternos session")
        except OSError:
            session = ""
    username = os.environ.get("ATERNOS_USERNAME", "").strip()
    password = os.environ.get("ATERNOS_PASSWORD", "").strip()

    client = Client()
    if session:
        client.login_with_session(session)
        try:
            list_servers(client)  # validates the cookie
            save_session(client)
            return client
        except Exception as exc:  # noqa: BLE001
            log(f"stored session rejected: {exc}")

    if username and password:
        try:
            client.login(username, password)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Aternos login failed: "
                + str(exc)
                + " — Aternos asks for a captcha on datacenter IPs; log in in a "
                "browser and set ATERNOS_SESSION instead."
            ) from exc
        save_session(client)
        return client

    raise RuntimeError(
        "Aternos credentials missing: set ATERNOS_SESSION (preferred) or "
        "ATERNOS_USERNAME/ATERNOS_PASSWORD in .env"
    )


def save_session(client) -> None:
    """Persist the session cookie so restarts do not need a fresh login."""
    try:
        cookie = client.atconn.session.cookies.get("ATERNOS_SESSION")
        if cookie:
            with open(SESSION_FILE, "w", encoding="utf-8") as handle:
                handle.write(cookie)
            os.chmod(SESSION_FILE, 0o600)
            log("saved Aternos session cookie")
    except Exception as exc:  # noqa: BLE001
        log(f"could not save session: {exc}")


def list_servers(client):
    account = getattr(client, "account", None)
    if account is not None and hasattr(account, "list_servers"):
        return account.list_servers()
    return client.list_servers()


def state_of(info: dict) -> str:
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
        return int(info.get("status")) == 2
    except (TypeError, ValueError):
        return False


def fetch_info(server) -> dict:
    """Read one specific server page.

    python-aternos fetches /server (whichever server is selected), which is wrong
    for accounts that can see several servers. /servers/<id>/ is per server.
    """
    page = server.atconn.request_cloudflare(
        f"https://aternos.org/servers/{server.servid}/", "GET"
    )
    match = STATUS_RE.search(page.text)
    if match is None:
        raise RuntimeError("Unable to parse Aternos status object")
    info = json.loads(match.group(1))
    info.setdefault("_id", server.servid)
    # Keep the library's own cache in sync: start()/eula() read server._info.
    server._info = info
    return info


def snapshot(server) -> dict:
    info = fetch_info(server)
    state = state_of(info)
    host = info.get("ip") or info.get("displayAddress") or ""
    if not host:
        subdomain = getattr(server, "subdomain", "") or ""
        host = f"{subdomain}.aternos.me" if subdomain else "?"
    port = info.get("port")
    return {
        "ok": True,
        "id": server.servid,
        "name": info.get("name") or getattr(server, "subdomain", "") or "?",
        "address": f"{host}:{port}" if port else host,
        "state": state,
        "label": info.get("label") or state,
        "players": info.get("players", 0),
        "slots": info.get("slots", "?"),
        "names": list(info.get("playerlist") or []),
        "software": f"{info.get('software', '?')} {info.get('version', '')}".strip(),
    }


def _subdomain(server) -> str:
    """server.subdomain reads _info['ip'] and explodes when the cache is empty."""
    try:
        return getattr(server, "subdomain", "") or ""
    except Exception:
        return ""


def pick_server(servers, wanted: str | None):
    if not wanted:
        configured = os.environ.get("ATERNOS_SERVER", "").strip()
        wanted = configured or None
    if not wanted:
        return servers[0]

    needle = wanted.strip().lower()
    for server in servers:
        info = getattr(server, "_info", {}) or {}
        haystack = " ".join(
            str(part)
            for part in (
                info.get("name"),
                info.get("ip"),
                server.servid,
                _subdomain(server),
            )
            if part
        ).lower()
        if needle in haystack:
            return server
    return servers[0]


def announce_name(server) -> str:
    return getattr(server, "_info", {}).get("name") or _subdomain(server) or server.servid


# --------------------------------------------------------------------------
# Daemon mode
# --------------------------------------------------------------------------


def serve() -> None:
    client = build_client()
    servers = list_servers(client)
    if not servers:
        emit({"ok": False, "error": "This Aternos account cannot see any servers"}, 1)

    log(f"serving {len(servers)} server(s)")

    last_state: dict[str, str] = {}

    def poll_loop() -> None:
        while True:
            for server in servers:
                try:
                    info = snapshot(server)
                except Exception as exc:  # noqa: BLE001
                    log(f"poll failed for {server.servid}: {exc}")
                    continue
                previous = last_state.get(info["id"])
                last_state[info["id"]] = info["state"]
                if previous is not None and previous != info["state"]:
                    send_line(
                        {
                            "event": "change",
                            "previous": previous,
                            **info,
                        }
                    )
            time.sleep(POLL)

    threading.Thread(target=poll_loop, daemon=True).start()

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            continue

        req_id = request.get("id")
        command = request.get("cmd")
        try:
            if command == "list":
                payload = {
                    "ok": True,
                    "servers": [snapshot(server) for server in servers],
                }
            elif command == "status":
                server = pick_server(servers, request.get("server"))
                payload = snapshot(server)
            elif command == "start":
                server = pick_server(servers, request.get("server"))
                info = snapshot(server)
                if is_online(info):
                    info["already"] = True
                    payload = info
                else:
                    try:
                        server.start()
                    except Exception as exc:  # noqa: BLE001
                        message = str(exc)
                        if "401" in message or "403" in message or "Access denied" in message:
                            raise RuntimeError(
                                "Aternos blocks automated start requests from this "
                                "server. Press Start on aternos.org and I'll announce "
                                "it here when it comes online."
                            ) from exc
                        raise
                    try:
                        server.confirm()
                    except Exception:
                        pass
                    time.sleep(2)
                    fresh = snapshot(server)
                    fresh["already"] = False
                    payload = fresh
            else:
                payload = {"ok": False, "error": f"unknown command: {command}"}
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": str(exc)}

        payload["id"] = req_id
        send_line(payload)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    target = sys.argv[2] if len(sys.argv) > 2 else None

    if command == "serve":
        try:
            serve()
        except Exception as exc:  # noqa: BLE001
            emit({"ok": False, "error": str(exc)}, 1)
        return

    try:
        client = build_client()
        servers = list_servers(client)
        server = pick_server(servers, target)
    except Exception as exc:  # noqa: BLE001
        emit({"ok": False, "error": str(exc)}, 1)

    try:
        if command == "status":
            emit(snapshot(server))
        if command == "list":
            emit({"ok": True, "servers": [snapshot(s) for s in servers]})
        if command == "start":
            info = snapshot(server)
            if is_online(info):
                info["already"] = True
                emit(info)
            try:
                server.start()
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if "401" in message or "403" in message or "Access denied" in message:
                    raise RuntimeError(
                        "Aternos denied the start request: this account has no "
                        "permission to start that server."
                    ) from exc
                raise
            try:
                server.confirm()
            except Exception:
                pass
            time.sleep(2)
            fresh = snapshot(server)
            fresh["already"] = False
            emit(fresh)
        emit({"ok": False, "error": f"unknown command: {command}"}, 3)
    except Exception as exc:  # noqa: BLE001
        emit({"ok": False, "error": str(exc)}, 1)


if __name__ == "__main__":
    main()
