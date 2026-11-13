"""Everything the bot can be asked to do.

`handle_command` returns True when it consumed the message; `answer` is the
shared pipeline that talks to the model and posts the result.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time

import discord

import ai
import imagine
import memory
import search
import stickers
import vision
from config import settings
from constants import CYRENE_SYSTEM_PROMPT, HELP_TEXT, TIME_KEYWORDS

log = logging.getLogger(__name__)

STICKER_PATTERN = re.compile(r"\[STICKER:\s*([a-zA-Z_]+)\s*\]", re.IGNORECASE)
STICKER_CLEAN = re.compile(r"\[STICKER:[^\]]*\]", re.IGNORECASE)

# In-memory session state
games: dict[int, dict] = {}
last_search: dict[int, dict] = {}
last_conversation: dict[int, dict] = {}
last_listing: dict[int, list[tuple[str, str]]] = {}
image_context: dict[int, str] = {}


# --------------------------------------------------------------------------
# Sending helpers
# --------------------------------------------------------------------------


def _stamp() -> str:
    return time.strftime("%H:%M-%d/%m/%Y")


async def send_text(channel, text: str) -> None:
    """Send text, splitting long messages and appending the clock suffix."""
    chunks = ai.split(text)
    if settings.timestamp_suffix:
        suffix = f"\n\n🕒  {_stamp()}"
        if len(chunks[-1]) + len(suffix) <= 2000:
            chunks[-1] += suffix
        else:
            chunks.append(suffix.strip())
    for chunk in chunks:
        await channel.send(chunk)


async def send_pictures(channel, pictures: list[imagine.Picture]) -> None:
    for picture in pictures:
        await channel.send(
            file=discord.File(io.BytesIO(picture.data), filename=picture.filename)
        )


# --------------------------------------------------------------------------
# Model selection and the answer pipeline
# --------------------------------------------------------------------------


def current_model(user_id: int) -> str:
    if memory.prefs.get("model", user_id, "flash") == "pro":
        return settings.deepseek_pro_model
    return settings.deepseek_model


async def answer(
    message: discord.Message,
    prompt: str,
    *,
    search_outcome: search.SearchOutcome | None = None,
    systems: list[str] | None = None,
    remember: bool = True,
) -> str:
    """Build context, ask the model, post the reply. Returns the raw reply."""
    channel = message.channel
    user_id = message.author.id
    model = current_model(user_id)
    thinking = bool(memory.prefs.get("thinking", user_id, True))

    async with channel.typing():
        system_messages = [{"role": "system", "content": CYRENE_SYSTEM_PROMPT}]
        system_messages.append(
            {
                "role": "system",
                "content": (
                    "IMPORTANT: The current real-world date and time is "
                    f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
                    "You MUST use this as the absolute truth for any time-related "
                    "questions. Ignore your internal knowledge cutoff if it "
                    "contradicts this time."
                ),
            }
        )

        if search_outcome is not None and search_outcome.found:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        f"Here are web search results for '{prompt}':\n\n"
                        f"{search_outcome.text}\n\n"
                        "Answer based on these results. If they do not contain the "
                        "answer, say so politely. ♪"
                    ),
                }
            )
        elif search_outcome is not None:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        f"The web search for '{prompt}' returned no usable results. "
                        "Answer from your own knowledge and say that the search "
                        "did not help. ♪"
                    ),
                }
            )
        else:
            knowledge = await memory.search(prompt, k=3)
            if knowledge:
                joined = "\n\n".join(knowledge)
                system_messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"Relevant knowledge from my stars:\n{joined}\n\n"
                            "You may use this if helpful, but answer naturally. ♪"
                        ),
                    }
                )

        remembered_image = image_context.get(channel.id)
        if remembered_image:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "The most recent image in this channel was described as: "
                        f"{remembered_image}\nIf the user asks about it, base your "
                        "answer on that description."
                    ),
                }
            )

        for extra in systems or []:
            system_messages.append({"role": "system", "content": extra})

        history = memory.history_for(channel.id, user_id)
        history.append({"role": "user", "content": prompt})
        messages = system_messages + list(history)

        try:
            reply = await ai.complete(messages, model=model, thinking=thinking)
        except ai.ChatError as exc:
            history.pop()
            await channel.send(f"⚠️ My brain hiccupped: {exc}")
            return ""

        if not reply:
            history.pop()
            await channel.send("Hmm, I'm not sure what to say... ♪")
            return ""

        history.append({"role": "assistant", "content": reply})

        sticker_match = STICKER_PATTERN.search(reply)
        clean = STICKER_CLEAN.sub("", reply).strip()
        if sticker_match:
            emotion = sticker_match.group(1).lower()
            if clean:
                await send_text(channel, clean)
            await stickers.send(channel, emotion)  # unknown emotions are ignored
        else:
            await send_text(channel, reply)

        if search_outcome is not None and search_outcome.links:
            sources = "\n".join(
                f"[{i + 1}] {url}" for i, url in enumerate(search_outcome.links)
            )
            await send_text(channel, f"**Sources:**\n{sources}")

        if remember:
            last_conversation[user_id] = {"user": prompt, "bot": reply}

    return reply


def wants_search(user_id: int, text: str) -> bool:
    """Explicit #autosearch wins, otherwise a few trigger words."""
    if memory.prefs.get("autosearch", user_id, False):
        return True
    lowered = text.lower()
    return any(keyword in lowered for keyword in TIME_KEYWORDS)


async def chat(message: discord.Message, prompt: str) -> None:
    """Plain conversational turn, with automatic search when appropriate."""
    outcome = None
    if wants_search(message.author.id, prompt):
        await message.channel.send(f"🔎 Searching for **{prompt}**...")
        outcome = await search.web_search(prompt)
        last_search[message.author.id] = {
            "query": prompt,
            "answer_text": "",
            "links": outcome.links,
        }
    reply = await answer(message, prompt, search_outcome=outcome)
    if outcome is not None and last_search.get(message.author.id):
        last_search[message.author.id]["answer_text"] = reply


# --------------------------------------------------------------------------
# Lyric game
# --------------------------------------------------------------------------


async def game_tick(message: discord.Message) -> bool:
    """Advance a running lyric game. Returns True if it consumed the message."""
    state = games.get(message.author.id)
    if state is None:
        return False

    content = message.content.strip()
    if content.startswith("#"):
        games.pop(message.author.id, None)
        return False  # let the command run, the game just ends

    lyrics: list[str] = state["lyrics"]
    index: int = state["current_index"]
    if index + 1 < len(lyrics):
        state["current_index"] = index + 1
        await message.channel.send(f"{lyrics[index + 1]} ♪")
    else:
        games.pop(message.author.id, None)
        await message.channel.send(
            "We've reached the end of the song. It was lovely singing with you ♪"
        )
    return True


# --------------------------------------------------------------------------
# Command dispatch
# --------------------------------------------------------------------------


async def handle_command(message: discord.Message) -> bool:
    """Return True when the message was a command we handled."""
    content = message.content.strip()
    if not content.startswith("#"):
        return False

    body = content[1:].strip()
    if not body:
        await message.channel.send("Please say something, like `# What's new?` ♪")
        return True

    lowered = body.lower()
    user_id = message.author.id
    channel = message.channel

    # --- meta -------------------------------------------------------------
    if lowered in {"help", "h", "commands"}:
        await send_text(channel, HELP_TEXT)
        return True

    if lowered == "ping":
        latency = int((time.time() - message.created_at.timestamp()) * 1000)
        await channel.send(f"🏓 Pong! `{latency} ms`")
        return True

    if lowered in {"reset", "clear history"}:
        memory.history_for(channel.id, user_id).clear()
        await channel.send("Conversation history cleared. A fresh start ♪")
        return True

    # --- preferences ------------------------------------------------------
    if lowered.startswith("thinking"):
        option = body[len("thinking") :].strip().lower()
        if option in {"on", "off"}:
            value = option == "on"
        else:
            value = not bool(memory.prefs.get("thinking", user_id, True))
        memory.prefs.set("thinking", user_id, value)
        await channel.send(
            f"Thinking mode **{'on' if value else 'off'}** ♪"
            + ("" if option else " (use `#thinking on|off` to set it explicitly)")
        )
        return True

    if lowered.startswith("autosearch"):
        option = body[len("autosearch") :].strip().lower()
        if option in {"on", "off"}:
            value = option == "on"
            memory.prefs.set("autosearch", user_id, value)
            await channel.send(
                f"Auto-search is now **{option}** ♪"
                + (
                    " I'll search before every answer."
                    if value
                    else " I'll rely on my memory again."
                )
            )
        else:
            value = bool(memory.prefs.get("autosearch", user_id, False))
            await channel.send(
                f"Auto-search is currently **{'on' if value else 'off'}**. "
                "Use `#autosearch on|off` ♪"
            )
        return True

    if lowered.startswith("model"):
        option = body[len("model") :].strip().lower()
        if option in {"flash", "deepseek-flash", "fast"}:
            memory.prefs.set("model", user_id, "flash")
            await channel.send(f"Using **{settings.deepseek_model}** ♪")
        elif option in {"pro", "deepseek-v4-pro", "smart"}:
            memory.prefs.set("model", user_id, "pro")
            await channel.send(f"Using **{settings.deepseek_pro_model}** ♪")
        else:
            current = current_model(user_id)
            await channel.send(
                f"Current model: **{current}**. Use `#model flash` or `#model pro` ♪"
            )
        return True

    # --- search -----------------------------------------------------------
    if lowered.startswith("search ") or lowered == "search":
        query = body[len("search") :].strip()
        if not query:
            await channel.send("What should I search for? `#search Nvidia stock price` ♪")
            return True
        await channel.send(f"🔎 Searching for **{query}**...")
        outcome = await search.web_search(query)
        last_search[user_id] = {
            "query": query,
            "answer_text": "",
            "links": outcome.links,
        }
        reply = await answer(message, query, search_outcome=outcome, remember=False)
        last_search[user_id]["answer_text"] = reply
        return True

    # --- learning ---------------------------------------------------------
    if lowered.startswith("learn"):
        await _handle_learn(message, body, user_id)
        return True

    # --- knowledge --------------------------------------------------------
    if lowered.startswith("knowledge"):
        await _handle_knowledge(message, user_id)
        return True

    if lowered.startswith("forget"):
        await _handle_forget(message, body, user_id)
        return True

    if lowered.startswith("clean"):
        total = await memory.clear()
        if total:
            await channel.send(
                f"✨ I cleansed **{total}** entries from my stars. A fresh page awaits ♪"
            )
        else:
            await channel.send("My stars are already empty, nothing to clean ♪")
        return True

    # --- images -----------------------------------------------------------
    if lowered.startswith("imagine"):
        await _handle_imagine(message, body, user_id)
        return True

    if lowered.startswith("edit"):
        await _handle_edit(message, body)
        return True

    if lowered.startswith("describe"):
        await _handle_describe(message, body, user_id)
        return True

    # --- games ------------------------------------------------------------
    if re.match(r"^let'?s sing\b", lowered):
        await _handle_song(message, body)
        return True

    # Unknown #command: treat as a chat prompt.
    await chat(message, body)
    return True


# --------------------------------------------------------------------------
# Command implementations
# --------------------------------------------------------------------------


async def _handle_learn(message: discord.Message, body: str, user_id: int) -> None:
    channel = message.channel
    lowered = body.lower()

    if lowered.startswith("learn that"):
        rest = body[len("learn that") :].strip().lower()
        from_search = rest == "search"

        if from_search:
            record = last_search.get(user_id)
            if not record:
                await channel.send(
                    "I have no recent search to learn from. Search something first ♪"
                )
                return
            query = record["query"]
            reply = record["answer_text"] or "(no summary)"
            links = record.get("links") or []
            if not links:
                stored = await memory.add(
                    f"Q: {query}\nA: {reply}", source=f"user:{message.author.name}"
                )
                await channel.send(
                    "I've learned the summary from the stars ♪"
                    if stored
                    else "I could not store that, sorry ♪"
                )
                return

            await channel.send(
                f"📚 Reading {min(3, len(links))} of {len(links)} source(s)..."
            )
            texts: list[str] = []
            used: list[str] = []
            for url in links[:3]:
                page = await search.fetch_page(url)
                if page:
                    texts.append(f"Source: {url}\n{page}")
                    used.append(url)
            if not texts:
                stored = await memory.add(
                    f"Q: {query}\nA: {reply}", source=f"user:{message.author.name}"
                )
                await channel.send(
                    "The pages were unreachable, so I kept the summary instead ♪"
                    if stored
                    else "I could not store that, sorry ♪"
                )
                return
            combined = f"Question: {query}\n\n" + "\n\n---\n\n".join(texts)
            stored = await memory.add(
                combined, source=f"user:{message.author.name} (web)"
            )
            await channel.send(
                f"✨ Learned from {len(used)} source(s) ♪"
                if stored
                else "I could not store that, sorry ♪"
            )
            return

        conversation = last_conversation.get(user_id)
        if not conversation:
            await channel.send(
                "I have no recent conversation to learn from. Chat with me first ♪"
            )
            return
        stored = await memory.add(
            f"Q: {conversation['user']}\nA: {conversation['bot']}",
            source=f"user:{message.author.name}",
        )
        await channel.send(
            "Saved our last exchange to my memory ♪"
            if stored
            else "I could not store that, sorry ♪"
        )
        return

    if lowered.startswith("learn from "):
        url = body[len("learn from ") :].strip()
        if not url.startswith(("http://", "https://")):
            await channel.send("Give me a full URL, e.g. `#learn from https://example.com` ♪")
            return
        await channel.send(f"📚 Reading {url} ...")
        page = await search.fetch_page(url, max_chars=8000)
        if not page:
            await channel.send("I could not read that page (blocked or not text) ♪")
            return
        stored = await memory.add(
            f"Source: {url}\n\n{page}",
            source=f"user:{message.author.name} (url)",
            url=url,
        )
        await channel.send(
            "✨ Learned it and stored it in my memory ♪"
            if stored
            else "I could not store that, sorry ♪"
        )
        return

    text = body[len("learn") :].strip()
    if not text:
        await channel.send("Tell me what to learn: `#learn Honkai Star Rail 4.2 out in April` ♪")
        return
    stored = await memory.add(text, source=f"user:{message.author.name}")
    await channel.send(
        "Added to my stars, thank you for sharing ♪"
        if stored
        else "I could not store that, sorry ♪"
    )


async def _handle_knowledge(message: discord.Message, user_id: int) -> None:
    channel = message.channel
    total = await memory.count()
    if total == 0:
        await channel.send("My stars hold no knowledge yet. Teach me with `#learn` ♪")
        return
    entries = await memory.listing(limit=50)
    last_listing[user_id] = entries
    lines = [f"I hold **{total}** pieces of knowledge. First {len(entries)}:"]
    for index, (_, document) in enumerate(entries, 1):
        preview = document[:60].replace("\n", " ")
        lines.append(f"`{index}.` {preview}")
    lines.append("Use `#forget <number>` to remove one.")
    await channel.send("\n".join(lines)[:1990])


async def _handle_forget(message: discord.Message, body: str, user_id: int) -> None:
    channel = message.channel
    argument = body[len("forget") :].strip()
    entries = last_listing.get(user_id)
    if not entries:
        await channel.send("Run `#knowledge` first so I know which number you mean ♪")
        return
    try:
        index = int(argument) - 1
    except ValueError:
        await channel.send("Use `#forget 2` with a number ♪")
        return
    if not 0 <= index < len(entries):
        await channel.send(f"Pick a number between 1 and {len(entries)} ♪")
        return
    entry_id, document = entries.pop(index)
    await memory.delete([entry_id])
    preview = document[:60].replace("\n", " ")
    await channel.send(f"Forgotten: `{preview}` ... the stars are emptier now ♪")


async def _handle_imagine(message: discord.Message, body: str, user_id: int) -> None:
    channel = message.channel
    prompt = body[len("imagine") :].strip()
    hq = False
    if prompt.lower().startswith("hq "):
        hq = True
        prompt = prompt[3:].strip()
    if not prompt:
        await channel.send("What should I draw? `#imagine a cat on a cloud` ♪")
        return

    async with channel.typing():
        await channel.send(
            "🎨 Painting..." if not hq else "🎨 Painting with the premium brush..."
        )
        try:
            pictures = await imagine.generate(prompt, hq=hq)
        except imagine.ImageError as exc:
            await channel.send(f"🖌️ I could not create that image: {exc}")
            return
    await send_pictures(channel, pictures)


async def _handle_edit(message: discord.Message, body: str) -> None:
    channel = message.channel
    instruction = body[len("edit") :].strip()
    if not instruction:
        await channel.send("Tell me how to edit it: `#edit make it watercolor` ♪")
        return
    image_bytes = await _first_image(message)
    if image_bytes is None:
        return
    async with channel.typing():
        await channel.send("🖌️ Editing your image...")
        try:
            pictures = await imagine.edit(image_bytes, instruction)
        except imagine.ImageError as exc:
            await channel.send(f"🖌️ Editing failed: {exc}")
            return
    await send_pictures(channel, pictures)


async def _handle_describe(
    message: discord.Message, body: str, user_id: int
) -> None:
    channel = message.channel
    question = body[len("describe") :].strip()
    image_bytes = await _first_image(message)
    if image_bytes is None:
        return

    prompt = question or "Describe this image in English in under 75 words."
    async with channel.typing():
        try:
            description = await vision.describe(image_bytes, prompt)
        except vision.VisionError as exc:
            await channel.send(f"👁️ I could not read the image: {exc}")
            return

    image_context[channel.id] = description
    if question:
        await answer(
            message,
            question,
            systems=[
                "The user attached an image. Its content: "
                f"{description}\nAnswer the question using this content."
            ],
            remember=False,
        )
    else:
        await send_text(channel, description)


async def _handle_song(message: discord.Message, body: str) -> None:
    channel = message.channel
    name = re.sub(r"^let'?s sing\b", "", body, flags=re.IGNORECASE).strip()
    if not name:
        await channel.send("Which song shall we sing? ♪")
        return
    entries = await memory.search(name, k=1)
    if not entries:
        await channel.send(
            "I don't know that song yet. Teach it with `#learn` first, or search it ♪"
        )
        return
    lyrics = [line.strip() for line in entries[0].splitlines() if line.strip()]
    if len(lyrics) < 2:
        await channel.send("That looks too short to sing. Maybe it is just a title? ♪")
        return
    games[message.author.id] = {
        "song": name,
        "lyrics": lyrics,
        "current_index": 0,
    }
    await channel.send(
        f"Let's sing **{name}**! I'll follow your lead. Start: {lyrics[0]} ♪"
    )


async def _first_image(message: discord.Message) -> bytes | None:
    """Download the first image attachment, telling the user when it is missing."""
    if not message.attachments:
        await message.channel.send("Please attach an image to that command ♪")
        return None
    attachment = message.attachments[0]
    looks_like_image = (
        (attachment.content_type or "").startswith("image/")
        or (attachment.filename or "").lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        )
    )
    if not looks_like_image:
        await message.channel.send("That does not look like an image file ♪")
        return None
    try:
        return await vision.download(attachment.url)
    except Exception as exc:
        log.warning("Attachment download failed: %s", exc)
        await message.channel.send("I could not download the attachment ♪")
        return None
