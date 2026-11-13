"""Persistent state: the Chroma knowledge base and small JSON preferences.

Chromadb ships its own ONNX MiniLM embedder, so no torch is needed.
All heavy calls run in a worker thread to keep the gateway responsive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Iterable

import chromadb
from chromadb.utils import embedding_functions

from config import settings

log = logging.getLogger(__name__)

COLLECTION_NAME = "my_knowledge"
MAX_DOC_CHARS = 6000

_lock = threading.Lock()
_collection = None


def _collection_sync():
    global _collection
    with _lock:
        if _collection is None:
            settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(settings.chroma_dir))
            _collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_functions.DefaultEmbeddingFunction(),
            )
        return _collection


# --------------------------------------------------------------------------
# Knowledge base
# --------------------------------------------------------------------------


def _add_sync(text: str, source: str, url: str | None) -> bool:
    text = text.strip()
    if not text:
        return False
    collection = _collection_sync()
    chunks = [
        text[i : i + MAX_DOC_CHARS] for i in range(0, len(text), MAX_DOC_CHARS)
    ]
    stamp = f"{int(time.time() * 1000)}"
    for index, chunk in enumerate(chunks):
        metadata: dict[str, Any] = {"source": source, "created": int(time.time())}
        if url:
            metadata["url"] = url
        collection.add(
            documents=[chunk],
            ids=[f"{stamp}_{index}"],
            metadatas=[metadata],
        )
    return True


def _search_sync(query: str, k: int) -> list[str]:
    collection = _collection_sync()
    if collection.count() == 0:
        return []
    result = collection.query(query_texts=[query], n_results=k)
    documents = result.get("documents") or []
    return documents[0] if documents else []


def _count_sync() -> int:
    return _collection_sync().count()


def _list_sync(limit: int) -> list[tuple[str, str]]:
    collection = _collection_sync()
    result = collection.get(limit=limit)
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    return list(zip(ids, documents))


def _delete_sync(ids: Iterable[str]) -> None:
    _collection_sync().delete(ids=list(ids))


def _clear_sync() -> int:
    collection = _collection_sync()
    everything = collection.get()
    ids = everything.get("ids") or []
    if ids:
        collection.delete(ids=ids)
    return len(ids)


async def add(text: str, source: str = "user", url: str | None = None) -> bool:
    try:
        return await asyncio.to_thread(_add_sync, text, source, url)
    except Exception as exc:
        log.exception("Could not store knowledge: %s", exc)
        return False


async def search(query: str, k: int = 3) -> list[str]:
    try:
        return await asyncio.to_thread(_search_sync, query, k)
    except Exception as exc:
        log.exception("Knowledge search failed: %s", exc)
        return []


async def count() -> int:
    try:
        return await asyncio.to_thread(_count_sync)
    except Exception:
        log.exception("Could not count knowledge")
        return 0


async def listing(limit: int = 50) -> list[tuple[str, str]]:
    try:
        return await asyncio.to_thread(_list_sync, limit)
    except Exception:
        log.exception("Could not list knowledge")
        return []


async def delete(ids: Iterable[str]) -> None:
    await asyncio.to_thread(_delete_sync, list(ids))


async def clear() -> int:
    return await asyncio.to_thread(_clear_sync)


# --------------------------------------------------------------------------
# Preferences (thinking / autosearch / model) persisted to JSON
# --------------------------------------------------------------------------


class Preferences:
    """Tiny JSON backed store: ``data[namespace][user_id] = value``."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._io_lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            self._data = json.loads(self._path.read_text("utf-8"))
        except Exception:
            log.warning("Preferences file is unreadable, starting fresh")
            self._data = {}

    def _save(self) -> None:
        with self._io_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self._path)

    def get(self, namespace: str, user_id: int, default: Any) -> Any:
        return self._data.get(namespace, {}).get(str(user_id), default)

    def set(self, namespace: str, user_id: int, value: Any) -> None:
        self._data.setdefault(namespace, {})[str(user_id)] = value
        self._save()


settings.data_dir.mkdir(parents=True, exist_ok=True)
prefs = Preferences(settings.data_dir / "prefs.json")

# Per (channel, user) short conversation memory, in RAM only.
histories: dict[tuple[int, int], Deque[dict[str, str]]] = {}


def history_for(channel_id: int, user_id: int) -> Deque[dict[str, str]]:
    key = (channel_id, user_id)
    history = histories.get(key)
    if history is None:
        history = deque(maxlen=settings.max_history)
        histories[key] = history
    return history
