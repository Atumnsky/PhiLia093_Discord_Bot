"""
Cyrene Discord Bot (PhiLia093)

================================================================================
OVERVIEW
================================================================================
This is a feature-rich Discord bot designed as a friendly AI companion named Cyrene (also known as PhiLia093, Peach, Love, Demiurge). It combines conversational AI with web search, a persistent knowledge base, and interactive games to create an engaging experience.

The bot uses:
- **DeepSeek API** (via OpenAI-compatible client) for natural language understanding and generation.
- **Tavily Search API** for real-time web search capabilities.
- **ChromaDB** with sentence embeddings (all-MiniLM-L6-v2) for a persistent, queryable knowledge base.
- **FlareSolverr** to bypass Cloudflare and fetch webpage content for learning.
- **Discord.py** for Discord integration.

================================================================================
FEATURES
================================================================================
1. **Conversational AI** – Responds to user messages starting with `#` using a friendly, warm personality. Supports optional "thinking mode" (showing reasoning).

2. **Web Search** – Use `#search <query>` to fetch real-time information from the web via Tavily. The bot will answer based on search results and provide source links.

3. **Auto-Search** – When enabled with `#autosearch on`, the bot automatically performs a web search for queries that appear to ask for current information (e.g., time, date, recent events). This is a heuristic and can be toggled per user.

4. **Knowledge Base (Long-term Memory)** – Users can teach the bot facts using `#learn <text>`. The bot stores these as vector embeddings in ChromaDB. Later, when relevant questions are asked, the bot retrieves and uses that knowledge.

5. **Learn from Webpages** – Use `#learn from <url>` to fetch and store the content of a webpage. The bot uses FlareSolverr to handle protected sites, then embeds the cleaned text.

6. **Learn from Search Results** – After performing a search, use `#learn that search` to save the AI-generated answer and the content of the first few source pages into the knowledge base.

7. **Learn from Conversation** – After a normal chat exchange, use `#learn that` to save that specific Q&A pair into memory.

8. **View and Manage Knowledge** – `#knowledge` lists the first 50 stored items with previews. `#forget <number>` deletes an item by its list number. `#clean database` wipes the entire knowledge base.

9. **Lyric Singing Game** – Start a lyric game with `#lets sing <song name>`. If the bot knows the lyrics (learned earlier), it will alternate lines with the user. Use `#exit` or `#stop` to quit.

10. **Thinking Mode Toggle** – `#thinking` switches on/off the display of the AI's internal reasoning (if supported by the model). Default is on.

================================================================================
COMMANDS (All commands must start with `#`)
================================================================================
- `# <your message>` – Normal chat with Cyrene.
- `#search <query>` – Perform a web search and get an answer.
- `#autosearch on/off` – Enable/disable automatic search for time-sensitive queries.
- `#thinking` – Toggle the display of reasoning (thinking mode).
- `#learn <text>` – Add a piece of knowledge to the bot's memory.
- `#learn from <url>` – Fetch and learn the content of a webpage.
- `#learn that` – Save the last conversation exchange into memory.
- `#learn that search` – Save the last search results (answer and source pages) into memory.
- `#knowledge` – List stored knowledge items (first 50).
- `#forget <number>` – Delete a knowledge item by its list number.
- `#clean database` – Delete all knowledge.
- `#lets sing <song name>` – Start a lyric game with a known song.
- `#exit` / `#stop` – Exit the current game.

================================================================================
CONFIGURATION (Environment Variables)
================================================================================
- `DEEPSEEK_API_KEY` – Your DeepSeek API key (required).
- `DISCORD_TOKEN` – Discord bot token (required).
- `TAVILY_API_KEY` – Tavily search API key (required for search functionality).
- `ONLINE_CHANNEL_ID` – Optional: ID of a text channel where the bot will announce when it comes online. If not set, the bot picks the first available channel in any guild.

Additionally, the bot expects FlareSolverr to be running at `http://localhost:8191/v1` (configurable in code). Modify `FLARESOLVERR_URL` if needed.

================================================================================
CODE STRUCTURE
================================================================================
- **Imports** – All necessary libraries.
- **Configuration** – API keys, model initialization, ChromaDB path, system prompt.
- **Global Variables** – History buffers, user preferences, caches, game states.
- **Helper Functions**:
  - `retrieve_knowledge(query)` – Queries ChromaDB for relevant documents.
  - `add_to_knowledge(content, source, url)` – Adds a document to the knowledge base.
  - `search_tavily(query)` – Performs a web search via Tavily.
  - `fetch_webpage_content(url)` – Fetches and cleans webpage text, with FlareSolverr fallback.
- **Discord Bot Events**:
  - `on_ready()` – Sends online message.
  - `on_message()` – Main message handler, processes commands and games.
- **Bot Run** – Starts the bot with the token.

================================================================================
EXTENDING / MODIFYING THE BOT
================================================================================
- **Changing Personality**: Edit `CYRENE_SYSTEM_PROMPT`. Adjust tone, rules, or name.
- **Adding New Commands**: Add new `if message.content.startswith(...)` blocks in `on_message()`. Follow existing patterns.
- **Modifying Search Behavior**: Change `max_results` in `search_tavily()`, or adjust the time-query heuristic.
- **Knowledge Base**: You can change the embedding model by replacing `SentenceTransformer('all-MiniLM-L6-v2')` with another model (ensure dimensionality matches ChromaDB).
- **Game Modes**: Add new game types by extending the `game_states` dictionary and handling them appropriately.
- **Caching**: Adjust `CACHE_DURATION` or modify `page_cache` logic.
- **Error Handling**: Enhance try/except blocks as needed.

================================================================================
NOTES & LIMITATIONS
================================================================================
- The bot only responds to messages that start with `#`. This prevents it from replying to every casual chat.
- Auto-search is triggered by a simple keyword check; it may not be perfect.
- Webpage fetching depends on FlareSolverr; ensure it is installed and running.
- Knowledge base embeddings are stored locally in `./chroma_knowledge`. Back up this folder if needed.
- The bot uses `deepseek-reasoner` model; you can change the model name in the API call.
- Discord message length limit is 2000 characters; the bot splits long responses automatically.
- The bot stores conversation history per channel+user, with a max length of 10 exchanges (adjustable via `MAX_HISTORY`).

================================================================================
AUTHOR & LICENSE
================================================================================
This bot was created for the Discord community. It is open for modification and redistribution under the terms of the MIT License (if applicable). Feel free to adapt it to your own needs.

For questions or contributions, please contact the original developer.

Enjoy your time with Cyrene! ✨
"""