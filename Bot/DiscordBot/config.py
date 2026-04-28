import os
from dotenv import load_dotenv

# 加载 .env 文件到环境变量
load_dotenv()

# API Keys（去掉默认值，强制必须配置）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
ALIYUN_API_KEY = os.getenv("ALIYUN_API_KEY")

# 检查必要的密钥是否存在，缺失则报错并退出
if not DISCORD_TOKEN:
    raise ValueError("环境变量 DISCORD_TOKEN 未设置！")
if not DEEPSEEK_API_KEY:
    raise ValueError("环境变量 DEEPSEEK_API_KEY 未设置！")

# Discord Channel IDs
ONLINE_CHANNEL_ID = 1485737959792578704

# Paths
CHROMA_PATH = "./chroma_knowledge"
STICKERS_DIR = "./stickers"


# 其他配置
MAX_HISTORY = 30
CACHE_DURATION = 300
FLARESOLVERR_URL = "http://localhost:8191/v1"
MAX_IMAGES_PER_CHANNEL = 10

print("[DEBUG] config.py 加载完成")
print(f"[DEBUG] DISCORD_TOKEN: {DISCORD_TOKEN[:10]}...")  # 只显示前10个字符
#print(f"[DEBUG] GROQ_API_KEY: {'已设置' if GROQ_API_KEY else '未设置'}")