import discord
import asyncio
import os
import aiohttp
import sys
from collections import deque
import time
import re
from typing import cast
from core import client
from constants import CYRENE_SYSTEM_PROMPT, TIME_KEYWORDS
from knowledge import retrieve_knowledge, add_to_knowledge
from search import search_tavily
from image_utils import describe_image
from sticker import load_stickers, send_sticker
from handlers import (
    history_dict, thinking_prefs, auto_search_prefs, last_search_results,
    last_knowledge_list, last_conversation, game_states, image_cache,
    last_image_desc_by_channel,
    handle_learning_commands, handle_knowledge_commands, handle_image_commands,
    get_latest_image_description
)
from config import DISCORD_TOKEN, ONLINE_CHANNEL_ID, MAX_HISTORY, MAX_IMAGES_PER_CHANNEL, PHILIA093_CHAT_CHANNEL

# ==================== 辅助函数 ====================
def format_time_suffix():
    """返回当前时间格式：HH:MM-DD/MM/YYYY"""
    return time.strftime("%H:%M-%d/%m/%Y")

async def send_with_time(channel, text: str, **kwargs):
    """发送消息并自动在末尾附加当前时间戳"""
    suffix = f"\n\n:flag_nl:  {format_time_suffix()}"
    full = text + suffix
    if len(full) > 2000:
        await channel.send(text, **kwargs)
    else:
        await channel.send(full, **kwargs)

# ==================== 主函数 ====================
async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    bot = discord.Client(intents=intents)

    # ---------- 辅助函数：发送离线消息 ----------
    async def send_offline_message_and_close():
        if ONLINE_CHANNEL_ID:
            try:
                channel = bot.get_channel(int(ONLINE_CHANNEL_ID))
                if channel:
                    text_channel = cast(discord.abc.Messageable, channel)
                    await text_channel.send("PhiLia093 is Offline! 👋")
                    guild_name = getattr(channel, 'guild', None)
                    channel_name = getattr(channel, 'name', None)
                    if guild_name and channel_name:
                        print(f"Offline message sent to {guild_name.name}#{channel_name}")
                else:
                    print(f"Channel with ID {ONLINE_CHANNEL_ID} not found.")
            except Exception as e:
                print(f"Failed to send offline message: {e}")
        await bot.close()

    # ---------- 事件：on_ready ----------
    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user}")
        channel = None
        if ONLINE_CHANNEL_ID:
            try:
                channel = bot.get_channel(int(ONLINE_CHANNEL_ID))
            except ValueError:
                print(f"Invalid ONLINE_CHANNEL_ID: {ONLINE_CHANNEL_ID}")
        if not channel:
            for guild in bot.guilds:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break
                if channel:
                    break
        if channel:
            bot.shutdown_channel = channel #type:ignore
            text_channel = cast(discord.abc.Messageable, channel)
            await text_channel.send("PhiLia093 is Online! ✨")
            guild_name = getattr(channel, 'guild', None)
            channel_name = getattr(channel, 'name', None)
            if guild_name and channel_name:
                print(f"Online message sent to {guild_name.name}#{channel_name}")
        load_stickers()

    # ---------- 通用对话处理函数 ----------
    async def handle_chat_message(message, prompt, is_search=False, search_results_text="", search_links=None, search_used=False):
        """统一的对话处理入口：调用 DeepSeek 生成回复并发送"""
        try:
            async with message.channel.typing():
                knowledge_docs, knowledge_metas = retrieve_knowledge(prompt)

                current_time = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
                system_messages = [{"role": "system", "content": CYRENE_SYSTEM_PROMPT}]
                system_messages.append({
                    "role": "system",
                    "content": (
                        f"IMPORTANT: The current real-world date and time is {current_time}. "
                        "You MUST use this as the absolute truth for any time-related questions. "
                        "Ignore your internal knowledge cutoff if it contradicts this time."
                    )
                })

                if search_used:
                    if search_results_text:
                        search_context = f"Here are some search results for '{prompt}':\n\n{search_results_text}\n\nPlease answer based on these results. If they don't contain the answer, say so politely. ♪"
                    else:
                        search_context = f"No search results found for '{prompt}'. Please answer using your own knowledge. ♪"
                    system_messages.append({"role": "system", "content": search_context})
                elif knowledge_docs:
                    knowledge_text = "\n\n".join(knowledge_docs)
                    system_messages.append({
                        "role": "system",
                        "content": f"Relevant knowledge from my stars:\n{knowledge_text}\n\nYou may use this if helpful, but answer naturally. ♪"
                    })

                channel_id = message.channel.id
                latest_desc = get_latest_image_description(channel_id)
                if latest_desc:
                    system_messages.append({
                        "role": "system",
                        "content": f"The following is the content extracted/recognized from the most recent image: {latest_desc}\nIf the user asks about this image or its content, please base your answer on this content and naturally mention 'According to the extracted text...'."
                    })

                key = (message.channel.id, message.author.id)
                if key not in history_dict:
                    history_dict[key] = deque(maxlen=MAX_HISTORY)
                history = history_dict[key]
                history.append({"role": "user", "content": prompt})

                messages = system_messages + list(history)

                thinking_enabled = thinking_prefs.get(message.author.id, True)
                response = await client.chat.completions.create(
                    model="deepseek-v4-flash",
                    messages=messages, #type: ignore
                    temperature=0.3,
                    max_tokens=2000,
                    extra_body={"enable_thinking": thinking_enabled}
                )
                reply = response.choices[0].message.content
                if reply is None:
                    reply = ""
                history.append({"role": "assistant", "content": reply})

                if search_used:
                    last_search_results[message.author.id] = {
                        'query': prompt,
                        'answer_text': reply,
                        'links': search_links or []
                    }

                sticker_match = re.search(r'\[STICKER:\s*(\w+)\]', reply, re.IGNORECASE)
                clean_reply = reply
                if sticker_match:
                    emotion = sticker_match.group(1).lower()
                    clean_reply = re.sub(r'\[STICKER:\s*\w+\]', '', reply, flags=re.IGNORECASE).strip()
                    if clean_reply:
                        await send_with_time(message.channel, clean_reply)
                    await send_sticker(message.channel, emotion)
                else:
                    if reply.strip():
                        await send_with_time(message.channel, reply)
                    else:
                        await message.channel.send("Hmm, I'm not sure what to say... ♪")

                if search_links and len(search_links) > 0:
                    sources = "\n".join([f"[{i+1}] {url}" for i, url in enumerate(search_links)])
                    source_msg = f"**Sources:**\n{sources}"
                    await send_with_time(message.channel, source_msg)

                if not is_search and bot.user and message.author.id != bot.user.id:
                    last_conversation[message.author.id] = {
                        'user': prompt,
                        'bot': reply
                    }

        except Exception as e:
            await message.channel.send(f"An error occurred: {e}")

    # ---------- 事件：on_message ----------
    @bot.event
    async def on_message(message):
        if message.author == bot.user:
            return

        user_id = message.author.id

        # --- 游戏模式处理 ---
        if user_id in game_states:
            state = game_states[user_id]
            if message.content.startswith("#"):
                if message.content.startswith("#exit") or message.content.startswith("#stop"):
                    del game_states[user_id]
                    await message.channel.send("Game ended. Let's chat normally now ♪")
                    return
                else:
                    del game_states[user_id]
            else:
                if state['mode'] == 'lyric_game':
                    lyrics = state['lyrics']
                    current_index = state['current_index']
                    if current_index < len(lyrics) - 1:
                        next_line = lyrics[current_index + 1]
                        state['current_index'] = current_index + 2
                        await message.channel.send(f"{next_line} ♪")
                    else:
                        del game_states[user_id]
                        await message.channel.send("We've reached the end of the song. It was lovely singing with you ♪")
                    return

        # --- 思考模式开关 ---
        if message.content.startswith("#thinking"):
            current = thinking_prefs.get(user_id, True)
            new_mode = not current
            thinking_prefs[user_id] = new_mode
            status = "on" if new_mode else "off"
            await message.channel.send(f"Thinking mode switched to: **{status}** ♪")
            return

        # --- 自动搜索模式开关 ---
        if message.content.startswith("#autosearch"):
            parts = message.content.split()
            if len(parts) == 2:
                option = parts[1].lower()
                if option == "on":
                    auto_search_prefs[user_id] = True
                    await message.channel.send("Auto-search mode is now **on**. I'll search the stars when my own memory fades ♪")
                elif option == "off":
                    auto_search_prefs[user_id] = False
                    await message.channel.send("Auto-search mode is now **off**. I'll rely on what I've learned ♪")
                else:
                    await message.channel.send("Please specify `on` or `off`, like `#autosearch on` ♪")
            else:
                current = auto_search_prefs.get(user_id, False)
                status = "on" if current else "off"
                await message.channel.send(f"Auto-search mode is currently **{status}**. Use `#autosearch on/off` to change ♪")
            return

        # --- 学习命令 ---
        if message.content.startswith("#learn"):
            handled = await handle_learning_commands(message, user_id)
            if handled:
                return

        # --- 知识库命令 ---
        if message.content.startswith(("#knowledge", "#forget", "#clean database")):
            handled = await handle_knowledge_commands(message, user_id)
            if handled:
                return

        # --- 启动歌词接龙游戏 ---
        if message.content.startswith("#lets sing "):
            song_name = message.content[10:].strip()
            if not song_name:
                await message.channel.send("Which song would you like to sing? Please tell me the name ♪")
                return
            docs, metas = retrieve_knowledge(song_name)
            if not docs:
                await message.channel.send("I don't know that song yet. Try teaching it to me with `#learn` first ♪")
                return
            lyrics = docs[0].split('\n')
            lyrics = [line.strip() for line in lyrics if line.strip()]
            if len(lyrics) < 2:
                await message.channel.send("That song seems too short to sing together. Maybe it's just a title? ♪")
                return
            game_states[message.author.id] = {
                'mode': 'lyric_game',
                'song_name': song_name,
                'lyrics': lyrics,
                'current_index': 0
            }
            await message.channel.send(f"Great! Let's sing '{song_name}' together. I'll sing after you. Start with the first line: {lyrics[0]} ♪")
            return

        # --- 图片命令 ---
        if message.content.startswith(("#imagine", "#edit", "#describe")):
            handled = await handle_image_commands(message)
            if handled:
                return

        # ===== 免前缀频道特殊处理 =====
        if PHILIA093_CHAT_CHANNEL and message.channel.id == PHILIA093_CHAT_CHANNEL:
            # 在免前缀频道，非 # 开头的消息直接触发对话
            if not message.content.startswith('#'):
                user_text = message.content.strip()
                if not user_text:
                    return

                # 自动判断是否需要搜索
                is_search = any(keyword in user_text.lower() for keyword in TIME_KEYWORDS)
                search_results_text = ""
                search_links = []
                if is_search:
                    await message.channel.send(f"Searching for **{user_text}**...")
                    search_results_text, search_links = await search_tavily(user_text, max_results=5)

                await handle_chat_message(
                    message=message,
                    prompt=user_text,
                    is_search=is_search,
                    search_results_text=search_results_text,
                    search_links=search_links,
                    search_used=is_search
                )
                return
            # 如果是以 # 开头，则继续向下走正常命令处理（不 return）

        # --- 原有的 # 开头命令处理逻辑 ---
        if not message.content.startswith("#"):
            return  # 非免前缀频道且不以 # 开头，忽略

        full_command = message.content[1:].strip()
        if not full_command:
            await message.channel.send("Please say something, like `# What's new in Honkai Star Rail?` ♪")
            return

        is_search = full_command.lower().startswith("search ")
        if is_search:
            query = full_command[7:].strip()
            if not query:
                await message.channel.send("Please specify what to search, e.g., `#search Nvidia stock price` ♪")
                return
            prompt = query
        else:
            prompt = full_command
            # 自动为时间查询开启搜索
            if any(keyword in prompt.lower() for keyword in TIME_KEYWORDS):
                is_search = True
                print("Auto-enabled search for time query")

        # 搜索预处理
        search_results_text = ""
        search_links = []
        if is_search:
            await message.channel.send(f"Searching for **{prompt}**...")
            search_results_text, search_links = await search_tavily(prompt, max_results=5)

        # 调用统一对话处理函数
        await handle_chat_message(
            message=message,
            prompt=prompt,
            is_search=is_search,
            search_results_text=search_results_text,
            search_links=search_links,
            search_used=is_search
        )

    # ---------- 启动 Bot ----------
    try:
        await bot.start(DISCORD_TOKEN) #type: ignore
    except asyncio.CancelledError:
        print("Bot cancelled (likely Ctrl+C), sending offline message...")
        await send_offline_message_and_close()
    except Exception as e:
        print(f"Unexpected error: {e}")
        await send_offline_message_and_close()
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())