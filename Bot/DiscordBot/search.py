import aiohttp
import time
from bs4 import BeautifulSoup
from config import TAVILY_API_KEY, FLARESOLVERR_URL, CACHE_DURATION

page_cache = {}

async def search_tavily(query: str, max_results: int = 5):
    """使用 Tavily API 搜索"""
    if not TAVILY_API_KEY:
        return "Error: Tavily API key not configured.", []
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False
            }
            async with session.post("https://api.tavily.com/search", json=payload) as resp:
                if resp.status != 200:
                    return f"Error: Tavily search failed with HTTP {resp.status}", []
                data = await resp.json()
                results = data.get("results", [])
                if not results:
                    return "No results found.", []
                parts = []
                links = []
                for i, res in enumerate(results, 1):
                    title = res.get("title", "No Title")
                    content = res.get("content", "")
                    url = res.get("url", "")
                    parts.append(f"[{i}] {title}\n{content[:300]}...")
                    links.append(url)
                return "\n\n".join(parts), links
    except Exception as e:
        return f"Error during Tavily search: {str(e)}", []

async def fetch_webpage_content(url: str, max_length: int = 8000, use_cache: bool = True) -> str:
    """获取网页内容（使用 FlareSolverr 或直接请求）"""
    if use_cache:
        now = time.time()
        if url in page_cache and now - page_cache[url][0] < CACHE_DURATION:
            print(f"Using cached content for {url}")
            cached = page_cache[url][1]
            if max_length and len(cached) > max_length:
                return cached[:max_length] + "... [truncated]"
            return cached

    # 尝试 FlareSolverr
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000
            }
            async with session.post(FLARESOLVERR_URL, json=payload, timeout=60) as resp:  # type: ignore
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("solution", {}).get("status") == 200:
                        html = data["solution"]["response"]
                        soup = BeautifulSoup(html, 'html.parser')
                        for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                            script.decompose()
                        text = soup.get_text(separator='\n', strip=True)
                        lines = [line.strip() for line in text.splitlines() if line.strip()]
                        clean_text = '\n'.join(lines)
                        if use_cache:
                            page_cache[url] = (time.time(), clean_text)
                        if max_length and len(clean_text) > max_length:
                            clean_text = clean_text[:max_length] + "... [truncated]"
                        return clean_text
    except Exception as e:
        print(f"FlareSolverr error for {url}: {e}")

    # 降级：直接请求
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'DNT': '1',
        'Connection': 'keep-alive',
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:  # type: ignore
                if resp.status != 200:
                    return ""
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    script.decompose()
                text = soup.get_text(separator='\n', strip=True)
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                clean_text = '\n'.join(lines)
                if use_cache:
                    page_cache[url] = (time.time(), clean_text)
                if max_length and len(clean_text) > max_length:
                    clean_text = clean_text[:max_length] + "... [truncated]"
                return clean_text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return ""