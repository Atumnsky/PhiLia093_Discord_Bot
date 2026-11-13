# PhiLia093 Discord Bot

Cyrene (ID: PhiLia093) — a friendly roleplay chatbot for Discord, with web search,
a small local knowledge base, sticker reactions, and image generation.

## Stack

| Feature | Service | Cost |
| --- | --- | --- |
| Chat / reasoning | DeepSeek `deepseek-flash`, `deepseek-v4-pro` (`#model pro`) | paid, very cheap |
| Image generation | [Pollinations.ai](https://pollinations.ai) `flux` (default), Aliyun `qwen-image-3.0-pro` for `#imagine hq` | free / paid |
| Image recognition | Aliyun DashScope `qwen3-vl-plus` (any OpenAI-compatible vision model works) | paid, ~1 cent / image |
| Web search | Tavily (free tier 1000 credits/month), keyless DuckDuckGo fallback | free / paid |
| Knowledge base | ChromaDB + local ONNX MiniLM embeddings (no torch, no API) | free |
| Stickers | local files in `stickers/<emotion>/` | free |

Free by default: image generation, search fallback, embeddings, stickers.
Everything paid is optional and only used when a key is present.

## Commands

Chat — prefix `#`, or no prefix at all inside a `PHILIA093_CHAT_CHANNEL`:

```
#hello                talk to Cyrene
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

Fun: `#lets sing <song>` (lyric game), `#ping`, `#help`.

## Local setup (Windows)

```bat
cd Bot\DiscordBot
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      :: then fill in the keys
venv\Scripts\python.exe main.py
```

Or just run `Bot\start_D_bot.bat` (creates the venv on first run).

Windows note: `main.py` forces UTF-8 on stdout, so Chinese log lines no longer
crash when output is redirected.

## Deployment (Oracle Cloud, PM2)

The instance runs both bots under PM2. The important part is the **interpreter**:
PM2 must use the venv python, otherwise `main.py` dies with
`ModuleNotFoundError: No module named 'discord'` and restart-loops.

```bash
ssh -i oracle_key_new.key ubuntu@141.148.245.160
cd ~/PhiLia093_Discord_Bot
git pull

cd Bot/DiscordBot
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt

pm2 delete discord-bot || true
pm2 start ecosystem.config.js
pm2 save
pm2 logs discord-bot --lines 30
```

Run PM2 once at boot (survives reboots):

```bash
pm2 startup systemd -u ubuntu --hp /home/ubuntu   # prints a sudo command
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u ubuntu --hp /home/ubuntu
```

Useful PM2 commands: `pm2 list`, `pm2 logs discord-bot`, `pm2 restart discord-bot`,
`pm2 stop all`, `pm2 save`.

`.env` lives at `Bot/DiscordBot/.env` and is git-ignored; copy it manually (it is
not part of the repo).

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
  stickers.py       sticker folders
  constants.py      persona prompt + help text
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
  channel. Set it to an existing channel ID (comma separated for several).
- **No images** — Pollinations is rate limited on heavy use; `IMAGE_PROVIDER=aliyun`
  switches the default backend to the paid one.
- **Logs** — `data/bot.log` (rotating), or `pm2 logs discord-bot`.
