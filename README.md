# PhiLia093 Discord Bot

PhiLia (ID: PhiLia093) — a friendly roleplay chatbot for Discord, with web search,
a small local knowledge base, sticker reactions, free image generation, a daily
news habit and a Minecraft (Aternos) starter.

## Stack

| Feature | Service | Cost |
| --- | --- | --- |
| Chat / reasoning | DeepSeek `deepseek-flash`, `deepseek-v4-pro` (`#model pro`) | paid, very cheap |
| Image generation | [Pollinations.ai](https://pollinations.ai) `flux` (default), Aliyun `qwen-image-3.0-pro` for `#imagine hq` | free / paid |
| Image recognition | Aliyun DashScope `qwen3-vl-plus` (any OpenAI-compatible vision model works) | paid, ~1 cent / image |
| Web search | Tavily (free tier 1000 credits/month), keyless DuckDuckGo fallback | free / paid |
| Knowledge base | ChromaDB + local ONNX MiniLM embeddings (no torch, no API) | free |
| Daily news | one search + one short reply per day | ~free |
| Minecraft | `python-aternos` (unofficial Aternos API) | free |
| Stickers | local files in `stickers/<emotion>/` | free |

## Commands

Chat — prefix `#`, or no prefix at all inside the channels listed in
`PHILIA093_CHAT_CHANNEL` (or a channel named `philia-chat`):

```
#hello                talk to PhiLia
#search <query>       search the web, then answer with sources
#autosearch on|off    search before every reply
#thinking on|off      toggle the reasoning mode
#model flash|pro      pick the chat model
#reset                clear this conversation's history
```

Knowledge:

```
#learn <text>         teach a fact
#learn that           save the last exchange
#learn that search    save the last search (reads up to 3 sources)
#learn from <url>     learn from a web page
#knowledge            list what she knows
#forget <n>           delete entry n from that list
#clean database       wipe the knowledge base
```

Images:

```
#imagine <prompt>     free image (Pollinations)
#imagine hq <prompt>  premium image (Qwen-Image, needs ALIYUN_API_KEY)
#describe [question]  describe an attached image
#edit <instruction>   edit an attached image (needs ALIYUN_API_KEY)
```

News & Minecraft:

```
#news                 fetch today's hottest story right now
#mc start             boot the Aternos server, then report when it is online
#mc status            current state, address and online players
```

Fun: `#lets sing <song>` (lyric game), `#ping`, `#help`.

## Daily news

`news.py` runs a background loop: every day at `NEWS_TIME` plus a random
`NEWS_JITTER_MINUTES` it searches the web, asks the model to pick the single
hottest global story, adds one personal reaction and a question, then posts it
with sources. The last run date is stored in `data/state.json`, so a restart
does not produce duplicates. Set `NEWS_ENABLED=false` to turn it off,
`NEWS_CHANNEL_ID` to post somewhere else.

## Agent bridge (Discord → DSH)

`#agent <task>` stores an instruction in `data/agent_tasks.json`. The bot only
writes text — it never executes anything. The DSH agent reads the queue over
SSH, does the work **inside Discord / bot scope only** (channels, messages,
roles, bot config, bot files), then posts the result back and closes the task.

```
#agent create a channel called news-only
#agent list
```

- Only user IDs in `AGENT_ALLOWED_USERS` may queue tasks; empty disables it.
- Max 5 pending tasks, 800 characters each.
- The agent side uses the CLI: `venv/bin/python agent_queue.py list|claim|done|fail`.

Scope rule: the agent refuses anything that would touch the user's own computer.
The bridge can only ever ask for Discord/bot changes.

## Minecraft (Aternos)

`#mc start` logs into Aternos with the account from `.env`, calls the start
endpoint, then polls every 15 seconds for up to 20 minutes and announces when
the server is actually online (address, players, version).

```
ATERNOS_USERNAME=   # or ATERNOS_SESSION=<cookie value>
ATERNOS_PASSWORD=
ATERNOS_SERVER=     # subdomain or address; empty = first server on the account
```

> ⚠️ Aternos' Terms of Service (§5.2e) forbid automated access. The account can
> be banned, and the world is not backed up by this. A dedicated Aternos account
> with shared access to the server is the safer option.

## Local setup (Windows)

```bat
cd Bot\DiscordBot
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      :: then fill in the keys
venv\Scripts\python.exe main.py
```

Or run `Bot\start_D_bot.bat` (creates the venv on first run).
`python tests/smoke_test.py` exercises every feature against the real APIs
without connecting to Discord.

## Deployment (Oracle Cloud, PM2)

The instance runs both bots under PM2. The important part is the **interpreter**:
PM2 must use the venv python, otherwise `main.py` dies with
`ModuleNotFoundError: No module named 'discord'` and restart-loops.

```bash
ssh -i oracle_key_new.key ubuntu@141.148.245.160
cd ~/PhiLia093_Discord_Bot
git pull

cd Bot/DiscordBot
venv/bin/python -m pip install -r requirements.txt
pm2 restart discord-bot        # or: pm2 start ecosystem.config.js
pm2 logs discord-bot --lines 30
```

Boot persistence (already enabled once):

```bash
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u ubuntu --hp /home/ubuntu
pm2 save
```

## Layout

```
Bot/DiscordBot/
  main.py           Discord client, event routing, graceful shutdown
  commands.py       every command + the answer pipeline
  ai.py             DeepSeek client, message splitting
  memory.py         Chroma knowledge base + JSON preferences
  search.py         Tavily / DuckDuckGo / page fetching
  vision.py         image understanding (OpenAI-compatible)
  imagine.py        Pollinations (free) + Aliyun Qwen-Image (optional)
  news.py           daily news loop
  minecraft.py      Aternos server control
  stickers.py       sticker folders
  constants.py      persona prompt + help text + language rules
  config.py         all environment handling
  tests/smoke_test.py
```

## Troubleshooting

- **`ModuleNotFoundError: No module named 'discord'`** — PM2 is using the system
  python. Start it with `ecosystem.config.js` (venv interpreter) instead of
  `pm2 start main.py --interpreter python3`.
- **`PrivilegedIntentsRequired`** — enable "Message Content Intent" in the
  Developer Portal → Bot.
- **Bot ignores plain messages** — `PHILIA093_CHAT_CHANNEL` points at a deleted
  channel. Set it to an existing channel ID (comma separated for several), or
  leave it empty and create a channel named `philia-chat`: the bot finds it by
  name automatically.
- **No "Online/Offline" chatter** — `STATUS_MESSAGES=false` (default).
- **No reply timestamps** — `TIMESTAMP_SUFFIX=false` (default). The model still
  receives the current date/time in its prompt, and Discord shows message times.
- **Wrong reply language** — `REPLY_LANGUAGE=english` (or `chinese`).
- **`#mc` says not configured** — fill `ATERNOS_USERNAME`/`ATERNOS_PASSWORD`;
  install with `pip install python-aternos`.
- **No images** — Pollinations is rate limited on heavy use; `IMAGE_PROVIDER=aliyun`
  switches the default backend to the paid one.
- **Logs** — `data/bot.log` (rotating), or `pm2 logs discord-bot`.
