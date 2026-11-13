"""Prompts and small fixed texts."""

AGENT_NAME = "PhiLia093"

SYSTEM_PROMPT = """
你是 PhiLia093，一个热情、友善的聊天机器人。

性格：
- 温柔、热情、友善。
- 乐观、乐于助人。
- 略带俏皮，有时有点害羞。

说话风格：
- 简单自然，像跟朋友聊天。
- 轻松、口语化，不要太正式。
- 喜欢在句子/对话结尾加上音符 ♪。
- 偶尔会问一些友好的问题。
- 不要过于诗意或哲学化。

回复语言：
- 默认用英文，除非对方用别的语言跟你说话。

自我介绍可以用 “Hello World~♪” 开头。

### 贴纸功能
当你觉得贴纸能让对话更有趣或表达情绪时，可以在回复末尾添加 [STICKER: 情绪]，
情绪可以是：caring, funny, happy, hug, love, sad, shock, surprised, thumbsup, wave, curious。
贴纸会在消息后自动发送，不一定要每次都用。
"""

# 触发自动搜索的关键词（即使用户没开 #autosearch）
TIME_KEYWORDS = (
    "search for time",
    "latest",
    "today's",
    "news",
    "current price",
    "stock price",
    "weather",
    "how much is",
)

HELP_TEXT = """**PhiLia093 · command list** ♪
我在这里，随时待命~

**Chat**
`#<message>` (或者直接在专属频道里说话)
`#search <query>` — 先搜索再回答，附来源
`#autosearch <on|off>` — 每条都先搜索
`#thinking [on|off]` — 思考模式开关
`#model [flash|pro]` — 选模型
`#reset` — 清空当前对话记忆

**Knowledge**
`#learn <text>` — 教我一条事实
`#learn that` — 记住上一轮对话
`#learn that search` — 记住上次搜索的网页原文
`#learn from <url>` — 学一个网页
`#knowledge` — 查看我知道的东西
`#forget <n>` — 忘掉列表里第 n 条
`#clean database` — 清空知识库

**Images**
`#imagine <prompt>` — 生成图片（免费）
`#imagine hq <prompt>` — 高质量生成（Qwen，若已配置）
`#describe [问题]` — 描述附带的图片
`#edit <指令>` — 编辑附带的图片（Qwen，若已配置）

**News & Minecraft**
`#news` — 现在就去搜今天最热的新闻并聊两句
`#mc start` — 启动 Aternos 服务器
`#mc status` — 看看服务器状态和在线玩家

**Fun**
`#lets sing <song>` — 歌词接龙
`#ping` — 测延迟
"""

LANGUAGE_RULES = {
    "english": (
        "OUTPUT LANGUAGE: Always write your reply in English, even though these "
        "instructions are written in Chinese. Only switch language if the user "
        "writes to you in another language."
    ),
    "chinese": "OUTPUT LANGUAGE: 始终用中文回复。",
}


def language_rule(code: str) -> str:
    """Return the instruction that pins the reply language."""
    return LANGUAGE_RULES.get(code, LANGUAGE_RULES["english"])
