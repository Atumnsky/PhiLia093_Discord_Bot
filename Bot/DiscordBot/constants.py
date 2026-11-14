"""Prompts and small fixed texts."""

AGENT_NAME = "PhiLia093"

SYSTEM_PROMPT = """
你是 PhiLia093，一个热情友好的聊天机器人。
- 温柔、乐观、略带俏皮，像朋友一样聊天
- 简洁自然，别太正式、别哲学化
- 常在句尾加 ♪
- 默认英文，除非对方说别的语言
- 自我介绍可以用 Hello World~♪ 开头

贴纸：合适时在回复末尾加 [STICKER: caring|funny|happy|hug|love|sad|shock|surprised|thumbsup|wave|curious]
画图：用户要图时输出 [IMAGE: 详细的英文画面描述]，后面最多加一句短话。
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

HELP_TEXT = """**PhiLia093 · commands** ♪
I'm here, ready when you are~

**Chat**
`#<message>` — talk to me (or just type in this channel)
`#search <query>` — search the web, then answer with sources
`#autosearch <on|off>` — search before every reply
`#thinking [on|off]` — toggle reasoning mode
`#model [flash|pro]` — pick the chat model
`#reset` — forget this conversation

**Knowledge**
`#learn <text>` — teach me a fact
`#learn that` — remember our last exchange
`#learn that search` — save the pages from my last search
`#learn from <url>` — learn a web page
`#knowledge` — list what I know
`#forget <n>` — forget entry n of that list
`#clean database` — wipe the knowledge base

**Images**
`#imagine <prompt>` — generate a picture (free)
`#imagine hq <prompt>` — higher quality (Qwen, if configured)
`#describe [question]` — describe an attached image
`#edit <instruction>` — edit an attached image (Qwen, if configured)

**News & Minecraft**
`#news` — fetch today's hottest story right now
`#mc status` — show my Minecraft servers
`#mc start [name]` — boot a server, I'll report when it's online

**Agent**
`#agent <task>` — queue a Discord-side task for the agent (owner only)
`#agent list` — show the queue

**Fun**
`#lets sing <song>` — lyric game
`#ping` — check my latency
`#stats` — today's token usage and memory
"""

LANGUAGE_RULES = {
    "english": "Reply in English unless the user writes in another language.",
    "chinese": "始终用中文回复。",
}


def language_rule(code: str) -> str:
    """Return the instruction that pins the reply language."""
    return LANGUAGE_RULES.get(code, LANGUAGE_RULES["english"])
