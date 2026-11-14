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
"""

LANGUAGE_RULES = {
    "english": "Reply in English unless the user writes in another language.",
    "chinese": "始终用中文回复。",
}


def language_rule(code: str) -> str:
    """Return the instruction that pins the reply language."""
    return LANGUAGE_RULES.get(code, LANGUAGE_RULES["english"])
