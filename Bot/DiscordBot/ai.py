"""DeepSeek chat completions (OpenAI compatible)."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from openai import AsyncOpenAI

from config import settings

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1900  # Discord hard limit is 2000, keep some slack

_client: AsyncOpenAI | None = None


class ChatError(RuntimeError):
    """Raised when the language model cannot produce an answer."""


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.deepseek_key,
            base_url=settings.deepseek_base_url,
            timeout=180.0,
            max_retries=2,
        )
    return _client


async def complete(
    messages: Sequence[dict[str, Any]],
    *,
    model: str | None = None,
    thinking: bool = True,
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    """Ask the model for a reply. Falls back to a non-thinking retry if the
    reasoning budget swallowed the whole answer."""
    model = model or settings.deepseek_model
    payload: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if thinking:
        payload["extra_body"] = {"enable_thinking": True}

    try:
        response = await client().chat.completions.create(**payload)  # type: ignore[arg-type]
    except Exception as exc:  # network / auth / rate limit
        log.warning("DeepSeek call failed: %s", exc)
        raise ChatError(str(exc)) from exc

    text = (response.choices[0].message.content or "").strip()
    if not text and thinking:
        log.info("Empty answer with thinking enabled, retrying without it")
        payload.pop("extra_body", None)
        payload["max_tokens"] = max(max_tokens, 2500)
        try:
            response = await client().chat.completions.create(**payload)  # type: ignore[arg-type]
            text = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            raise ChatError(str(exc)) from exc

    return text


def clip(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def split(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split long text on paragraph/line boundaries when possible."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    return chunks
