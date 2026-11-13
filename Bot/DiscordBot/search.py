"""Web search and page fetching.

Tavily is used when a key is configured (free tier: 1000 credits/month),
otherwise we fall back to DuckDuckGo's HTML endpoint, which needs no key.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp
from bs4 import BeautifulSoup

from config import settings

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_page_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 300
_PAGE_TIMEOUT = aiohttp.ClientTimeout(total=25)


@dataclass
class SearchOutcome:
    text: str = ""
    links: list[str] = field(default_factory=list)
    provider: str = ""
    ok: bool = False

    @property
    def found(self) -> bool:
        return bool(self.links)


async def _tavily(query: str, max_results: int) -> SearchOutcome:
    payload = {
        "api_key": settings.tavily_key,
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                body = await response.text()
                log.warning("Tavily HTTP %s: %s", response.status, body[:200])
                return SearchOutcome(provider="tavily")
            data = await response.json()

    results = data.get("results") or []
    parts: list[str] = []
    links: list[str] = []
    for index, item in enumerate(results, 1):
        title = item.get("title") or "No title"
        snippet = (item.get("content") or "").strip()
        url = item.get("url") or ""
        parts.append(f"[{index}] {title}\n{snippet[:400]}")
        if url:
            links.append(url)
    return SearchOutcome(text="\n\n".join(parts), links=links, provider="tavily", ok=True)


def _decode_ddg_link(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc:
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


async def _duckduckgo(query: str, max_results: int) -> SearchOutcome:
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            data={"q": query},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=25),
        ) as response:
            if response.status != 200:
                log.warning("DuckDuckGo HTTP %s", response.status)
                return SearchOutcome(provider="duckduckgo")
            html = await response.text()

    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []
    links: list[str] = []
    for block in soup.select("div.result"):
        anchor = block.select_one("a.result__a")
        if anchor is None:
            continue
        title = anchor.get_text(" ", strip=True)
        href = _decode_ddg_link(anchor.get("href", ""))
        snippet_el = block.select_one(".result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        if not href.startswith("http"):
            continue
        parts.append(f"[{len(parts) + 1}] {title}\n{snippet[:400]}")
        links.append(href)
        if len(links) >= max_results:
            break

    return SearchOutcome(text="\n\n".join(parts), links=links, provider="duckduckgo", ok=True)


async def web_search(query: str, max_results: int | None = None) -> SearchOutcome:
    """Search the web. Never raises."""
    query = query.strip()
    if not query:
        return SearchOutcome()
    limit = max_results or settings.max_search_results

    providers = []
    if settings.tavily_key:
        providers.append(_tavily)
    providers.append(_duckduckgo)

    for provider in providers:
        try:
            outcome = await provider(query, limit)
        except Exception as exc:
            log.warning("Search provider %s failed: %s", provider.__name__, exc)
            continue
        if outcome.found:
            return outcome
    return SearchOutcome(provider=providers[-1].__name__.strip("_"))


async def fetch_page(url: str, max_chars: int = 6000, use_cache: bool = True) -> str:
    """Download a page and reduce it to readable text. Never raises."""
    if not url.startswith(("http://", "https://")):
        return ""

    now = time.time()
    if use_cache:
        cached = _page_cache.get(url)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1][:max_chars]

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=_PAGE_TIMEOUT) as response:
                if response.status != 200:
                    log.info("Fetch %s -> HTTP %s", url, response.status)
                    return ""
                html = await response.text(errors="replace")
    except Exception as exc:
        log.info("Fetch %s failed: %s", url, exc)
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = "\n".join(lines)
    if use_cache:
        _page_cache[url] = (now, clean)
    return clean[:max_chars]
