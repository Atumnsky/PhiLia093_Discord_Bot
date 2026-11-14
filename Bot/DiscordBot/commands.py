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
from datetime import datetime

import discord

import ai
import imagine
import memory
import search
import stickers
import vision
from config import settings
from constants import HELP_TEXT, SYSTEM_PROMPT, TIME_KEYWORDS, language_rule

log = logging.getLogger(__name__)

STARTED_AT = time.time()

NO_PING = discord.AllowedMentions.none()


async def _send(channel, *args, **kwargs):
    """Send a message that never pings anyone and never shows link previews."""
    kwargs.setdefault("allowed_mentions", NO_PING)
    message = await channel.send(*args, **kwargs)

    content = args[0] if args else kwargs.get("content", "")
    if isinstance(content, str) and "http" in content:
        try:
            await message.edit(suppress=True)
        except Exception:
            log.debug("Could not suppress embeds", exc_info=True)
    return message


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
    return datetime.now(settings.tz).strftime("%H:%M-%d/%m/%Y")


async def send_text(channel, text: str) -> None:
    """Send text, splitting long messages and appending the clock suffix."""
    if not text or not text.strip():
        return
    chunks = ai.split(text)
    if settings.timestamp_suffix:
        suffix = f"\n\n🕒  {_stamp()}"
        if len(chunks[-1]) + len(suffix) <= 2000:
            chunks[-1] += suffix
        else:
            chunks.append(suffix.strip())
    for chunk in chunks:
        await _send(channel, chunk)


async def send_pictures(channel, pictures: list[imagine.Picture]) -> None:
    for picture in pictures:
        await _send(channel, 
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
        now = datetime.now(settings.tz)
        system_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        system_messages.append(
            {"role": "system", "content": language_rule(settings.reply_language)}
        )
        system_messages.append(
            {
                "role": "system",
                "content": (
                    "You cannot manage Discord yourself (no creating channels, "
                    "roles or changing settings). If the user asks for that, tell "
                    "them to send `#agent <what they want>` instead."
                ),
            }
        )
        system_messages.append(
            {
                "role": "system",
                "content": (
                    f"Now: {now.strftime('%Y-%m-%d %H:%M %Z')} "
                    f"({now.strftime('%A')}). This is the real time; ignore your "
                    "knowledge cutoff. For 'how long ago' prefer Discord timestamps."
                ),
            }
        )

        if search_outcome is not None and search_outcome.found:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        f"Web results for '{prompt}':\n\n{search_outcome.text}\n\n"
                        "Answer from these; say so if the answer is missing. ♪"
                    ),
                }
            )
        elif search_outcome is not None:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        f"No usable web results for '{prompt}'. Answer from your "
                        "own knowledge and mention the search failed. ♪"
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
                        "content": f"Known facts:\n{joined}",
                    }
                )

        remembered_image = image_context.get(channel.id)
        if remembered_image:
            system_messages.append(
                {
                    "role": "system",
                    "content": f"Latest image here: {remembered_image}",
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
            await _send(channel, f"⚠️ My brain hiccupped: {exc}")
            return ""

        if not reply:
            history.pop()
            await _send(channel, "Hmm, I'm not sure what to say... ♪")
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
        await _send(message.channel, f"🔎 Searching for **{prompt}**...")
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
    if state.get("channel") != message.channel.id:
        return False

    content = message.content.strip()
    if content.startswith("#"):
        games.pop(message.author.id, None)
        return False  # let the command run, the game just ends

    lyrics: list[str] = state["lyrics"]
    index: int = state["current_index"]
    if index + 1 < len(lyrics):
        state["current_index"] = index + 1
        await _send(message.channel, f"{lyrics[index + 1]} ♪")
    else:
        games.pop(message.author.id, None)
        await _send(message.channel, 
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
        await _send(message.channel, "Please say something, like `# What's new?` ♪")
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
        await _send(channel, f"🏓 Pong! `{latency} ms`")
        return True

    if lowered in {"reset", "clear history"}:
        memory.history_for(channel.id, user_id).clear()
        await _send(channel, "Conversation history cleared. A fresh start ♪")
        return True

    # --- preferences ------------------------------------------------------
    if lowered.startswith("thinking"):
        option = body[len("thinking") :].strip().lower()
        if option in {"on", "off"}:
            value = option == "on"
        else:
            value = not bool(memory.prefs.get("thinking", user_id, True))
        memory.prefs.set("thinking", user_id, value)
        await _send(channel, 
            f"Thinking mode **{'on' if value else 'off'}** ♪"
            + ("" if option else " (use `#thinking on|off` to set it explicitly)")
        )
        return True

    if lowered.startswith("autosearch"):
        option = body[len("autosearch") :].strip().lower()
        if option in {"on", "off"}:
            value = option == "on"
            memory.prefs.set("autosearch", user_id, value)
            await _send(channel, 
                f"Auto-search is now **{option}** ♪"
                + (
                    " I'll search before every answer."
                    if value
                    else " I'll rely on my memory again."
                )
            )
        else:
            value = bool(memory.prefs.get("autosearch", user_id, False))
            await _send(channel, 
                f"Auto-search is currently **{'on' if value else 'off'}**. "
                "Use `#autosearch on|off` ♪"
            )
        return True

    if lowered.startswith("model"):
        option = body[len("model") :].strip().lower()
        if option in {"flash", "deepseek-flash", "fast"}:
            memory.prefs.set("model", user_id, "flash")
            await _send(channel, f"Using **{settings.deepseek_model}** ♪")
        elif option in {"pro", "deepseek-v4-pro", "smart"}:
            memory.prefs.set("model", user_id, "pro")
            await _send(channel, f"Using **{settings.deepseek_pro_model}** ♪")
        else:
            current = current_model(user_id)
            await _send(channel, 
                f"Current model: **{current}**. Use `#model flash` or `#model pro` ♪"
            )
        return True

    # --- search -----------------------------------------------------------
    if lowered.startswith("search ") or lowered == "search":
        query = body[len("search") :].strip()
        if not query:
            await _send(channel, "What should I search for? `#search Nvidia stock price` ♪")
            return True
        await _send(channel, f"🔎 Searching for **{query}**...")
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
            await _send(channel, 
                f"✨ I cleansed **{total}** entries from my stars. A fresh page awaits ♪"
            )
        else:
            await _send(channel, "My stars are already empty, nothing to clean ♪")
        return True

    if lowered in {"stats", "usage"}:
        await _handle_stats(message)
        return True

    # --- daily news -------------------------------------------------------
    if lowered == "news" or lowered.startswith("news "):
        await _handle_news(message)
        return True

    # --- agent bridge (Discord -> DSH queue) ------------------------------
    if lowered == "agent" or lowered.startswith(("agent ", "task ", "dsh ")):
        await _handle_agent(message, body)
        return True

    # --- minecraft --------------------------------------------------------
    if lowered == "mc" or lowered.startswith(("mc ", "minecraft")):
        await _handle_minecraft(message, body)
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
                await _send(channel, 
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
                await _send(channel, 
                    "I've learned the summary from the stars ♪"
                    if stored
                    else "I could not store that, sorry ♪"
                )
                return

            await _send(channel, 
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
                await _send(channel, 
                    "The pages were unreachable, so I kept the summary instead ♪"
                    if stored
                    else "I could not store that, sorry ♪"
                )
                return
            combined = f"Question: {query}\n\n" + "\n\n---\n\n".join(texts)
            stored = await memory.add(
                combined, source=f"user:{message.author.name} (web)"
            )
            await _send(channel, 
                f"✨ Learned from {len(used)} source(s) ♪"
                if stored
                else "I could not store that, sorry ♪"
            )
            return

        conversation = last_conversation.get(user_id)
        if not conversation:
            await _send(channel, 
                "I have no recent conversation to learn from. Chat with me first ♪"
            )
            return
        stored = await memory.add(
            f"Q: {conversation['user']}\nA: {conversation['bot']}",
            source=f"user:{message.author.name}",
        )
        await _send(channel, 
            "Saved our last exchange to my memory ♪"
            if stored
            else "I could not store that, sorry ♪"
        )
        return

    if lowered.startswith("learn from "):
        url = body[len("learn from ") :].strip()
        if not url.startswith(("http://", "https://")):
            await _send(channel, "Give me a full URL, e.g. `#learn from https://example.com` ♪")
            return
        await _send(channel, f"📚 Reading {url} ...")
        page = await search.fetch_page(url, max_chars=8000)
        if not page:
            await _send(channel, "I could not read that page (blocked or not text) ♪")
            return
        stored = await memory.add(
            f"Source: {url}\n\n{page}",
            source=f"user:{message.author.name} (url)",
            url=url,
        )
        await _send(channel, 
            "✨ Learned it and stored it in my memory ♪"
            if stored
            else "I could not store that, sorry ♪"
        )
        return

    text = body[len("learn") :].strip()
    if not text:
        await _send(channel, "Tell me what to learn: `#learn Honkai Star Rail 4.2 out in April` ♪")
        return
    stored = await memory.add(text, source=f"user:{message.author.name}")
    await _send(channel, 
        "Added to my stars, thank you for sharing ♪"
        if stored
        else "I could not store that, sorry ♪"
    )


async def _handle_knowledge(message: discord.Message, user_id: int) -> None:
    channel = message.channel
    total = await memory.count()
    if total == 0:
        await _send(channel, "My stars hold no knowledge yet. Teach me with `#learn` ♪")
        return
    entries = await memory.listing(limit=50)
    last_listing[user_id] = entries
    lines = [f"I hold **{total}** pieces of knowledge. First {len(entries)}:"]
    for index, (_, document) in enumerate(entries, 1):
        preview = document[:60].replace("\n", " ")
        lines.append(f"`{index}.` {preview}")
    lines.append("Use `#forget <number>` to remove one.")
    await _send(channel, "\n".join(lines)[:1990])


async def _handle_forget(message: discord.Message, body: str, user_id: int) -> None:
    channel = message.channel
    argument = body[len("forget") :].strip()
    entries = last_listing.get(user_id)
    if not entries:
        await _send(channel, "Run `#knowledge` first so I know which number you mean ♪")
        return
    try:
        index = int(argument) - 1
    except ValueError:
        await _send(channel, "Use `#forget 2` with a number ♪")
        return
    if not 0 <= index < len(entries):
        await _send(channel, f"Pick a number between 1 and {len(entries)} ♪")
        return
    entry_id, document = entries.pop(index)
    await memory.delete([entry_id])
    preview = document[:60].replace("\n", " ")
    await _send(channel, f"Forgotten: `{preview}` ... the stars are emptier now ♪")


async def _handle_imagine(message: discord.Message, body: str, user_id: int) -> None:
    channel = message.channel
    prompt = body[len("imagine") :].strip()
    hq = False
    if prompt.lower().startswith("hq "):
        hq = True
        prompt = prompt[3:].strip()
    if not prompt:
        await _send(channel, "What should I draw? `#imagine a cat on a cloud` ♪")
        return

    async with channel.typing():
        await _send(channel, 
            "🎨 Painting..." if not hq else "🎨 Painting with the premium brush..."
        )
        try:
            pictures = await imagine.generate(prompt, hq=hq)
        except imagine.ImageError as exc:
            await _send(channel, f"🖌️ I could not create that image: {exc}")
            return
    await send_pictures(channel, pictures)


async def _handle_edit(message: discord.Message, body: str) -> None:
    channel = message.channel
    instruction = body[len("edit") :].strip()
    if not instruction:
        await _send(channel, "Tell me how to edit it: `#edit make it watercolor` ♪")
        return
    image_bytes = await _first_image(message)
    if image_bytes is None:
        return
    async with channel.typing():
        await _send(channel, "🖌️ Editing your image...")
        try:
            pictures = await imagine.edit(image_bytes, instruction)
        except imagine.ImageError as exc:
            await _send(channel, f"🖌️ Editing failed: {exc}")
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
            await _send(channel, f"👁️ I could not read the image: {exc}")
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


async def _handle_stats(message: discord.Message) -> None:
    """Today's token usage plus the bot's own footprint."""
    import ai

    usage = ai.usage_today()
    total = usage["prompt"] + usage["completion"]

    rss_mb = 0
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass

    uptime_s = int(time.time() - STARTED_AT)
    hours, remainder = divmod(uptime_s, 3600)
    minutes = remainder // 60

    now = datetime.now(settings.tz)
    await _send(
        message.channel,
        f"📊 **{now.strftime('%Y-%m-%d')}** ({settings.timezone})\n"
        f"calls **{usage['calls']}** · tokens **{total:,}** "
        f"(in {usage['prompt']:,} / out {usage['completion']:,})\n"
        f"memory **{rss_mb} MB** · uptime {hours}h {minutes}m",
    )


async def _handle_news(message: discord.Message) -> None:
    import news

    channel = message.channel
    await _send(channel, "📰 Let me check today's news...")
    async with channel.typing():
        text = await news.compose(channel)
    if not text:
        await _send(channel, "Nothing worth reporting came back - try again later ♪")


async def _handle_agent(message: discord.Message, body: str) -> None:
    """Store an instruction for the DSH agent. The bot never executes it."""
    import agent_queue

    channel = message.channel
    user_id = message.author.id

    if not settings.agent_allowed_users:
        await _send(channel, "🧠 The agent bridge is not configured (AGENT_ALLOWED_USERS).")
        return
    if user_id not in settings.agent_allowed_users:
        await _send(channel, "🧠 Only the owner can hand tasks to the agent.")
        return

    text = body
    for keyword in ("agent", "task", "dsh"):
        if text.lower().startswith(keyword):
            text = text[len(keyword) :].lstrip()
            break
    text = text.strip()

    if text.lower() in {"list", "status"}:
        pending = agent_queue.list_tasks("pending")
        running = agent_queue.list_tasks("in_progress")
        lines = [f"🧠 pending {len(pending)} · running {len(running)}"]
        for task in pending[:5]:
            lines.append(f"`#{task['id']}` {task['text'][:90]}")
        for task in running[:5]:
            lines.append(f"`#{task['id']}` (running) {task['text'][:80]}")
        if len(lines) == 1:
            lines.append("Nothing queued.")
        await _send(channel, "\n".join(lines))
        return

    if not text or text.lower() in {"help", "?"}:
        await _send(
            channel,
            "🧠 Hand me a task and I act **inside Discord only**.\n"
            "`#agent create a channel called news-only`\n"
            "`#agent list` shows the queue.",
        )
        return

    try:
        task = agent_queue.enqueue(
            text, user_id, message.author.name, channel.id, message.id
        )
    except RuntimeError:
        await _send(channel, "🧠 The queue is full (5 pending), wait for me to clear it.")
        return

    await _send(
        channel,
        f"🧠 Queued `#{task['id']}` for DSH: {task['text']}\n"
        "I'll post the result here once it is done.",
    )


async def _handle_minecraft(message: discord.Message, body: str) -> None:
    import minecraft as mc

    channel = message.channel
    argument = body
    for prefix in ("minecraft", "mc"):
        if argument.lower().startswith(prefix):
            argument = argument[len(prefix) :]
            break
    argument = argument.strip()

    action, _, target = argument.partition(" ")
    action = action.lower().strip()
    target = target.strip() or None

    if action in {"", "status", "s", "list", "ls"}:
        try:
            servers = await mc.list_status()
        except mc.MCError as exc:
            await _send(channel, f"⛏️ {exc}")
            return
        except Exception as exc:
            log.warning("Aternos status failed: %s", exc)
            await _send(channel, f"⛏️ Could not reach Aternos: {exc}")
            return
        if not servers:
            await _send(channel, "⛏️ No servers are visible on this Aternos account.")
            return
        await _send(channel, 
            "⛏️ **Minecraft servers**\n" + "\n".join(mc.format_status(s) for s in servers)
        )
        return

    if action in {"start", "on", "up"}:
        try:
            info = await mc.start(target)
        except mc.MCError as exc:
            await _send(channel, f"⛏️ {exc}")
            return
        except Exception as exc:
            log.warning("Aternos start failed: %s", exc)
            await _send(channel, f"⛏️ Could not start the server: {exc}")
            return

        if info.get("already"):
            await _send(channel, 
                f"🟢 **{info['name']}** is already online: `{info['address']}` "
                f"({mc.format_players(info)}) ♪"
            )
            return

        await _send(channel, 
            f"🕹️ Start request sent to **{info['name']}** (state: `{info.get('state')}`).\n"
            f"I'll post here the moment it's online ♪"
        )
        return

    await _send(channel, 
        "Usage: `#mc status` lists the servers · `#mc start [name]` asks Aternos to boot one ♪"
    )


async def _handle_song(message: discord.Message, body: str) -> None:
    channel = message.channel
    name = re.sub(r"^let'?s sing\b", "", body, flags=re.IGNORECASE).strip()
    if not name:
        await _send(channel, "Which song shall we sing? ♪")
        return
    entries = await memory.search(name, k=1)
    if not entries:
        await _send(channel, 
            "I don't know that song yet. Teach it with `#learn` first, or search it ♪"
        )
        return
    lyrics = [line.strip() for line in entries[0].splitlines() if line.strip()]
    if len(lyrics) < 2:
        await _send(channel, "That looks too short to sing. Maybe it is just a title? ♪")
        return
    games[message.author.id] = {
        "song": name,
        "lyrics": lyrics,
        "current_index": 0,
        "channel": channel.id,
    }
    await _send(channel, 
        f"Let's sing **{name}**! I'll follow your lead. Start: {lyrics[0]} ♪"
    )


async def _first_image(message: discord.Message) -> bytes | None:
    """Download the first image attachment, telling the user when it is missing."""
    if not message.attachments:
        await _send(message.channel, "Please attach an image to that command ♪")
        return None
    attachment = message.attachments[0]
    looks_like_image = (
        (attachment.content_type or "").startswith("image/")
        or (attachment.filename or "").lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        )
    )
    if not looks_like_image:
        await _send(message.channel, "That does not look like an image file ♪")
        return None
    try:
        return await vision.download(attachment.url)
    except Exception as exc:
        log.warning("Attachment download failed: %s", exc)
        await _send(message.channel, "I could not download the attachment ♪")
        return None
