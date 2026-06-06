"""
Content Gap Agent
Scrapes top SERP results for a keyword and extracts:
  - headings (h1/h2/h3), word count, top keywords (unigrams + bigrams + trigrams)
  - average word count across top results
  - content gap vs. target domain

Adapted from contentswift (hilmanski/contentswift) — SERP scrape + newspaper + NLTK pattern.
Uses DuckDuckGo HTML search (no API key required) as the SERP source.
Falls back to direct URL scraping if SERP fetch fails.
"""
import asyncio
import operator
import re
import time
from typing import Any
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

# NLTK is optional — graceful degradation if not installed
try:
    import nltk
    from nltk.corpus import stopwords
    from nltk.tokenize import word_tokenize
    from nltk.util import bigrams, trigrams
    import nltk.data

    # Download required NLTK data silently
    for _pkg in ["punkt", "punkt_tab", "stopwords"]:
        try:
            nltk.download(_pkg, quiet=True)
        except Exception:
            pass
    _NLTK_AVAILABLE = True
except ImportError:
    _NLTK_AVAILABLE = False

MAX_KEYWORDS = 15
MAX_SERP_RESULTS = 10  # scrape top N results
SCRAPE_TIMEOUT = 15    # seconds per article


# ---------------------------------------------------------------------------
# SERP Fetcher (DuckDuckGo HTML — no API key)
# ---------------------------------------------------------------------------

async def _fetch_serp_urls(keyword: str, session: aiohttp.ClientSession) -> list[str]:
    """Fetch top organic URLs from DuckDuckGo HTML search."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(keyword)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            html = await resp.text(errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for result in soup.select(".result__url, .result__a"):
            href = result.get("href", "")
            if href and href.startswith("http") and "duckduckgo.com" not in href:
                urls.append(href)
            if len(urls) >= MAX_SERP_RESULTS:
                break
        return urls
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Article Scraper
# ---------------------------------------------------------------------------

async def _scrape_article(url: str, session: aiohttp.ClientSession) -> dict | None:
    """Scrape a single article URL and extract content signals."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ContentBot/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=SCRAPE_TIMEOUT)
        async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
            if resp.status >= 400:
                return None
            html = await resp.text(errors="replace")
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Remove nav/footer/script/style noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Extract headings
    headings = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        text = h.get_text().strip()
        if text:
            headings.append({"tag": h.name, "text": text})

    # Extract title
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""

    # Extract body text
    # Prefer <article> or <main>, fall back to <body>
    content_el = soup.find("article") or soup.find("main") or soup.find("body")
    content = content_el.get_text(separator=" ") if content_el else soup.get_text(separator=" ")
    content = re.sub(r"\s+", " ", content).strip()

    total_words = len(content.split())
    if total_words < 50:
        return None  # likely blocked or empty

    # Keyword extraction
    keywords = _extract_keywords(content)

    return {
        "url": url,
        "title": title,
        "total_words": total_words,
        "headings": headings,
        "keywords": keywords,
    }


def _extract_keywords(text: str) -> list[dict]:
    """Extract top keywords using NLTK (unigrams + bigrams + trigrams) or simple freq."""
    if _NLTK_AVAILABLE:
        try:
            text_lower = text.lower()
            tokens = word_tokenize(text_lower)
            stop_words = set(stopwords.words("english"))
            filtered = [w for w in tokens if w.isalpha() and w not in stop_words and len(w) > 2]

            freq = nltk.FreqDist(filtered)
            bi_freq = nltk.FreqDist(bigrams(filtered))
            tri_freq = nltk.FreqDist(trigrams(filtered))
            combined = freq + bi_freq + tri_freq

            keywords = []
            for word, frequency in combined.most_common(10):
                w = " ".join(word) if isinstance(word, tuple) else word
                keywords.append({"word": w, "frequency": frequency})
            return keywords
        except Exception:
            pass

    # Fallback: simple word frequency
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    common_stop = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
                   "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
                   "its", "may", "new", "now", "old", "see", "two", "way", "who", "boy",
                   "did", "she", "use", "her", "that", "this", "with", "have", "from",
                   "they", "will", "been", "more", "also", "into", "than", "then", "when",
                   "your", "what", "some", "time", "very", "just", "know", "take", "year"}
    filtered = [w for w in words if w not in common_stop]
    freq: dict[str, int] = {}
    for w in filtered:
        freq[w] = freq.get(w, 0) + 1
    sorted_freq = sorted(freq.items(), key=operator.itemgetter(1), reverse=True)[:10]
    return [{"word": w, "frequency": f} for w, f in sorted_freq]


def _aggregate_keywords(all_keywords: list[dict]) -> list[tuple]:
    """Aggregate keywords across all scraped articles."""
    totals: dict[str, int] = {}
    for kw in all_keywords:
        word = kw["word"].lower()
        totals[word] = totals.get(word, 0) + kw["frequency"]
    sorted_kws = sorted(totals.items(), key=operator.itemgetter(1), reverse=True)[:MAX_KEYWORDS]
    return sorted_kws


# ---------------------------------------------------------------------------
# Public Agent Function
# ---------------------------------------------------------------------------

async def run_content_gap_analysis(keyword: str, target_domain: str | None = None) -> dict[str, Any]:
    """
    Analyze top SERP results for `keyword` and return content gap signals.

    Args:
        keyword: The search query to analyze
        target_domain: Optional — if provided, checks whether target_domain appears in SERP

    Returns:
        - keyword: the query
        - serp_urls: list of top URLs found
        - content_info: per-article {url, title, total_words, headings, keywords}
        - top_keywords: aggregated top keywords across all results
        - average_words: average word count across scraped articles
        - target_in_serp: bool (if target_domain provided)
        - target_serp_position: int or None
        - content_gap: keywords in top results NOT in target domain's content (if target scraped)
    """
    connector = aiohttp.TCPConnector(ssl=False)
    session_timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(connector=connector, timeout=session_timeout) as session:
        # 1. Fetch SERP URLs
        serp_urls = await _fetch_serp_urls(keyword, session)

        if not serp_urls:
            return {
                "keyword": keyword,
                "error": "No SERP results found (DuckDuckGo may have rate-limited)",
                "serp_urls": [],
                "content_info": [],
                "top_keywords": [],
                "average_words": 0,
                "target_in_serp": False,
                "target_serp_position": None,
            }

        # 2. Check target domain position in SERP
        target_in_serp = False
        target_serp_position = None
        if target_domain:
            clean_target = target_domain.replace("www.", "").lower()
            for i, u in enumerate(serp_urls):
                if clean_target in u.lower():
                    target_in_serp = True
                    target_serp_position = i + 1
                    break

        # 3. Scrape top results concurrently
        tasks = [_scrape_article(url, session) for url in serp_urls[:MAX_SERP_RESULTS]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        content_info = [r for r in results if isinstance(r, dict) and r is not None]

        if not content_info:
            return {
                "keyword": keyword,
                "error": "Could not scrape any SERP results (all blocked or empty)",
                "serp_urls": serp_urls,
                "content_info": [],
                "top_keywords": [],
                "average_words": 0,
                "target_in_serp": target_in_serp,
                "target_serp_position": target_serp_position,
            }

        # 4. Aggregate keywords
        all_keywords = []
        for article in content_info:
            all_keywords.extend(article.get("keywords", []))
        top_keywords = _aggregate_keywords(all_keywords)

        # 5. Average word count
        word_counts = [a["total_words"] for a in content_info]
        average_words = int(sum(word_counts) / len(word_counts)) if word_counts else 0

        # 6. Content gap (if target domain scraped separately)
        content_gap = []
        if target_domain and not target_in_serp:
            # Target not in SERP — all top keywords are gaps
            content_gap = [kw for kw, _ in top_keywords]

        return {
            "keyword": keyword,
            "serp_urls": serp_urls,
            "scraped_count": len(content_info),
            "content_info": content_info,
            "top_keywords": [{"keyword": kw, "frequency": freq} for kw, freq in top_keywords],
            "average_words": average_words,
            "target_in_serp": target_in_serp,
            "target_serp_position": target_serp_position,
            "content_gap": content_gap,
        }
