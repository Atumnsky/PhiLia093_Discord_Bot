import os
import random
import discord
from config import STICKERS_DIR

stickers = {}

def load_stickers():
    """加载本地贴纸，情绪文件夹名 -> 文件路径列表"""
    if not os.path.exists(STICKERS_DIR):
        print(f"贴纸文件夹 {STICKERS_DIR} 不存在，跳过加载")
        return
    for emotion in os.listdir(STICKERS_DIR):
        emotion_dir = os.path.join(STICKERS_DIR, emotion)
        if os.path.isdir(emotion_dir):
            files = []
            for f in os.listdir(emotion_dir):
                if f.lower().endswith(('.webp', '.png', '.gif', '.jpg', '.jpeg')):
                    files.append(os.path.join(emotion_dir, f))
            if files:
                stickers[emotion.lower()] = files
    print(f"贴纸加载完成: {list(stickers.keys())}")

async def send_sticker(channel, emotion: str):
    """发送随机贴纸（作为图片文件）"""
    emotion_lower = emotion.lower()
    if emotion_lower not in stickers or not stickers[emotion_lower]:
        return False
    filepath = random.choice(stickers[emotion_lower])
    try:
        await channel.send(file=discord.File(filepath))
        return True
    except Exception as e:
        print(f"发送贴纸失败: {e}")
        return False