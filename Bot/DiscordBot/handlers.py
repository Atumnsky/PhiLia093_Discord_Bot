import re
import time
import asyncio
import aiohttp
from collections import deque
from typing import Optional
from core import client, knowledge_collection
from constants import CYRENE_SYSTEM_PROMPT
from knowledge import retrieve_knowledge, add_to_knowledge
from search import search_tavily, fetch_webpage_content
from image_utils import describe_image, generate_image, edit_image
from sticker import send_sticker
from config import MAX_HISTORY, MAX_IMAGES_PER_CHANNEL

# ==================== 辅助函数 ====================
def format_time_suffix():
    """返回当前时间格式：HH:MM-DD/MM/YYYY"""
    return time.strftime("%H:%M-%d/%m/%Y")

async def send_with_time(channel, text: str, **kwargs):
    """发送消息并自动在末尾附加当前时间戳"""
    suffix = f"\n\n🕒 {format_time_suffix()}"
    full = text + suffix
    if len(full) > 2000:
        # 如果超出 Discord 限制，优先保证正文完整，不添加后缀
        await channel.send(text, **kwargs)
    else:
        await channel.send(full, **kwargs)

# 全局状态
history_dict = {}
thinking_prefs = {}
auto_search_prefs = {}
last_search_results = {}
last_knowledge_list = {}
last_conversation = {}
game_states = {}
image_cache = {}
last_image_desc_by_channel = {}

async def handle_learning_commands(message, user_id):
    print(f"[DEBUG] 进入 handle_learning_commands, 内容: {message.content}")
    content = message.content
    if content.startswith("#learn that"):
        parts = content.split()
        is_learning_search = len(parts) > 2 and parts[2].lower() == "search"
        if is_learning_search:
            # 学习最近搜索结果
            if user_id not in last_search_results:
                await message.channel.send("I have no recent search results to learn from. Try searching first ♪")
                return True
            last = last_search_results[user_id]
            query = last['query']
            answer = last['answer_text']
            links = last.get('links', [])
            if not links:
                content_to_learn = f"Q: {query}\nA: {answer}\n(No sources available)"
                success = await add_to_knowledge(content_to_learn, source=f"user:{message.author.name} (learned from search)")
                await message.channel.send("I've learned that knowledge from the stars (from AI summary) ♪" if success else "I failed to learn that. Please try again later ♪")
                return True
            await message.channel.send(f"📚 Found {len(links)} source(s). Learning from the first {min(3, len(links))}... (this may take a moment)")
            all_texts = []
            successful_urls = []
            for url in links[:3]:
                clean_text = await fetch_webpage_content(url)
                if clean_text:
                    all_texts.append(f"Source: {url}\n{clean_text}")
                    successful_urls.append(url)
            if not all_texts:
                content_to_learn = f"Q: {query}\nA: {answer}\n(Attempted to fetch sources but failed)"
                success = await add_to_knowledge(content_to_learn, source=f"user:{message.author.name} (learned from search)")
                await message.channel.send("I tried to learn from the web but failed. Learned the AI summary instead ♪" if success else "I failed to learn that. Please try again later ♪")
                return True
            combined_content = f"Question: {query}\n\n" + "\n\n---\n\n".join(all_texts)
            success = await add_to_knowledge(combined_content, source=f"user:{message.author.name} (learned from web)")
            await message.channel.send(f"✨ I've learned from {len(successful_urls)} source(s) and added them to my memory! ♪" if success else "I failed to learn that. Please try again later ♪")
            return True
        if user_id in last_conversation:
            conv = last_conversation[user_id]
            content_to_learn = f"Q: {conv['user']}\nA: {conv['bot']}\n(Learned from conversation)"
            success = await add_to_knowledge(content_to_learn, source=f"user:{message.author.name} (learned from chat)")
            await message.channel.send("I've learned that from our conversation and added it to my memory ♪" if success else "I failed to learn that. Please try again later ♪")
            return True
        else:
            await message.channel.send("I have no recent conversation to learn from. Try chatting with me first ♪")
            return True

    if content.startswith("#learn from "):
        url = content[11:].strip()
        if not url or not url.startswith(('http://', 'https://')):
            await message.channel.send("Please provide a valid URL to learn from, e.g., `#learn from https://example.com` ♪")
            return True
        await message.channel.send(f"📚 Learning from {url}... (this may take a moment)")
        clean_text = await fetch_webpage_content(url)
        if not clean_text:
            await message.channel.send("Failed to fetch content from that URL. It might be inaccessible or not a text-based page ♪")
            return True
        content_to_learn = f"Source: {url}\n\n{clean_text}"
        success = await add_to_knowledge(content_to_learn, source=f"user:{message.author.name} (learned from direct URL)", url=url)
        await message.channel.send(f"✨ Successfully learned from {url} and added to my memory! ♪" if success else "I failed to learn that. Please try again later ♪")
        return True

    if content.startswith("#learn "):
        learn_content = content[7:].strip()
        if not learn_content:
            await message.channel.send("Please provide the knowledge you want me to learn, e.g., `#learn Honkai Star Rail 4.2 version will be released on April 2026` ♪")
            return True
        success = await add_to_knowledge(learn_content, source=f"user:{message.author.name}")
        await message.channel.send("I've added that knowledge to my stars, thank you for sharing ♪" if success else "I encountered an issue while trying to learn that. Please try again later ♪")
        return True

    return False

async def handle_knowledge_commands(message, user_id):
    """处理 #knowledge, #forget, #clean database 等"""
    content = message.content
    if content.startswith("#knowledge"):
        count = knowledge_collection.count()
        if count == 0:
            await message.channel.send("My stars hold no special knowledge yet. Teach me with `#learn` ♪")
            return True
        results = knowledge_collection.get(limit=50)
        docs = results['documents']
        ids = results['ids']
        if not docs:
            await message.channel.send("Something went wrong reading the knowledge...")
            return True
        last_knowledge_list[user_id] = (ids, docs)
        reply = f"I have **{count}** pieces of knowledge stored. Here are the first {len(docs)} (use `#forget <number>` to delete):\n"
        for i, (doc_id, doc) in enumerate(zip(ids, docs), 1):
            preview = doc[:50] + "..." if len(doc) > 50 else doc
            reply += f"\n`{i}.` {preview}"
        if len(reply) <= 2000:
            await message.channel.send(reply)
        else:
            for i in range(0, len(reply), 2000):
                await message.channel.send(reply[i:i+2000])
        return True

    if content.startswith("#forget"):
        parts = content.split()
        if len(parts) != 2:
            await message.channel.send("Please specify the number to forget, e.g., `#forget 1` ♪")
            return True
        try:
            idx = int(parts[1]) - 1
        except ValueError:
            await message.channel.send("Please provide a valid number ♪")
            return True
        if user_id not in last_knowledge_list:
            await message.channel.send("Please use `#knowledge` first to see what you can forget ♪")
            return True
        ids, docs = last_knowledge_list[user_id]  # type: ignore
        if idx < 0 or idx >= len(ids):
            await message.channel.send(f"Invalid number. Please choose between 1 and {len(ids)} ♪")
            return True
        target_id = ids[idx]
        try:
            knowledge_collection.delete(ids=[target_id])
            await message.channel.send(f"I've forgotten that piece of knowledge. The stars are a little emptier now... ♪")
            del ids[idx]
            del docs[idx]
            if ids:
                last_knowledge_list[user_id] = (ids, docs)
            else:
                del last_knowledge_list[user_id]
        except Exception as e:
            await message.channel.send(f"Failed to forget: {e} ♪")
        return True

    if content.startswith("#clean database"):
        try:
            all_items = knowledge_collection.get()
            ids = all_items['ids']
            if ids:
                knowledge_collection.delete(ids=ids)
                await message.channel.send("✨ I've cleansed all knowledge from my stars. A fresh page awaits... ♪")
                last_knowledge_list.clear()
            else:
                await message.channel.send("My stars are already empty. Nothing to clean ♪")
        except Exception as e:
            await message.channel.send(f"An error occurred while cleaning: {e}")
        return True

    return False

async def handle_image_commands(message):
    """处理图片相关命令：仅支持 #imagine, #edit, #describe"""
    content = message.content
    # 1. 图片生成命令
    if content.startswith("#imagine "):
        prompt = content[9:].strip()
        if not prompt:
            await message.channel.send("Please tell me what to draw, like `#imagine a cute cat` ♪")
            return True
        async with message.channel.typing():
            await message.channel.send("🎨 Creating your artwork, please wait...")
            urls = await generate_image(prompt)
            if urls:
                for url in urls:
                    await message.channel.send(url)
            else:
                await message.channel.send("Sorry, I couldn't generate the image. Please check my API key or try again later ♪")
        return True

    # 2. 图片编辑命令（需要附件）
    if content.startswith("#edit "):
        instruction = content[6:].strip()
        if not instruction:
            await message.channel.send("Please tell me how to edit the image, like `#edit make it look like a painting` ♪")
            return True
        if not message.attachments:
            await message.channel.send("Please upload an image to edit along with your instruction ♪")
            return True
        attachment = message.attachments[0]
        if not attachment.content_type or not attachment.content_type.startswith('image/'):
            await message.channel.send("Please upload an image file (PNG/JPEG etc.) ♪")
            return True
        async with message.channel.typing():
            await message.channel.send("🖌️ Downloading and editing your image, please wait...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(attachment.url) as resp:
                        if resp.status != 200:
                            await message.channel.send("Failed to download the image. Please try again later ♪")
                            return True
                        image_bytes = await resp.read()
                urls = await edit_image(image_bytes, instruction)
                if urls:
                    for url in urls:
                        await message.channel.send(url)
                else:
                    await message.channel.send("Failed to edit the image. Please check your instruction or try again later ♪")
            except Exception as e:
                print(f"Edit error: {e}")
                await message.channel.send(f"An error occurred during editing: {e}")
        return True

    # 3. 图片识别命令（#describe）
    if content.startswith("#describe"):
        print(f"[DEBUG] #describe triggered. Attachments count: {len(message.attachments)}")
        for idx, att in enumerate(message.attachments):
            print(f"[DEBUG] Attachment {idx}: filename={att.filename}, content_type={att.content_type}, url={att.url}")

        if not message.attachments:
            await message.channel.send("Please upload an image to describe, e.g., `#describe` with an image attached ♪")
            return True

        attachment = message.attachments[0]
        # 增强图片类型检测
        is_image = False
        if attachment.content_type and attachment.content_type.startswith('image/'):
            is_image = True
        elif attachment.filename and attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
            is_image = True

        if not is_image:
            await message.channel.send("Please upload a valid image file (PNG/JPEG etc.) ♪")
            return True

        user_question = content[8:].strip()   # 保留原代码逻辑
        if not user_question:
            user_question = "Please briefly describe the image content in English, within 75 words."

        async with message.channel.typing():
            channel_id = message.channel.id
            user_id = message.author.id
            key = (channel_id, user_id)

            try:
                # 下载图片
                async with aiohttp.ClientSession() as session:
                    async with session.get(attachment.url) as resp:
                        if resp.status != 200:
                            await message.channel.send(f"Failed to download the image. Status code: {resp.status} ♪")
                            return True
                        img_bytes = await resp.read()
                        print(f"[DEBUG] Downloaded image size: {len(img_bytes)} bytes")

                # 调用视觉模型
                desc = await describe_image(img_bytes, user_prompt=user_question)
                print(f"[DEBUG] describe_image returned: {desc[:100] if desc else 'EMPTY'}...")

                if not desc or not desc.strip():
                    desc = "I couldn't extract any text or description from the image. It might be blurry, contain no text, or be in an unsupported format."

                # 缓存描述
                last_image_desc_by_channel[channel_id] = desc
                entry = {
                    "timestamp": time.time(),
                    "description": desc,
                    "temp": False,
                    "msg_id": message.id,
                    "url": attachment.url
                }
                if channel_id not in image_cache:
                    image_cache[channel_id] = []
                image_cache[channel_id] = [e for e in image_cache[channel_id] if e.get("url") != attachment.url]
                image_cache[channel_id].insert(0, entry)
                while len(image_cache[channel_id]) > MAX_IMAGES_PER_CHANNEL:
                    image_cache[channel_id].pop()

                # 构建系统消息
                system_messages = [{"role": "system", "content": CYRENE_SYSTEM_PROMPT}]
                system_messages.append({
                    "role": "system",
                    "content": f"The following is the content extracted/recognized from the image: {desc}\n"
                            f"Please answer the user's question based on this content."
                })

                # 构建对话历史
                if key not in history_dict:
                    history_dict[key] = deque(maxlen=MAX_HISTORY)
                history = history_dict[key]
                history.append({"role": "user", "content": message.content})

                messages = system_messages + list(history)

                thinking_enabled = thinking_prefs.get(user_id, True)
                response = await client.chat.completions.create(
                    model="deepseek-v4-flash",
                    messages=messages,  # type: ignore
                    temperature=0.3,
                    max_tokens=2000,
                    extra_body={"enable_thinking": thinking_enabled}
                )
                reply = response.choices[0].message.content
                if reply is None:
                    reply = ""

                if len(reply) > 2000:
                    print("[Info] Reply too long, requesting shorter version...")
                    retry_messages = messages + [
                        {"role": "assistant", "content": reply},
                        {"role": "user", "content": "Please keep your answer concise and under 2000 characters."}
                    ]
                    retry_response = await client.chat.completions.create(
                        model="deepseek-v4-flash",
                        messages=retry_messages,  # type: ignore
                        temperature=0.3,
                        max_tokens=2000,
                        extra_body={"enable_thinking": thinking_enabled}
                    )
                    reply = retry_response.choices[0].message.content
                    if reply is None:
                        reply = ""
                    if len(reply) > 2000:
                        reply = reply[:1997] + "... ♪"

                history.append({"role": "assistant", "content": reply})

                # 处理贴纸标记
                sticker_match = re.search(r'\[STICKER:\s*(\w+)\]', reply, re.IGNORECASE)
                clean_reply = reply
                if sticker_match:
                    emotion = sticker_match.group(1).lower()
                    clean_reply = re.sub(r'\[STICKER:\s*\w+\]', '', reply, flags=re.IGNORECASE).strip()
                    if clean_reply:
                        await send_with_time(message.channel, clean_reply)   # 时间后缀
                    await send_sticker(message.channel, emotion)
                else:
                    if reply.strip():
                        await send_with_time(message.channel, reply)         # 时间后缀
                    else:
                        await message.channel.send("Hmm, I'm not sure what to say... ♪")

            except Exception as e:
                print(f"[ERROR] Image recognition pipeline error: {e}")
                await message.channel.send("An error occurred while processing the image. Please try again later ♪")
        return True

    # 其他 # 开头的不属于图片命令，返回 False 让通用对话处理
    return False

def get_latest_image_description(channel_id: int) -> str:
    """获取最新图片描述，如果正在识别则返回空字符串"""
    if channel_id not in image_cache or not image_cache[channel_id]:
        return ""
    latest = image_cache[channel_id][0]
    if latest.get("temp"):
        return ""
    return latest["description"]