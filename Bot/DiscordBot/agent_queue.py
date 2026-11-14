"""Instruction queue for the DSH agent.

Discord is only a mailbox here: the bot stores the text and nothing else.
The agent (DeepSeek Harness) reads this queue, executes what it can inside
Discord / bot scope, and writes the result back.

CLI (run on the server from Bot/DiscordBot):
    venv/bin/python agent_queue.py list [pending|in_progress|done|failed]
    venv/bin/python agent_queue.py claim <id>
    venv/bin/python agent_queue.py done <id> "result text"
    venv/bin/python agent_queue.py fail <id> "reason"
    venv/bin/python agent_queue.py add "instruction" [user id]
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager

from config import settings

try:  # Linux (the bot host); Windows only runs the local test suite
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

QUEUE_FILE = settings.data_dir / "agent_tasks.json"
LOCK_FILE = settings.data_dir / "agent_tasks.lock"

MAX_TASKS = 200
MAX_PENDING = 5
MAX_TEXT = 800


@contextmanager
def _lock():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        yield
        return
    with open(LOCK_FILE, "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read() -> list[dict]:
    try:
        data = json.loads(QUEUE_FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write(tasks: list[dict]) -> None:
    tmp = QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(tasks[-MAX_TASKS:], ensure_ascii=False, indent=1), "utf-8"
    )
    tmp.replace(QUEUE_FILE)


def enqueue(
    text: str,
    user_id: int = 0,
    user_name: str = "",
    channel_id: int = 0,
    message_id: int = 0,
) -> dict:
    text = " ".join(text.split())[:MAX_TEXT]
    if not text:
        raise ValueError("empty instruction")

    with _lock():
        tasks = _read()
        pending = [task for task in tasks if task["status"] == "pending"]
        if len(pending) >= MAX_PENDING:
            raise RuntimeError("queue full")

        task = {
            "id": uuid.uuid4().hex[:6],
            "text": text,
            "status": "pending",
            "created": int(time.time()),
            "user_id": user_id,
            "user": user_name,
            "channel_id": channel_id,
            "message_id": message_id,
            "result": "",
        }
        tasks.append(task)
        _write(tasks)
        return task


def list_tasks(status: str | None = None) -> list[dict]:
    tasks = _read()
    if status:
        tasks = [task for task in tasks if task.get("status") == status]
    return tasks


def get(task_id: str) -> dict | None:
    for task in _read():
        if task.get("id") == task_id:
            return task
    return None


def claim(task_id: str) -> dict | None:
    with _lock():
        tasks = _read()
        for task in tasks:
            if task.get("id") == task_id and task["status"] == "pending":
                task["status"] = "in_progress"
                task["claimed"] = int(time.time())
                _write(tasks)
                return task
    return None


def finish(task_id: str, status: str, result: str = "") -> bool:
    with _lock():
        tasks = _read()
        for task in tasks:
            if task.get("id") == task_id:
                task["status"] = status
                task["result"] = result[:1000]
                task["finished"] = int(time.time())
                _write(tasks)
                return True
    return False


def describe(task: dict) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(task.get("created", 0)))
    return (
        f"#{task['id']} [{task['status']}] {stamp} by {task.get('user') or task.get('user_id')}\n"
        f"  {task['text']}"
        + (f"\n  -> {task['result']}" if task.get("result") else "")
    )


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1

    command = argv[1]
    if command == "list":
        status = argv[2] if len(argv) > 2 else None
        tasks = list_tasks(status)
        if not tasks:
            print("no tasks")
        for task in tasks:
            print(describe(task))
        return 0

    if command == "claim" and len(argv) > 2:
        task = claim(argv[2])
        print(describe(task) if task else f"task {argv[2]} is not pending")
        return 0 if task else 1

    if command in {"done", "fail"} and len(argv) > 2:
        message = argv[3] if len(argv) > 3 else ""
        ok = finish(argv[2], "done" if command == "done" else "failed", message)
        print("updated" if ok else "task not found")
        return 0 if ok else 1

    if command == "add" and len(argv) > 2:
        user = int(argv[3]) if len(argv) > 3 and argv[3].isdigit() else 0
        task = enqueue(argv[2], user_id=user, user_name="cli")
        print(describe(task))
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
